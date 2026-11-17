"""SCRUM-265 (1/2) — 재블라인드 응답 입력 검사 (09 "SCRUM-265 1/2 — 사전 등록" 평가자 명단·응답 양식). LLM·DB 0.

평가자 3명 고정(빠짐·넘침 거절) · support 값 셋 · choice 값 셋 · 빈 양식 거절.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.str.test_v4_blind2_reveal import RUN, _diag, _doc, _key, _responses, _right
from tests.str.v4_blind2_io import load_responses2, responses_template2
from tests.str.v4_blind2_reveal import Response2, reveal2


@pytest.mark.parametrize("bad", [None, "", "maybe", "YES", "예"])
def test_support_value_rejected(bad: str | None) -> None:
    with pytest.raises(ValueError):
        reveal2(_responses(support={("r2", 3): bad}), _key(), _diag(), _doc())
    rs = [
        Response2(r.rater, r.pair_no, r.choice, r.fix_a, r.fix_b, r.wrong_a, r.wrong_b, r.reason, r.support_a, bad, r.run_id)
        if (r.rater, r.pair_no) == ("r1", 1) else r
        for r in _responses()
    ]  # fmt: skip
    with pytest.raises(ValueError):
        reveal2(rs, _key(), _diag(), _doc())  # 채점 안 하는 v2 쪽도 빈 값은 거절


def test_missing_or_extra_rater_rejected() -> None:
    """추가 검토 1차 재현 — 3명이면 not_met(v4 고칠 양 3.67), r3 를 통째로 빼면 candidate 가 되던 입력은 거절."""
    rs = [
        Response2(r.rater, r.pair_no, r.choice, 9 if r.rater == "r3" else r.fix_a, 9 if r.rater == "r3" else r.fix_b,
                  r.wrong_a, r.wrong_b, r.reason, r.support_a, r.support_b, r.run_id)
        for r in _responses(fix=(1, 1))
    ]  # fmt: skip
    full = reveal2(rs, _key(), _diag(), _doc())
    assert full.verdict == "not_met" and round(full.fix_mean["v4"], 2) == 3.67
    with pytest.raises(ValueError):
        reveal2([r for r in rs if r.rater != "r3"], _key(), _diag(), _doc())
    extra = [Response2("r4", r.pair_no, r.choice, r.fix_a, r.fix_b, (), (), "", r.support_a, r.support_b, r.run_id)
             for r in rs if r.rater == "r1"]  # fmt: skip
    with pytest.raises(ValueError):
        reveal2(rs + extra, _key(), _diag(), _doc())
    with pytest.raises(ValueError):  # 한 명이 쌍 하나 빠짐
        reveal2([r for r in rs if (r.rater, r.pair_no) != ("r2", 5)], _key(), _diag(), _doc())


def test_choice_value_rejected() -> None:
    rs = _responses()
    rs[0] = Response2("r1", 1, "차이 없음", 1, 2, (), (), "", "yes", "yes", RUN)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        reveal2(rs, _key(), _diag(), _doc())


def _public() -> dict[str, Any]:
    return {"run_id": RUN, "pairs": [{"pair_no": n, "group": None} for n in range(1, 13)]}


def test_template_has_support_fields_and_blank_is_rejected(tmp_path: Path) -> None:
    rows = responses_template2(_public())
    assert len(rows) == 3 * 12
    assert all(r["support_a"] is None and r["support_b"] is None for r in rows)
    text = json.dumps(rows, ensure_ascii=False)
    for word in ("v2", "v4", "control", "대조", "seed", "regression", "회귀"):
        assert word not in text, word
    path = tmp_path / "responses.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        reveal2(load_responses2(path), _key(), _diag(), _doc())
    for r in rows:
        n = r["pair_no"]
        r.update(choice="same" if n == 12 else "A", fix_a=1, fix_b=2, support_b="unknown",
                 support_a=_right(n) if n <= 8 else "yes")  # fmt: skip
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    res = reveal2(load_responses2(path), _key(), _diag(), _doc())
    assert res.record["v4"] == 8 and res.verdict == "candidate"
