"""SCRUM-60 — Codex adversarial 3차 지적 회귀 (docs/str/06).

5개 지적 중 4개(관측값 소비·절 분리·자행/타행·방향)의 재현 사례. PATH/홉은 `_edge.py` 에 있음.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts, SectionV1
from tests.str.verification_support import count, facts_fan_in


def _by_name(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in checks if c.check is CodeCheckName.COUNT_MATCH]


def _by_draft(checks: list[CodeCheck]) -> dict[str | None, CodeCheck]:
    return {c.draft_value: c for c in _by_name(checks)}


def _facts_obs(value: float, inbound: int = 3) -> Facts:
    """observations[0].value = value, inbound.count = inbound (transaction_ids 동기화)."""
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


# ── [high] 관측값 소비가 단위 유무와 무관 (Codex 지적 2) ──


def test_observation_consumes_number_without_unit() -> None:
    """★ `모델 관측값은 31.0이며 입금은 3건` — 31.0 은 결과 없음(단위 없음)지만 '관측 단어 소비' 유지.

    그래야 뒤 3건이 관측값 우선 규칙으로 번지지 않고 ⑤ TX_COUNT(입금) 로 분류. inbound=3 이면 match.
    """
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "모델 관측값은 31.0이며 입금은 3건")
    )
    assert checks and all(c.match for c in checks), (
        f"3건이 관측값(31) 과 대조돼 MISMATCH 로 떨어짐: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_observation_with_unit_then_second_number_no_leak() -> None:
    """회귀: `모델 관측값(24시간 기준) 31개 상대 47건 입금` — 31=관측, 47=inbound(47) 각각 match."""
    checks = _by_name(
        count(
            _facts_obs(31.0, inbound=47),
            SectionV1.WHY_SUSPICIOUS,
            "모델 관측값(24시간 기준) 31개 상대 47건 입금",
        )
    )
    assert checks and all(c.match for c in checks)


# ── [medium] 숫자 뒤 쉼표·마침표·세미콜론 분리 (Codex 지적 3) ──


def test_clause_split_after_number_comma() -> None:
    """`모델 관측값은 31.0, 입금은 3건` — 두 절. 3건이 관측값으로 번지면 안 됨."""
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "모델 관측값은 31.0, 입금은 3건")
    )
    assert checks and all(c.match for c in checks)


def test_clause_split_after_number_period() -> None:
    """`모델 관측값은 31.0. 입금은 3건` — 마침표도 숫자 뒤면 분리."""
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "모델 관측값은 31.0. 입금은 3건")
    )
    assert checks and all(c.match for c in checks)


def test_clause_split_after_number_semicolon() -> None:
    """`모델 관측값은 31.0; 입금은 3건` — 세미콜론도 숫자 뒤면 분리."""
    checks = _by_name(
        count(_facts_obs(31.0, inbound=3), SectionV1.WHY_SUSPICIOUS, "모델 관측값은 31.0; 입금은 3건")
    )
    assert checks and all(c.match for c in checks)


def test_clause_preserves_thousands_comma() -> None:
    """회귀: `입금 1,000건` — 양옆 모두 숫자면 보존(한 절). 분리되면 1 과 000건 으로 깨짐."""
    data = facts_fan_in().model_dump(mode="json")
    ids = list(range(1, 1001))
    data["inbound"]["count"] = 1000
    data["inbound"]["transaction_ids"] = ids
    data["inbound"]["by_currency"][0]["count"] = 1000
    data["inbound"]["by_currency"][0]["transaction_ids"] = ids
    facts = Facts.model_validate(data)
    checks = _by_name(count(facts, SectionV1.WHAT_WHEN_WHERE, "입금 1,000건"))
    assert checks and all(c.match for c in checks)


# ── [medium] 자행·타행 숫자별 최근접 (Codex 지적 4) ──


def test_same_other_bank_both_in_clause() -> None:
    """★ `자행 0개 계좌와 타행 3개 계좌` — 0=SAME_BANK(same=0), 3=OTHER_BANK(other=3). 둘 다 match."""
    checks = _by_name(count(facts_fan_in(), SectionV1.SUMMARY, "자행 0개 계좌와 타행 3개 계좌"))
    draft_map = _by_draft(checks)
    zero_tok = next((c for d, c in draft_map.items() if d and d.startswith("0")), None)
    three_tok = next((c for d, c in draft_map.items() if d and d.startswith("3")), None)
    assert zero_tok is not None and three_tok is not None, f"토큰 둘 다 안 나옴: {list(draft_map)}"
    assert zero_tok.match, f"0개 (자행) 가 MISMATCH 로 떨어짐: source={zero_tok.source_value}"
    assert three_tok.match, f"3개 (타행) 가 MISMATCH 로 떨어짐: source={three_tok.source_value}"


def test_same_bank_mismatch_other_bank_match_in_clause() -> None:
    """`자행 5개 계좌와 타행 3개 계좌` — 5 는 자행(=0) MISMATCH, 3 은 타행(=3) match."""
    checks = _by_name(count(facts_fan_in(), SectionV1.SUMMARY, "자행 5개 계좌와 타행 3개 계좌"))
    draft_map = _by_draft(checks)
    five_tok = next((c for d, c in draft_map.items() if d and d.startswith("5")), None)
    three_tok = next((c for d, c in draft_map.items() if d and d.startswith("3")), None)
    assert five_tok is not None and three_tok is not None
    assert not five_tok.match
    assert three_tok.match


# ── [medium] 방향(입금·출금·내부) 숫자별 최근접 (Codex 지적 5) ──


def test_direction_in_out_both_in_clause() -> None:
    """★ `입금 3건이며 출금 0건` — 3=입금(inbound 3) match, 0=출금(outbound 0) match."""
    checks = _by_name(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "입금 3건이며 출금 0건"))
    draft_map = _by_draft(checks)
    three_tok = next((c for d, c in draft_map.items() if d and d.startswith("3")), None)
    zero_tok = next((c for d, c in draft_map.items() if d and d.startswith("0")), None)
    assert three_tok is not None and zero_tok is not None, f"토큰 안 나옴: {list(draft_map)}"
    assert three_tok.match, f"3건 (입금) MISMATCH: {three_tok.source_value}"
    assert zero_tok.match, f"0건 (출금) MISMATCH: {zero_tok.source_value}"


def test_direction_three_ways_split_by_commas() -> None:
    """회귀: `입금 3건, 출금 0건, 내부거래는 0건` — 세 절. 각 절 안 방향 단어 하나 → 전부 match."""
    checks = _by_name(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "입금 3건, 출금 0건, 내부거래는 0건"))
    assert checks and all(c.match for c in checks), (
        f"쉼표로 분리된 절 오탐: {[(c.draft_value, c.source_value, c.reason) for c in checks if not c.match]}"
    )


def test_direction_mismatch_still_caught_per_number() -> None:
    """`입금 100건이며 출금 0건` — 100=입금(3) MISMATCH, 0=출금(0) match. 숫자별로 독립 분류."""
    checks = _by_name(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "입금 100건이며 출금 0건"))
    draft_map = _by_draft(checks)
    hundred = next((c for d, c in draft_map.items() if d and d.startswith("100")), None)
    zero_tok = next((c for d, c in draft_map.items() if d and d.startswith("0")), None)
    assert hundred is not None and zero_tok is not None
    assert not hundred.match
    assert zero_tok.match


def test_direction_tie_distance_unparsed() -> None:
    """★ 거리 동률 UNPARSED: `출금 0건 내부` — 0건 앞뒤 거리 같으면 방향 애매 → UNPARSED."""
    checks = _by_name(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "출금 0건 내부"))
    bad = [c for c in checks if not c.match]
    assert bad and all(c.reason is CheckReason.UNPARSED for c in bad), (
        f"방향 동률이 UNPARSED 아님: {[(c.draft_value, c.reason) for c in checks]}"
    )
