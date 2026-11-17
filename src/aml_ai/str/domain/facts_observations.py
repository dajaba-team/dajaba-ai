"""reasons → 관측값·model_signals 재료 거르기 — 정본 docs/str/04 `observations[]`·`model_signals[]`. 순수 함수.

실제 ML reasons 는 피처 31개 중 |SHAP| 상위 3(부호 무관)이고, 추가 피처는 R02·R04 경보에서만 계산(아니면 0 채움).
점수를 낮춘 피처·룰 표시·계산 여부·0 채움 값이 의심 근거처럼 서술되지 않게 facts 단계에서 뺀다(SCRUM-264).
"""

from __future__ import annotations

from aml_ai.shared.schemas.scores import Reason
from aml_ai.shared.schemas.str import ObservationFacts
from aml_ai.str.domain.constants_ml import (
    ML_EXTRA_FEATURE_RULES,
    ML_EXTRA_FEATURES,
    ML_META_FEATURES,
    ML_PATH_FEATURE_RULES,
    ML_PATH_FEATURES,
)


def usable_reasons(reasons: list[Reason], rule_id: str) -> list[Reason]:
    """거르기 ①~④ 를 통과한 reasons(순서 유지). 기여값 숫자는 여기서도 밖으로 안 나감(안건 3)."""
    return [r for r in reasons if _usable(r, rule_id)]


def observations(reasons: list[Reason]) -> list[ObservationFacts]:
    """관측값만. value 가 null 인 항목은 뺀다. 기여값(contribution)은 넣지 않는다 (안건 3)."""
    return [
        ObservationFacts(
            name=r.name,
            value=r.observation.value,
            unit=r.observation.unit,
            window_start=r.observation.window_start,
            window_end=r.observation.window_end,
            basis=r.observation.basis,
            baseline=r.baseline.value,
        )
        for r in reasons
        if r.observation.value is not None
    ]


def _usable(r: Reason, rule_id: str) -> bool:
    contribution = r.contribution.value
    if contribution is None or contribution <= 0:  # ① 점수를 낮췄거나 부호 모름
        return False
    if r.name in ML_META_FEATURES:  # ② 룰 표시·계산 여부·데이터 품질
        return False
    if r.name in ML_EXTRA_FEATURES:
        rules = ML_PATH_FEATURE_RULES if r.name in ML_PATH_FEATURES else ML_EXTRA_FEATURE_RULES
        if not rule_id.startswith(rules):  # ③ 그 룰에서는 0 채움
            return False
        if r.observation.value == 0:  # ④ 0 채움과 진짜 0 을 구분 못 함
            return False
    return True
