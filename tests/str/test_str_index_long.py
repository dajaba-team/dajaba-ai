"""승인 STR 색인 — 긴 단락(≤5000) 받아 나눠 색인 (SCRUM-361, 정본 docs/str/10 "승인 STR 색인"). 가짜 저장소·임베딩.

청크 수 = 나눈 청크 합(≤ 상한 식) · 임베딩 한 번 · 키 순번 · 같은 요청 두 번 같은 응답 · 계좌 원문이 뒤쪽 청크에 있어도
RAW_ACCOUNT(나누기 전 판정) · 5000 받음.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import SectionV2, StrIndexRequest, StrIndexSkipReason, StrIndexStatus
from aml_ai.str.domain.str_index import chunk_bound
from tests.str.str_index_support import Embed, Repo, body, svc

LONG = ("가" * 499 + ". ") * 9 + "나" * 400  # 4909자 — 문장 끝에서 나뉨


def _req(*texts: str) -> StrIndexRequest:
    b = body()
    names = [s["section"] for s in b["sections"]]
    b["sections"] = [{"section": n, "text": t} for n, t in zip(names, texts, strict=False)]
    return StrIndexRequest.model_validate(b)


def test_long_sections_split_and_embedded_once() -> None:
    repo, embed = Repo(), Embed()
    texts = (LONG, "가" * 5000, "짧은 섹션 글입니다. " * 10)
    out = svc(repo, embed).index(_req(*texts))
    (ins,) = repo.inserts
    n = len(ins.chunks)
    assert out.status is StrIndexStatus.INDEXED and out.chunk_count == n == 5 + 5 + 1
    assert n <= sum(chunk_bound(t) for t in texts)  # 상한 식(백엔드 응답 확인과 같음)
    assert len(embed.calls) == 1 and len(embed.calls[0]) == n  # 청크 n개를 한 번에
    assert [c.chunk_id for c in ins.chunks][:2] == ["STR-2026-000012:SUBJECT:1", "STR-2026-000012:SUBJECT:2"]
    assert all(len(c.text) <= 1200 for c in ins.chunks)
    assert "".join(c.text for c in ins.chunks if c.section == "SUBJECT") == LONG  # 이어 붙이면 원문


def test_same_request_twice_same_response() -> None:
    repo, embed = Repo(), Embed()
    first = svc(repo, embed).index(_req(LONG))
    second = svc(repo, embed).index(_req(LONG))
    assert first == second.model_copy(update={"produced_at": first.produced_at})
    assert first.chunk_count == second.chunk_count == 5 and len(embed.calls) == 1  # 두 번째는 저장된 결과


def test_raw_account_in_later_chunk_is_skipped() -> None:
    """계좌 원문이 1200자 뒤(두 번째 청크)에 있어도 나누기 전 판정이라 RAW_ACCOUNT · 임베딩 0."""
    repo, embed = Repo(), Embed()
    text = "가" * 1500 + " 10_8000EBD30 로 보냄."
    out = svc(repo, embed).index(_req(text))
    assert (out.status, out.skip_reason, out.chunk_count) == (
        StrIndexStatus.SKIPPED,
        StrIndexSkipReason.RAW_ACCOUNT,
        0,
    )
    assert embed.calls == [] and repo.inserts == []


def test_max_request_63_chunks_fits_one_batch() -> None:
    """7항목 × 5000자 — 청크 최대 = 7 × 9(상한) · 실제 나누기로는 7 × 5 · 임베딩 한 번."""
    b = body()
    b["sections"] = [{"section": n, "text": "가" * 5000} for n in SectionV2]
    repo, embed = Repo(), Embed()
    out = svc(repo, embed).index(StrIndexRequest.model_validate(b))
    assert out.chunk_count == 35 <= 7 * 9 and len(embed.calls) == 1
