"""실제 ML reasons 거르기 상수 — 피처 이름은 준영 11/17 목록(31개) 기준 (docs/str/04 `observations[]` 거르기)."""

from __future__ import annotations

# 추가 피처 13개 — R02·R04 경보에서만 계산, 아니면 ML 이 0 채움.
ML_EXTRA_FEATURES: frozenset[str] = frozenset(
    {
        "evidence_ach_fraction",
        "evidence_cheque_fraction",
        "evidence_cash_fraction",
        "evidence_paid_max_share",
        "evidence_received_max_share",
        "evidence_span_fraction_96h",
        "evidence_last_hour_fraction",
        "evidence_min_path_hops_scaled",
        "evidence_features_applicable",
        "evidence_payment_known_fraction",
        "evidence_paid_ratio_coverage",
        "evidence_received_ratio_coverage",
        "evidence_path_available",
    }
)
ML_PATH_FEATURES: frozenset[str] = frozenset({"evidence_min_path_hops_scaled", "evidence_path_available"})
ML_EXTRA_FEATURE_RULES: tuple[str, ...] = ("R02", "R04")  # rule_id 앞부분(`R02_FAN_IN`)
ML_PATH_FEATURE_RULES: tuple[str, ...] = ("R04",)
# 메타 피처 11개 — 행동 관측이 아니라 룰 표시·계산 여부·데이터 품질. 관측값·model_signals 에서 뺌.
ML_META_FEATURES: frozenset[str] = frozenset(
    {
        *(f"rule_r0{i}" for i in range(1, 7)),
        "evidence_features_applicable",
        "evidence_path_available",
        "evidence_payment_known_fraction",
        "evidence_paid_ratio_coverage",
        "evidence_received_ratio_coverage",
    }
)
