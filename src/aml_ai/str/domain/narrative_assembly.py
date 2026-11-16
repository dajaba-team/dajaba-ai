"""조립 — 슬롯 문장 + 순서 목록(Plan)대로 렌더한 카탈로그 문장 → 7섹션 (docs/str/05 narrative_v4 "순서 목록과 조립"). 순수.

GROUNDS 는 슬롯 뒤에 사유 항목, OPINION 은 종합의견 부품만, 나머지는 슬롯만.
- "확인 안 됨" 사유 항목(명사구 있음)이 둘 이상이면 한 문장으로 묶음 — 첫 묶인 항목 자리·그 연결어(05 "묶기")
- 짝 사유 항목이 GROUNDS 에 있으면 확인 사항은 짧은 꼴(같은 사실 되풀이 안 함)
cites = 슬롯 cites ∪ 부품 cites(순서 유지 중복 제거). 결과는 NarrativeOutV2 와 같은 모양.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str.narrative import NARRATIVE_TEXT_MAX, LlmNarrativeSection, SectionV2
from aml_ai.str.domain.catalog_types import render
from aml_ai.str.domain.constants_v4 import CONNECTIVES, SLOT_JOIN
from aml_ai.str.domain.display_format import topic
from aml_ai.str.domain.grounds_catalog import NOT_CONFIRMED
from aml_ai.str.domain.narrative_plan import Candidates, Pick, Plan
from aml_ai.str.domain.slot_types import Slots

_Part = tuple[str, tuple[str, ...]]


class AssemblyTooLong(ValueError):
    """조립한 섹션이 1,200자를 넘음 — 코드 문제(생성기가 INTERNAL 로 바꿈)."""

    def __init__(self, section: SectionV2, length: int) -> None:
        super().__init__(f"assembled section too long section={section.value} length={length}")
        self.section = section
        self.length = length


def assemble(slots: Slots, plan: Plan, c: Candidates, ctx: dict[str, str]) -> list[LlmNarrativeSection]:
    sections: list[LlmNarrativeSection] = []
    for sec, parts in _parts(slots, plan, c, ctx).items():
        text = SLOT_JOIN.join(t for t, _ in parts)
        if len(text) > NARRATIVE_TEXT_MAX:
            raise AssemblyTooLong(sec, len(text))
        cites = list(dict.fromkeys(ci for _, cs in parts for ci in cs))
        sections.append(LlmNarrativeSection(section=sec, text=text, cites=cites))
    return sections


def section_lengths(slots: Slots, plan: Plan, c: Candidates, ctx: dict[str, str]) -> dict[str, int]:
    """PR 표용 — 섹션별 조립 글자 수(상한 검사 전)."""
    return {
        sec.value: len(SLOT_JOIN.join(t for t, _ in parts))
        for sec, parts in _parts(slots, plan, c, ctx).items()
    }


def _parts(slots: Slots, plan: Plan, c: Candidates, ctx: dict[str, str]) -> dict[SectionV2, list[_Part]]:
    grounds_ids = {p.item_id for p in plan.get(SectionV2.GROUNDS, [])}
    out: dict[SectionV2, list[_Part]] = {}
    for sec in SectionV2:
        parts: list[_Part] = [(s.text, s.cites) for s in slots.get(sec, [])]
        parts += _render_picks(plan.get(sec, []), c, ctx, grounds_ids)
        out[sec] = parts
    return out


def _render_picks(
    picks: list[Pick], c: Candidates, ctx: dict[str, str], grounds_ids: set[str]
) -> list[_Part]:
    bundled = [p for p in picks if c.by_id[p.item_id].noun is not None]
    bundled = bundled if len(bundled) > 1 else []
    parts: list[_Part] = []
    for p in picks:
        if p not in bundled:
            parts.append(_render_pick(p, c, ctx, grounds_ids))
        elif p == bundled[0]:
            parts.append(_render_bundle(bundled, c))
    return parts


def _render_bundle(picks: list[Pick], c: Candidates) -> _Part:
    items = [c.by_id[p.item_id] for p in picks]
    nouns = [i.noun or "" for i in items]
    text = f"{', '.join(nouns[:-1])}, {topic(nouns[-1])} {NOT_CONFIRMED}"
    return _with_connective(picks[0], text), tuple(ci for i in items for ci in i.cites)


def _render_pick(p: Pick, c: Candidates, ctx: dict[str, str], grounds_ids: set[str]) -> _Part:
    item = c.by_id[p.item_id]
    paired = item.pair is not None and item.pair in grounds_ids and item.short is not None
    text = render(item.short if paired and item.short else item.variants[p.variant_id], ctx)
    return _with_connective(p, text), item.cites


def _with_connective(p: Pick, text: str) -> str:
    connective = CONNECTIVES[p.connective_id]
    return f"{connective} {text}" if connective else text
