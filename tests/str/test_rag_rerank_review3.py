"""SCRUM-308-2 추가 검토 3 회귀 — 응답 모델(거절·형식 실패·모델명 없음) · 임베딩 모델 정규화·응답 대조 · 운영 리랭커 한도 기동 검사."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from aml_ai import main as app_main
from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure import embedding_client as ec
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.str import Reference
from aml_ai.str.infrastructure.retriever_rerank import LlmReranker, rerank_timeout_problem
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_recheck as recheck
from tests.str import rag_eval_v3_rerank_report as report
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import ref

KEYED = {"LLM_API_KEY": "k", "AI_LLM_MOCK": False}
ORDER = json.dumps({"order": ["C2", "C1"]})


def _llm(body: dict) -> HttpLlmClient:
    mock = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    # 리랭커는 total_timeout_s 를 넘겨 비동기 경로를 탐 — 둘 다 같은 모의(실제 주소로 안 나감)
    return HttpLlmClient(
        Settings(_env_file=None, **KEYED), http=httpx.Client(transport=mock), async_transport=mock
    )


def test_refusal_carries_response_model() -> None:
    refusal = {"model": "model-B", "output": [{"content": [{"type": "refusal", "refusal": "no"}]}]}
    reranker = LlmReranker(_llm(refusal), model="model-A", allowed_model="model-A", timeout_s=8.0)
    with pytest.raises(LlmInvalidOutput) as exc:
        reranker.order_with_model("q", [ref("a", 0.5), ref("b", 0.4)])
    assert exc.value.response_model == "model-B"  # 본문 파싱 전에 읽은 응답 모델


def test_missing_response_model_is_none_not_requested_name() -> None:
    reranker = LlmReranker(
        _llm({"output_text": ORDER}), model="model-A", allowed_model="model-A", timeout_s=8.0
    )
    ordered, model = reranker.order_with_model("q", [ref("a", 0.5), ref("b", 0.4)])
    assert [r.chunk_id for r in ordered] == ["b", "a"] and model is None  # 요청 모델로 안 채움


class _Mixed:
    """한 질의만 다른 결과(B 거절 또는 모델명 없음), 나머지는 A 정상."""

    def __init__(self, odd: str, kind: str) -> None:
        self.odd, self.kind = odd, kind

    def order_with_model(self, query: str, refs: list[Reference]) -> tuple[list[Reference], str | None]:
        if query == self.odd and self.kind == "refusal":
            exc = LlmInvalidOutput("llm output_text missing")
            exc.response_model, exc.response_received = "model-B", True  # 실제 클라이언트가 붙이는 표시
            raise exc
        return [refs[-1], *refs[:-1]], None if query == self.odd else "model-A"


def _judge(reranker: _Mixed, once: bool) -> dict:
    types = [JUDGED_TYPES[i % 4] for i in range(30)]
    queries = [{"id": f"Q{i:02}", "typology": t, "uses": ["hit"]} for i, t in enumerate(types)]
    cands = {
        q["id"]: [ref("w", 0.5), ref("y", 0.4), ref("z", 0.3), ref(f"{q['typology']}-a", 0.2)]
        for q in queries
    }
    texts = {q["id"]: ("emb", q["id"]) for q in queries}
    rounds = [live.run_round(reranker, queries, cands, texts)]
    reranker.odd = "none" if once else reranker.odd  # 두 번째 회차는 전부 A(once) — 회차 전체로 모아야 걸림
    rounds.append(live.run_round(reranker, queries, cands, texts))
    _, per_round = report.judge(queries, cands, rounds, {t: {f"{t}-a"} for t in JUDGED_TYPES})
    for rr, rnd in zip(per_round, rounds, strict=True):
        rr["response_models"] = rs.response_models(rnd)
    return rs.final_verdict(per_round, dry=False)


def test_a59_plus_b_refusal1_is_not_judged() -> None:
    out = _judge(_Mixed("Q07", "refusal"), once=True)
    assert out["judged"] is False and out["adopt"] is False and "2종" in out["reason"]


def test_one_response_without_model_is_not_judged() -> None:
    out = _judge(_Mixed("Q07", "no_model"), once=True)
    assert out["judged"] is False and out["adopt"] is False and "모델명이 없는" in out["reason"]


def test_all_same_model_still_judged() -> None:
    assert _judge(_Mixed("none", "refusal"), once=True)["judged"] is True


def _embed_transport(monkeypatch: pytest.MonkeyPatch, response_model: str | None, sent: list[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["model"])
        body = {
            "data": [{"embedding": [0.0] * 1536}],
            **({"model": response_model} if response_model else {}),
        }
        return httpx.Response(200, json=body)

    real = httpx.Client
    monkeypatch.setattr(ec.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize(("response_model", "ok"), [("emb", True), ("other-emb", False), (None, False)])
def test_embedding_response_model_must_match(
    monkeypatch: pytest.MonkeyPatch, response_model: str | None, ok: bool
) -> None:
    sent: list[str] = []
    _embed_transport(monkeypatch, response_model, sent)
    settings = Settings(_env_file=None, **KEYED, EMBEDDING_MODEL="emb", EMBEDDING_DIM=1536)
    if ok:
        assert len(recheck.embed_query("q", settings, dry=False).vectors) == 1
    else:
        with pytest.raises(ValueError, match="임베딩 응답 모델"):
            recheck.embed_query("q", settings, dry=False)
    assert sent == ["emb"]


def test_main_normalizes_embedding_model_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []
    monkeypatch.setattr(rs, "RESULT_FILE", tmp_path / "r.json")
    monkeypatch.setattr(live.rg, "refuse_before", lambda repo, o: ({}, {}, None))
    monkeypatch.setattr(live, "precheck", lambda s, loaded, dry: seen.append(s.embedding_model) or "멈춤")
    assert live.main([], settings=Settings(_env_file=None, **KEYED, EMBEDDING_MODEL=" emb ")) == 2
    assert seen == ["emb"]  # 사전 검사·요청·스냅샷·결과가 같은 정규화 값


@pytest.mark.parametrize(
    ("enabled", "timeout", "ok"),
    [(True, 8, True), (True, 8.5, False), (True, 120, False), (False, 120, True)],
)
def test_operational_timeout_cap(enabled: bool, timeout: float, ok: bool) -> None:
    s = Settings(_env_file=None, RAG_RERANK_ENABLED=enabled, RAG_RERANK_TIMEOUT_S=timeout)
    assert (rerank_timeout_problem(s) is None) is ok


def test_zero_timeout_rejected_by_settings() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, RAG_RERANK_ENABLED=True, RAG_RERANK_TIMEOUT_S=0)


def test_startup_fails_before_requests_when_cap_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None, RAG_RERANK_ENABLED=True, RAG_RERANK_TIMEOUT_S=120)
    monkeypatch.setattr(app_main, "get_settings", lambda: s)

    async def enter() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    with pytest.raises(RuntimeError, match="RAG_RERANK_TIMEOUT_S"):
        asyncio.run(enter())
