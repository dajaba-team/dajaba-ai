"""SCRUM-308-2 추가 검토 4 회귀 — 형식 오류 응답의 모델(output:[null]·usage 변환 실패) · 공백 모델명 · 임베딩 응답 모델
(공통 클라이언트·적재 INSERT 0·운영 RAG 없이) · 코퍼스 재임베딩 대조 · 리랭커 마감 재확인."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from tools.corpus_chunks import Chunk
from tools.ingest_corpus import _insert_chunks

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import EmbeddingModelMismatch, LlmInvalidOutput, RetrievalUnavailable
from aml_ai.shared.infrastructure import embedding_client as ec
from aml_ai.shared.infrastructure.embedding_client import HttpEmbeddingClient
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.common import Typology
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.retriever_rerank import LlmReranker, RerankFailed, rerank_first
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_recheck as recheck
from tests.str import rag_eval_v3_rerank_report as report
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import Calls, Embed, facts, install, ref
from tests.str.test_rag_rerank import FakeLlm

KEYED = {"LLM_API_KEY": "k", "AI_LLM_MOCK": False}
GOOD = {"output_text": json.dumps({"order": ["C4", "C1", "C2", "C3"]})}
BAD_OUTPUT = {"model": "model-B", "output": [None]}
BAD_USAGE = {"model": "model-B", **GOOD, "usage": {"input_tokens": "x"}}


def _client(pick) -> HttpLlmClient:  # noqa: ANN001 — 요청 → 응답 본문
    mock = httpx.MockTransport(lambda r: httpx.Response(200, json=pick(r.content.decode())))
    return HttpLlmClient(
        Settings(_env_file=None, **KEYED), http=httpx.Client(transport=mock), async_transport=mock
    )


@pytest.mark.parametrize("body", [BAD_OUTPUT, BAD_USAGE])
def test_malformed_body_keeps_model_and_marks_received(body: dict) -> None:
    reranker = LlmReranker(_client(lambda _: body), model="model-A", allowed_model="model-A", timeout_s=8.0)
    with pytest.raises(LlmInvalidOutput) as exc:
        reranker.order_with_model("q", [ref("a", 0.5), ref("b", 0.4)])
    assert exc.value.response_model == "model-B" and exc.value.response_received is True


def _verdict(pick) -> dict:  # noqa: ANN001
    types = [JUDGED_TYPES[i % 4] for i in range(30)]
    queries = [{"id": f"Q{i:02}", "typology": t, "uses": ["hit"]} for i, t in enumerate(types)]
    cands = {
        q["id"]: [ref("w", 0.5), ref("y", 0.4), ref("z", 0.3), ref(f"{q['typology']}-a", 0.2)]
        for q in queries
    }
    texts = {q["id"]: ("emb", q["id"]) for q in queries}
    reranker = LlmReranker(_client(pick), model="model-A", allowed_model="model-A", timeout_s=8.0)
    rounds = [live.run_round(reranker, queries, cands, texts) for _ in range(rs.ROUNDS)]
    _, per_round = report.judge(queries, cands, rounds, {t: {f"{t}-a"} for t in JUDGED_TYPES})
    for rr, rnd in zip(per_round, rounds, strict=True):
        rr["response_models"] = rs.response_models(rnd)
    return rs.final_verdict(per_round, dry=False)


@pytest.mark.parametrize("bad", [BAD_OUTPUT, BAD_USAGE])
def test_a59_plus_b_malformed1_not_judged(bad: dict) -> None:
    out = _verdict(lambda body: bad if "Q07" in body else {"model": "model-A", **GOOD})  # 회차마다 B 1 · A 29
    assert out["judged"] is False and out["adopt"] is False and "2종" in out["reason"]


def test_all_a_still_judged() -> None:
    assert _verdict(lambda body: {"model": "model-A", **GOOD})["judged"] is True


@pytest.mark.parametrize("blank", [" ", ""])
def test_blank_response_model_is_none_not_judged(blank: str) -> None:
    out = _verdict(lambda body: {"model": blank, **GOOD})
    assert out["judged"] is False and out["adopt"] is False and "모델명이 없는" in out["reason"]


def _embed(monkeypatch: pytest.MonkeyPatch, response_model: str | None, sent: list[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["model"])
        n = len(json.loads(request.content)["input"])
        body = {
            "data": [{"embedding": [0.1] * 1536, "index": i} for i in range(n)],
            **({"model": response_model} if response_model is not None else {}),
        }
        return httpx.Response(200, json=body)

    real = httpx.Client
    monkeypatch.setattr(ec.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


EMB = Settings(_env_file=None, **KEYED, EMBEDDING_MODEL=" emb ", EMBEDDING_DIM=1536)


@pytest.mark.parametrize(
    ("response_model", "ok"), [("emb", True), (" emb ", True), ("other", False), (None, False), ("", False)]
)
def test_shared_embedding_client_checks_response_model(
    monkeypatch: pytest.MonkeyPatch, response_model: str | None, ok: bool
) -> None:
    sent: list[str] = []
    _embed(monkeypatch, response_model, sent)
    client = HttpEmbeddingClient(EMB)
    if ok:
        assert len(client.embed(["a", "b"])) == 2
    else:
        with pytest.raises(EmbeddingModelMismatch):
            client.embed(["a"])
    assert sent and set(sent) == {"emb"} and client.model == "emb"  # 요청·DB 기록 모두 정규화 값


def test_ingest_inserts_nothing_on_model_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _embed(monkeypatch, "model-B", [])
    session = MagicMock()
    with pytest.raises(EmbeddingModelMismatch):
        _insert_chunks(session, HttpEmbeddingClient(EMB), {"id": "d"}, [Chunk(page=1, text="본문", tokens=1)])
    session.execute.assert_not_called()  # INSERT 0


def test_operational_retrieval_goes_without_rag_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _embed(monkeypatch, "model-B", [])
    retriever = Retriever(MagicMock(), HttpEmbeddingClient(EMB), enabled=True)
    assert issubclass(EmbeddingModelMismatch, RetrievalUnavailable)
    svc = SimpleNamespace(retriever=retriever, generator=SimpleNamespace(prompt_version="narrative_v4"))
    assert DraftService._references(svc, facts(Typology.FAN_IN)) == []  # 기존 임베딩 실패와 같은 처리


def test_corpus_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"c1": ("본문1", [1.0, 0.0]), "c2": ("본문2", [0.0, 1.0])}
    monkeypatch.setattr(recheck.HttpEmbeddingClient, "embed", lambda self, texts: [[1.0, 0.001], [0.0, 1.0]])
    ok = recheck.recheck(stored, EMB)
    assert ok["chunks"] == 2 and ok["below"] == 0 and recheck.recheck_problem(ok) is None
    monkeypatch.setattr(
        recheck.HttpEmbeddingClient, "embed", lambda self, texts: [[0.0, 1.0], [0.0, 1.0]]
    )  # c1 다른 벡터
    bad = recheck.recheck(stored, EMB)
    assert bad["below"] == 1 and "1/2" in recheck.recheck_problem(bad)


def test_corpus_recheck_failure_stops_before_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.str.test_rag_eval_v3_rerank_review2 import REAL, _loaded, _Reranker

    reranker = _Reranker(["m-1"])
    monkeypatch.setattr(live.recheck, "embed_query", lambda text, s, d: None)
    monkeypatch.setattr(live, "fetch_candidates", lambda qs, p, loaded, m: (
        {q["id"]: [ref("w", 0.5), ref("y", 0.4)] if q["typology"] else [] for q in qs}, {}))  # fmt: skip
    monkeypatch.setattr(live.recheck, "recheck", lambda stored, s: {"chunks": 3, "min_cos": 0.5, "below": 1})
    monkeypatch.setattr(live, "make_reranker", lambda s: reranker)
    with pytest.raises(ValueError, match="코퍼스 재임베딩 대조 실패"):
        live.evaluate(Settings(_env_file=None, **REAL, RAG_RERANK_TIMEOUT_S=8), _loaded(), {}, dry=False)
    assert reranker.calls == 0


def _clock(*values: float):  # noqa: ANN202
    it = iter(values)
    return lambda: next(it)


@pytest.mark.parametrize(("after", "late"), [(8.07, True), (7.99, False)])
def test_deadline_rechecked_before_returning_order(after: float, late: bool) -> None:
    """7.92 초 수신 + 0.15 초 처리 = 8.07 초 → 원래 순서(운영·평가 공통). 7.99 면 다시 줄 세움."""
    llm = FakeLlm(text=json.dumps({"order": ["C2", "C1"]}))
    reranker = LlmReranker(llm, model="m", allowed_model="m", timeout_s=8.0, clock=_clock(0.0, after))
    refs = [ref("a", 0.5), ref("b", 0.4)]
    if late:
        with pytest.raises(RerankFailed, match="deadline"):
            reranker.order_with_model("q", refs)
        reranker = LlmReranker(llm, model="m", allowed_model="m", timeout_s=8.0, clock=_clock(0.0, after))
        assert rerank_first(reranker, "q", refs, k=3, release=lambda: None) == refs  # 원래 [a, b]
    else:
        assert [r.chunk_id for r in reranker.order_with_model("q", refs)[0]] == ["b", "a"]


def test_retrieve_keeps_top3_when_deadline_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    first = [ref(f"t{i}", 0.6 - i / 100) for i in range(1, 6)]
    install(monkeypatch, calls, filtered=first, unfiltered={}, cosine_a={})
    llm = FakeLlm(text=json.dumps({"order": ["C5", "C4", "C3", "C2", "C1"]}))
    reranker = LlmReranker(llm, model="m", allowed_model="m", timeout_s=8.0, clock=_clock(0.0, 8.5))
    retriever = Retriever(MagicMock(), Embed(calls), enabled=True, reranker=reranker)
    f = facts(Typology.FAN_IN).model_copy(update={"model_signals": ["distinct_senders_24h"]})
    assert retriever.retrieve(f) == first[:3] and len(llm.calls) == 1
