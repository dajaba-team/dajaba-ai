"""SCRUM-310 추가 검토 1 회귀 — 계좌 원문 후보 먼저(허용 모양 옆 조각 · 섹션 경계 · 분할 16진 · 은행 번호 + 짧은 조각,
서비스 임베딩 0회) · 전각 문서번호 400 · 저장된 retrieval_version 재사용 · 읽기 종료 실패 503 · EMBEDDING_DIM 기동 검사."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import DbUnavailable
from aml_ai.shared.schemas.str import StrIndexRequest, StrIndexSkipReason, StrIndexStatus
from aml_ai.shared.versioning import str_index_problem
from aml_ai.str.domain.str_index import request_hash
from aml_ai.str.infrastructure.str_index_repository import Stored, StrIndexRepository
from tests.str.str_index_support import ON, Embed, Repo, body, req, svc, with_text

SINGLE = [  # 추가 검토 2 에서 실제 계좌 대조로 바뀜 — 가짜 저장소의 케이스 계좌 10_8000EBD30 · 20_0100AAF7C 기준
    pytest.param("8000EBD 2022-09-02", id="H1-fragment-next-to-date"),
    pytest.param("80-00-EB-D3-0", id="H3-split-key"),
    pytest.param("0100 AAF 7C", id="H3-split-hex-letters"),
    pytest.param("10_12 34", id="bank-short-pieces"),
]


@pytest.mark.parametrize("raw", SINGLE)
def test_raw_candidates_detected_and_not_embedded(raw: str) -> None:
    repo, embed = Repo(), Embed()
    out = svc(repo, embed).index(with_text(f"상대 계좌 {raw} 로 보냄."))
    assert out.skip_reason is StrIndexSkipReason.RAW_ACCOUNT and embed.calls == [] and repo.inserts == []


@pytest.mark.parametrize(("end", "start"), [("상대 계좌 8000", "EBD30 로 보냄."), ("계좌 0100A", "AF7C 로")])
def test_section_boundary_candidate_detected(end: str, start: str) -> None:
    b = body()
    b["sections"] = [*b["sections"][:2], {"section": "PLACE", "text": end}, {"section": "INSTRUMENT", "text": start},
                     *b["sections"][2:]]  # fmt: skip
    repo, embed = Repo(), Embed()
    out = svc(repo, embed).index(StrIndexRequest.model_validate(b))
    assert out.skip_reason is StrIndexSkipReason.RAW_ACCOUNT and embed.calls == [] and repo.inserts == []


def test_example_and_normal_shapes_still_index() -> None:
    lines = "2022-09-02 00:14부터 22:51까지 · 합계 1,234,567,890.123456 이스라엘 셰켈(ILS) · 대상 10_****BD30 · #80062240"
    assert svc().index(with_text(lines)).status is StrIndexStatus.INDEXED
    assert svc().index(req()).status is StrIndexStatus.INDEXED


@pytest.mark.parametrize("no", ["STR-２０２６-000012", "STR-2026-００００１２", "STR-٢٠٢٦-000012"])
def test_non_ascii_digits_report_no_400(no: str) -> None:
    with pytest.raises(ValidationError):
        StrIndexRequest.model_validate(body(report_no=no))


def test_reuse_returns_stored_version_both_paths() -> None:
    r = req()
    first = svc(Repo(Stored(request_hash(r), 4, "old-model@11111111"))).index(r)  # 사전 확인 경로

    class Late(Repo):
        def insert(self, doc):  # noqa: ANN001, ANN202
            return Stored(request_hash(r), 4, "old-model@11111111")  # 잠금 안에서 먼저 저장된 행

    second = svc(Late(), EMBEDDING_MODEL="new-model").index(r)
    assert first.retrieval_version == second.retrieval_version == "old-model@11111111"


class _Rows:
    def all(self) -> list:
        return []

    def first(self) -> None:
        return None

    def scalar_one_or_none(self) -> dict:
        return {"subject": {"account_key": "10_8000EBD30"}}  # facts — 거래 ID 없음


class _BrokenCommitSession:
    new = dirty = deleted = ()

    def in_transaction(self) -> bool:
        return True

    def execute(self, *a, **kw):  # noqa: ANN002, ANN003, ANN202
        return _Rows()

    def commit(self) -> None:
        raise OperationalError("commit", {}, Exception("connection lost"))


def test_read_release_failure_is_503_and_no_embedding() -> None:
    embed = Embed()
    service = svc(StrIndexRepository(_BrokenCommitSession()), embed)  # type: ignore[arg-type]
    with pytest.raises(DbUnavailable):
        service.index(req())
    assert embed.calls == []


def test_startup_checks_embedding_dim() -> None:
    assert str_index_problem(Settings(_env_file=None, **{**ON, "EMBEDDING_DIM": 768})) is not None
    assert str_index_problem(Settings(_env_file=None, **{**ON, "EMBEDDING_DIM": 1536})) is None
    assert (
        str_index_problem(Settings(_env_file=None, **{**ON, "EMBEDDING_DIM": 768, "RAG_ENABLED": False}))
        is None
    )
