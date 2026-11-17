"""SCRUM-264 — v4 관측값 표기 사전 이름 기준 (docs/str/05 narrative_v4 "표기 사전"·GROUNDS 슬롯).

실제 reasons 형식(basis `model_feature`, unit·window·baseline null)으로 v4 가 생성되는지,
20개 표기 문구가 06 코드 검사를 그대로 통과하는지(문구 속 숫자·한글 수사 → 여기서 잡힘).
"""

from __future__ import annotations

import re

import pytest

from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.shared.errors import NarrativeAssemblyFailed
from aml_ai.shared.schemas.str import Facts, ObservationFacts
from aml_ai.str.domain.constants_ml import ML_META_FEATURES
from aml_ai.str.domain.display_format import topic_before_paren
from aml_ai.str.domain.display_labels_check import missing_labels
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.facts_support import CASES, build, make_req
from tests.str.v4_slot_support import assembled, failures, load_fixture

LABELS = load_display_labels()
REAL = load_json(FIXTURES / "reasons_real_r02.json")
# 준영 11/17 피처 31개 — 기본 18 + 추가 13
ML_FEATURES = {
    "evidence_count", "evidence_span_seconds", "evidence_min_gap_seconds", "evidence_max_gap_seconds",
    "focal_in_count", "focal_out_count", "focal_distinct_senders", "focal_distinct_receivers",
    "evidence_account_count", "paid_raw_currency_count", "received_raw_currency_count", "payment_format_count",
    *(f"rule_r0{i}" for i in range(1, 7)),
    "evidence_ach_fraction", "evidence_cheque_fraction", "evidence_cash_fraction", "evidence_paid_max_share",
    "evidence_received_max_share", "evidence_span_fraction_96h", "evidence_last_hour_fraction",
    "evidence_min_path_hops_scaled", "evidence_features_applicable", "evidence_payment_known_fraction",
    "evidence_paid_ratio_coverage", "evidence_received_ratio_coverage", "evidence_path_available",
}  # fmt: skip
NAMED = sorted(ML_FEATURES - ML_META_FEATURES)
SAMPLE_VALUE = {"건": 3.0, "개": 2.0, "초": 106320.0, "": 0.25}
JUDGMENT_WORDS = ("의심", "이례", "비정상", "특이", "위험")


def _obs(
    name: str, value: float, *, window: tuple[str | None, str | None] = (None, None)
) -> ObservationFacts:
    return ObservationFacts(
        name=name, value=value, unit=None, window_start=window[0], window_end=window[1],
        basis="model_feature", baseline=None,
    )  # fmt: skip


def _with(observations: list[ObservationFacts]) -> Facts:
    return load_fixture("facts_fan_in.json").model_copy(update={"observations": observations})


def _grounds(facts: Facts) -> str:
    return next(s.text for s in assembled(facts) if s.section.value == "GROUNDS")


# ---------- 사전 모양 ----------


def test_name_labels_cover_exactly_non_meta_features() -> None:
    assert len(NAMED) == 20
    assert sorted(LABELS["observation_name"]) == NAMED
    assert sorted(LABELS["observation_name_unit"]) == NAMED
    assert set(LABELS["observation_name_unit"].values()) <= set(SAMPLE_VALUE)


@pytest.mark.parametrize("name", NAMED)
def test_label_has_no_digit_or_judgment_word(name: str) -> None:
    label = LABELS["observation_name"][name]
    assert label and not re.search(r"\d", label)
    assert not any(w in label for w in JUDGMENT_WORDS)


# ---------- 20개 렌더 → 06 코드 검사 실패 0 ----------


@pytest.mark.parametrize("name", NAMED)
def test_each_name_renders_and_passes_code_checks(name: str) -> None:
    unit = LABELS["observation_name_unit"][name]
    facts = _with([_obs(name, SAMPLE_VALUE[unit])])
    text = _grounds(facts)
    value = int(SAMPLE_VALUE[unit]) if SAMPLE_VALUE[unit].is_integer() else SAMPLE_VALUE[unit]
    assert f"모델 관측값에서 {LABELS['observation_name'][name]}" in text
    assert f"{value}{unit}임." in text
    assert failures(facts, assembled(facts)) == []


