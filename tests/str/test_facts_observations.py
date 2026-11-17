"""SCRUM-264 — 실제 ML reasons 거르기 (docs/str/04 `observations[]`·`model_signals[]` 거르기 ①~④).

실제 reasons: 피처 31개 중 |SHAP| 상위 3(부호 무관), basis 늘 `model_feature`, unit·window·baseline null,
추가 13개는 R02·R04 에서만 계산(경로 2개는 R04 만), 아니면 0 채움.
"""

from __future__ import annotations

from typing import Any

import pytest

from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.str.domain.constants_ml import (
    ML_EXTRA_FEATURES,
    ML_META_FEATURES,
    ML_PATH_FEATURES,
)
from tests.conftest import EXAMPLES, FIXTURES, load_json
from tests.str.facts_support import CASES, build, make_req

REAL = load_json(FIXTURES / "reasons_real_r02.json")


def _r(name: str, value: float | None = 3.0, contribution: float | None = 0.3) -> dict[str, Any]:
    """실제 형식 reason 하나 — basis model_feature, unit·window·baseline null."""
    return {
        "name": name,
        "observation": {"value": value, "unit": None, "window_start": None, "window_end": None, "basis": "model_feature"},
        "baseline": {"value": None, "definition": None},
        "contribution": {"method": "TreeSHAP", "value": contribution, "scale": "log_odds"},
    }  # fmt: skip


def _facts(reasons: list[dict[str, Any]], rule_id: str = "R02_FAN_IN") -> Any:
    return build(CASES["mixed"], rule_id=rule_id, reasons=reasons)


def _names(reasons: list[dict[str, Any]], rule_id: str = "R02_FAN_IN") -> list[str]:
    return [o.name for o in _facts(reasons, rule_id).observations]


# ---------- 상수 모양 ----------


def test_feature_sets_shape() -> None:
    """추가 13 · 경로 2(추가 13 안) · 메타 11(룰 표시 6 + 계산 여부 2 + 데이터 품질 3)."""
    assert len(ML_EXTRA_FEATURES) == 13
    assert {"evidence_min_path_hops_scaled", "evidence_path_available"} == ML_PATH_FEATURES
    assert ML_PATH_FEATURES <= ML_EXTRA_FEATURES
    assert {
        *(f"rule_r0{i}" for i in range(1, 7)),
        "evidence_features_applicable",
        "evidence_path_available",
        "evidence_payment_known_fraction",
        "evidence_paid_ratio_coverage",
        "evidence_received_ratio_coverage",
    } == ML_META_FEATURES


# ---------- 정상 ----------


def test_real_sample_all_negative_gives_no_observations() -> None:
    """준영 예시 그대로 — 기여값 셋 다 음수 → 관측값·model_signals 둘 다 비움."""
    f = _facts(REAL["reasons"], REAL["rule_id"])
    assert f.observations == []
    assert f.model_signals == []


def test_positive_contribution_kept_with_value() -> None:
    f = _facts([_r("evidence_count", 5.0, 0.9), _r("payment_format_count", 2.0, -0.2)])
    assert [(o.name, o.value, o.basis) for o in f.observations] == [("evidence_count", 5.0, "model_feature")]
    assert f.model_signals == ["evidence_count"]


def test_existing_example_reasons_unchanged() -> None:
    """기존 예시 reasons(지어낸 이름·양수 기여)는 거르기 대상 아님 — v1~v3 녹화 facts 그대로."""
    example = load_json(EXAMPLES / "draft_request.json")
    f = _facts(example["reasons"])
    assert [o.name for o in f.observations] == [r["name"] for r in example["reasons"]]


def test_mock_score_reasons_give_no_observations() -> None:
    """목업 점수 경로(model=null 시연 환경) — observation 전부 null → 관측값 없음, 이름은 model_signals 에."""
    alert = make_req(CASES["mixed"]["transactions"]).alert
    mock = [r.model_dump(mode="json") for r in ScoreService._mock(alert).reasons]
    f = _facts(mock)
    assert f.observations == []
    assert f.model_signals == ["mock_feature"]


# ---------- 경계: 룰 ----------


@pytest.mark.parametrize(
    ("rule_id", "name", "kept"),
    [
        ("R01_LARGE", "evidence_ach_fraction", False),  # 추가 13 — R02·R04 밖
        ("R03_STRUCTURING", "evidence_cash_fraction", False),
        ("R05_SCATTER_GATHER", "evidence_paid_max_share", False),
        ("R02_FAN_IN", "evidence_ach_fraction", True),
        ("R04_CYCLE", "evidence_ach_fraction", True),
        ("R04_CYCLE", "evidence_min_path_hops_scaled", True),  # 경로 — R04 만
        ("R02_FAN_IN", "evidence_min_path_hops_scaled", False),
        ("R01_LARGE", "evidence_count", True),  # 기본 18 — 룰 무관
    ],
)
def test_rule_gates_extra_features(rule_id: str, name: str, kept: bool) -> None:
    assert _names([_r(name, 0.5)], rule_id) == ([name] if kept else [])


# ---------- 경계: 기여값·0 채움·메타 ----------


@pytest.mark.parametrize("contribution", [0.0, -0.01, None])
def test_non_positive_or_null_contribution_dropped(contribution: float | None) -> None:
    assert _names([_r("evidence_count", 5.0, contribution)]) == []


@pytest.mark.parametrize("name", sorted(ML_META_FEATURES))
def test_meta_features_dropped(name: str) -> None:
    assert _names([_r(name, 1.0)], "R04_CYCLE") == []
    assert _facts([_r(name, 1.0)], "R04_CYCLE").model_signals == []


def test_extra_feature_zero_dropped_basic_zero_kept() -> None:
    """추가 13 의 0 은 0 채움과 구분 못 해 뺌(진짜 0 도 빠짐 — 09 미결). 기본 18 의 0 은 실제 0."""
    names = _names([_r("evidence_ach_fraction", 0.0), _r("focal_out_count", 0.0)])
    assert names == ["focal_out_count"]


def test_null_value_dropped_from_observations_but_name_in_signals() -> None:
    f = _facts([_r("evidence_count", None)])
    assert f.observations == []
    assert f.model_signals == ["evidence_count"]


def test_model_signals_top3_after_filter() -> None:
    reasons = [
        _r("evidence_count", 5.0, -1.0),
        _r("focal_in_count"),
        _r("rule_r02"),
        _r("focal_out_count"),
        _r("payment_format_count"),
        _r("evidence_account_count"),
    ]
    assert _facts(reasons).model_signals == ["focal_in_count", "focal_out_count", "payment_format_count"]
