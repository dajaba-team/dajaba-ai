"""SCRUM-308-2 리랭커 연결 — Retriever 후보 수 · v4 에서만 · retrieval_version 꼬리 · 기동 해시 · 출력 스키마 (str/10 "리랭커")."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str.narrative_version import llm_output_model
from aml_ai.shared.schemas.str.rerank_llm import RERANK_ORDER_MAX, RerankOut
from aml_ai.shared.versioning import retrieval_version
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.domain.constants import RAG_CANDIDATES, RAG_TOP_K
from aml_ai.str.domain.frozen_prompts import FROZEN_PROMPTS
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR
from aml_ai.str.infrastructure.prompt_index import check_frozen_prompts
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.retriever_rerank import LlmReranker
from tests.str.retriever_fill_support import Calls, Embed, facts, install, ref
from tests.str.test_rag_rerank import FakeLlm

FIRST = [ref(f"t{i}", 0.5 - i / 100) for i in range(1, 8)]


def _retriever(calls: Calls, reranker: LlmReranker | None) -> Retriever:
    return Retriever(MagicMock(), Embed(calls), enabled=True, reranker=reranker,
                     release=lambda: calls.order.append("release"))  # fmt: skip


def test_off_keeps_candidate_limit_k_and_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=FIRST, unfiltered={}, cosine_a={})
    out = _retriever(calls, None).retrieve(facts(Typology.FAN_IN))
    assert out == FIRST[:RAG_TOP_K]
    assert [s["limit"] for s in calls.searches] == [RAG_TOP_K] and calls.order == ["embed", "pg_filtered"]


def test_on_reads_candidates_then_reranks_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=FIRST, unfiltered={}, cosine_a={})
    order = {"order": [f"C{i}" for i in (7, 6, 5, 4, 3, 2, 1)]}
    llm = FakeLlm(text=json.dumps(order))
    out = _retriever(calls, LlmReranker(llm, model="m", allowed_model="m", timeout_s=8.0)).retrieve(
        facts(Typology.FAN_IN)
    )
    assert [r.chunk_id for r in out] == ["t7", "t6", "t5"]
    assert [r.score for r in out] == [FIRST[6].score, FIRST[5].score, FIRST[4].score]  # cosine 그대로
    assert [s["limit"] for s in calls.searches] == [RAG_CANDIDATES]
    assert calls.order == ["embed", "pg_filtered", "release"] and len(llm.calls) == 1


def test_on_with_one_candidate_calls_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=FIRST[:1], unfiltered={}, cosine_a={})
    llm = FakeLlm(text="{}")
    out = _retriever(calls, LlmReranker(llm, model="m", allowed_model="m", timeout_s=8.0)).retrieve(
        facts(Typology.CYCLE)
    )
    assert out == FIRST[:1] and llm.calls == [] and "release" not in calls.order


@pytest.mark.parametrize(
    ("enabled", "prompt", "active"),
    [(True, "narrative_v4", True), (True, "narrative_v2", False), (True, "narrative_v3", False),
     (False, "narrative_v4", False)],
)  # fmt: skip
def test_active_only_on_v4_and_draft_wiring(enabled: bool, prompt: str, active: bool) -> None:
    s = Settings(_env_file=None, RAG_ENABLED=True, AI_LLM_MOCK=True, RAG_RERANK_ENABLED=enabled,
                 NARRATIVE_PROMPT=prompt)  # fmt: skip
    assert s.rag_rerank_active is active
    reranker = DraftService.build(MagicMock(), s).retriever._reranker  # noqa: SLF001
    assert isinstance(reranker, LlmReranker) if active else reranker is None


def test_defaults_and_model_fallback() -> None:
    s = Settings(_env_file=None)
    assert (s.rag_rerank_enabled, s.rag_rerank_model, s.rag_rerank_timeout_s) == (False, "", 8.0)
    on = Settings(_env_file=None, RAG_ENABLED=True, AI_LLM_MOCK=True, RAG_RERANK_ENABLED=True,
                  LLM_MODEL_JUDGE="judge-m")  # fmt: skip
    assert DraftService.build(MagicMock(), on).retriever._reranker._model == "judge-m"  # noqa: SLF001
    with pytest.raises(ValueError):
        Settings(_env_file=None, RAG_RERANK_TIMEOUT_S=0)


def _version(tmp_path, **over: object) -> str | None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    base = {"RAG_ENABLED": True, "EMBEDDING_MODEL": "emb", "CORPUS_DIR": str(tmp_path)}
    return retrieval_version(Settings(_env_file=None, **{**base, **over}))


def test_retrieval_version_tail(tmp_path) -> None:
    assert "+" not in _version(tmp_path)
    assert _version(tmp_path, RAG_RERANK_ENABLED=True).endswith("+rr:rerank_v1")
    both = _version(tmp_path, RAG_RERANK_ENABLED=True, RAG_GAP_FILL_ENABLED=True, ELASTIC_INDEX="ix")
    assert both.endswith("+rr:rerank_v1+fill:abc+kw:ix") and len(both) <= 128  # 꼬리 순서 rr → fill
    assert "+" not in _version(tmp_path, RAG_RERANK_ENABLED=True, NARRATIVE_PROMPT="narrative_v3")


def test_prompt_frozen_and_schema() -> None:
    digest = hashlib.sha256((PROMPTS_DIR / "rerank_v1.md").read_bytes()).hexdigest()
    assert FROZEN_PROMPTS["rerank_v1"] == digest
    check_frozen_prompts()  # 기동 해시 검사 통과
    assert llm_output_model("rerank_v1") is RerankOut and RERANK_ORDER_MAX == RAG_CANDIDATES
