"""SCRUM-146 후보 목록 합치기 — RRF (docs/str/10 "다중 질의·합치기"). 순수.

입력 = 후보 목록 여러 개(목록마다 rank 1부터). 점수 = Σ 1 / (k + rank). 정렬: RRF 큰 순 → 그 청크의 최대
cosine 큰 순 → chunk_id 오름차순. chunk_id 하나에 한 번. cosine = 여러 목록에서 받은 값 중 최대
(`Reference.score` 로 나감 — RRF 는 밖에 안 나감). SCRUM-275 키워드 목록도 같은 입력 모양.
"""

from __future__ import annotations

from dataclasses import dataclass

from aml_ai.str.domain.constants import RAG_RRF_K


@dataclass(frozen=True)
class Candidate:
    chunk_id: str
    rank: int  # 1부터
    cosine: float


@dataclass(frozen=True)
class Fused:
    chunk_id: str
    rrf: float
    cosine: float  # 최대 cosine


def rrf_fuse(lists: list[list[Candidate]], k: int = RAG_RRF_K) -> list[Fused]:
    scores: dict[str, Fused] = {}
    for candidates in lists:
        for candidate in candidates:
            previous = scores.get(candidate.chunk_id)
            scores[candidate.chunk_id] = Fused(
                candidate.chunk_id,
                (previous.rrf if previous else 0.0) + 1 / (k + candidate.rank),
                max(previous.cosine, candidate.cosine) if previous else candidate.cosine,
            )
    return sorted(scores.values(), key=lambda item: (-item.rrf, -item.cosine, item.chunk_id))
