"""SCRUM-310 승인 STR 색인 서비스(가짜 저장소·임베딩) — 스위치·계좌 원문·짧음·같은 번호·임베딩 실패·로그 (str/03)."""

from __future__ import annotations

import pytest

from aml_ai.shared.errors import InvalidRequest, LlmUnavailable
from aml_ai.shared.schemas.str import StrIndexSkipReason, StrIndexStatus
from aml_ai.str.application import str_index_service as mod
from aml_ai.str.domain.str_index import request_hash
from aml_ai.str.infrastructure.str_index_repository import Stored
from tests.str.str_index_support import Embed, Repo, body, req, svc, with_text
from tests.str.test_rag_rerank import LogSpy


def test_indexes_example_once() -> None:
    repo, embed = Repo(), Embed()
    out = svc(repo, embed).index(req())
    assert out.status is StrIndexStatus.INDEXED and out.chunk_count == 4 and out.retrieval_version
    assert len(embed.calls) == 1 and len(embed.calls[0]) == 4  # 섹션 n개를 한 번에
    (ins,) = repo.inserts
    assert (
        ins.section_set == "V2"
        and ins.draft_id == "DRF-000312"
        and ins.chunks[0].chunk_id == "STR-2026-000012:SUBJECT:1"  # SCRUM-361 — 섹션 안 순번
    )


@pytest.mark.parametrize("env", [{"STR_INDEX_ENABLED": False}, {"RAG_ENABLED": False}])
def test_switch_off_is_skipped_disabled(env: dict) -> None:
    repo, embed = Repo(), Embed()
    out = svc(repo, embed, **env).index(req())
    assert (out.status, out.skip_reason, out.chunk_count) == (
        StrIndexStatus.SKIPPED,
        StrIndexSkipReason.DISABLED,
        0,
    )
    assert embed.calls == [] and repo.reads == 0 and repo.inserts == []


@pytest.mark.parametrize("raw", ["10_8000EBD30", "8000EBD30", "8000-EBD-30", "10_12345", "앞 8000EB"])
def test_raw_account_skipped_without_embedding(raw: str) -> None:
    """케이스 계좌(가짜 저장소 10_8000EBD30)의 키·조각 · 명시적 계좌 키(짧아도)."""
    repo, embed = Repo(), Embed()
    out = svc(repo, embed).index(with_text(f"상대 계좌 {raw} 로 보냄."))
    assert out.skip_reason is StrIndexSkipReason.RAW_ACCOUNT and out.chunk_count == 0
    assert embed.calls == [] and repo.inserts == []


@pytest.mark.parametrize(("chars", "reason"), [(99, StrIndexSkipReason.TOO_SHORT), (100, None)])
def test_too_short_boundary(chars: int, reason) -> None:  # noqa: ANN001
    r = req(sections=[{"section": "METHOD", "text": "가 " * chars}])  # 공백은 안 셈
    out = svc().index(r)
    assert out.skip_reason is reason


def test_blank_sections_are_not_chunks() -> None:
    b = body()
    b["sections"] = [*b["sections"], {"section": "OPINION", "text": "   "}]
    repo = Repo()
    from aml_ai.shared.schemas.str import StrIndexRequest

    out = svc(repo).index(StrIndexRequest.model_validate(b))
    assert out.chunk_count == 4 and "OPINION" not in [c.section for c in repo.inserts[0].chunks]


def test_same_request_again_no_embedding() -> None:
    r = req()
    repo, embed = Repo(Stored(request_hash(r), 4, "old-model@11111111")), Embed()
    out = svc(repo, embed).index(r)
    assert (
        out.status is StrIndexStatus.INDEXED
        and out.chunk_count == 4
        and embed.calls == []
        and repo.inserts == []
    )


def test_same_number_different_body_is_400() -> None:
    repo, embed = Repo(Stored("other-hash", 4, "m@1")), Embed()
    with pytest.raises(InvalidRequest):
        svc(repo, embed).index(req())
    assert embed.calls == []


def test_concurrent_winner_with_other_body_is_400() -> None:
    """임베딩 뒤 잠금 안에서 다른 본문 행을 만나면 400(동시 요청)."""

    class Late(Repo):
        def insert(self, doc):  # noqa: ANN001, ANN202
            self.inserts.append(doc)
            return Stored("other-hash", 4, "m@1")

    with pytest.raises(InvalidRequest):
        svc(Late()).index(req())


@pytest.mark.parametrize("embed", [Embed(fail=True), Embed(short=True)])
def test_embedding_failure_is_502_and_no_insert(embed: Embed) -> None:
    repo = Repo()
    with pytest.raises(LlmUnavailable):
        svc(repo, embed).index(req())
    assert repo.inserts == []


def test_log_has_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    spy.info = lambda msg, extra=None: spy.records.append((msg, dict(extra or {})))  # type: ignore[method-assign]
    monkeypatch.setattr(mod, "log", spy)
    r = req()
    svc().index(r)
    ((msg, extra),) = spy.records
    assert msg == "str_index_done" and set(extra) == {
        "report_no", "section_set", "sections", "chunks", "status", "skip_reason", "latency_ms"}  # fmt: skip
    assert not any(s.text[:10] in str(extra) for s in r.sections)


@pytest.mark.parametrize("made_up", ["110-123-456789", "123456789012"])
def test_made_up_numbers_pass_known_limit(made_up: str) -> None:
    """데이터에 없는 번호는 통과(알려진 한계 — 실제 정보가 아니라 유출 아님, 추가 검토 2)."""
    assert svc().index(with_text(f"상대 계좌 {made_up} 로 보냄.")).status is StrIndexStatus.INDEXED


def test_no_facts_skipped_without_embedding() -> None:
    repo, embed = Repo(no_facts=True), Embed()
    out = svc(repo, embed).index(req())
    assert out.skip_reason is StrIndexSkipReason.NO_FACTS and embed.calls == [] and repo.inserts == []
