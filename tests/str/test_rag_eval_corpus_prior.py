"""SCRUM-304 이전 판정 기록 prior (추가 검토 2 반영 — 한 번 나온 미달을 지우거나 바꿔 결론을 돌리는 길). 순수."""

from __future__ import annotations

import pytest

from tests.str.rag_eval_corpus_support import Prior, Run, verdict
from tests.str.test_rag_eval_corpus_verdict import FAN_OK, GRADES, _all, _manifest, _pre, _typed

FIRST = verdict(_all(8, 2, 2), _pre(), GRADES, FAN_OK, manifest=_manifest(_all(8, 2, 2)),
                pre_sha256=_pre().sha256(), prior=None, prior_sha256=None)  # fmt: skip
PRIOR = Prior.from_verdict(FIRST)  # SG·GS 미달
RECORDED = PRIOR.sha256()  # 305 — 원장에 적힌 첫 판정 기록 해시


def _again(runs: list[Run], pre=None, prior: Prior | None = PRIOR, recorded: str | None = RECORDED) -> dict:
    pre = pre or _pre()
    return verdict(runs, pre, GRADES, FAN_OK, manifest=_manifest(runs), pre_sha256=pre.sha256(),
                   prior=prior, prior_sha256=recorded)  # fmt: skip


def test_first_verdict_fails_sg() -> None:
    assert dict(PRIOR.statuses) == {"CYCLE": "pass", "SCATTER_GATHER": "fail", "GATHER_SCATTER": "fail"}
    assert FIRST["conclusion"] == "restore"


def test_recorded_fail_keeps_restore_even_if_inputs_would_pass() -> None:
    out = _again(_all(8, 8, 2))  # prior 없으면 CYCLE·SG 통과 → 채택이 될 입력
    assert out["typology"]["SCATTER_GATHER"] == {**out["typology"]["SCATTER_GATHER"], "status": "fail", "reason": "pinned"}  # fmt: skip
    assert out["conclusion"] == "restore"


@pytest.mark.parametrize(
    "statuses",
    [
        {"CYCLE": "pass", "SCATTER_GATHER": "pass", "GATHER_SCATTER": "fail"},  # SG fail → pass 로 바꾼 기록
        {"CYCLE": "pass", "SCATTER_GATHER": "not_judged", "GATHER_SCATTER": "fail"},
    ],
)
def test_changed_record_is_rejected(statuses: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="prior differs"):
        _again(_all(8, 8, 2), prior=Prior(statuses))


@pytest.mark.parametrize(
    "statuses",
    [
        {"cycle": "pass", "scatter_gather": "fail", "gather_scatter": "fail"},  # 소문자 키
        {"CYCLE": "pass", "GATHER_SCATTER": "fail"},  # SG 빠짐
        {
            "CYCLE": "pass",
            "SCATTER_GATHER": "fail",
            "GATHER_SCATTER": "fail",
            "FX_RELAY": "pass",
        },  # 모르는 키
        {"CYCLE": "pass", "SCATTER_GATHER": "FAIL", "GATHER_SCATTER": "fail"},  # 모르는 값
    ],
)
def test_malformed_record_is_rejected_before_verdict(statuses: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="prior must list"):
        Prior(statuses)


def test_record_from_verdict_needs_exact_typology_keys() -> None:
    with pytest.raises(ValueError):
        Prior.from_verdict({"typology": {"cycle": {"status": "pass"}}})


@pytest.mark.parametrize(("prior", "recorded"), [(PRIOR, None), (None, RECORDED)])
def test_record_and_hash_come_together(prior: Prior | None, recorded: str | None) -> None:
    with pytest.raises(ValueError, match="together"):
        _again(_all(8, 8, 2), prior=prior, recorded=recorded)


def test_record_is_read_only_and_copied() -> None:
    source = {"CYCLE": "pass", "SCATTER_GATHER": "fail", "GATHER_SCATTER": "fail"}
    prior = Prior(source)
    source["SCATTER_GATHER"] = "pass"
    assert prior.sha256() == RECORDED
    with pytest.raises(TypeError):
        prior.statuses["SCATTER_GATHER"] = "pass"  # type: ignore[index]


def test_recorded_fail_stays_fail_with_too_few_tags() -> None:
    out = _again(_all(8, 8, 2), pre=_pre(tagged={"SCATTER_GATHER": 3}))
    assert out["typology"]["SCATTER_GATHER"]["status"] == "fail"


def test_recorded_fail_stays_fail_with_too_few_queries() -> None:
    runs = _typed("CYCLE", 8) + _typed("SCATTER_GATHER", 5, 5) + _typed("GATHER_SCATTER", 2)
    out = _again(runs)
    assert out["typology"]["SCATTER_GATHER"]["status"] == "fail"
    assert out["typology"]["GATHER_SCATTER"]["status"] == "fail"
