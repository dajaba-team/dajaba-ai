"""SCRUM-308-3 청크 맥락 판정 하네스 — 규칙 ③ · 실행 순서(재임베딩 대조 실패면 결과 0) · 거절 · 원문 0 (DB·임베딩 0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aml_ai.shared.config import Settings
from tests.str import rag_eval_v3_ctx_live as live
from tests.str import rag_eval_v3_ctx_support as cs
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import ref
from tests.str.test_rag_eval_v3_rerank_review2 import _loaded

REAL = {"AI_LLM_MOCK": False, "EMBEDDING_MODEL": " emb "}
SIDE = {"chunks": 3, "min_cos": 1.0, "below": 0, "closer_violations": 0}
OK = {"current": SIDE, "ctx": SIDE, "indistinct": 0}


def _m(p3: float, hit: float = 1.0, rec: float = 0.5) -> dict:
    return {"types": {t: {"n": 6, "precision3": p3, "hit3": hit, "recall10": rec} for t in JUDGED_TYPES},
            "mean_precision3": p3}  # fmt: skip


@pytest.mark.parametrize(
    ("ctx", "leaks", "adopt", "failed"),
    [
        (_m(0.6), [], True, None),
        (_m(0.599), [], False, "precision_gain"),
        (_m(0.7, hit=0.833), [], False, "no_hit_drop"),
        (_m(0.7, rec=0.4), [], False, "no_recall10_drop"),
        (_m(0.7), ["FX01"], False, "no_answer_empty"),
    ],
)
def test_rule3(ctx: dict, leaks: list, adopt: bool, failed: str | None) -> None:
    out = cs.verdict(_m(0.5), ctx, leaks, dry=False)
    assert out["adopt"] is adopt and out["judged"] is True
    assert failed is None or out["checks"][failed] is False


def test_dry_never_judged() -> None:
    out = cs.verdict(_m(0.5), _m(0.9), [], dry=True)
    assert out["judged"] is False and out["adopt"] is False


def test_metrics_precision_and_recall10() -> None:
    queries = [{"id": "Q", "typology": "FAN_IN"}]
    out = cs.metrics({"Q": ["a", "x", "y", "b"]}, queries, {"FAN_IN": {"a", "b"}})
    t = out["types"]["FAN_IN"]
    assert (t["precision3"], t["hit3"], t["recall10"]) == (0.333, 1.0, 1.0)


def _got(loaded: dict, ctx_top: str) -> dict:
    qs = loaded["tests/str/rag_eval_v3/queries_dev.json"]["queries"]

    def tops(first: str) -> dict:  # noqa: E306
        return {
            q["id"]: (
                [ref(first if first != "ans" else f"{q['typology']}-a", 0.5), ref("w", 0.4)]
                if q["typology"]
                else []
            )
            for q in qs
        }

    return {"current_on": tops("w"), "ctx_on": tops(ctx_top), "current_off": tops("w"), "ctx_off": tops(ctx_top),
            "stored": {"current": {"c": ("t", [1.0])}, "ctx": {"c": ("h\nt", [1.0])}}, "ctx_table": "ai.reference_chunks_ctx"}  # fmt: skip


def _patch(monkeypatch: pytest.MonkeyPatch, got: dict, recheck_out: dict) -> list:
    calls: list = []
    monkeypatch.setattr(live.recheck, "embed_query", lambda text, s, d: None)
    monkeypatch.setattr(live, "fetch", lambda qs, p, loaded, s, dry: got)
    monkeypatch.setattr(
        live.pr, "paired_recheck", lambda cur, ctx, s: calls.extend([len(cur), len(ctx)]) or recheck_out
    )
    return calls


def test_evaluate_adopts_and_keeps_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _loaded()
    calls = _patch(monkeypatch, _got(loaded, "ans"), OK)
    doc = live.evaluate(Settings(_env_file=None, **REAL), loaded, {}, dry=False)
    assert calls == [1, 1]  # 두 표 재임베딩 대조
    assert doc["verdict"]["adopt"] is True and doc["verdict"]["gain"] > 0.1
    assert hs.forbidden_keys(doc) == [] and set(doc["corpus_recheck"]) == {"current", "ctx", "indistinct"}
    assert {"current_on", "ctx_on", "current_off", "ctx_off"} <= set(doc["queries"][0])


@pytest.mark.parametrize("bad", ["current", "ctx"])
def test_recheck_failure_stops(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    loaded = _loaded()
    monkeypatch.setattr(live.recheck, "embed_query", lambda text, s, d: None)
    monkeypatch.setattr(live, "fetch", lambda qs, p, ld, s, dry: _got(loaded, "ans"))
    monkeypatch.setattr(live.pr, "paired_recheck", lambda cur, ctx, s: {**OK, bad: {**SIDE, "below": 1}})
    with pytest.raises(ValueError, match=f"{bad} 표"):
        live.evaluate(Settings(_env_file=None, **REAL), loaded, {}, dry=False)


def test_no_answer_leak_in_current_table_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _loaded()
    got = _got(loaded, "ans")
    got["current_on"]["NR"] = [ref("w", 0.5)]
    _patch(monkeypatch, got, OK)
    with pytest.raises(ValueError, match="정답 없는 질의"):
        live.evaluate(Settings(_env_file=None, **REAL), loaded, {}, dry=False)


def test_main_refuses_existing_result_before_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    out.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cs, "RESULT_FILE", out)
    monkeypatch.setattr(live.rg.cg, "criteria_problem", lambda repo: None)
    monkeypatch.setattr(live, "evaluate", lambda *a, **k: pytest.fail("외부 호출까지 감"))
    assert live.main([], settings=Settings(_env_file=None, **REAL)) == 2


def test_precheck_refuses_mock_and_blank_model() -> None:
    assert "AI_LLM_MOCK" in live.precheck(
        Settings(_env_file=None, AI_LLM_MOCK=True, EMBEDDING_MODEL="e"), {}, False
    )
    assert "EMBEDDING_MODEL" in live.precheck(
        Settings(_env_file=None, AI_LLM_MOCK=False, EMBEDDING_MODEL=""), {}, False
    )


def test_main_normalizes_model_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []
    monkeypatch.setattr(cs, "RESULT_FILE", tmp_path / "r.json")
    monkeypatch.setattr(live.rg, "refuse_before", lambda repo, o: ({live.rg.POSITIONS: {}}, {}, None))
    monkeypatch.setattr(live.ex, "read_manifest", lambda repo, p: ({}, "d", None))
    monkeypatch.setattr(live, "precheck", lambda s, loaded, dry: seen.append(s.embedding_model) or "멈춤")
    assert live.main([], settings=Settings(_env_file=None, **REAL)) == 2 and seen == ["emb"]
