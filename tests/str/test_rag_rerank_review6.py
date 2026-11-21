"""SCRUM-308-2 추가 검토 6 회귀 — 200 뒤 압축 해제 실패도 받은 응답(모델 None) · 동점 후보에서 리랭커 폴백 = 리랭커 끔(-m db)."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.retriever_rerank import LlmReranker
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_report as report
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import ref
from tests.str.retriever_search_support import FakeEmbedder, facts_typology, insert_chunk, vec
from tests.str.test_rag_rerank import FakeLlm

KEYED = {"LLM_API_KEY": "k", "AI_LLM_MOCK": False}


def _client(pick) -> HttpLlmClient:  # noqa: ANN001 — 요청 본문 → httpx.Response
    mock = httpx.MockTransport(lambda r: pick(r.content.decode()))
    return HttpLlmClient(
        Settings(_env_file=None, **KEYED), http=httpx.Client(transport=mock), async_transport=mock
    )


def _ok() -> httpx.Response:
    return httpx.Response(
        200, json={"model": "model-A", "output_text": json.dumps({"order": ["C4", "C1", "C2", "C3"]})}
    )


def _gzip(status: int) -> httpx.Response:
    return httpx.Response(
        status, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip")
    )  # 본문은 읽을 때 풀림


@pytest.mark.parametrize("total", [None, 8.0])  # 기존 경로(동기) · 리랭커 경로(호출 전체 한도, 비동기)
def test_http200_decoding_failure_is_received_without_model(total: float | None) -> None:
    client = _client(lambda _: _gzip(200))
    with pytest.raises(LlmInvalidOutput) as exc:
        client.complete_json(
            system="s", user="u", model="m", max_tokens=10, tag="rerank_v1", total_timeout_s=total
        )
    assert exc.value.response_received is True and exc.value.response_model is None


@pytest.mark.parametrize("total", [None, 8.0])
def test_non200_decoding_failure_keeps_current_classification(total: float | None) -> None:
    with pytest.raises(httpx.DecodingError):  # 200 이 아니면 지금처럼 예외 그대로
        _client(lambda _: _gzip(500)).complete_json(
            system="s", user="u", model="m", max_tokens=10, tag="rerank_v1", total_timeout_s=total
        )


def test_one_decoding_failure_per_round_not_judged() -> None:
    types = [JUDGED_TYPES[i % 4] for i in range(30)]
    queries = [{"id": f"Q{i:02}", "typology": t, "uses": ["hit"]} for i, t in enumerate(types)]
    cands = {
        q["id"]: [ref("w", 0.5), ref("y", 0.4), ref("z", 0.3), ref(f"{q['typology']}-a", 0.2)]
        for q in queries
    }
    texts = {q["id"]: ("emb", q["id"]) for q in queries}
    client = _client(lambda body: _gzip(200) if "Q07" in body else _ok())  # 회차마다 30 중 1
    reranker = LlmReranker(client, model="model-A", allowed_model="model-A", timeout_s=8.0)
    rounds = [live.run_round(reranker, queries, cands, texts) for _ in range(rs.ROUNDS)]
    assert all(rnd["Q07"]["responded"] for rnd in rounds)
    _, per_round = report.judge(queries, cands, rounds, {t: {f"{t}-a"} for t in JUDGED_TYPES})
    for rr, rnd in zip(per_round, rounds, strict=True):
        rr["response_models"] = rs.response_models(rnd)
    out = rs.final_verdict(per_round, dry=False)
    assert out["judged"] is False and out["adopt"] is False and "모델명이 없는" in out["reason"]


def _clock(*values: float):  # noqa: ANN202
    it = iter(values)
    return lambda: next(it)


@pytest.mark.db
def test_tied_candidates_fallback_equals_reranker_off(_db_engine: Engine, mixed: Facts) -> None:
    """동점 10청크 — 리랭커 끔 = 모델 불일치 폴백 = 마감 폴백(ID·순서), 동점은 chunk_id 순."""
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        ids = [
            insert_chunk(
                conn,
                doc_id="tie",
                doc_title="Tie",
                page=p,
                typologies=["FAN_IN"],
                text_body="같은 본문",
                v=vec(1.0),
            )
            for p in range(1, 11)
        ]
    f = facts_typology(mixed, Typology.FAN_IN).model_copy(update={"model_signals": ["distinct_senders_24h"]})
    order = json.dumps({"order": [f"C{i}" for i in range(10, 0, -1)]})
    with sessionmaker(bind=_db_engine)() as s:
        off = Retriever(s, FakeEmbedder(vec(1.0)), enabled=True).retrieve(f)
        mismatch = LlmReranker(FakeLlm(text=order), model="m", allowed_model="other", timeout_s=8.0)
        late = LlmReranker(
            FakeLlm(text=order), model="m", allowed_model="m", timeout_s=8.0, clock=_clock(0.0, 9.0)
        )
        outs = [
            Retriever(s, FakeEmbedder(vec(1.0)), enabled=True, reranker=r).retrieve(f)
            for r in (mismatch, late)
        ]
    key = [(r.chunk_id, r.page) for r in off]
    assert len(off) == 3 and [k[0] for k in key] == sorted(ids)[:3]
    assert all([(r.chunk_id, r.page) for r in out] == key for out in outs)
