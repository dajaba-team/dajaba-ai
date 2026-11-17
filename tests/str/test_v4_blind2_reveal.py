"""SCRUM-265 (1/2) — 재블라인드 집계 (09 2026-11-17 "SCRUM-265 1/2 — 사전 등록" ①②). LLM·DB 0.

① 12쌍 v4 전부 · ②③④ 새 8건만 · ③ v4 ≤ v2 그리고 v4 ≤ 2.0 · ④ v4 쪽 답만, 사건마다 3명 중 2명 이상, 8건 모두.
"""

from __future__ import annotations

from typing import Any

from tests.str.v4_blind2_io import diag_hash
from tests.str.v4_blind2_reveal import Response2, render_revealed2_md, reveal2

RATERS = ("r1", "r2", "r3")
JUDGED = [f"c{i}" for i in range(1, 9)]  # c1~c5 예 · c6~c8 아니오/알 수 없음
REGRESSION = ["g1", "g2", "g3"]
WRONG = "입금 합계는 1 미국 달러임."
RUN = "20261117-000000"  # 생성 실행 run_id


def _doc() -> dict[str, Any]:
    cases = [
        {"case_id": c, "role": "judged", "answer": ["yes"] if i <= 5 else ["no", "unknown"]}
        for i, c in enumerate(JUDGED, 1)
    ]
    cases += [{"case_id": c, "role": "regression", "answer": None} for c in REGRESSION]
    return {"cases": cases, "control_case_id": "c1"}


def _key(failing_pair: int | None = None) -> dict[str, Any]:
    """쌍 1~8 새 사건(v4 = A) · 9~11 회귀 · 12 대조. 같은 실행의 진단(_diag(failing_pair)) 해시로 묶음."""
    pairs = [
        {"pair_no": n, "case_id": c, "control": False, "A": "v4", "B": "v2"} for n, c in enumerate(JUDGED, 1)
    ]
    pairs += [
        {"pair_no": n, "case_id": c, "control": False, "A": "v4", "B": "v2"}
        for n, c in enumerate(REGRESSION, 9)
    ]
    pairs.append({"pair_no": 12, "case_id": "c1", "control": True, "A": "v4", "B": "v4"})
    return {"run_id": RUN, "seed": 1, "pairs": pairs, "diag_sha256": diag_hash(_diag(failing_pair))}


def _diag(failing_pair: int | None = None) -> dict[str, Any]:
    side = {"chars": 100, "sentences": {}, "code_check_failures": 0}
    return {
        "run_id": RUN,
        "pairs": [
            {"pair_no": n, "A": {**side, "code_check_failures": int(n == failing_pair)}, "B": side}
            for n in range(1, 13)
        ],
    }


def _right(case_no: int) -> str:
    return "yes" if case_no <= 5 else "no"


def _responses(
    v4_wins: int = 5, *, fix: tuple[int, int] = (1, 2), control: tuple[str, ...] = ("same",) * 3,
    support: dict[tuple[str, int], str | None] | None = None, wrong_v4: tuple[str, ...] = (),
) -> list[Response2]:  # fmt: skip
    """앞 v4_wins 개 새 사건은 세 명 모두 v4(A), 나머지는 v2(B). fix=(v4, v2). support_a 기본은 정답."""
    support = support or {}
    out = []
    for r in RATERS:
        for n in range(1, 13):
            new_case = "A" if n <= v4_wins or n > 8 else "B"  # 회귀(9~11)는 v4
            choice = control[RATERS.index(r)] if n == 12 else new_case
            ans = support.get((r, n), _right(n) if n <= 8 else "yes")
            wa = wrong_v4 if (r == "r1" and n == 9) else ()
            out.append(Response2(r, n, choice, fix[0], fix[1], wa, (), "", ans, "unknown", RUN))  # type: ignore[arg-type]
    return out


def test_all_four_met_is_candidate() -> None:
    res = reveal2(_responses(), _key(), _diag(), _doc())
    assert (res.fact_ok, res.preference_ok, res.fix_ok, res.support_ok) == (True, True, True, True)
    assert res.verdict == "candidate"


