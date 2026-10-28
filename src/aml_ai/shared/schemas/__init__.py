"""규약 JSON 의 Pydantic 한 벌 — 규약 v0.2 (10/27·10/28). 다른 곳에 dict 모양을 다시 적지 않는다 (docs/shared/01).

common.py   공통 타입 — ID·금액·통화·날짜·유형
alerts.py   규약 2절 경보 (점수 요청 입력, STR 요청 안의 alert), rule_facts.paths
scores.py   규약 3절 점수 응답 — reasons(observation·baseline·contribution), data_quality_status 4값
str.py      규약 5절 초안·검증·요약 요청·응답, facts, narrative(cites·evidence_ids)
errors.py   규약 6.3 에러 JSON
"""
