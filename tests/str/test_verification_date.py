"""SCRUM-59 — DATE_MATCH 통과·오탐 막기. docs/str/06 DATE_MATCH 줄, 08 "정상 문장 오탐 테스트".

세 파일로 나눔(파일 200·함수 40 관문):
- 이 파일: 통과(녹화 v1·v2 포함) + 오탐 막기(날짜 아닌 표현)
- `test_verification_date_mismatch.py`: 잡기(MISMATCH·UNPARSED·MISSING)
- `test_verification_date_scope.py`: 괄호 관측 분기(★B 보충 — 괄호 바로 앞/안·관측+개설 UNPARSED·괄호 밖 거래)
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, SectionV1, SectionV2
from tests.str.verification_support import date, facts_fan_in


def _only_matches(checks: list) -> list:
    return [c for c in checks if c.match]


def _mismatches(checks: list) -> list:
    return [c for c in checks if not c.match]


def test_narrative_ok_summary_date_matches() -> None:
    """`2022-09-02 하루 동안` — 거래 날짜 period 안(날짜만)."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022-09-02 하루 동안 입금")
    assert len(out) == 1 and out[0].match
    assert out[0].draft_value == "2022-09-02"


def test_narrative_ok_who_onboarded_matches() -> None:
    """`계좌 개설일 2021-03-14` — 개설 단어 ±10자 → onboarded_at 일치."""
    out = date(facts_fan_in(), SectionV1.WHO, "계좌 개설일 2021-03-14임")
    assert len(out) == 1 and out[0].match
    assert "onboarded_at" in (out[0].source_value or "")


