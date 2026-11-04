"""SCRUM-60 — Codex adversarial 5차 지적 회귀 (docs/str/06).

- 기간 단위 경계: "31 일반 계좌"·"3 주요 상대" 접두사를 기간으로 잘못 잡는 오탐.
- 날짜 제외: "10월 3일" 의 10·3 이 관측 소비·COUNT 비교에 끼어드는 오탐.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts, SectionV1
from tests.str.verification_support import count, facts_fan_in


def _by_name(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in checks if c.check is CodeCheckName.COUNT_MATCH]


def _facts_obs(value: float, inbound: int = 3) -> Facts:
    data = facts_fan_in().model_dump(mode="json")
    ids = list(range(1, inbound + 1))
    data["inbound"]["count"] = inbound
    data["inbound"]["transaction_ids"] = ids
    data["inbound"]["by_currency"][0]["count"] = inbound
    data["inbound"]["by_currency"][0]["transaction_ids"] = ids
    data["observations"] = [
        {
            "name": "x",
            "value": value,
            "unit": "count",
            "window_start": "2022-09-02T00:00:00",
            "window_end": "2022-09-03T00:00:00",
            "basis": None,
            "baseline": None,
        }
    ]
    return Facts.model_validate(data)


# ── [high] 기간 단위 경계 (adversarial 5차 지적 1) ──


def test_period_boundary_bare_prefix_not_consumed() -> None:
    """★ `관측값 31 일반 계좌이며 입금은 31건` — `31 일` 을 기간으로 보면 31 소비, 31건 이 관측값 통과.

    공백 없는 경우만 기간이어야 하므로 31 이 소비 안 됨. 31 자체가 관측(=31) → match. 31건 은
    같은 절 두 번째 숫자라 관측 우선 미적용 → TX_COUNT(입금), inbound=3 과 MISMATCH.
    """
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "관측값 31 일반 계좌이며 입금은 31건")
    )
    draft_map = {c.draft_value: c for c in checks}
    # 31건 토큰이 있어야 하고 MISMATCH 여야 함(inbound=3)
    bad_31 = next((c for d, c in draft_map.items() if d and "31" in d and "건" in d and not c.match), None)
    assert bad_31 is not None and bad_31.reason is CheckReason.MISMATCH, (
        f"31건 이 MISMATCH 로 안 떨어짐 — 기간 오탐 의심: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_period_boundary_bare_prefix_two_cases() -> None:
    """`관측값 3 주요 상대 31건` — `3 주` 가 기간이 아니라야 함. 3 소비, 31건=inbound(31)."""
    checks = _by_name(
        count(_facts_obs(3.0, inbound=31), SectionV1.WHY_SUSPICIOUS, "관측값 3 주요 상대이며 입금 31건")
    )
    # 31건 은 inbound=31 match, 3개 토큰이 아닌 "주요 상대" 라 기타 토큰 있을 수 있지만 모두 match
    assert checks and all(c.match for c in checks), (
        f"3 주요 의 3 이 기간으로 잘못 걸림: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_period_attached_still_skipped() -> None:
    """회귀: `관측값 24시간 기준 31개 상대 47건 입금`(공백 없이 24시간) — 24 건너뛰고 31 소비, 47 match."""
    data = _facts_obs(31.0, inbound=47).model_dump(mode="json")
    facts = Facts.model_validate(data)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "관측값 24시간 기준 31개 상대 47건 입금"))
    assert checks and all(c.match for c in checks)


def test_period_suffix_allowed_gan_dongan() -> None:
    """`관측값 3일간 … 31개 상대`·`관측값 3개월 동안 … 31개 상대` — 3일·3개월 건너뛰고 31 소비."""
    facts = _facts_obs(31.0, inbound=3)
    for text in ("관측값 3일간 활동 31개 상대", "관측값 3개월 동안 활동 31개 상대"):
        checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, text))
        assert checks and all(c.match for c in checks), f"{text}: {checks}"


# ── [high] 날짜 전체 span 제외 (adversarial 5차 지적 2) ──


def test_date_month_day_excluded_from_observation_consumption() -> None:
    """★ `관측값(10월 3일 기준) 31개 상대` — 10월 3일 전체 제외, 31 이 관측 소비, counterparties=3."""
    facts = _facts_obs(31.0, inbound=3)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "관측값(10월 3일 기준) 31개 상대"))
    assert checks and all(c.match for c in checks), (
        f"날짜 10월 3일 의 10 이 관측 소비해 31 이 다른 집합과 비교됨: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_date_month_day_excluded_wrong_observation_mismatch() -> None:
    """★ `관측값(10월 3일 기준) 3개 상대` — 날짜 제외 뒤 3 이 관측 소비, obs=31 과 MISMATCH."""
    facts = _facts_obs(31.0, inbound=3)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "관측값(10월 3일 기준) 3개 상대"))
    bad = [c for c in checks if not c.match]
    assert bad and any(c.reason is CheckReason.MISMATCH for c in bad), (
        f"3 이 counterparties=3 과 match 돼 관측 검증 우회: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_date_with_year_excluded() -> None:
    """회귀: 연도 포함 `관측값(2022년 10월 3일 기준) 31개 상대` — 전체 날짜 span 제외 → 31 관측 match."""
    facts = _facts_obs(31.0, inbound=3)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "관측값(2022년 10월 3일 기준) 31개 상대"))
    assert checks and all(c.match for c in checks)


def test_date_with_year_mismatch() -> None:
    """`관측값(2022년 10월 3일 기준) 3개 상대` — 날짜 제외 뒤 3 이 관측 소비, obs=31 과 MISMATCH."""
    facts = _facts_obs(31.0, inbound=3)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "관측값(2022년 10월 3일 기준) 3개 상대"))
    bad = [c for c in checks if not c.match]
    assert bad and any(c.reason is CheckReason.MISMATCH for c in bad)


def test_iso_date_excluded() -> None:
    """ISO `2022-10-03` 도 전체 span 제외 — `관측값(2022-10-03 기준) 31개 상대` match."""
    facts = _facts_obs(31.0, inbound=3)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "관측값(2022-10-03 기준) 31개 상대"))
    assert checks and all(c.match for c in checks)
