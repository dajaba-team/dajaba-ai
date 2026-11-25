"""SCRUM-425 `excerpt` 가 응답 두 곳에 실림 — 초안 v4 `generation_meta.references[]` · 참고 사례 검색 결과 (DB·LLM 0).

원문 `text` 는 응답에 안 나감 · 기존 칸 순서 그대로 · excerpt 맨 끝 · 본문은 로그에 안 남음.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse, Reference, ReferenceSearchRequest
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.application.reference_search_service import EmbeddingCache, ReferenceSearchService
from aml_ai.str.domain.reference_search import Hit
from aml_ai.str.infrastructure.reference_snippet import reference_excerpt
from aml_ai.str.infrastructure.retriever_sql import reference_search_sql
from tests.conftest import EXAMPLES, load_json

BODY = (
    "This report covers general banking supervision topics. "
    "Many senders deposit cash at different branches. "
    "Later sections discuss wire transfers abroad."
)
SECRET_WORD = "branches"  # 본문에만 있는 낱말 — 로그에 나오면 안 됨
REF_KEYS = [
    "chunk_id",
    "doc_id",
    "doc_title",
    "page",
    "score",
    "text",
    "excerpt",
]  # develop 처럼 `text` 는 null
RESULT_KEYS = [
    "doc_id", "doc_title", "publisher", "year", "page", "score", "chunk_id", "typologies", "source_type", "excerpt",
]  # fmt: skip


# ---------- 초안 v4 ----------


def _draft_response(references: list[Reference]) -> dict:
    example = DraftResponse.model_validate(load_json(EXAMPLES / "draft_response.json"))
    req = DraftRequest.model_validate(load_json(EXAMPLES / "draft_request.json"))
    settings = get_settings().model_copy(update={"narrative_prompt": "narrative_v4"})
    svc = DraftService(
        settings=settings, session=None, reader=None, fewshot=None, retriever=None,  # type: ignore[arg-type]
        generator=SimpleNamespace(prompt_version="narrative_v4"), judge=None, rewriter=None, generations=None,  # type: ignore[arg-type]
    )  # fmt: skip
    gen = SimpleNamespace(
        llm_model="m", prompt_version="narrative_v4", tokens_in=1, tokens_out=1, latency_ms=1
    )
    res = svc._build_response(
        req, example.generation_id, example.facts, example.narrative, gen, [], references, None
    )
    return json.loads(res.model_dump_json())


def _ref(i: int, text: str | None = BODY) -> Reference:
    return Reference(chunk_id=f"c{i}", doc_id="d", doc_title="t", page=i, score=0.5, text=text)


def test_draft_v4_references_carry_excerpt_without_text() -> None:
    body = _draft_response([_ref(1), _ref(2, text=None)])
    refs = body["generation_meta"]["references"]
    assert [list(r) for r in refs] == [REF_KEYS, REF_KEYS]  # 칸 순서 · excerpt 맨 끝
    assert all(r["text"] is None for r in refs)  # 원문은 계속 안 나감(develop 과 같은 null)
    facts_typology = body["facts"]["typology"]
    assert refs[0]["excerpt"] == reference_excerpt(BODY, facts_typology)
    assert refs[0]["excerpt"].startswith("Many senders deposit")  # 유형(FAN_IN) 패턴 문장
    assert refs[1]["excerpt"] is None  # 본문 없음 → null
    assert SECRET_WORD not in json.dumps(refs).replace(refs[0]["excerpt"], "")  # 고른 구절 밖 본문 없음


def test_draft_v4_no_references_stays_empty() -> None:
    assert _draft_response([])["generation_meta"]["references"] == []


# ---------- 참고 사례 검색 ----------


def test_search_sql_reads_chunk_text_order_unchanged() -> None:
    sql = str(reference_search_sql())
    inner, outer = sql.split(") SELECT ")
    assert " text" in inner.split("FROM")[0] and " text" in outer.split("FROM")[0]
    assert "ORDER BY d + 0, chunk_id" in sql and "typologies && CAST(:tys AS text[])" in sql


def _hit(cid: str, tags: tuple[str, ...], text: str | None, score: float) -> Hit:
    return Hit(cid, "doc", "T", "Pub", 2020, 1, tags, score, text=text)


class _Repo:
    def __init__(self, hits: list[Hit]) -> None:
        self.hits = hits

    def search(self, vec, typologies, model, *, deadline, clock):  # noqa: ANN001, ANN201, ARG002
        return self.hits


def _search(hits: list[Hit], typologies: list[str]):  # noqa: ANN202
    s = Settings(_env_file=None, EMBEDDING_MODEL="emb")
    svc = ReferenceSearchService(
        settings=s, repo=_Repo(hits), embed=lambda _t, _d: [1.0, 0.0], retrieval_version="emb@00000000",
        cache=EmbeddingCache(25),
    )  # fmt: skip
    return svc.search(ReferenceSearchRequest.model_validate({"typologies": typologies}), None)


CYCLE_BODY = (
    "Funds move in a loop and return to the originating party after several hops."  # FAN_IN 패턴 낱말 없음
)


def test_search_result_excerpt_uses_first_requested_typology_in_tags() -> None:
    both = BODY + " " + CYCLE_BODY
    hits = [_hit("a", ("CYCLE", "FAN_IN"), both, 0.9), _hit("b", ("FAN_IN",), BODY, 0.8)]
    res = _search(hits, ["CYCLE", "FAN_IN"])
    a, b = res.results
    assert a.excerpt == reference_excerpt(both, "CYCLE")  # 요청 순서 첫 번째가 태그에 있음
    assert b.excerpt == reference_excerpt(BODY, "FAN_IN")  # CYCLE 태그 없음 → 다음 요청 유형
    assert a.excerpt != reference_excerpt(both, "FAN_IN")


def test_search_result_excerpt_none_without_body_and_keys_order() -> None:
    res = _search([_hit("a", ("FAN_IN",), None, 0.9)], ["FAN_IN"])
    (r,) = res.results
    assert r.excerpt is None
    dumped = json.loads(res.model_dump_json())["results"][0]
    assert list(dumped) == RESULT_KEYS and "text" not in dumped


def test_search_logs_do_not_contain_body(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        _search([_hit("a", ("FAN_IN",), BODY, 0.9)], ["FAN_IN"])
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert SECRET_WORD not in logged


def test_search_response_size_with_ten_results_is_small() -> None:
    """결과 최대 10 × excerpt 300 유닛 — 응답 크기 확인만(할 일 5)."""
    long_body = ("Many senders deposit into one account " + "x" * 200 + ". ") * 3
    hits = [_hit(f"c{i}", ("FAN_IN",), long_body, 0.9 - i * 0.01) for i in range(10)]
    s = Settings(_env_file=None, EMBEDDING_MODEL="emb")
    svc = ReferenceSearchService(
        settings=s, repo=_Repo(hits), embed=lambda _t, _d: [1.0, 0.0], retrieval_version="emb@00000000",
        cache=EmbeddingCache(25),
    )  # fmt: skip
    req = ReferenceSearchRequest.model_validate({"typologies": ["FAN_IN"], "top_k": 10})
    res = svc.search(req, None)
    assert all(r.excerpt and r.excerpt.endswith("…") for r in res.results)
    assert len(res.model_dump_json().encode()) < 16_000


# ---------- 계약 예시 ----------


@pytest.mark.parametrize("name", ["reference_search_response_found.json", "draft_response.json"])
def test_contract_examples_validate_with_excerpt(name: str) -> None:
    from aml_ai.shared.schemas.str import ReferenceSearchResponse

    data = load_json(EXAMPLES / name)
    if name.startswith("reference"):
        rows = ReferenceSearchResponse.model_validate(data).results
        assert rows and all("excerpt" in r for r in data["results"])
    else:
        DraftResponse.model_validate(data)
        rows = data["generation_meta"]["references"]
        assert all(list(r)[-1] == "excerpt" for r in rows)
