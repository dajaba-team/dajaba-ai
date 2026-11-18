"""SCRUM-146 — 검색어 만들기 (docs/str/10 "다중 질의·합치기", ★A (c) 표). LLM·DB 0.

(a) = 지금 build_query 그대로(첫 번째) · (b) = 유형 패턴만 · (c) = facts 범주 영문(숫자 0) · 상한 3 · retriever 는 같은 이름을 다시 내보냄.
"""

from __future__ import annotations

import json
import re

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain import rag_queries
from aml_ai.str.domain.constants import RAG_MAX_QUERIES
from aml_ai.str.domain.rag_queries import SearchQuery, build_queries, build_query, facts_query_en
from aml_ai.str.infrastructure import retriever
from tests.conftest import FIXTURES

BASELINE_FAN_IN = (
    "집중 입금 FAN_IN many senders deposit into one account account_in_counterparties_24h RETAIL"
)


def _fan_in() -> Facts:  # INBOUND · 상대 3 · ACH · 타행 3 · USD 하나
    return Facts.model_validate(json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8")))


def _with(**update: object) -> Facts:
    return _fan_in().model_copy(update=update)


def test_a_is_todays_query_unchanged() -> None:
    assert build_query(_fan_in()) == BASELINE_FAN_IN
    assert build_queries(_fan_in())[0] == SearchQuery("a", "en", BASELINE_FAN_IN)


def test_retriever_reexports_same_objects() -> None:
    """옮긴 뒤에도 기존 import 경로가 같은 객체 — 문장 0 변경."""
    assert retriever.build_query is rag_queries.build_query
    assert retriever.TYPOLOGY_PATTERN_EN is rag_queries.TYPOLOGY_PATTERN_EN
    assert retriever.TYPOLOGY_KO is rag_queries.TYPOLOGY_KO


def test_all_three_in_order() -> None:
    qs = build_queries(_fan_in())
    assert [q.kind for q in qs] == ["a", "b", "c"] and len(qs) <= RAG_MAX_QUERIES
    assert qs[1].text == "many senders deposit into one account"
    assert qs[2].text == (
        "incoming funds only, several counterparties, via ACH transfers, accounts at other financial institutions"
    )
    assert {q.lang for q in qs} == {"en"}


@pytest.mark.parametrize(
    ("kinds", "want"), [(("a",), ["a"]), (("a", "c"), ["a", "c"]), (("a", "b", "c"), ["a", "b", "c"])]
)
def test_kinds_select_combination(kinds: tuple[str, ...], want: list[str]) -> None:
    assert [q.kind for q in build_queries(_fan_in(), kinds)] == want


def test_kinds_must_include_a() -> None:
    with pytest.raises(ValueError):
        build_queries(_fan_in(), ("b", "c"))


@pytest.mark.parametrize(
    ("direction", "fragment"),
    [("INBOUND", "incoming funds only"), ("OUTBOUND", "outgoing funds only"),
     ("MIXED", "both incoming and outgoing funds")],
)  # fmt: skip
def test_direction_fragment(direction: str, fragment: str) -> None:
    assert facts_query_en(_with(direction=direction)).startswith(fragment)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("count", "word"), [(1, "few"), (2, "few"), (3, "several"), (9, "several"), (10, "many")]
)
def test_counterparty_scale_boundaries(count: int, word: str) -> None:
    f = _fan_in()
    f = f.model_copy(update={"counterparties": f.counterparties.model_copy(update={"count": count})})
    assert f"{word} counterparties" in facts_query_en(f)  # type: ignore[operator]


def test_payment_formats_in_facts_order_and_unmapped_dropped() -> None:
    q = facts_query_en(_with(payment_formats=["Wire", "Reinvestment", "Cash"]))
    assert "via wire transfers and cash" in q  # type: ignore[operator]
    assert "einvest" not in q.lower()  # type: ignore[union-attr]


def test_multiple_currencies_and_other_banks() -> None:
    f = _fan_in()
    usd = f.inbound.by_currency[0]
    eur = usd.model_copy(update={"currency": "EUR"})
    two = f.model_copy(update={"inbound": f.inbound.model_copy(update={"by_currency": [usd, eur]})})
    assert facts_query_en(two).endswith("multiple currencies")  # type: ignore[union-attr]
    none_other = f.model_copy(
        update={"counterparty_banks": f.counterparty_banks.model_copy(update={"other_bank_accounts": 0})}
    )
    assert "other financial institutions" not in facts_query_en(none_other)  # type: ignore[operator]


def test_no_digits_or_amounts_in_c() -> None:
    q = facts_query_en(_fan_in())
    assert q and not re.search(r"\d", q)
    for word in ("USD", "42", "10_8000", _fan_in().subject.account_key):
        assert word not in q


def test_empty_c_is_dropped() -> None:
    f = _fan_in()
    bare = f.model_copy(
        update={
            "direction": "INTERNAL",
            "counterparties": f.counterparties.model_copy(update={"count": 0}),
            "payment_formats": ["Reinvestment"],
            "counterparty_banks": f.counterparty_banks.model_copy(update={"other_bank_accounts": 0}),
        }
    )
    assert facts_query_en(bare) is None
    assert [q.kind for q in build_queries(bare)] == ["a", "b"]


def test_no_pattern_and_same_text_dropped() -> None:
    """패턴 없는 유형은 (b) 없음 · typology None 도 (a) 는 지금 문장 그대로."""
    assert [q.kind for q in build_queries(_with(typology=Typology.FX_RELAY))] == ["a", "c"]
    none = _with(typology=None)
    assert build_queries(none)[0].text == build_query(none)
