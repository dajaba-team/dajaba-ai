"""SCRUM-308 ② 판정 하네스 추가 검토 1 회귀 — 정답 없는 질의 결과·실패율 분모 · 실측 모드 · 질의 문장 한 번 · 잠금·게시."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import Reference
from tests.str import rag_eval_result_io as rio
from tests.str import rag_eval_v3_rerank_guard as rg
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_report as report
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import ref

ANS = {t: {f"{t}-a"} for t in JUDGED_TYPES}


def _q(qid: str, typ: str | None) -> dict:
    return {"id": qid, "typology": typ, "base": "facts_fan_in.json", "overrides": {}, "uses": ["hit"]}


def test_fx_candidates_stop_judgment() -> None:
    """FX_RELAY 에 태그가 새로 붙어 결과가 생기면 ② 의 '정답 없는 질의 0건' 위반 → 판정 중단."""
    queries = [_q("FI01", "FAN_IN"), _q("FX01", "FX_RELAY"), _q("NR01", None)]
    cands = {"FI01": [ref("FAN_IN-a", 0.5)], "FX01": [ref("x", 0.4)], "NR01": []}
    assert rg.no_answer_problem(queries, cands, ANS) == "정답 없는 질의에 결과가 있음: ['FX01']"
    cands["FX01"] = []
    assert rg.no_answer_problem(queries, cands, ANS) is None


class _FailSome:
    """질의 id 목록에 있으면 실패 — 회차 전체 폴백을 셈."""

    def __init__(self, fail: set[str]) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def order_with_model(self, query: str, refs: list[Reference]) -> tuple[list[Reference], str]:
        self.calls.append(query)
        if query in self.fail:
            raise RuntimeError("provider")
        return [refs[1], refs[0], *refs[2:]], "m"


def test_five_of_32_failures_block_adopt() -> None:
    """추가 검토 1 — 실패 5/32(15.6%)가 정답 있는 30 만 세서 3/30(10%)로 줄면 채택됐음 → 전체 대상으로 셈."""
    types = [JUDGED_TYPES[i % 4] for i in range(30)]
    queries = [_q(f"Q{i:02}", t) for i, t in enumerate(types)] + [_q("X1", "FAN_IN"), _q("X2", "FAN_IN")]
    cands = {
        q["id"]: [ref("w", 0.5), ref(f"{q['typology']}-a", 0.4), ref("z", 0.3), ref("y", 0.2)]
        for q in queries
    }
    texts = {q["id"]: ("emb", q["id"]) for q in queries}
    reranker = _FailSome({"Q00", "Q01", "Q02", "X1", "X2"})
    rounds = [live.run_round(reranker, queries, cands, texts) for _ in range(2)]
    answers = {**ANS}
    _, per_round = report.judge(queries, cands, rounds, answers)
    assert [(r["failed"], r["calls"], r["fail_rate"]) for r in per_round] == [(5, 32, 0.156)] * 2
    assert all(r["checks"]["fail_rate"] is False and r["passed"] is False for r in per_round)


def test_out_of_vocab_query_is_fallback_without_call() -> None:
    queries = [_q("FI01", "FAN_IN")]
    cands = {"FI01": [ref("a", 0.5), ref("b", 0.4)]}
    reranker = _FailSome(set())
    out = live.run_round(reranker, queries, cands, {"FI01": ("emb", None)})
    assert out["FI01"] == {
        "order": ["a", "b"],
        "ms": None,
        "failed": "unregistered_signal",
        "called": True,
        "model": None,
        "responded": False,
    }
    assert reranker.calls == []


@pytest.mark.parametrize(
    ("over", "word"),
    [({"AI_LLM_MOCK": True}, "AI_LLM_MOCK"), ({"LLM_MODEL_JUDGE": ""}, "모델이 비어"),
     ({"LLM_REASONING_EFFORT": "high"}, "LLM_REASONING_EFFORT")],
)  # fmt: skip
def test_real_mode_refuses_mock_empty_model_effort(over: dict, word: str) -> None:
    base = {
        "AI_LLM_MOCK": False,
        "LLM_MODEL_JUDGE": "judge-m",
        "LLM_REASONING_EFFORT": "low",
        "EMBEDDING_MODEL": "emb",
        "RAG_RERANK_TIMEOUT_S": 8,
    }  # 테스트 env 는 녹화 재생
    assert word in rg.real_mode_problem(Settings(_env_file=None, **{**base, **over}))
    assert rg.real_mode_problem(Settings(_env_file=None, **base)) is None


def test_query_texts_built_once_and_reused() -> None:
    fixtures = {
        "tests/str/fixtures/facts_fan_in.json": json.loads(
            Path("tests/str/fixtures/facts_fan_in.json").read_text()
        )
    }
    texts = live.build_texts([_q("FI01", "FAN_IN"), _q("NR01", None)], fixtures)
    assert set(texts) == {"FI01"}  # 유형 없는 질의는 검색 안 함
    emb, rr = texts["FI01"]
    assert emb == rr  # 등록 목록 안이면 리랭커 질의 = 임베딩 (a) 문장
    reranker = _FailSome(set())
    for _ in range(2):
        live.run_round(reranker, [_q("FI01", "FAN_IN")], {"FI01": [ref("a", 0.5), ref("b", 0.4)]}, texts)
    assert reranker.calls == [rr, rr]  # 두 회차 같은 문장


def test_fixture_inputs_are_checked() -> None:
    queries = {
        "queries": [
            {"base": "facts_fan_in.json"},
            {"base": "facts_cycle_nopaths.json"},
            {"base": "facts_fan_in.json"},
        ]
    }
    assert rg.fixture_paths(queries) == (
        "tests/str/fixtures/facts_cycle_nopaths.json",
        "tests/str/fixtures/facts_fan_in.json",
    )


def test_lock_and_atomic_publish(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    with rio.run_lock(out):
        assert rio.lock_path(out).exists()
        with pytest.raises(rio.ResultLocked), rio.run_lock(out):
            pass  # 두 번째 실행은 잠금에서 막힘
        rio.publish_new(out, '{"a": 1}\n')
    assert not rio.lock_path(out).exists() and out.read_text() == '{"a": 1}\n'
    with pytest.raises(FileExistsError):
        rio.publish_new(out, '{"a": 2}\n')  # 기존 결과 안 덮음
    assert out.read_text() == '{"a": 1}\n' and not list(tmp_path.glob(".*.tmp"))
