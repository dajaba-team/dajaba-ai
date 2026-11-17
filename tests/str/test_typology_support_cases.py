"""SCRUM-265 (2/2) — 판정 ↔ 사전 등록 사건 파일 · 판정 문장 (docs/str/08 "유형 뒷받침 판정·문구"). LLM·DB 0.

사건 파일(`v4_blind2_cases.json`)은 고치지 않음 — 판정이 칸과 다르면 판정 코드가 틀린 것(09 사전 등록 ④).
판정 문장: 05 표 그대로 · 숫자 0 · 06 COUNT 정상 · 입금(출금) 0 이면 "위 거래".
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.typology_support import Support, typology_support
from aml_ai.str.domain.typology_support_text import support_sentence
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_blind2_cases import case_facts, load_cases
from tests.str.v4_slot_support import assembled, failures

LABELS = load_display_labels()
DOC = load_cases()
FACTS = case_facts(DOC)
SLOT_SUPPORT = {"supported": {Support.SUPPORTED}, "mixed": {Support.SUPPORTED},
                "unsupported": {Support.UNCONFIRMED, Support.UNMET}}  # fmt: skip
REGRESSION = {"reg_fan_in": Support.UNMET, "reg_scatter_gather": Support.UNCONFIRMED,
              "reg_customer_missing": Support.UNMET}  # fmt: skip


def _support(f: Facts) -> Support | None:
    return typology_support(masking.mask_for_llm(f))


@pytest.mark.parametrize(
    "case", [c for c in DOC["cases"] if c["role"] == "judged"], ids=lambda c: c["case_id"]
)
def test_judged_cases_match_slot(case: dict) -> None:
    assert _support(FACTS[case["case_id"]]) in SLOT_SUPPORT[case["slot"]], case["case_id"]


def test_regression_cases_recorded() -> None:
    """228 손으로 만든 픽스처는 등록된 식으로 불충족·미확인 — 참고용이라 칸 없음(09 2/2 판정 ⑦)."""
    assert {k: _support(FACTS[k]) for k in REGRESSION} == REGRESSION


def _grounds(f: Facts) -> str:
    return next(s.text for s in assembled(f) if s.section is SectionV2.GROUNDS)


EXPECTED_FIRST = {
    "sup_fan_in": "위 입금의 서로 다른 송금인 수는 자금 집중(FAN_IN) 유형의 탐지 기준을 충족함.",
    "sup_fan_out": "위 출금의 서로 다른 수취인 수는 자금 분산(FAN_OUT) 유형의 탐지 기준을 충족함.",
    "sup_cycle": "확인된 경로는 자금 순환(CYCLE) 분류와 부합함.",
    "sup_scatter_gather": "확인된 경로는 분산 후 집중(SCATTER_GATHER) 분류와 부합함.",
    "uns_cycle": "자금 순환(CYCLE) 분류를 뒷받침하는 경로는 제공된 자료로 확인되지 않음.",
    "uns_scatter_gather": "분산 후 집중(SCATTER_GATHER) 분류를 뒷받침하는 경로는 제공된 자료로 확인되지 않음.",
    "uns_fan_in": "위 입금의 서로 다른 송금인 수는 자금 집중(FAN_IN) 유형의 탐지 기준에 미치지 않음.",
    "mix_fan_in": "위 입금의 서로 다른 송금인 수는 자금 집중(FAN_IN) 유형의 탐지 기준을 충족함.",
}


@pytest.mark.parametrize("case_id", sorted(EXPECTED_FIRST))
def test_grounds_first_sentence_is_judgment(case_id: str) -> None:
    assert _grounds(FACTS[case_id]).startswith(EXPECTED_FIRST[case_id] + " ")


@pytest.mark.parametrize("case_id", sorted(FACTS))
def test_judgment_sentence_passes_code_checks(case_id: str) -> None:
    f = FACTS[case_id]
    sentence = support_sentence(masking.mask_for_llm(f), LABELS)
    assert sentence is not None and not any(ch.isdigit() for ch in sentence.text)
    assert failures(f, assembled(f)) == []


def test_zero_flow_unmet_uses_wi_georae() -> None:
    """FAN_IN 이고 입금 0 → "위 거래의 서로 다른 송금인 수"(O-HEAD·C0 와 같은 규칙). FAN_OUT 출금 0 도."""
    fan_out_case = FACTS["sup_fan_out"]  # 입금 0
    as_fan_in = fan_out_case.model_copy(update={"typology": Typology.FAN_IN})
    text = support_sentence(masking.mask_for_llm(as_fan_in), LABELS)
    assert text is not None
    assert text.text == "위 거래의 서로 다른 송금인 수는 자금 집중(FAN_IN) 유형의 탐지 기준에 미치지 않음."
    fan_in_case = FACTS["sup_fan_in"]  # 출금 0
    as_fan_out = fan_in_case.model_copy(update={"typology": Typology.FAN_OUT})
    text = support_sentence(masking.mask_for_llm(as_fan_out), LABELS)
    assert text is not None
    assert text.text == "위 거래의 서로 다른 수취인 수는 자금 분산(FAN_OUT) 유형의 탐지 기준에 미치지 않음."
    for f in (as_fan_in, as_fan_out):
        assert failures(f, assembled(f)) == []


def test_supported_flow_sentence_never_needs_wi_georae() -> None:
    """뒷받침됨은 하한 ≥ 임계값 — 그 방향 거래가 늘 1 이상이라 "위 거래" 대체꼴은 해당 없음."""
    for case_id in ("sup_fan_in", "sup_fan_out", "mix_fan_in"):
        masked = masking.mask_for_llm(FACTS[case_id])
        flow = "inbound" if masked["typology"] == "FAN_IN" else "outbound"
        assert typology_support(masked) is Support.SUPPORTED and masked[flow]["count"] >= 1
        sentence = support_sentence(masked, LABELS)
        assert sentence is not None and "위 거래" not in sentence.text


def test_no_judgment_sentence_for_other_typology() -> None:
    f = FACTS["sup_fan_in"].model_copy(update={"typology": Typology.PASS_THROUGH})
    assert support_sentence(masking.mask_for_llm(f), LABELS) is None
    none = FACTS["sup_fan_in"].model_copy(update={"typology": None})
    assert support_sentence(masking.mask_for_llm(none), LABELS) is None
