"""SCRUM-308 ② 리랭커 판정 하네스 — 지표 손 계산 · 규칙 ② 경계 · p95 · 회차 기록 · 거절 · 원문 0 (docs/str/10 308 절 ②)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import Reference
from tests.str import rag_eval_v3_rerank_guard as rg
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_report as report
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES, forbidden_keys
from tests.str.rag_eval_v3_rerank_live import DryReranker
from tests.str.retriever_fill_support import ref

ANS = {t: {f"{t}-a1", f"{t}-a2"} for t in JUDGED_TYPES}


def _metric(p3: float, hit: float = 1.0) -> dict:
    return {
        "types": {t: {"n": 6, "precision3": p3, "hit3": hit} for t in JUDGED_TYPES},
        "mean_precision3": p3,
    }


def test_metrics_hand_example() -> None:
    rows = [
        {"typology": "FAN_IN", "top": ["FAN_IN-a1", "x", "FAN_IN-a2", "FAN_IN-a1x"]},  # 2/3 · hit
        {"typology": "FAN_IN", "top": ["x", "y"]},  # 결과 2건이어도 분모 3 → 0 · hit 0
        {"typology": "CYCLE", "top": ["CYCLE-a2"]},  # 1/3
        {"typology": "FX_RELAY", "top": ["z"]},  # 정답 없는 유형 — 분모에서 뺌
    ]
    out = rs.metrics(rows, ANS)
    assert out["types"]["FAN_IN"] == {"n": 2, "precision3": round(1 / 3, 3), "hit3": 0.5}
    assert out["types"]["CYCLE"] == {"n": 1, "precision3": round(1 / 3, 3), "hit3": 1.0}
    assert out["mean_precision3"] == round(1 / 3, 3) and "FX_RELAY" not in out["types"]


def test_p95_nearest_rank() -> None:
    assert rs.p95([]) is None
    assert rs.p95([5.0]) == 5.0
    assert rs.p95([float(i) for i in range(1, 21)]) == 19.0  # ⌈0.95·20⌉ = 19 번째
    assert rs.p95([float(i) for i in range(1, 31)]) == 29.0  # ⌈28.5⌉ = 29 번째


@pytest.mark.parametrize(
    ("rr", "ms", "failed", "passed", "bad"),
    [
        (_metric(0.9), [100.0] * 30, 3, True, None),  # +0.10 정확히 · 실패율 0.10 정확히 → 통과
        (_metric(0.899), [100.0] * 30, 0, False, "precision_gain"),
        (_metric(1.0, hit=5 / 6), [100.0] * 30, 0, False, "no_hit_drop"),  # 질의 하나라도 hit 잃음
        (_metric(1.0), [100.0] * 28 + [5000.1] * 2, 0, False, "p95"),
        (_metric(1.0), [100.0] * 30, 4, False, "fail_rate"),
    ],
)
def test_round_verdict_boundaries(rr: dict, ms: list, failed: int, passed: bool, bad: str | None) -> None:
    out = rs.round_verdict(_metric(0.8), rr, ms, failed, len(ms))
    assert out["passed"] is passed
    if bad:
        assert out["checks"][bad] is False


def test_both_rounds_must_pass() -> None:
    ok, ng = {"passed": True}, {"passed": False}
    assert rs.verdict([ok, ok])["adopt"] is True
    assert rs.verdict([ok, ng]) == {"judged": True, "rounds_passed": [True, False], "adopt": False}
    assert rs.verdict([ok])["judged"] is False


class _Failing:
    def order_with_model(self, query: str, refs: list[Reference]) -> tuple[list[Reference], str]:
        raise LlmUnavailable("llm unavailable")


def test_run_round_records_failures_as_original_order() -> None:
    queries = [{"id": "FI01", "typology": "FAN_IN", "base": "facts_fan_in.json", "overrides": {}, "uses": ["hit"]},
               {"id": "CY01", "typology": "CYCLE", "base": "facts_fan_in.json", "overrides": {}, "uses": ["hit"]}]  # fmt: skip
    cands = {"FI01": [ref("a", 0.5), ref("b", 0.4)], "CY01": [ref("c", 0.5)]}
    texts = {"FI01": ("emb", "q"), "CY01": ("emb", "q")}
    ok = live.run_round(DryReranker(), queries, cands, texts)
    assert ok["FI01"]["order"] == ["b", "a"] and ok["FI01"]["failed"] is None and ok["FI01"]["ms"] is not None
    assert ok["CY01"] == {
        "order": ["c"],
        "ms": None,
        "failed": None,
        "called": False,
        "model": None,
        "responded": False,
    }  # 후보 1 → 호출 0
    bad = live.run_round(_Failing(), queries, cands, texts)
    assert bad["FI01"]["order"] == ["a", "b"] and bad["FI01"]["failed"] == "LlmUnavailable"
    assert bad["FI01"]["responded"] is False  # 공급자 오류 — 응답을 못 받음(응답 모델 집계 밖)


def test_record_has_no_body_keys() -> None:
    q = {"id": "FI01", "typology": "FAN_IN", "uses": ["hit"]}
    positions = {"a": {"doc_id": "d", "page": 1, "pos": 2, "text": "본문"}}
    rec = report.record(
        q, [ref("a", 0.51234567)], positions, [{"FI01": {"order": ["a"], "ms": 1.0, "failed": None}}]
    )  # noqa: SLF001
    assert forbidden_keys(rec) == [] and rec["candidates"][0]["cosine"] == 0.512346


def test_refuse_before(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rg.cg, "criteria_problem", lambda repo: "기준 다름")
    assert rg.refuse_before(tmp_path, None)[2] == "기준 다름"
    monkeypatch.setattr(rg.cg, "criteria_problem", lambda repo: None)
    out = tmp_path / "result_308_rerank.json"
    out.write_text("{}", encoding="utf-8")
    assert "이미 있음" in rg.refuse_before(tmp_path, out)[2]
    monkeypatch.setattr(
        rg.cg, "read_committed", lambda repo, paths: (None, {}, "입력이 기준 커밋과 다름(positions_722.json)")
    )
    assert rg.refuse_before(tmp_path, None)[2] == "입력이 기준 커밋과 다름(positions_722.json)"
    assert rg.INPUTS == (rg.cg.CANDIDATES, rg.cg.QUERIES, rg.POSITIONS)
    monkeypatch.setattr(
        rg.cg,
        "read_committed",
        lambda repo, paths: (
            {rg.cg.CANDIDATES: {"consensus_pending": True}, rg.cg.QUERIES: {"queries": [{"base": "f.json"}]}},
            {},
            None,
        ),  # fmt: skip
    )
    assert "정답 확인 안 끝남" in rg.refuse_before(tmp_path, None)[2]


def test_repo_inputs_match_criteria_commit_when_history_present() -> None:
    if rg.cg.criteria_problem(live.REPO):
        pytest.skip("기준 커밋 기록 없음(얕은 체크아웃) — 판정 실행은 호스트 전체 리포에서")
    assert rg.refuse_before(live.REPO, None)[2] is None
