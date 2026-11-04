"""SCRUM-60 — Codex adversarial 4차 지적 회귀 (docs/str/06).

- 괄호 속 관측값 소비: `모델 관측값(31)이며 입금은 3건` 에서 `31` 을 소비해 3건이 inbound 와 대조.
- 계좌·곳 단위는 상대 수: `3계좌를 거친 경로 2개` 에서 3계좌 가 PATH 가 아니라 COUNTERPARTY.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts, SectionV1
from tests.str.verification_support import count, facts_cycle, facts_fan_in


def _by_name(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in checks if c.check is CodeCheckName.COUNT_MATCH]


def _only_fail(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in _by_name(checks) if not c.match]


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


# ── [high] 괄호 속 관측값도 소비 (adversarial 4차 지적 1) ──


def test_observation_in_parens_consumes_and_blocks_leak() -> None:
    """★ `모델 관측값(31)이며 입금은 3건` — 31(괄호 안) 소비, 3건 = inbound(3) match."""
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "모델 관측값(31)이며 입금은 3건")
    )
    # 3건은 inbound(3) 과 대조돼 match (관측값 우선이 번지지 않음)
    assert checks and all(c.match for c in checks), (
        f"3건이 관측값 우선으로 번짐: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_observation_in_parens_mismatch_31_inbound() -> None:
    """★ `모델 관측값(31)이며 입금은 31건` — 31건은 inbound(3) 과 대조돼 MISMATCH."""
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "모델 관측값(31)이며 입금은 31건")
    )
    # 31건 은 결과(토큰) 가 있어야 하고 inbound=3 와 불일치
    draft_vals = [c.draft_value for c in checks]
    assert any(d and "31" in d and "건" in d for d in draft_vals), f"31건 토큰 없음: {draft_vals}"
    bad = _only_fail(checks)
    assert bad and any(c.reason is CheckReason.MISMATCH for c in bad)


def test_observation_period_skipped_number_31_consumed_next() -> None:
    """회귀: `모델 관측값(24시간 기준) 31개 상대 47건` — 24시간 건너뜀, 31=관측, 47=inbound(47)."""
    checks = _by_name(
        count(
            _facts_obs(31.0, inbound=47), SectionV1.WHY_SUSPICIOUS, "모델 관측값(24시간 기준) 31개 상대 47건"
        )
    )
    assert checks and all(c.match for c in checks)


def test_observation_parens_period_before_bare_number() -> None:
    """`관측값은 (24시간 기준) 31` — 24시간 건너뛰고 31 소비. 31 자체는 단위 없음이라 결과 없음."""
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "관측값은 (24시간 기준) 31")
    )
    # 결과 없음(단위 없는 숫자) — 어쨌든 소비 됐고 뒤 숫자가 없으니 오탐 없음
    assert checks == [], f"단위 없는 31 이 토큰이 됨: {[(c.draft_value, c.reason) for c in checks]}"


# ── [medium] 계좌·곳 단위는 COUNTERPARTY (adversarial 4차 지적 2) ──


def test_bare_counterparty_unit_three_counterparty_match() -> None:
    """★ `3계좌를 거친 경로 2개` (facts_cycle VERIFIED, max_accounts=3, count=2):
    `3계좌` = COUNTERPARTY (상대 수) match · `2개` = PATH match."""
    facts = facts_cycle("VERIFIED")
    checks = _by_name(count(facts, SectionV1.HOW, "3계좌를 거친 경로 2개"))
    draft_map = {c.draft_value: c for c in checks}
    three = next((c for d, c in draft_map.items() if d and "3" in d), None)
    two = next((c for d, c in draft_map.items() if d and "2" in d), None)
    assert three is not None and two is not None, f"토큰 둘 다 안 나옴: {list(draft_map)}"
    assert three.match, f"3계좌 (상대 수) MISMATCH: source={three.source_value}"
    assert two.match, f"2개 (경로 수) MISMATCH: source={two.source_value}"


def test_bare_counterparty_unit_two_counterparty_mismatch() -> None:
    """★ `2계좌를 거친 경로 2개` — 2계좌는 counterparties.count(=3) 와 다르므로 MISMATCH."""
    facts = facts_cycle("VERIFIED")
    checks = _by_name(count(facts, SectionV1.HOW, "2계좌를 거친 경로 2개"))
    draft_map = {c.draft_value: c for c in checks}
    # 첫 번째 "2" 는 "2계좌" (COUNTERPARTY), 두 번째 "2" 는 "2개" (PATH)
    two_cp = next((c for d, c in draft_map.items() if d and d.startswith("2계좌")), None)
    two_path = next((c for d, c in draft_map.items() if d and d.startswith("2개")), None)
    assert two_cp is not None and two_path is not None, f"토큰 분리 안 됨: {list(draft_map)}"
    # 2계좌 는 상대 수 = 3 과 MISMATCH. facts_cycle max_accounts=3 도 포함됐지만 2 는 그 집합에 없음.
    assert not two_cp.match, f"2계좌 가 match 로 통과: source={two_cp.source_value}"
    assert two_cp.reason is CheckReason.MISMATCH
    assert two_path.match, f"2개 (경로 수) MISMATCH: source={two_path.source_value}"


def test_counterparty_with_separator_unit_still_passes() -> None:
    """회귀: `3개 계좌를 거친 경로 2개` — `3개` = COUNTERPARTY, `2개` = PATH (기존 동작)."""
    facts = facts_cycle("VERIFIED")
    checks = _by_name(count(facts, SectionV1.HOW, "3개 계좌를 거친 경로 2개"))
    assert checks and all(c.match for c in checks)
