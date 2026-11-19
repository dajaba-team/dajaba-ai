"""SCRUM-304 코퍼스 확장 판정 — ② 0건 · ③ FAN · 무관한 질의 · 전체 결론 (docs/str/10 "코퍼스 확장 판정 (holdout_v2)"). 순수."""

from __future__ import annotations

import pytest

from tests.str.rag_eval_corpus_support import FanCase, PreRun, Run, verdict
from tests.str.test_rag_eval_corpus_verdict import FAN_OK, GRADES, _all, _pre, _typed, _verdict

NO_SG_GS = {"SCATTER_GATHER": 0, "GATHER_SCATTER": 0}
FX = [Run(f"FX{i}", "FX_RELAY", f"fx {i}", []) for i in range(4)]


def _sg_gs_empty() -> list[Run]:
    return [
        Run(r.id, r.typology, r.text, []) for r in _typed("SCATTER_GATHER", 0) + _typed("GATHER_SCATTER", 0)
    ]


def test_zero_tag_typologies_must_return_nothing() -> None:
    out = _verdict(_typed("CYCLE", 8) + _sg_gs_empty() + FX, _pre(tagged=NO_SG_GS))
    assert out["empty"]["judged"] == ["SCATTER_GATHER", "GATHER_SCATTER", "FX_RELAY"]
    assert out["empty"]["ok"] is True and out["empty"]["failures"] == []


def test_one_result_on_zero_tag_typology_breaks_empty() -> None:
    fx = [*FX[:3], Run("FX3", "FX_RELAY", "fx 3", ["stray"])]
    out = _verdict(_typed("CYCLE", 8) + _sg_gs_empty() + fx, _pre(tagged=NO_SG_GS))
    assert out["empty"]["ok"] is False and out["empty"]["failures"] == ["FX3"]
    assert out["conclusion"] == "restore"


def test_tagged_typology_leaves_empty_check_as_reference() -> None:
    gs = [Run(r.id, r.typology, r.text, []) for r in _typed("GATHER_SCATTER", 0)]
    runs = _typed("CYCLE", 8) + _typed("SCATTER_GATHER", 8) + gs + FX
    out = _verdict(runs, _pre(tagged={"GATHER_SCATTER": 0}))
    assert out["empty"]["judged"] == ["GATHER_SCATTER", "FX_RELAY"]
    assert out["empty"]["excluded"] == {"SCATTER_GATHER": 12}
    assert out["empty"]["ok"] is True  # SG 결과 8×1건은 ② 실패가 아님


def test_unrelated_queries_never_change_conclusion() -> None:
    base = _verdict(_all(8, 8, 2) + FX, _pre(tagged={"FX_RELAY": 0}))
    unrelated = [Run("NR1", None, "RETAIL", []), Run("NR2", None, "MANUFACTURING", ["a", "b", "c"])]
    out = _verdict(_all(8, 8, 2) + FX + unrelated, _pre(tagged={"FX_RELAY": 0}))
    assert out["unrelated"] == [{"id": "NR1", "returned": 0}, {"id": "NR2", "returned": 3}]
    assert {k: out[k] for k in ("typology", "empty", "fan", "conclusion")} == {
        k: base[k] for k in ("typology", "empty", "fan", "conclusion")
    }


def test_fan_drop_to_three_quarters_breaks() -> None:
    fan = [FanCase(f"D{i:02d}", ["g"], ["g"] if i < 10 else ["x"], {"g": 1}) for i in range(7, 11)]
    out = _verdict(_all(8, 8, 8), fan=fan)
    assert (out["fan"]["hit_before"], out["fan"]["hit_after"]) == (1.0, 0.75)
    assert out["fan"]["ok"] is False and out["conclusion"] == "restore"


def test_fan_displaced_answers_are_counted_even_when_hit_holds() -> None:
    fan = [FanCase("D07", ["a", "b", "c"], ["a", "new", "c"], {"a": 2, "b": 1}), *FAN_OK[1:]]
    out = _verdict(_all(8, 8, 8), fan=fan)
    assert out["fan"]["ok"] is True and out["fan"]["displaced"] == 1


@pytest.mark.parametrize(
    ("hits", "pre", "conclusion", "passed"),
    [
        ((8, 8, 8), _pre(), "adopt", 3),
        ((6, 2, 6), _pre(), "adopt", 2),
        ((6, 2, 2), _pre(), "restore", 1),
        ((8, 8, 8), _pre(tagged={"SCATTER_GATHER": 2}), "adopt", 2),  # SG 판정 안 함 → CYCLE·GS 둘 다 통과
        ((8, 8, 2), _pre(tagged={"SCATTER_GATHER": 2}), "restore", 1),  # 판정 안 함은 통과로 안 셈
    ],
)
def test_conclusion(hits: tuple[int, int, int], pre: PreRun, conclusion: str, passed: int) -> None:
    out = _verdict(_all(*hits), pre)
    assert out["passed"] == passed and out["conclusion"] == conclusion


def test_all_pass_but_fan_or_empty_broken_restores() -> None:
    fan_bad = [FanCase("D07", ["g"], ["x"], {"g": 1}), *FAN_OK[1:]]
    assert _verdict(_all(8, 8, 8), fan=fan_bad)["conclusion"] == "restore"
    fx_bad = [Run("FX0", "FX_RELAY", "fx", ["stray"])]
    assert _verdict(_all(8, 8, 8) + fx_bad)["conclusion"] == "restore"


def test_verdict_records_criteria() -> None:
    out = _verdict(_all(8, 8, 8))
    assert out["criteria"]["min_queries"] == 6 and out["criteria"]["min_tagged_chunks"] == 10


def test_verdict_requires_manifest_and_snapshot() -> None:
    with pytest.raises(TypeError):
        verdict(_all(8, 8, 8), _pre(), GRADES, FAN_OK)  # type: ignore[call-arg]
