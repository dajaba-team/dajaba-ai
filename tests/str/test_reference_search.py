"""SCRUM-309 참고 사례 검색 — 질의·가리기·정리(순수) · 서비스(캐시·예산·실패 분류·로그) (DB·임베딩 0)."""

from __future__ import annotations

import time

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import DbUnavailable, LlmUnavailable
from aml_ai.shared.schemas.str import ReferenceSearchRequest, ReferenceSearchStatus
from aml_ai.str.application import reference_search_service as mod
from aml_ai.str.application.reference_search_service import EmbeddingCache, ReferenceSearchService
from aml_ai.str.domain import reference_search as dom
from aml_ai.str.domain.rag_queries import TYPOLOGY_PATTERN_EN
from aml_ai.str.domain.reference_search import Hit, arrange, masked_query, query_text
from tests.str.test_rag_rerank import LogSpy

VERSION = "emb@36b5a2d5"
RAW = "10_8000EBD30"  # 계약 예시와 같은 모양의 계좌 키


def _in(seconds: float) -> float:
    return time.monotonic() + seconds  # embed_within 은 절대 마감(검토 3)


def _hit(cid: str, doc: str, score: float, tags: tuple[str, ...] = ("CYCLE",)) -> Hit:
    return Hit(cid, doc, f"T-{doc}", "Pub", 2020, 1, tags, score)


def test_query_text_order_and_masked_tail() -> None:
    got = query_text(["CYCLE", "FAN_IN"], "tail")
    assert got == f"{TYPOLOGY_PATTERN_EN['FAN_IN']} {TYPOLOGY_PATTERN_EN['CYCLE']} tail"  # 정해진 순서
    assert query_text(["CYCLE"], None) == TYPOLOGY_PATTERN_EN["CYCLE"]


def test_masked_query_hides_accounts_and_empty_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    out = masked_query(f"계좌 {RAW} 와 ABCD1234EF 로 송금")
    assert out is not None and RAW not in out and "8000EBD30" not in out and "ABCD1234EF" not in out
    assert masked_query(None) is None
    monkeypatch.setattr(dom, "mask_question", lambda s: "   ")
    assert masked_query("x") is None  # 가린 뒤 빈 값 → 유형 질의만


def test_arrange_dedupe_per_doc_top_k_and_ties() -> None:
    hits = [_hit("a1", "A", 0.9), _hit("a1", "A", 0.9), _hit("a2", "A", 0.8), _hit("a3", "A", 0.7), _hit("a4", "A", 0.6),
            _hit("b2", "B", 0.5), _hit("b1", "B", 0.5)]  # fmt: skip
    out = arrange(hits, top_k=10, per_doc=3)
    assert [h.chunk_id for h in out] == ["a1", "a2", "a3", "b1", "b2"]  # 중복 1 · 한 문서 3 · 동점 chunk_id
    assert len(arrange(hits, top_k=2, per_doc=3)) == 2 and arrange([], top_k=5, per_doc=3) == []