def test_narrative_ok_what_when_where_pair_in_period() -> None:
    """`2022-09-02 00:14부터 22:51 사이` — 00:14 쌍 1건만. 22:51 은 시각만 따로 → 결과 없음."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2022-09-02 00:14부터 22:51 사이")
    assert len(out) == 1 and out[0].match
    # draft 조각이 날짜+시각(ISO 결합이든 공백 결합이든) 모양
    assert "2022-09-02" in out[0].draft_value and "00:14" in out[0].draft_value


def test_v1_recording_who_birthdate_matches() -> None:
    """v1 녹화 WHO `고객 가입일은 2021-03-14` — `가입` 이 ONBOARD_WORDS."""
    out = date(facts_fan_in(), SectionV1.WHO, "고객 가입일은 2021-03-14이고 과거 경보 이력은 1건임")
    assert len(_only_matches(out)) == 1
    assert "onboarded_at" in (_only_matches(out)[0].source_value or "")


def test_v1_recording_what_when_where_iso_t_matches() -> None:
    """v1 녹화 `거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지` — ISO T + 초 환원."""
    out = date(
        facts_fan_in(),
        SectionV1.WHAT_WHEN_WHERE,
        "거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지이며, ACH 입금 3건.",
    )
    matches = _only_matches(out)
    assert len(matches) == 2  # 두 ISO T 날짜+시각 쌍, 둘 다 period 끝점이라 통과
    assert all("2022-09-02T" in c.draft_value for c in matches)


def test_v1_recording_observation_bracket_prefix_matches() -> None:
    """★★ v1 녹화 — `모델 관측값(2022-09-02T00:00:00부터 2022-09-03T00:00:00까지, ...)`.

    여는 괄호 **바로 앞** 이 `관측값` 으로 끝남 → 괄호 안 두 날짜는 observation 용도. ★B 보충 핵심 회귀.
    """
    text = (
        "다수 상대방의 입금이 집중되는 FAN_IN 유형이라는 점에서 자금세탁 의심 여부의 검토가 필요함. "
        "모델이 주목한 항목은 입금 상대방 수이며, "
        "모델 관측값(2022-09-02T00:00:00부터 2022-09-03T00:00:00까지, 24시간 기준)은 3.0으로 제시됨."
    )
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, text)
    assert all(c.match for c in out), [(c.draft_value, c.source_value, c.reason) for c in out if not c.match]
    assert len(_only_matches(out)) == 2
    assert all("observation" in (c.source_value or "") for c in _only_matches(out))


def test_v2_recording_date_section_matches() -> None:
    """v2 녹화 DATE `거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지임`."""
    out = date(
        facts_fan_in(), SectionV2.DATE, "거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지임."
    )
    matches = _only_matches(out)
    assert len(matches) == 2


def test_v2_recording_observation_bracket_inside_matches() -> None:
    """★★ v2 녹화 — `모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-03T00:00:00 기준)`.

    괄호 **안** 에 `관측 구간` 이 있음 → 괄호 안 두 날짜는 observation.
    """
    text = (
        "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-03T00:00:00 기준)에서 "
        "서로 다른 입금 상대방 수는 3.0으로 관측됨."
    )
    out = date(facts_fan_in(), SectionV2.GROUNDS, text)
    assert all(c.match for c in out), [(c.draft_value, c.source_value, c.reason) for c in out if not c.match]
    assert len(_only_matches(out)) == 2
    assert all("observation" in (c.source_value or "") for c in _only_matches(out))


# ── 오탐 막기(날짜 아님 → 결과 없음) ─────────────────────────────────


def test_amount_text_not_a_date() -> None:
    assert date(facts_fan_in(), SectionV1.SUMMARY, "42,750.50 US Dollar") == []


def test_decimal_not_a_date() -> None:
    """`3.0으로` — `3.0` 이 날짜 `2022.9.2` 모양 아님(연·월·일 셋 다 숫자여야 함)."""
    assert date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "3.0으로 제시됨") == []


def test_duration_hours_not_a_date() -> None:
    assert date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "24시간 기준") == []


def test_account_id_not_a_date() -> None:
    assert date(facts_fan_in(), SectionV1.WHO, "대상 계좌는 10_****BD30임") == []


def test_rule_id_not_a_date() -> None:
    assert date(facts_fan_in(), SectionV1.HOW, "R04_CYCLE 룰로 분류됨") == []


def test_count_only_not_a_date() -> None:
    """SUMMARY 섹션으로 — WHAT_WHEN_WHERE 는 날짜 0개면 MISSING 이 추가되는 섹션."""
    assert date(facts_fan_in(), SectionV1.SUMMARY, "입금 3건") == []


def test_time_only_without_date_not_matched() -> None:
    """시각만 따로(`22:51`)는 날짜와 쌍이 아니면 대조 안 함. SUMMARY 섹션으로(MISSING 회피)."""
    assert date(facts_fan_in(), SectionV1.SUMMARY, "22:51 입금") == []


# ── v1·v2 둘 다 돌아야 — EVIDENCE_IN_SCOPE 처럼 섹션 상관없이 ───────


def test_section_v2_subject_onboarded_matches() -> None:
    """v2 집합 SUBJECT 섹션에서도 개설 단어가 돈다."""
    out = date(facts_fan_in(), SectionV2.SUBJECT, "계좌 개설일 2021-03-14임")
    assert len(_only_matches(out)) == 1


def test_check_name_is_date_match() -> None:
    """결과 `check` 가 `DATE_MATCH` — 다른 check 로 섞여 들어가지 않음."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022-09-02 입금")
    assert all(c.check is CodeCheckName.DATE_MATCH for c in out)


def test_reason_none_when_match() -> None:
    """match=true 면 reason=None."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022-09-02 입금")
    assert out[0].reason is None


def test_mismatch_reason_is_mismatch() -> None:
    """`9월 5일`(주입 3) — 기간 밖 → reason=MISMATCH 로만 (UNPARSED/OUT_OF_SCOPE/MISSING 아님)."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "9월 5일 입금")
    bad = _mismatches(out)
    assert len(bad) == 1 and bad[0].reason is CheckReason.MISMATCH