def test_all_names_three_at_a_time_pass_code_checks() -> None:
    """실제는 상위 3개 — 셋씩 묶어도 COUNT 가 관측값마다 따로 대조(절마다 관측 단어)."""
    for i in range(0, len(NAMED), 3):
        names = NAMED[i : i + 3]
        obs = [_obs(n, SAMPLE_VALUE[LABELS["observation_name_unit"][n]]) for n in names]
        facts = _with(obs)
        assert failures(facts, assembled(facts)) == [], names


def test_particle_follows_word_before_paren() -> None:
    """괄호로 끝나는 표기는 괄호 앞 말 기준 — `평균)는` 아님."""
    assert (
        topic_before_paren("통화별 최대 지급 금액 비중(거래 수 가중 평균)")
        == "통화별 최대 지급 금액 비중(거래 수 가중 평균)은"
    )
    assert topic_before_paren("근거 거래 수") == "근거 거래 수는"
    assert topic_before_paren("결제 방식 종류 수") == "결제 방식 종류 수는"
    for name in NAMED:  # 20개 렌더 문장의 조사가 위 규칙과 같은지
        label = LABELS["observation_name"][name]
        assert f"모델 관측값에서 {topic_before_paren(label)} " in _grounds(_with([_obs(name, 3.0)]))


# ---------- null 형식 문장 ----------


def test_all_windows_null_says_once_at_end() -> None:
    text = _grounds(
        _with([_obs("evidence_count", 5.0), _obs("focal_in_count", 3.0), _obs("payment_format_count", 2.0)])
    )
    assert text.count("모델 관측값에서 ") == 3
    assert "(관측 구간 자료 없음)" not in text
    assert text.count("모델 관측값의 관측 구간은 자료 없음.") == 1
    assert text.count("비교 기준값은 자료 없음.") == 1
    assert text.index("관측 구간은 자료 없음") < text.index("비교 기준값은 자료 없음")


def test_mixed_windows_keep_per_sentence_form() -> None:
    """일부만 구간 있음 → 지금 괄호 문형 그대로(부재 주장은 집계 전체를 볼 때만)."""
    w = ("2022-09-02T00:00:00", "2022-09-03T00:00:00")
    text = _grounds(_with([_obs("evidence_count", 5.0, window=w), _obs("focal_in_count", 3.0)]))
    assert "모델 관측값(2022-09-02T00:00:00~2022-09-03T00:00:00 기준)에서 근거 거래 수는 5건임." in text
    assert "모델 관측값(관측 구간 자료 없음)에서 " in text
    assert "모델 관측값의 관측 구간은 자료 없음." not in text


# ---------- 실제 경로 끝까지 ----------


def test_real_sample_builds_v4_without_observations() -> None:
    """준영 예시(셋 다 음수) → facts 관측값 없음 → v4 생성 성공, GROUNDS "모델 관측값은 자료 없음"."""
    facts = build(CASES["mixed"], rule_id=REAL["rule_id"], reasons=REAL["reasons"])
    assert facts.observations == []
    assert "모델 관측값은 자료 없음" in _grounds(facts)


def test_mock_score_path_builds_v4() -> None:
    """목업 점수 경로(시연 환경 model=null) — `mock_feature` 는 관측값이 없어 사전을 안 거침."""
    alert = make_req(CASES["mixed"]["transactions"]).alert
    mock = [r.model_dump(mode="json") for r in ScoreService._mock(alert).reasons]
    facts = build(CASES["mixed"], reasons=mock)
    assert facts.observations == []
    assert "모델 관측값은 자료 없음" in _grounds(facts)


# ---------- 실패 ----------


def test_unknown_name_fails_before_assembly() -> None:
    """사전에 없는 이름 → 조용히 원문 이름을 내보내지 않고 display_label_missing."""
    facts = _with([_obs("brand_new_feature", 3.0)])
    assert ("observation_name", "brand_new_feature") in missing_labels(facts.model_dump(mode="json"), LABELS)
    with pytest.raises(NarrativeAssemblyFailed):
        assembled(facts)


def test_basis_is_not_used_as_fallback() -> None:
    """basis 가 옛 사전에 있어도 이름이 없으면 실패 — basis 로 대신 찾지 않음."""
    obs = _obs("account_in_counterparties_24h", 3.0).model_copy(
        update={"basis": "distinct_inbound_counterparties"}
    )
    with pytest.raises(NarrativeAssemblyFailed):
        assembled(_with([obs]))
