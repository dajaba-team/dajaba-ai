"""SCRUM-265 (2/2) — 관측값 줄인 꼴("{표기} 관측값은 {값}{단위}임.")을 사전 20개 이름 전부로 (docs/str/05 GROUNDS 슬롯).

둘째 자리부터는 "모델 관측값에서"가 빠짐 → 이름 표기 속 `계좌`·`송금`·`입금` 이 06 COUNT 에서 다른 종류로
읽히지 않는지. 이름마다 둘째 자리에 넣어 렌더 → 코드 검사 실패 0 + 그 값 변조가 잡힘. LLM·DB 0.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection, ObservationFacts
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain.display_slots_method import obs_value
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.test_v4_observation_names import NAMED, SAMPLE_VALUE
from tests.str.v4_slot_support import assembled, failures, load_fixture

LABELS = load_display_labels()
MUTATED = {
    "건": 9.0,
    "개": 9.0,
    "초": 9.0,
    "": 0.75,
}  # 첫 관측값(근거 거래 수 3·대상 계좌로 들어온 근거 거래 수 3)과 겹치지 않음


def _obs(name: str, value: float) -> ObservationFacts:
    return ObservationFacts(name=name, value=value, unit=None, window_start=None, window_end=None,
                            basis="model_feature", baseline=None)  # fmt: skip


def _facts(name: str) -> Facts:
    first = "focal_in_count" if name == "evidence_count" else "evidence_count"
    unit = LABELS["observation_name_unit"][name]
    obs = [_obs(first, 3.0), _obs(name, SAMPLE_VALUE[unit])]
    return load_fixture("facts_fan_in.json").model_copy(update={"observations": obs})


def _short(name: str, value: float) -> str:
    unit = LABELS["observation_name_unit"][name]
    return f"{LABELS['observation_name'][name]} 관측값은 {obs_value(value)}{unit}임."


@pytest.mark.parametrize("name", NAMED)
def test_short_form_second_position_passes_code_checks(name: str) -> None:
    facts = _facts(name)
    unit = LABELS["observation_name_unit"][name]
    grounds = next(s.text for s in assembled(facts) if s.section is SectionV2.GROUNDS)
    assert _short(name, SAMPLE_VALUE[unit]) in grounds and grounds.count("모델 관측값에서") == 1
    assert failures(facts, assembled(facts)) == []


# 비율(단위 없음)·초 단위는 06 COUNT 대조 밖 — 긴 꼴(첫 자리)에서도 변조가 안 잡히는 기존 한계.
# 출처: 05 관측 단위 절 "`초`·`%`·단위 없음은 06 COUNT 대조 밖"(SCRUM-264) · 09 미결 "06 검사기 포함·집합 판정
# … 단위 없는 관측값 …"(닫음 → 06 "포함·집합 판정" 절). 06 이 이 단위를 읽게 되면 아래 단언이 깨짐 → "잡힘"으로 바꿀 것.
COUNT_BLIND_UNITS = ("", "초")
CHECKED = [n for n in NAMED if LABELS["observation_name_unit"][n] not in COUNT_BLIND_UNITS]
BLIND = [n for n in NAMED if LABELS["observation_name_unit"][n] in COUNT_BLIND_UNITS]


def _long_facts(name: str) -> Facts:
    unit = LABELS["observation_name_unit"][name]
    return load_fixture("facts_fan_in.json").model_copy(
        update={"observations": [_obs(name, SAMPLE_VALUE[unit])]}
    )


def _mutation_caught(facts: Facts, old: str, new: str) -> bool:
    sections: list[LlmNarrativeSection] = []
    for s in assembled(facts):
        if s.section is SectionV2.GROUNDS:
            assert old in s.text, (old, s.text)
            s = s.model_copy(update={"text": s.text.replace(old, new, 1)})
        sections.append(s)
    return bool(failures(facts, sections))


def _caught_both(name: str) -> tuple[bool, bool]:
    """(줄인 꼴 둘째 자리, 긴 꼴 첫 자리) 값 변조가 잡히는지."""
    unit = LABELS["observation_name_unit"][name]
    v, m = SAMPLE_VALUE[unit], MUTATED[unit]
    short = _mutation_caught(_facts(name), _short(name, v), _short(name, m))
    long = _mutation_caught(_long_facts(name), f"{obs_value(v)}{unit}임.", f"{obs_value(m)}{unit}임.")
    return short, long


def test_units_split_nine_and_eleven() -> None:
    assert len(CHECKED) == 9 and len(BLIND) == 11 and len(NAMED) == 20


@pytest.mark.parametrize("name", CHECKED)
def test_count_unit_mutation_caught_in_both_forms(name: str) -> None:
    assert _caught_both(name) == (True, True), name


@pytest.mark.parametrize("name", BLIND)
def test_ratio_and_seconds_not_checked_in_either_form(name: str) -> None:
    """줄인 꼴로 새로 생긴 조용한 통과 0 — 긴 꼴과 똑같이 안 잡힘(기존 한계)."""
    assert _caught_both(name) == (False, False), name