def test_preference_counts_only_new_cases_and_reports_record() -> None:
    """회귀 3건(쌍 9~11)은 세 명 모두 v4 여도 ② 에 안 셈 — 승·무·패는 새 8건으로."""
    res = reveal2(_responses(4), _key(), _diag(), _doc())
    assert res.record == {"v4": 4, "v2": 4, "none": 0}
    assert res.preference_ok is False and res.verdict == "not_met"
    assert set(res.case_winner) == set(JUDGED)
    assert set(res.regression_winner) == set(REGRESSION)


def test_fix_needs_v4_not_above_v2_and_at_most_two() -> None:
    assert reveal2(_responses(fix=(2, 2)), _key(), _diag(), _doc()).fix_ok is True
    res = reveal2(_responses(fix=(3, 4)), _key(), _diag(), _doc())
    assert res.fix_mean == {"v2": 4.0, "v4": 3.0} and res.fix_ok is False  # v4 ≤ v2 지만 2.0 넘음
    assert reveal2(_responses(fix=(2, 1)), _key(), _diag(), _doc()).fix_ok is False


def test_fix_mean_excludes_regression_pairs() -> None:
    rs = [
        Response2(r.rater, r.pair_no, r.choice, 9 if 9 <= r.pair_no <= 11 else r.fix_a, r.fix_b, r.wrong_a, r.wrong_b,
                  r.reason, r.support_a, r.support_b, r.run_id)
        for r in _responses()
    ]  # fmt: skip
    assert reveal2(rs, _key(), _diag(), _doc()).fix_mean["v4"] == 1.0


def test_support_scored_on_v4_side_only() -> None:
    """B(v2) 쪽 답은 전부 unknown 이어도 무관. v4 쪽이 틀린 사건이 하나라도 2명 넘으면 미달."""
    ok = reveal2(_responses(), _key(), _diag(), _doc())
    assert ok.support_correct == {c: 3 for c in JUDGED}
    one_wrong = {("r1", 1): "no"}  # 2/3 정답 → 통과
    assert reveal2(_responses(support=one_wrong), _key(), _diag(), _doc()).support_ok is True
    two_wrong = {("r1", 1): "no", ("r2", 1): "unknown"}  # 1/3 → 미달
    res = reveal2(_responses(support=two_wrong), _key(), _diag(), _doc())
    assert res.support_correct["c1"] == 1 and res.support_ok is False and res.verdict == "not_met"


def test_unsupported_slot_accepts_no_and_unknown_but_not_yes() -> None:
    both = {("r1", 6): "unknown", ("r2", 6): "no", ("r3", 6): "unknown"}
    assert reveal2(_responses(support=both), _key(), _diag(), _doc()).support_correct["c6"] == 3
    yes = {("r1", 7): "yes", ("r2", 7): "yes"}
    res = reveal2(_responses(support=yes), _key(), _diag(), _doc())
    assert res.support_correct["c7"] == 1 and res.support_ok is False


def test_regression_support_not_scored() -> None:
    wrong = {(r, 10): "no" for r in RATERS}
    res = reveal2(_responses(support=wrong), _key(), _diag(), _doc())
    assert res.support_ok is True and "g2" not in res.support_correct


def test_fact_includes_regression_v4() -> None:
    """① 은 12쌍 v4 전부 — 회귀 쌍 v4 코드 검사 실패·확인된 틀린 문장도 깸."""
    assert reveal2(_responses(), _key(failing_pair=10), _diag(failing_pair=10), _doc()).fact_ok is False
    confirmed = {("r1", 9, "A", WRONG)}
    res = reveal2(_responses(wrong_v4=(WRONG,)), _key(), _diag(), _doc(), confirmed)
    assert res.fact_ok is False and res.verdict == "not_met"


def test_control_two_raters_is_directional() -> None:
    res = reveal2(_responses(control=("A", "B", "same")), _key(), _diag(), _doc())
    assert res.control_diff_raters == 2 and res.verdict == "directional"


def test_md_shows_record_and_support() -> None:
    md = render_revealed2_md(reveal2(_responses(), _key(), _diag(), _doc()))
    for want in ("승 5", "무 0", "패 3", "④ 유형 뒷받침", "2.0", "회귀", *JUDGED, *REGRESSION):
        assert want in md, want
