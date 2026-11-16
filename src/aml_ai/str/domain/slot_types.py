"""슬롯 문장 타입·작은 생성 도우미 (docs/str/05 narrative_v4). 순수."""

from __future__ import annotations

from dataclasses import dataclass

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain.constants_v4 import NO_DATA
from aml_ai.str.domain.display_format import topic


@dataclass(frozen=True)
class SlotSentence:
    text: str
    cites: tuple[str, ...]


Slots = dict[SectionV2, list[SlotSentence]]


def slot(text: str, *cites: str) -> SlotSentence:
    return SlotSentence(text=text, cites=tuple(cites))


def no_data(name: str, *cites: str) -> SlotSentence:
    """`{name}은/는 자료 없음.`"""
    return slot(f"{topic(name)} {NO_DATA}.", *cites)
