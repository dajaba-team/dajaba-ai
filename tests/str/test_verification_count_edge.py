"""SCRUM-60 — COUNT_MATCH 경계 테스트 (관측값 우선·MISMATCH·UNPARSED·경로). docs/str/06.

기본 (정상 통과·결과 없음)은 `test_verification_count.py`. 녹화 통과는 `_recorded.py`.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    SectionV1,
)
from tests.str.verification_support import (
    count,
    facts_cycle,
    facts_fan_in,
    facts_with_observation_value,
)


def _by_name(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in checks if c.check is CodeCheckName.COUNT_MATCH]


def _only_fail(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in _by_name(checks) if not c.match]


def _facts_inbound_47_obs_31() -> Facts:
    data = facts_fan_in().model_dump(mode="json")
    ids_47 = list(range(1, 48))
    data["inbound"]["count"] = 47
    data["inbound"]["transaction_ids"] = ids_47
    data["inbound"]["by_currency"][0]["count"] = 47
    data["inbound"]["by_currency"][0]["transaction_ids"] = ids_47
    data["observations"] = [
        {
            "name": "x",
            "value": 31,
            "unit": "count",
            "window_start": "2022-09-02T00:00:00",
            "window_end": "2022-09-03T00:00:00",
            "basis": None,
            "baseline": None,
        }
    ]
    return Facts.model_validate(data)


# ── 관측값 우선 (★ 5문장) ──


def test_observation_first_number_31() -> None:
    """`모델 관측값 … 31개 상대` — 31 은 관측값 `{31}` 과 대조."""
    facts = facts_with_observation_value(31)
    checks = _by_name(count(facts, SectionV1.WHY_SUSPICIOUS, "모델 관측값(24시간 기준) 31개 상대"))
    assert checks and all(c.match for c in checks)


def test_observation_prefers_value_over_counterparties() -> None:
    """★ draft_response 본문: `모델 관측값(…) 입금 상대 계좌 수가 3개로` — 3.0 ≡ 3."""
    checks = _by_name(
        count(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "모델 관측값(24시간 기준) 입금 상대 계좌 수가 3개로")
    )
    assert checks and all(c.match for c in checks)


def test_observation_first_only_then_inbound() -> None:
    """★ 진희 좁힘: `모델 관측값 … 상대 31곳에서 47건 입금` — 31=관측, 47=inbound."""
    checks = _by_name(
        count(
            _facts_inbound_47_obs_31(), SectionV1.WHY_SUSPICIOUS, "모델 관측값 기준 상대 31곳에서 47건 입금"
        )
    )
    assert checks and all(c.match for c in checks), (
        f"관측값 우선 첫 번째만 적용 실패: {[(c.draft_value, c.source_value, c.reason) for c in checks]}"
    )


def test_observation_float_no_unit_skipped() -> None:
    """v1 녹화: `모델 관측값(…) 3.0으로 제시됨` — 단위 없음 → 결과 없음."""
    checks = _by_name(count(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "모델 관측값은 3.0으로 제시됨"))
    assert checks == []


def test_observation_comma_splits_clauses() -> None:
    """06: `모델 관측 상대 31개, 입금 47건` — 쉼표 뒤 절은 관측값 아님."""
    checks = _by_name(
        count(_facts_inbound_47_obs_31(), SectionV1.WHY_SUSPICIOUS, "모델 관측 상대 31개, 입금 47건")
    )
    assert checks and all(c.match for c in checks)


# ── MISMATCH (오류 주입 4·27·28 + 방향·종류) ──


def test_prior_alert_mismatch() -> None:
    bad = _only_fail(count(facts_fan_in(), SectionV1.WHO, "과거 경보 47건"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_inbound_wrong_number() -> None:
    bad = _only_fail(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "입금 100건"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_outbound_wrong_number() -> None:
    bad = _only_fail(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "출금 100건"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_payment_format_mismatch() -> None:
    """오류 주입 27: `ACH 50건`(ACH 3) → MISMATCH."""
    bad = _only_fail(count(facts_fan_in(), SectionV1.HOW, "ACH 50건"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_bank_split_mismatch() -> None:
    """오류 주입 28: `자행 5 계좌`(자행 0) → MISMATCH."""
    bad = _only_fail(count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "자행 5 계좌"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_counterparty_wrong_number() -> None:
    """오류 주입 4: `13개 계좌`(상대 수 3) → MISMATCH."""
    bad = _only_fail(count(facts_fan_in(), SectionV1.SUMMARY, "13개 계좌"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


# ── UNPARSED ──


def test_korean_numeral_unparsed() -> None:
    """오류 주입 20: `서른한 개 계좌` → UNPARSED."""
    bad = _only_fail(count(facts_fan_in(), SectionV1.SUMMARY, "서른한 개 계좌"))
    assert bad and all(c.reason is CheckReason.UNPARSED for c in bad)


def test_overlapping_kinds_unparsed() -> None:
    """과거 경보 + 관측 단어가 같은 절 → 종류 중첩, UNPARSED."""
    bad = _only_fail(count(facts_fan_in(), SectionV1.WHO, "과거 경보 관측 31건"))
    assert bad and all(c.reason is CheckReason.UNPARSED for c in bad)


# ── 경로 (미결 26 AI 몫 닫음) ──


def test_cycle_verified_passes() -> None:
    """오류 주입 24: VERIFIED cycle facts(count=2, max_accounts=3)에 `3개 계좌 … 순환 경로 2개`."""
    text = "3개 계좌를 거쳐 원래 계좌로 돌아오는 순환 경로 2개"
    checks = _by_name(count(facts_cycle("VERIFIED"), SectionV1.HOW, text))
    assert checks and all(c.match for c in checks)


def test_cycle_verified_wrong_mismatch_each_number() -> None:
    """오류 주입 25 (Codex adversarial 3차 반영): `4개 계좌 … 순환 경로 3개` — **두 숫자 각각** MISMATCH.

    facts_cycle(VERIFIED): count=2, max_accounts=3, max_hops=3. "4개 계좌" → 상대 수(cp=3) MISMATCH.
    "순환 경로 3개" → PATH(count=2) MISMATCH. max_hops=3 와 통과하면 안 됨(PATH 는 count 와만 비교).
    """
    checks = _by_name(count(facts_cycle("VERIFIED"), SectionV1.HOW, "4개 계좌를 거쳐 순환 경로 3개"))
    by_draft = {c.draft_value: c for c in checks}
    assert any("4" in d for d in by_draft), f"4개 계좌 토큰 없음: {list(by_draft)}"
    assert any("3" in d and "3개" in d for d in by_draft), f"3개 토큰 없음: {list(by_draft)}"
    four = next(c for d, c in by_draft.items() if "4" in d)
    three = next(c for d, c in by_draft.items() if d != four.draft_value and "3" in d)
    assert not four.match and four.reason is CheckReason.MISMATCH
    assert not three.match and three.reason is CheckReason.MISMATCH


def test_cycle_verified_path_only_wrong_mismatch() -> None:
    """★ Codex adversarial 3차 신규: 경로 수만 틀린 사례 — `순환 경로 3개`(paths.count=2) → MISMATCH.

    max_hops=3 와 우연히 같아도 PATH 는 count 와만 비교하므로 MISMATCH 여야 함.
    """
    bad = _only_fail(count(facts_cycle("VERIFIED"), SectionV1.HOW, "순환 경로 3개"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_cycle_hop_unit_matches_max_hops() -> None:
    """PATH_HOPS 분리: `3홉`·`3단계` 는 max_hops=3 과 통과. 단위 `홉` 은 PATH 집합에 안 들어감."""
    for text in ("3홉 경로", "3단계 경로"):
        checks = _by_name(count(facts_cycle("VERIFIED"), SectionV1.HOW, text))
        assert checks and all(c.match for c in checks), f"{text}: {checks}"


def test_cycle_unverified_mismatch() -> None:
    """오류 주입 26 (미결 26 AI 몫): UNVERIFIED 인데 경로 숫자 인용 → MISMATCH."""
    bad = _only_fail(count(facts_cycle("UNVERIFIED"), SectionV1.HOW, "순환 경로 2개"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_no_paths_mismatch() -> None:
    """paths=None(경로형 아님)인데 경로 단어 인용 → MISMATCH."""
    bad = _only_fail(count(facts_fan_in(), SectionV1.HOW, "순환 경로 2개"))
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)
