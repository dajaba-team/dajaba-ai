"""scoring — 점수 파이프라인. 담당 준영. str/ 과 같은 4계층.

api/router.py           POST /v1/scores
application/score_service.py   loader → aml_ml.score() → predictions 저장 → 응답. AI_SCORING_MOCK=true 면 고정 점수
domain/                 (비어 있음 — 피처·모델 로직은 aml_ml 패키지 안. docs/shared/02)
infrastructure/         prediction_repository (ai.predictions, alert_features), orm (점수 쪽 3테이블)

str/ 을 import 하지 않는다. 준영이 자기 방식으로 채운다 — 아래는 백엔드 연동용 목업.
"""
