"""SCRUM-126 — RAG 평가 지표 (순수 함수, docs/str/10 "평가").

두 벌 계산(엄격=2점만 / 넓은=1점 이상):
- hit@3        — 기대 청크 하나라도 top-3 에 든 질의 비율
- precision@3  — top-3 중 기대 청크 비율
- recall@3     — |기대 ∩ top-3| ÷ |기대|

보조 지표:
- overlap_rate         — top-3 안에서 본문 공통 100자 이상 쌍 비율 (중복 근거 감시)
- same_typology_jaccard — 같은 expected_set 참조 질의들의 top-3 chunk_id Jaccard 평균
                         (SCRUM-146 다중 질의 비교 근거)

`retrieval_eval.json` 모양:
    expected_set ∈ {"FAN_IN","FAN_OUT","CYCLE", null}  # null = 빈 집합(분모 밖)
    expected_sets[유형] = {"2": [chunk_id,...], "1": [...]}  # 2=그래프 패턴, 1=관련 약함
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

Mode = Literal["strict", "wide"]


def resolve_expected(
    expected_set: str | None,
    *,
    expected_sets: Mapping[str, Mapping[str, Sequence[str]]],
) -> dict[str, set[str]] | None:
    """`expected_set` 이름을 `{"2": set, "1": set}` 으로 해석.

    `None` → None (빈 집합 질의, 지표 분모 밖).
    이름이 `expected_sets` 밖이면 `KeyError`.
    """
    if expected_set is None:
        return None
    if expected_set not in expected_sets:
        raise KeyError(f"expected_set {expected_set!r} not in expected_sets")
    grp = expected_sets[expected_set]
    return {"2": set(grp["2"]), "1": set(grp["1"])}


def _expected_set_for_mode(expected: Mapping[str, set[str]], mode: Mode) -> set[str]:
    if mode == "strict":
        return set(expected["2"])
    # wide = 2점 ∪ 1점
    return set(expected["2"]) | set(expected["1"])


def hit_at_k(top_k: Sequence[str], expected: set[str]) -> int:
    """기대 청크 하나라도 top-k 에 들면 1, 아니면 0."""
    return 1 if any(c in expected for c in top_k) else 0


def precision_at_k(top_k: Sequence[str], expected: set[str]) -> float:
    """top-k 중 기대 청크 비율."""
    if not top_k:
        return 0.0
    return sum(1 for c in top_k if c in expected) / len(top_k)


def recall_at_k(top_k: Sequence[str], expected: set[str]) -> float:
    """|기대 ∩ top-k| ÷ |기대|."""
    if not expected:
        return 0.0
    return sum(1 for c in top_k if c in expected) / len(expected)


def scored_metrics(
    top_k: Sequence[str], expected: Mapping[str, Sequence[str]], *, mode: Mode
) -> dict[str, float]:
    """한 질의의 hit·precision·recall 을 모드별로."""
    exp_set = _expected_set_for_mode({k: set(v) for k, v in expected.items()}, mode)
    return {
        "hit": hit_at_k(top_k, exp_set),
        "precision": precision_at_k(top_k, exp_set),
        "recall": recall_at_k(top_k, exp_set),
    }


def _norm(s: str) -> str:
    """NFKC + 공백 정돈 (`" ".join(s.split())`)."""
    return " ".join(unicodedata.normalize("NFKC", s).split())


def _longest_common_substring(a: str, b: str, *, min_len: int = 1) -> int:
    """두 문자열의 가장 긴 공통 부분문자열 길이. `min_len` 미만이면 조기 종료 없음."""
    if not a or not b:
        return 0
    # DP O(len(a)·len(b)) — 청크 짧으니 OK.
    prev = [0] * (len(b) + 1)
    best = 0
    for _i, ca in enumerate(a, 1):
        curr = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
                    if best >= min_len and best == max(len(a), len(b)):
                        return best
        prev = curr
    return best


def overlap_rate(
    chunks: Iterable[Mapping[str, str]],
    *,
    min_common_chars: int = 100,
) -> int:
    """top-k 안에서 본문이 겹치는 청크 쌍 수.

    각 청크 `text` 를 NFKC·공백정돈 뒤 쌍마다 가장 긴 공통 부분문자열 길이 비교.
    `min_common_chars` 이상이면 1쌍. 반환값은 쌍 수(비율 아님 — 호출 측에서 /총쌍 수).
    """
    norms = [_norm(c["text"]) for c in chunks]
    n = len(norms)
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            if _longest_common_substring(norms[i], norms[j], min_len=min_common_chars) >= min_common_chars:
                pairs += 1
    return pairs


def same_typology_jaccard(
    query_tops: Mapping[str, tuple[Sequence[str], str | None]],
) -> dict[str, float | None]:
    """같은 `expected_set` 참조 질의들의 top-k chunk_id Jaccard 평균.

    `query_tops[qid] = (top_chunk_ids, expected_set_name)`. SCRUM-146 다중 질의 비교 근거 —
    질의 문장이 거의 같으면 결과도 거의 같음. 한 유형에 쌍이 없으면 `None`.
    """
    by_set: dict[str, list[set[str]]] = {}
    for _qid, (top, set_name) in query_tops.items():
        if set_name is None:
            continue
        by_set.setdefault(set_name, []).append(set(top))
    out: dict[str, float | None] = {}
    for set_name, tops in by_set.items():
        if len(tops) < 2:
            out[set_name] = None
            continue
        sims: list[float] = []
        for i in range(len(tops)):
            for j in range(i + 1, len(tops)):
                union = tops[i] | tops[j]
                if not union:
                    continue
                sims.append(len(tops[i] & tops[j]) / len(union))
        out[set_name] = sum(sims) / len(sims) if sims else None
    return out
