"""SCRUM-275 ES 키워드 검색어 — 언어별 (docs/str/10 "빈칸만 채우기"). 순수."""

from __future__ import annotations

import json
import re

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.constants_rag_query import QUERY_LANG_EN, QUERY_LANG_KO
from aml_ai.str.domain.rag_queries import (
    TYPOLOGY_KO,
    TYPOLOGY_PATTERN_EN,
    TYPOLOGY_PATTERN_KO,
    keyword_queries,
)
from tests.conftest import FIXTURES


def _facts(typology: Typology | None) -> Facts:
    data = json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8"))
    data["typology"] = typology.value if typology else None
    return Facts.model_validate(data)


def test_cycle_has_one_query_per_language_en_first() -> None:
    queries = keyword_queries(_facts(Typology.CYCLE))
    assert [q.lang for q in queries] == [QUERY_LANG_EN, QUERY_LANG_KO]
    assert queries[0].text == TYPOLOGY_PATTERN_EN["CYCLE"]  # 출발점: 영문 = (b)
    assert queries[1].text.startswith(TYPOLOGY_KO["CYCLE"])
    assert TYPOLOGY_PATTERN_KO["CYCLE"] in queries[1].text


def test_ko_patterns_cover_en_patterns() -> None:
    assert set(TYPOLOGY_PATTERN_KO) == set(TYPOLOGY_PATTERN_EN)


@pytest.mark.parametrize("typology", list(Typology))
def test_no_digits_in_keyword_queries(typology: Typology) -> None:
    for q in keyword_queries(_facts(typology)):
        assert not re.search(r"\d", q.text)  # 숫자·계좌·금액 0


def test_typology_without_pattern_has_only_ko_name_or_nothing() -> None:
    queries = keyword_queries(_facts(Typology.HIGH_VALUE))
    assert [q.lang for q in queries] == [QUERY_LANG_KO]
    assert queries[0].text == TYPOLOGY_KO["HIGH_VALUE"]


def test_none_typology_is_empty() -> None:
    assert keyword_queries(_facts(None)) == []
