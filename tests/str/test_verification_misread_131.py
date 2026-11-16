"""SCRUM-131 (2/n) — 검사기 오판 회귀 (docs/str/06 DATE_MATCH ②, 08 오판 회귀 줄).

A `등록일` 개설 단어 · B 괄호 없는 관측 기간은 거래 날짜로 고정(추가 검토 2차에서 되돌림).
C(은행·상대 경쟁)는 추가 검토 3차에서 되돌려 테스트 없음(develop 동작).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CodeCheck, SectionV1
from tests.str.verification_support import date, facts_fan_in

B_TEXT = "모델 관측값은 2022-09-02T00:00:00부터 2022-09-03T00:00:00까지의 24시간 기준 3.0"


def _sources(checks: list[CodeCheck]) -> list[tuple[str | None, str | None, bool]]:
    return [(c.draft_value, c.source_value, c.match) for c in checks]


# ── A 등록일 ──


def test_a_registered_date_is_onboard() -> None:
    """v1 녹화 WHO — `등록일` 은 개설일 용도 → onboarded_at 과 match (전: 거래 날짜 → 기간 밖 MISMATCH)."""
    out = date(facts_fan_in(), SectionV1.WHO, "고객 등록일은 2021-03-14이며 등록 업종은 소매업")
    assert len(out) == 1 and out[0].match, _sources(out)
    assert (out[0].source_value or "").startswith("onboarded_at")


def test_a_bare_register_word_is_not_onboard() -> None:
    """`등록` 단독(`등록 업종`)은 개설 단어 아님 → 날짜는 거래 날짜 그대로."""
    out = date(facts_fan_in(), SectionV1.WHO, "등록 업종 변경 2021-03-14")
    assert len(out) == 1 and not out[0].match
    assert (out[0].source_value or "").startswith("period")


# ── B 괄호 없는 관측 기간 ──


@pytest.mark.parametrize(
    "text",
    [
        B_TEXT,
        "모델 관측값은 2022-09-02T00:00:00~2022-09-03T00:00:00 기준 3.0",
        "관측 구간은 2022-09-02T00:00:00 ~ 2022-09-03T00:00:00이며 값은 3.0",
    ],
)
def test_b_unbracketed_observation_range_is_transaction(text: str) -> None:
    """괄호 없는 관측 범위는 인정 안 함(추가 검토 2차) → 거래 날짜, 시각까지 기간 밖이라 둘 다 MISMATCH."""
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, text)
    assert len(out) == 2 and not any(c.match for c in out), _sources(out)
    assert all((c.source_value or "").startswith("period") for c in out)


def test_b_transaction_word_between_blocks_observation() -> None:
    """관측 단어와 범위 사이에 `거래`·`기간` → 거래 날짜(09-01 기간 밖 MISMATCH, 09-02 match)."""
    out = date(
        facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "관측값은 3.0이며 거래 기간은 2022-09-01부터 2022-09-02까지"
    )
    assert [c.match for c in out] == [False, True], _sources(out)
    assert all((c.source_value or "").startswith("period") for c in out)


def test_b_single_date_stays_transaction() -> None:
    """범위 아닌 단독 날짜 — 관측 단어 있어도 거래 날짜(기간 밖 MISMATCH 그대로)."""
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "관측값 산출일 2022-09-05")
    assert len(out) == 1 and not out[0].match
    assert (out[0].source_value or "").startswith("period")


def test_b_range_in_other_clause_stays_transaction() -> None:
    """관측 단어가 앞 절(`.` 뒤)에 있으면 범위는 거래 날짜."""
    out = date(
        facts_fan_in(),
        SectionV1.WHY_SUSPICIOUS,
        "모델 관측값은 3.0임. 2022-09-02T00:00:00부터 2022-09-03T00:00:00까지 입금",
    )
    assert all((c.source_value or "").startswith("period") for c in out), _sources(out)


def test_b_only_first_range_after_observation_word() -> None:
    """관측 단어와 범위 사이에 다른 날짜가 있으면 그 범위는 관측 아님(첫 날짜만 시작점)."""
    out = date(
        facts_fan_in(),
        SectionV1.WHY_SUSPICIOUS,
        "관측값 3.0 산출일 2022-09-02 이후 2022-09-02T00:00:00부터 2022-09-03T00:00:00까지",
    )
    assert all((c.source_value or "").startswith("period") for c in out), _sources(out)


def test_verifier_version_bumped() -> None:
    """같은 본문 결과가 바뀌므로 11.4 → 11.5 (131-1 의 11.4 단언을 옮김)."""
    from aml_ai.str.domain.constants import VERIFIER_VERSION

    assert VERIFIER_VERSION == "verify-2026.11.5"
