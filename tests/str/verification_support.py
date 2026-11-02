"""verification 테스트 helpers (SCRUM-58).

`test_verification.py`·`test_verification_amount.py`·`test_verification_account.py` 공용.
`facts_support.py` 와 같은 자리 — 리포 안 공유 패턴.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import (
    Facts,
    NarrativeSection,
    NarrativeSectionBase,
    RevisedNarrativeSection,
    SectionV1,
    SectionV2,
)
from aml_ai.str.domain import verification
from tests.conftest import FIXTURES, load_json


def narrative_ok() -> list[NarrativeSection]:
    return [
        NarrativeSection.model_validate(s) for s in load_json(FIXTURES / "narrative_ok.json")["narrative"]
    ]


def facts_fan_in() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def facts_total(total: str) -> Facts:
    """fan_in 복사 + inbound USD total 교체(주입용)."""
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["inbound"]["by_currency"][0]["total"] = total
    return Facts.model_validate(data)


def facts_with_range(min_: str, max_: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["amount_range"] = [{"currency": "USD", "min": min_, "max": max_}]
    return Facts.model_validate(data)


def section(section_: SectionV1 | SectionV2, text: str) -> NarrativeSectionBase:
    """빈 cites·evidence_ids 로 섹션 하나. v1·v2 둘 다 수용."""
    if section_ in SectionV1:
        return NarrativeSection(section=section_, text=text, cites=[], evidence_ids=[])
    return RevisedNarrativeSection(section=section_, text=text, cites=[], evidence_ids=[])


def amount(facts: Facts, section_: SectionV1 | SectionV2, text: str) -> list:
    return verification.amount_match(facts, [section(section_, text)])


def account(facts: Facts, section_: SectionV1 | SectionV2, text: str) -> list:
    return verification.account_id_match(facts, [section(section_, text)])
