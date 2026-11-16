"""응답의 좌우를 키로 풀고 사건 단위 판정으로 집계한다."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from tests.str.v4_blind_reveal import Confirmed, Response, WrongSentence

Winner = Literal["v2", "v4", "none"]
Pairs = dict[int, dict[str, Any]]


def validate_responses(responses: list[Response], pairs: Pairs, metrics: Pairs) -> None:
    """빈 응답·중복 표·누락된 쌍·잘못된 선택이나 음수 건수를 거부한다."""
    if not responses or set(pairs) != set(metrics):
        raise ValueError("응답과 쌍별 지표가 필요함")
    seen: set[tuple[str, int]] = set()
    for r in responses:
        if r.pair_no not in pairs or r.choice not in ("A", "B", "same"):
            raise ValueError("응답의 쌍 번호 또는 선택 오류")
        counts = (r.fix_a, r.fix_b)
        if any(type(n) is not int or n < 0 for n in counts):
            raise ValueError("문장 수는 0 이상의 정수여야 함")
        for sentences in (r.wrong_a, r.wrong_b):
            if not isinstance(sentences, tuple) or any(not isinstance(s, str) for s in sentences):
                raise ValueError("틀린 문장은 문자열 튜플이어야 함")
        ballot = (r.rater, r.pair_no)
        if not r.rater or ballot in seen:
            raise ValueError("평가자 누락 또는 중복 응답")
        seen.add(ballot)
    if any((rater, number) not in seen for rater, _ in seen for number in pairs):
        raise ValueError("평가자별로 모든 쌍의 응답이 필요함")


def case_winners(responses: list[Response], pairs: Pairs, majority_raters: int) -> dict[str, Winner]:
    votes: dict[str, Counter[str]] = {p["case_id"]: Counter() for p in pairs.values() if not p["control"]}
    for r in responses:
        pair = pairs[r.pair_no]
        if not pair["control"] and r.choice != "same":
            votes[pair["case_id"]][pair[r.choice]] += 1
    return {
        case: (
            "v4"
            if vote["v4"] >= majority_raters and vote["v4"] > vote["v2"]
            else "v2"
            if vote["v2"] >= majority_raters and vote["v2"] > vote["v4"]
            else "none"
        )
        for case, vote in votes.items()
    }


def collect_wrong_sentences(
    responses: list[Response],
    pairs: Pairs,
    confirmed: Confirmed,
) -> list[WrongSentence]:
    """모든 보고 문장을 응답 순서대로 모으고 원문이 일치하는 확인만 붙인다."""
    from tests.str.v4_blind_reveal import WrongSentence

    return [
        WrongSentence(
            r.rater,
            r.pair_no,
            pairs[r.pair_no]["case_id"],
            side,
            pairs[r.pair_no][side],
            text,
            (r.rater, r.pair_no, side, text) in confirmed,
        )
        for r in responses
        for side, sentences in (("A", r.wrong_a), ("B", r.wrong_b))
        for text in sentences
    ]


def fact_passes(wrong_sentences: list[WrongSentence], pairs: Pairs, metrics: Pairs) -> bool:
    code_ok = all(
        metrics[number][side]["code_check_failures"] == 0
        for number, pair in pairs.items()
        for side in ("A", "B")
        if pair[side] == "v4"
    )
    return code_ok and not any(w.confirmed and w.version == "v4" for w in wrong_sentences)


def mean_fixes(responses: list[Response], pairs: Pairs) -> dict[str, float]:
    counts: dict[str, list[int]] = {"v2": [], "v4": []}
    for r in responses:
        pair = pairs[r.pair_no]
        if not pair["control"]:
            counts[pair["A"]].append(r.fix_a)
            counts[pair["B"]].append(r.fix_b)
    if not all(counts.values()):
        raise ValueError("비교할 사건 응답이 필요함")
    return {version: float(sum(values) / len(values)) for version, values in counts.items()}


def agreement(responses: list[Response], pairs: Pairs, winners: dict[str, Winner]) -> dict[str, float]:
    matches: dict[str, list[bool]] = {r.rater: [] for r in responses}
    for r in responses:
        pair = pairs[r.pair_no]
        if pair["control"] or winners[pair["case_id"]] == "none":
            continue
        version = pair[r.choice] if r.choice != "same" else "same"
        matches[r.rater].append(version == winners[pair["case_id"]])
    return {rater: sum(values) / len(values) if values else 0.0 for rater, values in matches.items()}
