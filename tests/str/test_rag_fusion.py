"""SCRUM-146 — RRF 합치기 (docs/str/10 "다중 질의·합치기"). 순수, LLM·DB 0.

점수 Σ 1/(60 + rank) · RRF 큰 순 → 최대 cosine 큰 순 → chunk_id 오름차순 · chunk_id 한 번 · cosine 은 최대값.
"""

from __future__ import annotations

import pytest

from aml_ai.str.domain.constants import RAG_RRF_K
from aml_ai.str.domain.rag_fusion import Candidate, Fused, rrf_fuse


def _c(cid: str, rank: int, cos: float) -> Candidate:
    return Candidate(cid, rank, cos)


def test_k_is_60() -> None:
    assert RAG_RRF_K == 60


def test_empty_and_single_list() -> None:
    assert rrf_fuse([]) == [] and rrf_fuse([[]]) == []
    out = rrf_fuse([[_c("x", 1, 0.9), _c("y", 2, 0.8)]])
    assert out == [Fused("x", pytest.approx(1 / 61), 0.9), Fused("y", pytest.approx(1 / 62), 0.8)]


def test_chunk_in_two_lists_sums_and_keeps_max_cosine() -> None:
    out = rrf_fuse([[_c("x", 2, 0.7), _c("y", 1, 0.9)], [_c("x", 1, 0.8)]])
    assert [f.chunk_id for f in out] == ["x", "y"]
    assert out[0].rrf == pytest.approx(1 / 62 + 1 / 61) and out[0].cosine == 0.8
    assert len({f.chunk_id for f in out}) == len(out)


def test_tie_breaks_by_cosine_then_chunk_id() -> None:
    same_rank = rrf_fuse([[_c("b", 1, 0.5)], [_c("a", 1, 0.5)], [_c("c", 1, 0.6)]])
    assert [f.chunk_id for f in same_rank] == ["c", "a", "b"]


def test_custom_k() -> None:
    assert rrf_fuse([[_c("x", 1, 0.1)]], k=0)[0].rrf == pytest.approx(1.0)
