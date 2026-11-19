"""SCRUM-304 코퍼스 확장 판정 (docs/str/10 "코퍼스 확장 판정 (holdout_v2)", 09 2026-11-19 — 결과 보기 전 고정). 순수.

합성 입력만 — 검색·DB·LLM 0.
"""

from __future__ import annotations

import pytest

from tests.str.rag_eval_corpus_support import (
    ADOPT_MIN_PASSED,
    FAN_BASELINE_HIT,
    GRADE_MIN,
    MIN_QUERIES,
    MIN_TAGGED_CHUNKS,
    FanCase,
    PreRun,
    Run,
    hits_needed,
    verdict,
)

JUDGED = ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")


def _pre(tagged: dict[str, int] | None = None, checked: dict[str, bool] | None = None) -> PreRun:
    base = {"CYCLE": 30, "SCATTER_GATHER": 12, "GATHER_SCATTER": 15, "FX_RELAY": 0}
    return PreRun(tagged={**base, **(tagged or {})}, checked=checked or dict.fromkeys(JUDGED, True))


def _typed(typ: str, hits: int, n: int = 8, *, prefix: str = "") -> list[Run]:
    """hit 질의는 정답 청크 `{typ}-ok` 를 top-3 에, 나머지는 `{typ}-no`(등급 0)."""
    return [
        Run(f"{prefix}{typ}{i}", typ, f"{prefix}{typ} text {i}", [f"{typ}-ok" if i < hits else f"{typ}-no"])
        for i in range(n)
    ]


GRADES = {(t, f"{t}-ok"): 1 for t in JUDGED}
FAN_OK = [FanCase(f"D{i:02d}", [f"g{i}"], [f"g{i}"], {f"g{i}": 1}) for i in range(7, 11)]


def _manifest(runs: list[Run]) -> list[tuple[str, str | None, str]]:
    return [(r.id, r.typology, r.text) for r in runs]


def _verdict(runs: list[Run], pre: PreRun | None = None, fan: list[FanCase] | None = None, **kw) -> dict:
    """고정 질의 목록·실행 전 해시는 받은 입력 그대로, 첫 판정(prior None) — 대조·prior 테스트는 guard·prior 파일."""
    pre = pre or _pre()
    kw = {"manifest": _manifest(runs), "pre_sha256": pre.sha256(), "prior": None, "prior_sha256": None, **kw}
    return verdict(runs, pre, GRADES, FAN_OK if fan is None else fan, **kw)


def _all(cy: int, sg: int, gs: int) -> list[Run]:
    return _typed("CYCLE", cy) + _typed("SCATTER_GATHER", sg) + _typed("GATHER_SCATTER", gs)


def test_registered_numbers() -> None:
    assert (MIN_QUERIES, MIN_TAGGED_CHUNKS, GRADE_MIN, ADOPT_MIN_PASSED, FAN_BASELINE_HIT) == (
        6,
        10,
        1,
        2,
        1.0,
    )


@pytest.mark.parametrize(("n", "need"), [(8, 6), (7, 6), (6, 5)])
def test_hits_needed_is_ceil_three_quarters(n: int, need: int) -> None:
    assert hits_needed(n) == need


@pytest.mark.parametrize(("n", "hits", "status"), [(8, 6, "pass"), (8, 5, "fail"), (7, 6, "pass"), (7, 5, "fail"), (6, 5, "pass"), (6, 4, "fail")])  # fmt: skip
def test_hit_boundary(n: int, hits: int, status: str) -> None:
    out = _verdict(_typed("CYCLE", hits, n) + _typed("SCATTER_GATHER", 8) + _typed("GATHER_SCATTER", 8))
    assert out["typology"]["CYCLE"]["status"] == status
    assert out["typology"]["CYCLE"]["need"] == hits_needed(n)


def test_grade_zero_in_top3_is_not_a_hit_and_only_top3_counts() -> None:
    runs = [Run(f"C{i}", "CYCLE", f"t{i}", ["x", "y", "z", "CYCLE-ok"]) for i in range(8)]
    out = _verdict(runs + _typed("SCATTER_GATHER", 8) + _typed("GATHER_SCATTER", 8))
    assert out["typology"]["CYCLE"]["hits"] == 0


def test_duplicate_query_text_counts_once() -> None:
    runs = _typed("CYCLE", 5, 6)
    runs += [Run("dup", "CYCLE", runs[0].text, runs[0].top), Run("dup2", "CYCLE", runs[5].text, runs[5].top)]
    cyc = _verdict(runs + _typed("SCATTER_GATHER", 8) + _typed("GATHER_SCATTER", 8))["typology"]["CYCLE"]
    assert (cyc["queries"], cyc["hits"], cyc["need"], cyc["status"]) == (6, 5, 5, "pass")


def test_duplicates_dropping_below_six_is_not_judged() -> None:
    runs = _typed("CYCLE", 5, 5) + [Run("dup", "CYCLE", "CYCLE text 0", ["CYCLE-ok"])]
    cyc = _verdict(runs + _typed("SCATTER_GATHER", 8) + _typed("GATHER_SCATTER", 8))["typology"]["CYCLE"]
    assert (cyc["queries"], cyc["status"], cyc["reason"]) == (5, "not_judged", "queries")


@pytest.mark.parametrize(
    ("pre", "reason"),
    [
        (_pre(tagged={"SCATTER_GATHER": 9}), "tagged"),
        (_pre(checked={"CYCLE": True, "SCATTER_GATHER": False, "GATHER_SCATTER": True}), "unchecked"),
    ],
)
def test_not_judged_by_tags_or_check(pre: PreRun, reason: str) -> None:
    sg = _verdict(_all(8, 8, 8), pre)["typology"]["SCATTER_GATHER"]
    assert (sg["status"], sg["reason"]) == ("not_judged", reason)


def test_ten_tagged_is_enough() -> None:
    sg = _verdict(_all(8, 8, 8), _pre(tagged={"SCATTER_GATHER": 10}))["typology"]["SCATTER_GATHER"]
    assert sg["status"] == "pass"
