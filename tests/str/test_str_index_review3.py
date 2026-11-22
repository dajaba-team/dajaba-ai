"""SCRUM-310 추가 검토 3 회귀 — 과다 노출 마스킹 · facts 거래 일부 누락 503 · 서식 문자 구분자 · 섹션 경계 공백·긴 토큰 묶음 ·
은행 번호 + 계좌 앞자리 · 같은 번호 먼저. 계좌 사례는 전부 RAW_ACCOUNT + 임베딩 0 + 저장 0."""

from __future__ import annotations

import pytest

from aml_ai.shared.errors import DbUnavailable, InvalidRequest
from aml_ai.shared.schemas.str import StrIndexRequest, StrIndexSkipReason, StrIndexStatus
from aml_ai.str.domain.str_index import request_hash
from aml_ai.str.infrastructure.str_index_repository import Stored, StrIndexRepository
from tests.str.str_index_support import Embed, Repo, body, req, svc, with_text

CASE = {"10_8000EBD30", "800102_12345678"}
REAL = {"20_0100AAF7C", "10_31415926"}  # 원천 계좌 표에만 있는(케이스 밖) 계좌


def _two(end: str, start: str) -> StrIndexRequest:
    b = body()
    b["sections"] = [*b["sections"][:2], {"section": "PLACE", "text": end}, {"section": "INSTRUMENT", "text": start},
                     *b["sections"][2:]]  # fmt: skip
    return StrIndexRequest.model_validate(b)


RAW = [
    pytest.param(with_text("상대 계좌 10_****31415926 로 보냄."), id="H1-masked-then-full"),
    pytest.param(with_text("상대 계좌 8000​EBD30 로 보냄."), id="H3-zero-width-case"),
    pytest.param(with_text("상대 계좌 0100­AAF7C 로 보냄."), id="H3-soft-hyphen-real"),
    pytest.param(with_text("상대 계좌 0100⁠AAF﻿7C 로 보냄."), id="H3-word-joiner-bom-real"),
    pytest.param(_two("상대 계좌 0100AA ", "  F7C 로 보냄."), id="H4-boundary-with-spaces-real"),
    pytest.param(with_text("상대 계좌 0 1 0 0 A A F 7 C 로 보냄."), id="H4-nine-tokens-real"),
    pytest.param(with_text("상대 은행 800102 1234 계좌, 끝자리 ****5678."), id="H5-bank-prefix-space"),
    pytest.param(
        _two("상대 은행 800102-1234 계좌", "끝자리는 ****5678 임."), id="H5-bank-prefix-other-section"
    ),
]


@pytest.mark.parametrize("r", RAW)
def test_raw_cases_skipped_not_embedded_not_stored(r: StrIndexRequest) -> None:
    repo, embed = Repo(case=CASE, accounts=REAL), Embed()
    out = svc(repo, embed).index(r)
    assert out.skip_reason is StrIndexSkipReason.RAW_ACCOUNT and out.chunk_count == 0
    assert embed.calls == [] and repo.inserts == []


@pytest.mark.parametrize("line", ["대상 계좌는 10_****BD30임.", "상대 은행 800102_****5678 계좌로 보냄."])
def test_proper_masking_still_indexes(line: str) -> None:
    assert svc(Repo(case=CASE, accounts=REAL)).index(with_text(line)).status is StrIndexStatus.INDEXED


class _TxSession:
    """facts 거래 ID 1·2·3 중 일부만 원천 표에 있는 세션 흉내."""

    def __init__(self, rows: list[tuple[int, str, str]]) -> None:
        self.rows = rows

    def execute(self, stmt, params=None):  # noqa: ANN001, ANN201
        sql = str(stmt)
        if "FROM ai.generations" in sql:
            return _Result(
                scalar={"subject": {"account_key": "10_8000EBD30"}, "inbound": {"transaction_ids": [1, 2, 3]}}
            )
        return _Result(rows=[_Row(*r) for r in self.rows])


class _Row:
    def __init__(self, tid: int, f: str, t: str) -> None:
        self.transaction_id, self.from_account_key, self.to_account_key = tid, f, t


class _Result:
    def __init__(self, scalar=None, rows=None) -> None:  # noqa: ANN001
        self._scalar, self._rows = scalar, rows or []

    def scalar_one_or_none(self):  # noqa: ANN201
        return self._scalar

    def all(self) -> list:
        return self._rows


@pytest.mark.parametrize(
    "rows",
    [
        [(1, "020_C0000001", "10_8000EBD30"), (2, "020_C0000002", "10_8000EBD30")],  # 3개 중 2개
        [
            (1, "020_C0000001", "10_8000EBD30"),
            (2, "", "10_8000EBD30"),
            (3, "020_C0000003", "10_8000EBD30"),
        ],  # 빈 계좌
    ],
)
def test_partial_source_transactions_is_503(rows: list) -> None:
    with pytest.raises(DbUnavailable):
        StrIndexRepository(_TxSession(rows)).case_accounts("DRF-000312")  # type: ignore[arg-type]


def test_partial_transactions_service_503_no_embedding() -> None:
    class Partial(Repo):
        def case_accounts(self, draft_id: str):  # noqa: ANN201
            raise DbUnavailable("str index source transactions incomplete")

    repo, embed = Partial(), Embed()
    with pytest.raises(DbUnavailable):
        svc(repo, embed).index(req())
    assert embed.calls == [] and repo.inserts == []


def test_account_table_failure_is_503_no_embedding() -> None:
    class Down(Repo):
        def any_account(self, candidates: list[str]) -> bool:
            raise DbUnavailable("str index account check failed")

    repo, embed = Down(case={"10_8000EBD30"}), Embed()  # 케이스 밖이라 원천 표를 봐야 함
    with pytest.raises(DbUnavailable):
        svc(repo, embed).index(
            with_text("상대 계좌 0100​AAF7C 로")
        )  # 서식 문자를 지운 뒤에도 후보가 남아 표를 봄
    assert embed.calls == [] and repo.inserts == []


def test_same_number_first_even_if_facts_lost() -> None:
    r = req()
    repo, embed = Repo(Stored(request_hash(r), 4, "m@1"), no_facts=True), Embed()
    out = svc(repo, embed).index(r)
    assert (
        out.status is StrIndexStatus.INDEXED
        and out.chunk_count == 4
        and embed.calls == []
        and repo.lookups == 0
    )


def test_same_number_different_body_400_even_if_facts_lost() -> None:
    repo = Repo(Stored("other-hash", 4, "m@1"), no_facts=True)
    with pytest.raises(InvalidRequest):
        svc(repo).index(req())
