"""순서 목록(Plan) — GROUNDS·OPINION 에 어떤 카탈로그 부품을 어떤 순서로 (docs/str/05 narrative_v4 "순서 목록"). 순수.

기본 경로는 코드가 만든다(`default_plan`). 나중에 LLM 편집자가 같은 모양을 내면 `validate_plan` 으로 검증하고,
실패면 `default_plan` 으로 완성한다(v2 자동 전환 없음).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain.catalog_types import CatalogItem
from aml_ai.str.domain.constants_v4 import (
    CONNECTIVES,
    DEFAULT_CONNECTIVE,
    GROUNDS_ITEMS_MAX,
    OPINION_OPTIONAL_MAX,
)
from aml_ai.str.domain.grounds_catalog import grounds_candidates
from aml_ai.str.domain.opinion_catalog import opinion_candidates, opinion_head


@dataclass(frozen=True)
class Pick:
    item_id: str
    variant_id: int = 0
    connective_id: str = DEFAULT_CONNECTIVE


Plan = dict[SectionV2, list[Pick]]  # GROUNDS·OPINION 만 — 나머지 섹션은 슬롯 그대로


@dataclass(frozen=True)
class Candidates:
    grounds: list[CatalogItem]
    head: CatalogItem
    checks: list[CatalogItem]
    by_id: dict[str, CatalogItem] = field(default_factory=dict)


def candidates(facts: dict[str, Any], flags: dict[str, bool]) -> Candidates:
    grounds, head, checks = (
        grounds_candidates(facts, flags),
        opinion_head(facts),
        opinion_candidates(facts, flags),
    )
    return Candidates(grounds, head, checks, {i.id: i for i in (*grounds, head, *checks)})


def default_plan(c: Candidates) -> Plan:
    """사유 우선순위 상위 3 · 첫 문장 + 필수 전부 + 선택 상위 2(표 순서 유지) — 변형 0, 연결어 없음."""
    optional = {i.id for i in c.checks if not i.required}
    chosen = [i for i in c.checks if not i.required][:OPINION_OPTIONAL_MAX]
    keep = {i.id for i in c.checks if i.id not in optional} | {i.id for i in chosen}
    return {
        SectionV2.GROUNDS: [Pick(i.id) for i in c.grounds[:GROUNDS_ITEMS_MAX]],
        SectionV2.OPINION: [Pick(c.head.id)] + [Pick(i.id) for i in c.checks if i.id in keep],
    }


def validate_plan(plan: Plan, c: Candidates) -> list[str]:
    """실패 사유 코드(중복 제거, 순서 유지). 비면 통과."""
    problems: list[str] = []
    grounds, opinion = plan.get(SectionV2.GROUNDS, []), plan.get(SectionV2.OPINION, [])
    allowed = {
        SectionV2.GROUNDS: {i.id for i in c.grounds},
        SectionV2.OPINION: {c.head.id} | {i.id for i in c.checks},
    }
    for sec, picks in ((SectionV2.GROUNDS, grounds), (SectionV2.OPINION, opinion)):
        problems += _pick_problems(picks, allowed[sec], c)
    if set(plan) - {SectionV2.GROUNDS, SectionV2.OPINION}:
        problems.append("section_not_allowed")
    if len(grounds) > GROUNDS_ITEMS_MAX:
        problems.append("too_many_grounds")
    if not opinion or opinion[0].item_id != c.head.id:
        problems.append("head_not_first")
    ids = {p.item_id for p in opinion}
    if any(i.required and i.id not in ids for i in c.checks):
        problems.append("required_missing")
    if (
        sum(1 for p in opinion if p.item_id in {i.id for i in c.checks if not i.required})
        > OPINION_OPTIONAL_MAX
    ):
        problems.append("too_many_optional")
    return list(dict.fromkeys(problems))


def _pick_problems(picks: list[Pick], allowed: set[str], c: Candidates) -> list[str]:
    problems: list[str] = []
    if len({p.item_id for p in picks}) != len(picks):
        problems.append("duplicate_item")
    for n, p in enumerate(picks):
        if p.item_id not in allowed:
            problems.append("unknown_item")
        elif not 0 <= p.variant_id < len(c.by_id[p.item_id].variants):
            problems.append("unknown_variant")
        if p.connective_id not in CONNECTIVES:
            problems.append("unknown_connective")
        elif n == 0 and p.connective_id != DEFAULT_CONNECTIVE:
            problems.append("connective_on_first")
    return problems
