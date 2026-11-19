"""질문 답변 응답 draft_value 허용 모양 (SCRUM-290 2/2 추가 검토 2, docs/str/06 "질문 답변" 7번)."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName
from aml_ai.str.domain.ask_public import MASK, public_checks


def _check(draft: str | None, match: bool = False) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.AMOUNT_MATCH,
        section=None,
        draft_value=draft,
        source_value="inbound USD 42750.50",
        match=match,
        reason=None if match else CheckReason.MISMATCH,
    )


@pytest.mark.parametrize(
    "draft",
    [
        "3건",
        "1,200건",
        "2단계",
        "30 계좌",
        "42750.50 (USD)",
        "42,750.50 (USD)",
        "2022-09-02",
        "2022-09-02T00:14:00",
        "2022-09-02 00:14",
        "2022년 9월 2일 00:14",
        "9월 2일 오후 2시 30분",
        "2022/09/02",
        "2022.9.2",
        "10_****BD30",
        "****BD30",
        "끝자리 BD30",
        "인용 키 범위 밖 2개",
    ],
)
def test_allowed_shapes_are_kept(draft: str) -> None:
    (out,) = public_checks([_check(draft)])
    assert out.draft_value == draft


@pytest.mark.parametrize(
    "draft",
    ["999 자금세탁 확정 (USD)", "세 곳", "서른한 건", "입금 거래는 모두 5건이에요.", "3건 확정", "abc"],
)
def test_other_text_is_masked(draft: str) -> None:
    (out,) = public_checks([_check(draft)])
    assert out.draft_value == MASK
    assert out.source_value == "inbound USD 42750.50" and out.match is False  # 다른 칸은 그대로


def test_none_stays_none() -> None:
    (out,) = public_checks([_check(None, match=True)])
    assert out.draft_value is None
