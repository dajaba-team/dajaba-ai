"""SCRUM-308 ② 판정 하네스 추가 검토 2 회귀 — 타임아웃 8초 · DB 임베딩 모델 · 픽스처 객체만 · 잠금 직후 재검사 ·
응답 모델 2종 · dry 판정 · 외부 호출 횟수와 최종 판정."""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import Reference
from tests.str import rag_eval_v3_cutoff_guard as cg
from tests.str import rag_eval_v3_rerank_guard as rg
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import ref

REAL = {
    "AI_LLM_MOCK": False,
    "LLM_MODEL_JUDGE": "judge-m",
    "LLM_REASONING_EFFORT": "low",
    "EMBEDDING_MODEL": "emb",
}
FIXTURE = "tests/str/fixtures/facts_fan_in.json"


@pytest.mark.parametrize(
    ("timeout", "ok"), [(4, False), (8.5, False), (20, False), (8, True), ("8", True), ("8.0", True)]
)
def test_timeout_must_be_criteria_value(timeout: object, ok: bool) -> None:
    reason = rg.real_mode_problem(Settings(_env_file=None, **REAL, RAG_RERANK_TIMEOUT_S=timeout))
    assert (reason is None) is ok and (ok or "RAG_RERANK_TIMEOUT_S" in reason)


def test_blank_model_names_refused() -> None:
    s = Settings(_env_file=None, **{**REAL, "LLM_MODEL_JUDGE": "  "}, RAG_RERANK_MODEL=" ")
    assert "모델이 비어" in rg.real_mode_problem(s)


class _Session:
    def __init__(self, models: list[str]) -> None:
        self.models = models

    def execute(self, *_: object) -> _Session:
        return self

    def scalars(self) -> list[str]:
        return self.models


@pytest.mark.parametrize(
    ("models", "ok"), [(["emb"], True), (["other"], False), (["emb", "other"], False), ([], False)]
)
def test_db_embedding_model_single_and_equal(models: list[str], ok: bool) -> None:
    assert (rg.embedding_model_problem(_Session(models), " emb ") is None) is ok


def _q(qid: str, typ: str | None) -> dict:
    return {"id": qid, "typology": typ, "base": "facts_fan_in.json", "overrides": {}, "uses": ["hit"]}


def test_texts_come_only_from_verified_fixture_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    """검증한 객체만으로 — 파일을 못 읽게 해도 만들어지고, 객체를 바꾸면 문장이 그 값을 따름(파일 재읽기 0)."""
    obj = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
    obj["customer"]["industry"] = "WHOLESALE"
    before = copy.deepcopy(obj)
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("파일 읽음")))
    texts = live.build_texts([_q("FI01", "FAN_IN")], {FIXTURE: obj})
    assert "WHOLESALE" in texts["FI01"][0] and texts["FI01"][0] == texts["FI01"][1]
    assert obj == before  # 원본 객체는 안 바뀜(질의마다 복사본에 overrides)


class _Reranker:
    def __init__(self, models: list[str]) -> None:
        self.models, self.calls = models, 0

    def order_with_model(self, query: str, refs: list[Reference]) -> tuple[list[Reference], str]:
        self.calls += 1
        return [refs[-1], *refs[:-1]], self.models[self.calls % len(self.models)]


def _loaded() -> dict:
    cand = {"candidates": {t: [{"chunk_id": f"{t}-a", "grade": 2, "db_tagged": True}] for t in JUDGED_TYPES}}
    queries = {"queries": [_q(f"Q{i}", t) for i, t in enumerate(JUDGED_TYPES)] + [_q("NR", None)]}
    positions = {
        "positions": {
            c: {"doc_id": "d", "page": 1, "pos": 1} for t in JUDGED_TYPES for c in ("w", "y", "z", f"{t}-a")
        }
    }
    fixture = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
    return {cg.CANDIDATES: cand, cg.QUERIES: queries, rg.POSITIONS: positions, FIXTURE: fixture}


def _run(monkeypatch: pytest.MonkeyPatch, reranker: _Reranker, dry: bool = False) -> tuple[dict, list[int]]:
    embeds: list[int] = []
    monkeypatch.setattr(live.recheck, "embed_query", lambda text, s, d: embeds.append(1) or None)
    monkeypatch.setattr(live.recheck, "recheck", lambda stored, s: {"chunks": 1, "min_cos": 1.0, "below": 0})
    monkeypatch.setattr(
        live,
        "fetch_candidates",
        lambda qs, p, loaded, m: (
            {
                q["id"]: (
                    [ref("w", 0.5), ref("y", 0.4), ref("z", 0.3), ref(f"{q['typology']}-a", 0.2)]
                    if q["typology"]
                    else []
                )
                for q in qs
            },
            {},
        ),
    )  # fmt: skip — 정답이 4위 → 리랭커(마지막을 앞으로)가 precision@3 을 올림
    monkeypatch.setattr(live, "make_reranker", lambda s: reranker)
    if dry:
        monkeypatch.setattr(live, "DryReranker", lambda: reranker)
    doc = live.evaluate(Settings(_env_file=None, **REAL, RAG_RERANK_TIMEOUT_S=8), _loaded(), {}, dry=dry)
    return doc, embeds


def test_external_calls_and_final_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    reranker = _Reranker(["m-1"])
    doc, embeds = _run(monkeypatch, reranker)
    assert (
        len(embeds) == 4 and reranker.calls == 4 * rs.ROUNDS
    )  # 임베딩 = 유형 있는 질의 · LLM = 4 질의 × 2 회차
    assert doc["configuration"]["llm_calls"] == 8 and doc["configuration"]["embedding_batches"] == 4
    assert doc["verdict"] == {"judged": True, "rounds_passed": [True, True], "adopt": True}
    assert [r["response_models"] for r in doc["rounds"]] == [["m-1"], ["m-1"]]


def test_two_response_models_not_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    reranker = _Reranker(["m-1", "m-2"])
    doc, _ = _run(monkeypatch, reranker)
    assert reranker.calls == 8 and doc["verdict"]["judged"] is False and doc["verdict"]["adopt"] is False
    assert "응답 모델 2종" in doc["verdict"]["reason"]


def test_dry_never_judged_even_if_metrics_improve(monkeypatch: pytest.MonkeyPatch) -> None:
    doc, _ = _run(monkeypatch, _Reranker(["dry"]), dry=True)
    assert all(r["passed"] for r in doc["rounds"])  # 지표는 남김
    assert doc["dry"] is True and doc["verdict"]["judged"] is False and doc["verdict"]["adopt"] is False


def test_lock_then_recheck_result_skips_evaluate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "result_308_rerank.json"
    monkeypatch.setattr(rs, "RESULT_FILE", out)
    monkeypatch.setattr(rg, "refuse_before", lambda repo, o: (_loaded(), {}, None))
    monkeypatch.setattr(live, "precheck", lambda s, loaded, dry: None)

    @contextmanager
    def lock_then_other_run_publishes(path: Path):
        path.write_text("{}", encoding="utf-8")  # 사전 검사와 잠금 사이에 다른 실행이 게시
        yield

    monkeypatch.setattr(live.rio, "run_lock", lock_then_other_run_publishes)
    monkeypatch.setattr(live, "evaluate", lambda *a, **k: pytest.fail("외부 호출이 시작됨"))
    assert live.main([], settings=Settings(_env_file=None, **REAL)) == 2
    assert out.read_text() == "{}"
