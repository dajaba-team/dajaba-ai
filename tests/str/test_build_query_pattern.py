"""SCRUM-126 — `build_query` 에 유형별 영문 패턴 한 문장 추가 (★L-1 baseline hit 개선용).

- `TYPOLOGY_PATTERN_EN` 다섯 유형(FAN_IN·FAN_OUT·CYCLE·SCATTER_GATHER·GATHER_SCATTER)
- 쿼리 순서: `{한국어} {영문 코드} {영문 패턴} {model_signals} {industry}`
- `typology` 없거나 enum 밖이면 패턴 없음(쿼리에 안 들어감)
"""

from __future__ import annotations

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import TYPOLOGY_PATTERN_EN, build_query


def test_pattern_dict_has_five_v2_typologies() -> None:
    assert TYPOLOGY_PATTERN_EN["FAN_IN"] == "many senders deposit into one account"
    assert TYPOLOGY_PATTERN_EN["FAN_OUT"] == "one account sends funds to many beneficiaries"
    assert TYPOLOGY_PATTERN_EN["CYCLE"] == "funds move through accounts and return to the originating account"
    assert "split across intermediate accounts" in TYPOLOGY_PATTERN_EN["SCATTER_GATHER"]
    assert "pooled into one account" in TYPOLOGY_PATTERN_EN["GATHER_SCATTER"]


def test_fan_in_query_contains_pattern(mixed: Facts) -> None:
    q = build_query(mixed.model_copy(update={"typology": Typology.FAN_IN}))
    assert "many senders deposit into one account" in q
    assert "FAN_IN" in q


def test_cycle_query_contains_pattern(mixed: Facts) -> None:
    q = build_query(mixed.model_copy(update={"typology": Typology.CYCLE}))
    assert "return to the originating account" in q


def test_scatter_gather_query_contains_pattern(mixed: Facts) -> None:
    q = build_query(mixed.model_copy(update={"typology": Typology.SCATTER_GATHER}))
    assert "intermediate accounts" in q
    assert "흩었다 모으기" in q


def test_typology_none_keeps_pattern_out(mixed: Facts) -> None:
    """typology=None 이면 패턴·한국어·영문 코드 전부 안 들어감."""
    q = build_query(mixed.model_copy(update={"typology": None}))
    for pat in TYPOLOGY_PATTERN_EN.values():
        assert pat not in q


def test_query_order_pattern_after_code_before_signals(mixed: Facts) -> None:
    """순서 — `한국어 -> 영문 코드 -> 영문 패턴 -> model_signals -> industry`."""
    facts = mixed.model_copy(update={
        "typology": Typology.FAN_IN,
        "model_signals": ["account_in_counterparties_24h"],
    })  # fmt: skip
    q = build_query(facts)
    i_ko = q.index("집중 입금")
    i_code = q.index("FAN_IN")
    i_pat = q.index("many senders deposit into one account")
    i_sig = q.index("account_in_counterparties_24h")
    assert i_ko < i_code < i_pat < i_sig
