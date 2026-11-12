"""SCRUM-126 — RAG 평가 지표 단위 테스트 (docs/str/10 "평가").

두 벌 계산(엄격=2점만 / 넓은=1점 이상) · overlap_rate(본문 공통 100자 쌍) ·
same_typology_jaccard(같은 expected_set 참조 질의 top-3 Jaccard 평균, SCRUM-146 비교 근거).

retrieval_eval.json 모양 검사: queries 10 · expected_set ∈ {FAN_IN·FAN_OUT·CYCLE·null} ·
expected_sets 키 정확히 3개 · "2" 리스트 ≥ 1 · "2"∩"1" = ∅ · 중복 없음 · chunk_id 64자 hex.

develop 에서는 `tools.rag_eval` 모듈 자체가 없어 collection ImportError — 실패해야 정상.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tools.rag_eval import (
    hit_at_k,
    overlap_rate,
    precision_at_k,
    recall_at_k,
    resolve_expected,
    same_typology_jaccard,
    scored_metrics,
)

CHUNK_RE = re.compile(r"^[0-9a-f]{64}$")

EVAL_JSON = Path(__file__).resolve().parents[1] / "str" / "retrieval_eval.json"


# ──────────────────── 지표 함수 (두 벌 계산) ────────────────────


def test_scored_metrics_strict_vs_wide_two_in_three() -> None:
    """기대 2={A,B}·1={C}, top-3={A,B,D} → 엄격 hit=1·p=2/3·r=1.0 / 넓은 hit=1·p=2/3·r=2/3."""
    expected = {"2": ["A", "B"], "1": ["C"]}
    top = ["A", "B", "D"]
    strict = scored_metrics(top, expected, mode="strict")
    wide = scored_metrics(top, expected, mode="wide")
    assert strict == {"hit": 1, "precision": 2 / 3, "recall": 2 / 2}
    assert wide == {"hit": 1, "precision": 2 / 3, "recall": 2 / 3}


def test_hit_zero_when_no_overlap() -> None:
    assert hit_at_k(["X", "Y", "Z"], {"A", "B"}) == 0


def test_precision_counts_only_expected() -> None:
    assert precision_at_k(["A", "B", "C"], {"A", "C"}) == 2 / 3


def test_recall_caps_at_one_when_expected_small() -> None:
    assert recall_at_k(["A", "B", "C"], {"A"}) == 1.0


def test_recall_below_one_when_expected_larger_than_k() -> None:
    """기대 5개 중 3개만 top-3 에 → 3/5."""
    assert recall_at_k(["A", "B", "C"], {"A", "B", "C", "D", "E"}) == 3 / 5


def test_empty_top_gives_zero() -> None:
    expected = {"2": ["A"], "1": []}
    r = scored_metrics([], expected, mode="strict")
    assert r == {"hit": 0, "precision": 0.0, "recall": 0.0}


# ──────────────────── expected_set=null 은 분모 밖 ────────────────────


def test_null_expected_set_returned_as_empty_marker() -> None:
    """빈 집합 질의(expected_set=None) — 지표 분모 밖, '빈 결과 맞음' 별도.

    resolve_expected 가 None 을 받으면 특수값(빈 집합 표식) 반환.
    """
    result = resolve_expected(None, expected_sets={"FAN_IN": {"2": ["A"], "1": []}})
    assert result is None  # 빈 집합 질의 — 지표 계산에서 제외


# ──────────────────── overlap_rate — 본문 공통 100자 쌍 ────────────────────


def test_overlap_rate_catches_shared_text_pair() -> None:
    """top-3 안 두 청크 본문이 NFKC·공백정돈 뒤 공통 100자 이상이면 1쌍.

    9761a3b1·d994051 (ffiec p6 이어진 CYCLE 청크) 같은 경계 쌍 재현.
    """
    common = "funds are moved back to the first bank " * 4  # 100자 이상 공통
    chunks = [
        {"chunk_id": "a" * 64, "text": "intro " + common + " outro-A"},
        {"chunk_id": "b" * 64, "text": "intro " + common + " outro-B"},
        {"chunk_id": "c" * 64, "text": "완전히 다른 적색신호 bullet 내용 없음 공통"},
    ]
    assert overlap_rate(chunks, min_common_chars=100) == 1  # 1 쌍 (a,b)


def test_overlap_rate_zero_when_all_distinct() -> None:
    chunks = [
        {"chunk_id": "a" * 64, "text": "first distinct content aaa"},
        {"chunk_id": "b" * 64, "text": "second very different bbb"},
        {"chunk_id": "c" * 64, "text": "third quite unrelated ccc"},
    ]
    assert overlap_rate(chunks, min_common_chars=100) == 0


# ──────────────────── same_typology_jaccard ────────────────────


def test_same_typology_jaccard_averages_pairs() -> None:
    """같은 expected_set 참조 질의들의 top-3 Jaccard 평균. SCRUM-146 비교 근거."""
    query_tops = {
        "Q01": (["A", "B", "C"], "FAN_IN"),
        "Q02": (["A", "B", "D"], "FAN_IN"),  # Q01 과 2/4 = 0.5
        "Q03": (["A", "B", "E"], "FAN_IN"),  # Q01 과 2/4=0.5, Q02 와 2/4=0.5
        "Q05": (["X", "Y", "Z"], "FAN_OUT"),  # 한 개뿐 — Jaccard 계산 제외
    }
    j = same_typology_jaccard(query_tops)
    assert j["FAN_IN"] == pytest.approx(0.5)  # 세 쌍 평균
    assert j["FAN_OUT"] is None  # 쌍 없음


# ──────────────────── retrieval_eval.json 모양 검사 ────────────────────


def test_retrieval_eval_json_shape() -> None:
    data = json.loads(EVAL_JSON.read_text(encoding="utf-8"))
    queries = data["queries"]
    assert len(queries) == 10

    v2_typos = {"FAN_IN", "FAN_OUT", "CYCLE", "SCATTER_GATHER", "GATHER_SCATTER", "PASS_THROUGH",
                "STACK", "BIPARTITE", "STRUCTURING", "NEW_ACCOUNT_LARGE", "HIGH_VALUE",
                "DORMANT_BURST"}  # fmt: skip
    allowed_set = {"FAN_IN", "FAN_OUT", "CYCLE", None}
    for q in queries:
        assert q["typology"] in v2_typos, q
        assert q["expected_set"] in allowed_set, q
        # expected_set != None 이면 typology 와 일치
        if q["expected_set"] is not None:
            assert q["typology"] == q["expected_set"], q

    sets = data["expected_sets"]
    assert set(sets.keys()) == {"FAN_IN", "FAN_OUT", "CYCLE"}
    for ty, grp in sets.items():
        assert set(grp.keys()) == {"2", "1"}, ty
        two = grp["2"]
        one = grp["1"]
        assert len(two) >= 1, f"{ty}: 2점 ≥ 1 필수"
        assert len(set(two)) == len(two), f"{ty}/2: 중복"
        assert len(set(one)) == len(one), f"{ty}/1: 중복"
        assert set(two).isdisjoint(set(one)), f"{ty}: 2·1 겹침"
        for cid in two + one:
            assert CHUNK_RE.match(cid), f"{ty}: chunk_id 64자 hex 아님 — {cid!r}"


# ──────────────────── 실패: 모르는 chunk_id ────────────────────


def test_scored_metrics_rejects_unknown_chunk_in_expected() -> None:
    """expected_sets 바깥을 resolve_expected 로 받으면 오류."""
    with pytest.raises(KeyError):
        resolve_expected("FAN_IN", expected_sets={"FAN_OUT": {"2": ["A"], "1": []}})
