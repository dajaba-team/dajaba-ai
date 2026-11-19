"""SCRUM-304 판정 입력 고정·대조 (추가 검토 1 반영 — prior 는 test_rag_eval_corpus_prior.py — 결과를 본 뒤 입력을 바꿔 결론을 돌리는 길). 순수."""

from __future__ import annotations

import pytest

from tests.str.rag_eval_corpus_guard import normalized_sha256
from tests.str.rag_eval_corpus_support import FanCase, PreRun, Run, query_manifest, verdict
from tests.str.test_rag_eval_corpus_verdict import FAN_OK, GRADES, _all, _manifest, _pre

FX = [Run(f"FX{i}", "FX_RELAY", f"fx {i}", []) for i in range(3)] + [
    Run("FX3", "FX_RELAY", "fx 3", ["stray"])
]
RUNS = _all(8, 8, 8) + FX  # FX3 이 태그 0 유형에서 1건 → 복원


def _run(runs: list[Run], pre: PreRun, fan: list[FanCase] = FAN_OK, *, manifest=None, snapshot=None) -> dict:
    return verdict(runs, pre, GRADES, fan, manifest=manifest or _manifest(RUNS),
                   pre_sha256=snapshot or _pre().sha256(), prior=None, prior_sha256=None)  # fmt: skip


def test_reserved_inputs_give_restore() -> None:
    assert _run(RUNS, _pre())["conclusion"] == "restore"


def test_prerun_is_read_only_inside() -> None:
    pre = _pre()
    with pytest.raises(TypeError):
        pre.tagged["FX_RELAY"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        pre.checked["CYCLE"] = False  # type: ignore[index]


def test_prerun_copies_its_input() -> None:
    source = {"CYCLE": 30, "SCATTER_GATHER": 12, "GATHER_SCATTER": 15, "FX_RELAY": 0}
    pre = PreRun(tagged=source, checked=dict.fromkeys(("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER"), True))
    before = pre.sha256()
    source["FX_RELAY"] = 1
    assert pre.tagged["FX_RELAY"] == 0 and pre.sha256() == before


@pytest.mark.parametrize("drop", ["FX_RELAY", "CYCLE"])
def test_prerun_needs_every_typology(drop: str) -> None:
    tagged = {"CYCLE": 30, "SCATTER_GATHER": 12, "GATHER_SCATTER": 15, "FX_RELAY": 0}
    del tagged[drop]
    with pytest.raises(ValueError):
        PreRun(tagged=tagged, checked=dict.fromkeys(("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER"), True))


def test_snapshot_hash_ignores_key_order() -> None:
    assert normalized_sha256({"a": 1, "b": [2]}) == normalized_sha256({"b": [2], "a": 1})


def test_changed_tag_count_after_run_is_rejected() -> None:
    """같은 결과 그대로, FX_RELAY 태그만 1 로 바꾸면 ② 대상에서 빠져 채택이 될 길 — 해시로 거절."""
    with pytest.raises(ValueError, match="pre-run"):
        _run(RUNS, _pre(tagged={"FX_RELAY": 1}))
    with pytest.raises(ValueError, match="pre-run"):
        _run(RUNS, _pre(checked={"CYCLE": True, "SCATTER_GATHER": False, "GATHER_SCATTER": True}))


def test_dropping_the_failing_fx_row_is_rejected() -> None:
    with pytest.raises(ValueError, match="missing \\['FX3'\\]"):
        _run(RUNS[:-1], _pre())


@pytest.mark.parametrize(
    "runs",
    [
        RUNS + [RUNS[0]],  # 같은 질의 두 번
        RUNS + [Run("X1", "CYCLE", "new", ["CYCLE-ok"])],  # 목록 밖
        RUNS[:-1] + [Run("FX3", "FX_RELAY", "fx other", [])],  # 문자열 바꿈
        RUNS[:-1] + [Run("FX3", "CYCLE", "fx 3", [])],  # 유형 바꿈
    ],
)
def test_runs_must_match_fixed_list(runs: list[Run]) -> None:
    with pytest.raises(ValueError):
        _run(runs, _pre())


@pytest.mark.parametrize(
    "fan",
    [
        FAN_OK[:3],  # D10 뺌
        [*FAN_OK, FAN_OK[0]],  # D07 두 번
        [*FAN_OK[:3], FanCase("D11", ["g"], ["g"], {"g": 1})],  # 목록 밖
    ],
)
def test_fan_needs_d07_to_d10_once_each(fan: list[FanCase]) -> None:
    with pytest.raises(ValueError, match="fan"):
        _run(RUNS, _pre(), fan)


def test_dropping_failed_d10_cannot_turn_restore_into_adopt() -> None:
    fan = [*FAN_OK[:3], FanCase("D10", ["g"], ["x"], {"g": 1})]
    runs = _all(8, 8, 8) + FX[:3]
    manifest = _manifest(runs)
    assert _run(runs, _pre(), fan, manifest=manifest)["conclusion"] == "restore"
    with pytest.raises(ValueError):
        _run(runs, _pre(), fan[:3], manifest=manifest)


def test_repo_manifest_is_the_fixed_query_list() -> None:
    manifest = query_manifest()
    assert len(manifest) == 30 and len({i for i, _, _ in manifest}) == 30
    assert len({t for _, _, t in manifest}) == 30
