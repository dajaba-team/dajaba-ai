"""리랭커 질의 등록 목록 V1 (SCRUM-308-2 추가 검토 2 — docs/str/10 "리랭커"). 목록 밖 신호·업종이면 리랭커 안 부름.

새 신호·업종이 생기면 **이 목록부터** 고치고 버전을 올린다(V2). 출처와 같은지는 테스트가 대조한다:
- 신호 ① 점수 모델 reason 이름 = `aml_ml.FEATURE_NAMES`(aml_ml 0.1.0rc2, 31개 — `scoring/infrastructure/aml_ml_adapter`
  가 그대로 `Reason.name` 으로 넘김) ② v3 평가 세트 `tests/str/rag_eval_v3/queries_dev.json`(기준 커밋 87aef09)과
  그 base 픽스처의 `model_signals`(합성 IBM 계열 이름 6개)
- 업종 ① 고객 업종 표시 라벨 `contracts/display_labels_v1.json` `industry` 9개 ② v3 평가 세트 업종(RESTAURANT)
- 모의 점수(`AI_SCORING_MOCK`)의 `mock_feature` 는 실제 reason 이 아니라 넣지 않음(리랭커 원래 순서)
"""

from __future__ import annotations

RERANK_REGISTRY_VERSION = "V1"

RERANK_SIGNALS_MODEL: frozenset[str] = frozenset(
    {
        "evidence_count", "evidence_span_seconds", "evidence_min_gap_seconds", "evidence_max_gap_seconds",
        "focal_in_count", "focal_out_count", "focal_distinct_senders", "focal_distinct_receivers",
        "evidence_account_count", "paid_raw_currency_count", "received_raw_currency_count", "payment_format_count",
        "rule_r01", "rule_r02", "rule_r03", "rule_r04", "rule_r05", "rule_r06",
        "evidence_ach_fraction", "evidence_cheque_fraction", "evidence_cash_fraction", "evidence_paid_max_share",
        "evidence_received_max_share", "evidence_span_fraction_96h", "evidence_last_hour_fraction",
        "evidence_min_path_hops_scaled", "evidence_features_applicable", "evidence_payment_known_fraction",
        "evidence_paid_ratio_coverage", "evidence_received_ratio_coverage", "evidence_path_available",
    }
)  # fmt: skip
RERANK_SIGNALS_EVAL_V3: frozenset[str] = frozenset(
    {
        "account_in_counterparties_24h", "cross_border_amount_24h", "distinct_recipients_24h",
        "distinct_senders_24h", "inflow_outflow_ratio_2h", "outflow_ratio_2h",
    }
)  # fmt: skip
RERANK_INDUSTRIES_LABELS: frozenset[str] = frozenset(
    {
        "RETAIL",
        "WHOLESALE",
        "MANUFACTURING",
        "SERVICE",
        "FINANCE",
        "REAL_ESTATE",
        "CONSTRUCTION",
        "OTHER",
        "TRADING",
    }
)
RERANK_INDUSTRIES_EVAL_V3: frozenset[str] = frozenset({"RESTAURANT", "RETAIL", "TRADING", "WHOLESALE"})

RAG_RERANK_REGISTRY_V1: dict[str, frozenset[str]] = {
    "signals": RERANK_SIGNALS_MODEL | RERANK_SIGNALS_EVAL_V3,
    "industries": RERANK_INDUSTRIES_LABELS | RERANK_INDUSTRIES_EVAL_V3,
}
