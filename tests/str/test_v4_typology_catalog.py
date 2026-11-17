"""SCRUM-265 (2/2) — 판정 반영 카탈로그 (docs/str/05 "유형 뒷받침 판정"·C0·Y3·G-CYCLE-PATH). LLM·DB 0.

뒷받침 안 됨: GROUNDS 첫 문장 판정 · OPINION 둘째 C0 · Y3·G-CYCLE-PATH 꺼짐 · 금지 낱말 0(낱말 단위).
뒷받침됨: 부합·충족 판정 문장 · C0 없음. C0·판정 문장 린트 · validate_plan `c0_not_second`.
"""

from __future__ import annotations

import re

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants_v4 import UNSUPPORTED_BANNED_WORDS
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.narrative_plan import Pick, candidates, default_plan, validate_plan
from aml_ai.str.domain.typology_support import Support, typology_support
from aml_ai.str.domain.typology_support_text import support_sentence
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_blind2_cases import case_facts, load_cases
from tests.str.v4_catalog_lint import lint
from tests.str.v4_slot_support import assembled
from tests.str.v4_typology_words import banned_hits

LABELS = load_display_labels()
FACTS = case_facts(load_cases())
UNSUPPORTED = ["uns_cycle", "uns_scatter_gather", "uns_fan_in", "reg_fan_in", "reg_scatter_gather",
               "reg_customer_missing"]  # fmt: skip
SUPPORTED = ["sup_fan_in", "sup_fan_out", "sup_cycle", "sup_scatter_gather", "mix_fan_in"]
C0 = {
    "FAN_IN": "자금 집중 분류의 근거가 된 송금인별 입금 내역을 확인할 필요가 있음.",
    "FAN_OUT": "자금 분산 분류의 근거가 된 수취인별 출금 내역을 확인할 필요가 있음.",
    "CYCLE": "경로 확인 자료를 보완할 필요가 있음.",
    "SCATTER_GATHER": "분산 후 집중 분류의 근거가 된 중간 계좌 경로 자료를 보완할 필요가 있음.",
}
_SENT = re.compile(r"(?<=[.])\s+")


def _section(f: Facts, sec: SectionV2) -> list[str]:
    text = next(s.text for s in assembled(f) if s.section is sec)
    return _SENT.split(text)


def _plan_ids(f: Facts) -> set[str]:
    masked = masking.mask_for_llm(f)
    plan = default_plan(candidates(masked, derive_flags(masked)))
    return {p.item_id for picks in plan.values() for p in picks}


@pytest.mark.parametrize("case_id", UNSUPPORTED)
def test_unsupported_limits_first_and_c0_second(case_id: str) -> None:
    f = FACTS[case_id]
    masked = masking.mask_for_llm(f)
    assert typology_support(masked) in (Support.UNCONFIRMED, Support.UNMET)
    sentence = support_sentence(masked, LABELS)
    assert sentence is not None and _section(f, SectionV2.GROUNDS)[0] == sentence.text
    assert _section(f, SectionV2.OPINION)[1] == C0[masked["typology"]]
    assert not {"Y3", "G-CYCLE-PATH"} & _plan_ids(f)
    body = " ".join(_section(f, SectionV2.GROUNDS) + _section(f, SectionV2.OPINION))
    assert banned_hits(body) == [], case_id


@pytest.mark.parametrize("case_id", SUPPORTED)
def test_supported_has_match_sentence_and_no_c0(case_id: str) -> None:
    f = FACTS[case_id]
    first = _section(f, SectionV2.GROUNDS)[0]
    assert "충족함" in first or "부합함" in first
    assert "C0" not in _plan_ids(f)


def test_c0_uses_wi_georae_when_flow_is_zero() -> None:
    """FAN_IN 입금 0 → "자금 집중 분류의 근거가 된 거래 내역을 확인할 필요가 있음."(O-HEAD 와 같은 규칙)."""
    as_fan_in = FACTS["sup_fan_out"].model_copy(update={"typology": Typology.FAN_IN})  # 입금 0
    assert (
        _section(as_fan_in, SectionV2.OPINION)[1]
        == "자금 집중 분류의 근거가 된 거래 내역을 확인할 필요가 있음."
    )
    as_fan_out = FACTS["sup_fan_in"].model_copy(update={"typology": Typology.FAN_OUT})  # 출금 0
    assert (
        _section(as_fan_out, SectionV2.OPINION)[1]
        == "자금 분산 분류의 근거가 된 거래 내역을 확인할 필요가 있음."
    )


def test_banned_words_are_word_level() -> None:
    assert set(UNSUPPORTED_BANNED_WORDS) == {"부합", "충족", "뒷받침됨", "전형적"}
    assert banned_hits("탐지 기준을 충족함.") == ["충족"] and banned_hits("분류와 부합함.") == ["부합"]
    assert banned_hits("불충족 상태임.") == [] and banned_hits("분류를 뒷받침하는 경로.") == []


def _judgment_and_c0_texts() -> list[str]:
    texts = list(C0.values()) + [
        "자금 집중 분류의 근거가 된 거래 내역을 확인할 필요가 있음.",
        "자금 분산 분류의 근거가 된 거래 내역을 확인할 필요가 있음.",
    ]
    for f in FACTS.values():
        s = support_sentence(masking.mask_for_llm(f), LABELS)
        if s is not None:
            texts.append(re.sub(r"\([A-Z_]+\)", "", s.text))  # 코드 병기는 슬롯 표기(린트 문자 밖)
    return texts


@pytest.mark.parametrize("text", _judgment_and_c0_texts())
def test_judgment_and_c0_pass_lint(text: str) -> None:
    assert lint(text) == [], text


@pytest.mark.parametrize("word", ["오분류", "해당하지 않음", "잘못"])
def test_lint_bans_misclassification_words(word: str) -> None:
    assert "forbidden_word" in lint(f"이 유형은 {word} 가능성이 있음.")


def test_validate_plan_c0_must_be_second() -> None:
    masked = masking.mask_for_llm(FACTS["uns_fan_in"])
    c = candidates(masked, derive_flags(masked))
    plan = default_plan(c)
    assert validate_plan(plan, c) == [] and plan[SectionV2.OPINION][1].item_id == "C0"
    moved = [plan[SectionV2.OPINION][0], *plan[SectionV2.OPINION][2:], plan[SectionV2.OPINION][1]]
    assert "c0_not_second" in validate_plan({**plan, SectionV2.OPINION: moved}, c)
    dropped = [p for p in plan[SectionV2.OPINION] if p.item_id != "C0"]
    assert "required_missing" in validate_plan({**plan, SectionV2.OPINION: dropped}, c)
    cyc = masking.mask_for_llm(FACTS["uns_cycle"])
    cc = candidates(cyc, derive_flags(cyc))
    cplan = default_plan(cc)
    assert "unknown_item" in validate_plan(
        {**cplan, SectionV2.OPINION: [*cplan[SectionV2.OPINION], Pick("Y3")]}, cc
    )
