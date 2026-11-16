"""SCRUM-228 (2/2) 1단계 — 블라인드 공개 집계 왕복 (09 2026-11-17 2/2 1단계 ★A 기준 ①~③·대조쌍 2명 규칙). LLM·DB 0.

다수결 = 평가자 2명 이상이 같은 쪽을 고른 사건만 우세(1:0:2 는 우세 없음). 틀린 문장은 확인된 것만 ① 에 셈.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.str.v4_blind_reveal import Response, render_revealed_md, reveal
from tests.str.v4_blind_reveal_io import load_responses, responses_template

RATERS = ("r1", "r2", "r3")
CASES = [f"c{i}" for i in range(1, 9)]  # 대조쌍 제외 8 — 과반 5
WRONG = "입금 합계는 1 미국 달러임."


def _key(v4_side: str = "A") -> dict[str, Any]:
    v2_side = "B" if v4_side == "A" else "A"
    pairs = [
        {"pair_no": n, "case_id": c, "control": False, v4_side: "v4", v2_side: "v2"}
        for n, c in enumerate(CASES, 1)
    ]
    pairs.append({"pair_no": 9, "case_id": "c1", "control": True, "A": "v4", "B": "v4"})
    return {"seed": 1, "pairs": pairs, "v2_original": {}, "replaced": {}, "unknown": {}}


def _diag(v4_failures: int = 0, v4_side: str = "A") -> dict[str, Any]:
    side = {"chars": 100, "sentences": {}}
    other = "B" if v4_side == "A" else "A"
    return {
        "pairs": [
            {"pair_no": n, v4_side: {**side, "code_check_failures": v4_failures if n == 1 else 0},
             other: {**side, "code_check_failures": 0}}
            for n in range(1, 10)
        ]
    }  # fmt: skip


def _responses(
    v4_win_cases: int, *, control: tuple[str, ...] = ("same", "same", "same"), v4_side: str = "A",
    fix: tuple[int, int] = (1, 2), wrong_v4: tuple[str, ...] = (), wrong_v2: tuple[str, ...] = (),
) -> list[Response]:  # fmt: skip
    """앞 v4_win_cases 개 사건은 세 명 모두 v4, 나머지는 v2. fix=(v4, v2) 고칠 문장 수. 틀린 문장은 r1 이 쌍 1 에만."""
    v4c, v2c = ("A", "B") if v4_side == "A" else ("B", "A")
    out = []
    for r in RATERS:
        for n in range(1, 9):
            choice = v4c if n <= v4_win_cases else v2c
            fa, fb = fix if v4_side == "A" else fix[::-1]
            wv4, wv2 = (wrong_v4, wrong_v2) if (r == "r1" and n == 1) else ((), ())
            wa, wb = (wv4, wv2) if v4_side == "A" else (wv2, wv4)
            out.append(Response(r, n, choice, fa, fb, wa, wb))  # type: ignore[arg-type]
        out.append(Response(r, 9, control[RATERS.index(r)], 0, 0))  # type: ignore[arg-type]
    return out


def _with_pair(rs: list[Response], pair_no: int, choices: tuple[str, str, str]) -> list[Response]:
    picks = dict(zip(RATERS, choices, strict=True))
    return [r if r.pair_no != pair_no else Response(r.rater, pair_no, picks[r.rater], 0, 0) for r in rs]  # type: ignore[arg-type]


def test_all_three_criteria_met_is_candidate() -> None:
    res = reveal(_responses(5), _key(), _diag())
    assert (res.fact_ok, res.preference_ok, res.fix_ok) == (True, True, True)
    assert res.v4_wins == 5 and res.cases == 8 and res.verdict == "candidate"


def test_mapping_follows_key_when_v4_is_on_b_side() -> None:
    res = reveal(_responses(6, v4_side="B"), _key("B"), _diag(v4_side="B"))
    assert res.v4_wins == 6 and res.verdict == "candidate"


def test_preference_needs_strict_majority_of_cases() -> None:
    res = reveal(_responses(4), _key(), _diag())
    assert res.preference_ok is False and res.verdict == "not_met"


def test_case_majority_needs_two_raters_on_same_side() -> None:
    """1:0:2(v4 1명·v2 0명·차이 없음 2명)·1:1:1 은 우세 없음, 2:1 은 그쪽 우세."""
    rs = _with_pair(_responses(5), 1, ("A", "same", "same"))
    rs = _with_pair(rs, 2, ("A", "B", "same"))
    rs = _with_pair(rs, 3, ("A", "A", "B"))
    res = reveal(rs, _key(), _diag())
    assert (
        res.case_winner["c1"] == "none" and res.case_winner["c2"] == "none" and res.case_winner["c3"] == "v4"
    )
    assert res.v4_wins == 3 and res.preference_ok is False


def test_fact_fails_on_code_check_from_diag() -> None:
    assert reveal(_responses(8), _key(), _diag(v4_failures=1)).fact_ok is False


def test_unconfirmed_wrong_sentence_does_not_break_fact() -> None:
    res = reveal(_responses(8, wrong_v4=(WRONG,)), _key(), _diag())
    assert res.fact_ok is True
    assert [(w.rater, w.pair_no, w.case_id, w.version, w.text, w.confirmed) for w in res.wrong_sentences] == [
        ("r1", 1, "c1", "v4", WRONG, False)
    ]


def test_confirmed_wrong_sentence_breaks_fact_only_for_v4() -> None:
    confirmed = {("r1", 1, "A", WRONG)}
    res = reveal(_responses(8, wrong_v4=(WRONG,)), _key(), _diag(), confirmed)
    assert res.fact_ok is False and res.wrong_sentences[0].confirmed is True
    v2_only = reveal(_responses(8, wrong_v2=(WRONG,)), _key(), _diag(), {("r1", 1, "B", WRONG)})
    assert v2_only.fact_ok is True  # ① 은 v4 의 틀린 문장만


def test_fix_mean_v4_must_not_exceed_v2() -> None:
    assert reveal(_responses(8, fix=(2, 2)), _key(), _diag()).fix_ok is True
    res = reveal(_responses(8, fix=(3, 2)), _key(), _diag())
    assert res.fix_ok is False and res.fix_mean == {"v2": 2.0, "v4": 3.0}


def test_control_two_raters_seeing_difference_makes_it_directional() -> None:
    res = reveal(_responses(8, control=("A", "B", "same")), _key(), _diag())
    assert res.control_diff_raters == 2 and res.verdict == "directional"
    one = reveal(_responses(8, control=("A", "same", "same")), _key(), _diag())
    assert one.control_diff_raters == 1 and one.verdict == "candidate"


def test_rater_agreement_and_md_render() -> None:
    rs = _with_pair(_responses(5, wrong_v4=(WRONG,)), 1, ("A", "A", "B"))
    res = reveal(rs, _key(), _diag())
    assert res.rater_agreement["r1"] == 1.0 and res.rater_agreement["r3"] < 1.0
    md = render_revealed_md(res)
    assert all(c in md for c in CASES)
    assert "전환 후보" in md or "candidate" in md
    assert not any("一" <= ch <= "鿿" for ch in md)  # 한자 제목 없음


def _public() -> dict[str, Any]:
    return {"pairs": [{"pair_no": n, "group": "g1"} for n in range(1, 10)]}


def test_responses_template_has_one_blank_row_per_rater_and_pair() -> None:
    rows = responses_template(_public())
    assert len(rows) == 3 * 9
    assert {(r["rater"], r["pair_no"]) for r in rows} == {
        (f"평가자{i}", n) for i in (1, 2, 3) for n in range(1, 10)
    }
    fields = {"rater", "pair_no", "choice", "fix_a", "fix_b", "wrong_a", "wrong_b", "reason"}
    assert all(set(r) == fields for r in rows)
    assert all(r["choice"] == "" and r["fix_a"] is None and r["wrong_a"] == [] for r in rows)
    text = json.dumps(rows, ensure_ascii=False)
    for word in ("v2", "v4", "control", "대조", "g1", "seed"):
        assert word not in text, word


def test_blank_template_is_rejected_and_filled_template_round_trips(tmp_path: Path) -> None:
    rows = responses_template(_public())
    path = tmp_path / "responses.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        reveal(load_responses(path), _key(), _diag())
    for r in rows:
        control = r["pair_no"] == 9
        r.update(
            choice="same" if control else "A", fix_a=1, fix_b=2, wrong_a=[WRONG] if r["pair_no"] == 1 else []
        )
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    res = reveal(load_responses(path), _key(), _diag())
    assert res.v4_wins == 8 and res.verdict == "candidate" and len(res.wrong_sentences) == 3
