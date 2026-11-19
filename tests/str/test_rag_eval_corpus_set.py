"""SCRUM-304 holdout_v2 질의 세트 (docs/str/10 "코퍼스 확장 판정 (holdout_v2)"). `build_query` 만 — 검색·DB 0."""

from __future__ import annotations

from collections import Counter

import pytest

from aml_ai.str.domain.rag_queries import build_query
from tests.str import rag_eval_corpus_draw as draw
from tests.str import rag_eval_v2_ledger as ledger
from tests.str.rag_eval_corpus_draw import INDUSTRIES, SIGNALS, UNRELATED_INDUSTRIES, draw_queries
from tests.str.rag_eval_corpus_guard import normalized_sha256
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR, UNRELATED_NOTE, load_queries, query_text
from tests.str.rag_eval_v2_support import build_facts
from tests.str.rag_eval_v2_support import load_queries as load_v2
from tests.str.test_rag_eval_v2_ledger_format import consumed_problems, ledger_problems

_QUERIES = load_queries()
_V2_TEXTS = {build_query(build_facts(q)) for split in ("dev", "holdout") for q in load_v2(split)}
QUERY_KEYS = {"id", "split", "typology", "base", "overrides", "uses"}
# 추가 검토 1 — 추출 규칙을 모듈과 따로 고정(10_rag "질의 세트"·09 2026-11-19). 모듈과 파일을 함께 바꿔도 여기서 걸림
EXPECTED_SEED = 304
EXPECTED_SIGNALS = [
    "account_in_counterparties_24h",
    "cross_border_amount_24h",
    "distinct_recipients_24h",
    "distinct_senders_24h",
    "inflow_outflow_ratio_2h",
    "outflow_ratio_2h",
]
EXPECTED_INDUSTRIES = ["RETAIL", "WHOLESALE", "TRADING", "RESTAURANT", None]
EXPECTED_UNRELATED = ["RETAIL", "MANUFACTURING"]
EXPECTED_PLAN = [
    ("CYCLE", "CY", 8, ["facts_cycle_nopaths.json", "facts_multi_currency.json"], ["hit"]),
    ("SCATTER_GATHER", "SG", 8, ["facts_scatter_gather.json"], ["hit", "empty"]),
    ("GATHER_SCATTER", "GS", 8, ["facts_scatter_gather.json"], ["hit", "empty"]),
    ("FX_RELAY", "FX", 4, ["facts_multi_currency.json"], ["empty"]),
]
QUERIES_SHA256 = (
    "cd66f3b7c4e9c1f434aef9fa2456046621440facfdcae793ba3567971428139a"  # 정규화 JSON(키 정렬·공백 없음)
)


def test_file_is_the_seeded_draw() -> None:
    """손으로 고르지 않음 — 시드 304 기계 추출을 다시 돌리면 같은 파일."""
    assert draw_queries(_V2_TEXTS) == _QUERIES


def test_draw_rule_matches_fixed_values() -> None:
    assert draw.QUERY_SEED == EXPECTED_SEED
    assert draw.SIGNALS == EXPECTED_SIGNALS and draw.INDUSTRIES == EXPECTED_INDUSTRIES
    assert draw.UNRELATED_INDUSTRIES == EXPECTED_UNRELATED and draw.PLAN == EXPECTED_PLAN


def test_query_file_hash_is_pinned() -> None:
    assert normalized_sha256(_QUERIES) == QUERIES_SHA256


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("QUERY_SEED", 305),
        ("SIGNALS", EXPECTED_SIGNALS[:-1]),
        ("INDUSTRIES", ["RETAIL", "WHOLESALE", "MANUFACTURING", "RESTAURANT", None]),
        ("INDUSTRIES", list(reversed(EXPECTED_INDUSTRIES))),
    ],
)
def test_changed_seed_or_range_breaks_the_pins(
    monkeypatch: pytest.MonkeyPatch, name: str, value: object
) -> None:
    """시드·범위를 바꿔 다시 만들면 고정 해시와 달라지고, 고정값 검사도 실패."""
    monkeypatch.setattr(draw, name, value)
    assert normalized_sha256(draw_queries(_V2_TEXTS)) != QUERIES_SHA256
    with pytest.raises(AssertionError):
        test_draw_rule_matches_fixed_values()


def test_allocation_and_uses() -> None:
    assert Counter(q["typology"] for q in _QUERIES) == {
        "CYCLE": 8,
        "SCATTER_GATHER": 8,
        "GATHER_SCATTER": 8,
        "FX_RELAY": 4,
        None: 2,
    }
    uses = {q["typology"]: q["uses"] for q in _QUERIES}
    assert uses == {
        "CYCLE": ["hit"],
        "SCATTER_GATHER": ["hit", "empty"],
        "GATHER_SCATTER": ["hit", "empty"],
        "FX_RELAY": ["empty"],
        None: ["reference"],
    }
    assert {q["split"] for q in _QUERIES} == {"holdout_v2"} and len({q["id"] for q in _QUERIES}) == 30


def test_texts_are_distinct_and_new() -> None:
    texts = [query_text(q) for q in _QUERIES]
    assert len(set(texts)) == len(texts)
    assert not set(texts) & _V2_TEXTS


def test_no_answers_and_only_query_fields() -> None:
    for q in _QUERIES:
        assert set(q) - {"note"} == QUERY_KEYS
        assert set(q["overrides"]) <= {"industry", "model_signals"}


def test_unrelated_queries_are_reference_only() -> None:
    unrelated = [q for q in _QUERIES if q["typology"] is None]
    assert [q["note"] for q in unrelated] == [UNRELATED_NOTE] * 2
    assert [query_text(q) for q in unrelated] == ["RETAIL", "MANUFACTURING"]
    assert all(build_facts(q).typology is None for q in unrelated)


def test_override_values_come_from_draw_vocabulary() -> None:
    """범주 값만 — 계좌·금액·이름 칸 없음."""
    for q in _QUERIES:
        assert set(q["overrides"]["model_signals"]) <= set(SIGNALS)
        assert q["overrides"]["industry"] in {*INDUSTRIES, *UNRELATED_INDUSTRIES}


def test_ledger_starts_empty_and_well_formed() -> None:
    path = CORPUS_EVAL_DIR / ledger.LEDGER_NAME
    assert path.is_file() and path.read_text(encoding="utf-8") == ""
    assert ledger_problems(CORPUS_EVAL_DIR, consumed=[]) == []
    assert consumed_problems(CORPUS_EVAL_DIR, consumed=[]) == []
