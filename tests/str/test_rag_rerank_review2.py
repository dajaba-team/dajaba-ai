"""SCRUM-308-2 리랭커 추가 검토 2 회귀 — 등록 목록 V1(출처 대조) · 운영 Retriever 에서 미등록 섞이면 LLM 0·원래 상위 3 · 모델명 strip."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import aml_ml
import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.common import Typology
from aml_ai.str.domain import constants_rerank_registry as reg
from aml_ai.str.domain.constants import RAG_CANDIDATES, RAG_TOP_K
from aml_ai.str.domain.rag_rerank import rerank_query
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.retriever_rerank import LlmReranker, rerank_model
from tests.str.rag_eval_v2_support import build_facts
from tests.str.retriever_fill_support import Calls, Embed, facts, install, ref
from tests.str.test_rag_rerank import FakeLlm

V3 = json.loads(Path("tests/str/rag_eval_v3/queries_dev.json").read_text(encoding="utf-8"))["queries"]
LABELS = json.loads(Path("contracts/display_labels_v1.json").read_text(encoding="utf-8"))


def _fixture(base: str) -> dict:
    return json.loads(Path(f"tests/str/fixtures/{base}").read_text(encoding="utf-8"))


def test_registry_matches_sources() -> None:
    assert set(aml_ml.FEATURE_NAMES) == reg.RERANK_SIGNALS_MODEL  # 점수 모델 reason 이름 그대로
    eval_signals = {
        s for q in V3 for s in q["overrides"].get("model_signals", _fixture(q["base"])["model_signals"])
    }
    assert eval_signals == reg.RERANK_SIGNALS_EVAL_V3
    assert set(LABELS["industry"]) == reg.RERANK_INDUSTRIES_LABELS
    eval_industries = {
        q["overrides"]["industry"] if "industry" in q["overrides"] else (_fixture(q["base"]).get("customer") or {}).get("industry")
        for q in V3
    } - {None}  # fmt: skip
    assert eval_industries == reg.RERANK_INDUSTRIES_EVAL_V3 and "RESTAURANT" in eval_industries
    assert reg.RERANK_REGISTRY_VERSION == "V1" and "mock_feature" not in reg.RAG_RERANK_REGISTRY_V1["signals"]


def test_every_typed_eval_query_is_registered() -> None:
    """평가 세트가 등록 목록 밖으로 떨어지면 판정 불가 — 유형 있는 32 질의 모두 리랭커 질의가 만들어져야 함."""
    typed = [q for q in V3 if q["typology"]]
    assert len(typed) == 32 and all(rerank_query(build_facts(q)) is not None for q in typed)


def _with(signals: list[str], industry: str | None = "RETAIL"):
    f = facts(Typology.FAN_IN).model_copy(update={"model_signals": signals})
    return f.model_copy(update={"customer": f.customer.model_copy(update={"industry": industry})})


@pytest.mark.parametrize(
    ("signals", "industry", "registered"),
    [(["distinct_senders_24h", "focal_in_count", "evidence_count"], "WHOLESALE", True),  # 등록된 다중 신호
     (["distinct_senders_24h", "sample_new_feature"], "RETAIL", False),  # 모양은 맞지만 미등록 하나
     (["distinct_senders_24h"], "SHIPPING", False),  # 미등록 업종
     (["mock_feature"], "RETAIL", False)],  # 모의 점수 이름
)  # fmt: skip
def test_rerank_query_uses_registry(signals: list[str], industry: str, registered: bool) -> None:
    assert (rerank_query(_with(signals, industry)) is not None) is registered


def test_retrieve_with_unregistered_signal_calls_llm_zero_and_keeps_top3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 경로 — 미등록 신호가 섞인 요청은 LLM 0회 · 원래 상위 3건 그대로(추가 검토 2-재)."""
    calls = Calls()
    first = [ref(f"t{i}", 0.6 - i / 100) for i in range(1, 9)]
    install(monkeypatch, calls, filtered=first, unfiltered={}, cosine_a={})
    llm = FakeLlm(text=json.dumps({"order": [f"C{i}" for i in range(8, 0, -1)]}))
    retriever = Retriever(MagicMock(), Embed(calls), enabled=True, reranker=LlmReranker(llm, model="m", allowed_model="m", timeout_s=8.0),
                          release=lambda: calls.order.append("release"))  # fmt: skip
    out = retriever.retrieve(_with(["distinct_senders_24h", "sample_new_feature"]))
    assert out == first[:RAG_TOP_K] and llm.calls == [] and "release" not in calls.order
    assert [s["limit"] for s in calls.searches] == [RAG_CANDIDATES]
    out = retriever.retrieve(_with(["distinct_senders_24h"]))  # 같은 후보, 등록된 신호만 → 1회 · 다시 줄 세움
    assert [r.chunk_id for r in out] == ["t8", "t7", "t6"] and len(llm.calls) == 1


@pytest.mark.parametrize(
    ("rerank", "judge", "expected"),
    [("  ", "judge-m", "judge-m"), (" rr-m ", "judge-m", "rr-m"), ("", "  ", ""), (" ", "", "")],
)
def test_model_name_strip_then_fallback(rerank: str, judge: str, expected: str) -> None:
    assert rerank_model(Settings(_env_file=None, RAG_RERANK_MODEL=rerank, LLM_MODEL_JUDGE=judge)) == expected