class _Embed:
    """`embed(text, deadline)` 자리 — 받은 문장·절대 마감을 기록(시계 0 이면 한도 초와 같음)."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.texts: list[str] = []
        self.timeouts: list[float] = []
        self.fail = fail

    def __call__(self, text: str, total_s: float) -> list[float]:
        self.timeouts.append(total_s)
        if self.fail:
            raise self.fail
        self.texts.append(text)
        return [1.0, 0.0]


class _Repo:
    def __init__(self, hits: list[Hit] | None = None, fail: Exception | None = None) -> None:
        self.hits, self.fail, self.calls = hits or [], fail, 0

    def search(self, vec, typologies, model, *, deadline, clock):  # noqa: ANN001, ANN201
        self.calls += 1
        self.deadline = deadline
        if self.fail:
            raise self.fail
        return self.hits


def _svc(embed: _Embed, repo: _Repo, clock=None, **env) -> ReferenceSearchService:  # noqa: ANN001
    s = Settings(_env_file=None, EMBEDDING_MODEL="emb", **env)
    extra = {"clock": clock} if clock else {}
    return ReferenceSearchService(
        settings=s, repo=repo, embed=embed, retrieval_version=VERSION, cache=EmbeddingCache(25), **extra
    )


def _req(**kw) -> ReferenceSearchRequest:  # noqa: ANN003
    return ReferenceSearchRequest.model_validate({"typologies": ["CYCLE"], **kw})


def test_found_empty_and_no_text_fields() -> None:
    embed = _Embed()
    out = _svc(embed, _Repo([_hit("c1", "A", 0.5, ("CYCLE", "FAN_IN"))])).search(_req(), None)
    assert out.status is ReferenceSearchStatus.FOUND and out.results[0].typologies[0].value == "CYCLE"
    assert "text" not in out.model_dump()["results"][0] and out.search_meta.candidates == 1
    assert _svc(_Embed(), _Repo([])).search(_req(), None).status is ReferenceSearchStatus.EMPTY


def test_embedding_input_has_no_raw_account() -> None:
    embed = _Embed()
    _svc(embed, _Repo()).search(_req(query=f"{RAW} 에서 돌아오는 흐름"), None)
    assert len(embed.texts) == 1 and RAW not in embed.texts[0] and "8000EBD30" not in embed.texts[0]


def test_cache_only_for_typology_only_queries() -> None:
    embed, cache = _Embed(), EmbeddingCache(25)
    svc = _svc(embed, _Repo())
    svc.cache = cache
    svc.search(_req(typologies=["CYCLE", "FAN_IN"]), None)
    svc.search(_req(typologies=["FAN_IN", "CYCLE"]), None)  # 순서만 다름 → 적중
    assert len(embed.texts) == 1
    svc.search(_req(typologies=["CYCLE", "FAN_IN"], query="q"), None)
    svc.search(_req(typologies=["CYCLE", "FAN_IN"], query="q"), None)
    assert len(embed.texts) == 3  # 검색어 있으면 캐시 안 씀


def test_budget_header_shortens_embed_timeout() -> None:
    embed = _Embed()
    _svc(embed, _Repo(), clock=lambda: 0.0).search(_req(), 1500)
    assert embed.timeouts == [1.5]
    embed2 = _Embed()
    _svc(embed2, _Repo(), clock=lambda: 0.0).search(_req(), None)
    assert embed2.timeouts == [3.0]  # 기본: min(3, 5)


def test_budget_exhausted_before_embedding() -> None:
    embed, repo = _Embed(), _Repo()
    with pytest.raises(LlmUnavailable):
        _svc(embed, repo, clock=iter([0.0, 6.0]).__next__).search(_req(), None)
    assert embed.timeouts == [] and repo.calls == 0


def test_late_embedding_is_502_and_not_cached() -> None:
    embed, repo = _Embed(), _Repo()
    svc = _svc(embed, repo, clock=iter([0.0, 0.0, 5.5]).__next__)
    with pytest.raises(LlmUnavailable):
        svc.search(_req(), None)
    assert repo.calls == 0 and svc.cache.get((("CYCLE",), "emb", "v1")) is None


def test_embedding_failure_propagates_and_skips_db() -> None:
    repo = _Repo()
    with pytest.raises(LlmUnavailable):
        _svc(_Embed(fail=LlmUnavailable("x")), repo).search(_req(), None)
    assert repo.calls == 0


def test_db_failure_propagates_503() -> None:
    with pytest.raises(DbUnavailable):
        _svc(_Embed(), _Repo(fail=DbUnavailable("x"))).search(_req(), None)


def test_log_has_no_query_or_text(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    spy.info = lambda msg, extra=None: spy.records.append((msg, dict(extra or {})))  # type: ignore[method-assign]
    monkeypatch.setattr(mod, "log", spy)
    _svc(_Embed(), _Repo([_hit("c1", "A", 0.5)])).search(_req(query=f"비밀 {RAW}"), None)
    ((msg, extra),) = spy.records
    assert msg == "reference_search_done" and set(extra) == {
        "typologies",
        "query_len",
        "results",
        "candidates",
        "latency_ms",
        "cache_hit",
    }
    assert "비밀" not in str(extra) and RAW not in str(extra)
