"""규약 JSON 의 Pydantic 한 벌. 다른 곳에 dict 모양을 다시 적지 않는다 (docs/shared/01).

common.py   공통 타입 — ID·금액·통화·날짜
alerts.py   규약 2절 경보 (점수 요청 입력, STR 요청 안의 alert)
scores.py   규약 3절 점수 응답
str.py      규약 5절 초안·검증·요약 요청·응답, facts, narrative
errors.py   규약 6절 에러 JSON

10/27 회의 뒤 바뀔 곳: scores(score+threshold, reasons[], data_quality_status, feature_version),
str(evidence/context 분리, typology_source RULE 만, passed·status), errors(코드 2개).
"""
