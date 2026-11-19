"""SCRUM-275 평가 세트 30 (docs/str/10 "평가 세트"). 배분 · 질의마다 다른 facts · 범주 칸만."""

from __future__ import annotations

from collections import Counter

import pytest

from aml_ai.str.domain.rag_queries import build_queries
from tests.str.rag_eval_v2_support import OVERRIDE_KEYS, build_facts, load_queries

_DEV = load_queries("dev")
_HOLDOUT = load_queries("holdout")
_ALL = _DEV + _HOLDOUT


def test_sizes_and_split() -> None:
    assert len(_DEV) == 14 and len(_HOLDOUT) == 16
    assert {q["split"] for q in _DEV} == {"dev"} and {q["split"] for q in _HOLDOUT} == {"holdout"}
    assert len({q["id"] for q in _ALL}) == 30


@pytest.mark.parametrize(
    ("split", "expected"),
    [
        (
            "dev",
            {"CYCLE": 6, "FAN_IN": 2, "FAN_OUT": 2, "SCATTER_GATHER": 2, "GATHER_SCATTER": 1, "FX_RELAY": 1},
        ),
        (
            "holdout",
            {"CYCLE": 8, "FAN_IN": 2, "FAN_OUT": 2, "SCATTER_GATHER": 1, "GATHER_SCATTER": 2, "FX_RELAY": 1},
        ),
    ],
)
def test_allocation(split: str, expected: dict[str, int]) -> None:
    assert Counter(q["typology"] for q in load_queries(split)) == expected


def test_no_answer_queries_are_untagged_typologies() -> None:
    empties = [q for q in _ALL if q["expect_empty"]]
    assert len(empties) == 8
    assert Counter(q["typology"] for q in empties) == {
        "SCATTER_GATHER": 3,
        "GATHER_SCATTER": 3,
        "FX_RELAY": 2,
    }
    assert all(not q["expect_empty"] for q in _ALL if q["typology"] in {"CYCLE", "FAN_IN", "FAN_OUT"})


def test_every_query_builds_valid_facts_with_its_typology() -> None:
    for q in _ALL:
        facts = build_facts(q)
        assert facts.typology is not None and facts.typology.value == q["typology"]


def test_overrides_are_category_fields_only() -> None:
    for q in _ALL:
        assert set(q["overrides"]) <= OVERRIDE_KEYS


def test_each_query_has_its_own_search_text() -> None:
    """11/18 기준선은 (c) 문장이 10개 모두 같았음 — 이번엔 (a)+(c) 조합이 질의마다 다름."""
    texts = [tuple(s.text for s in build_queries(build_facts(q))) for q in _ALL]
    assert len(set(texts)) == 30
    cycle_c = {build_queries(build_facts(q))[-1].text for q in _ALL if q["typology"] == "CYCLE"}
    assert len(cycle_c) >= 10  # (c) 문장 자체도 CYCLE 14개 중 10개 이상 다름
