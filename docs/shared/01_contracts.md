# 01. 규약과 코드를 맞추는 법

규약(「AML·STR 인터페이스 규약」, Claude Docs)이 백엔드 ↔ AI 서버 사이의 JSON을 정한다. 코드에서 그 규약이 사는 자리는 세 곳이고, 셋이 항상 같아야 한다.

| 자리 | 무엇 | 누가 |
|---|---|---|
| 규약 문서 | 사람이 읽는 정본. 필드 이름·타입·예시·에러 코드 | 진희 관리, 변경은 "규약 변경 요청" |
| `src/aml_ai/shared/schemas/` | Pydantic 모델. `common.py`(ID·금액·통화·날짜 타입), `alerts.py`(점수 요청), `scores.py`(점수 응답), `str.py`(초안·검증 요청·응답), `errors.py` | 진희 — 바뀌면 준영에게 알림 |
| `contracts/examples/*.json` | 규약의 예시 JSON 그대로. 경보 1개, 점수 응답 1개, 초안 요청·응답, 검증 요청·응답, 에러 1개 | 백엔드 리포와 **같은 파일** — 한 곳에서 복사 |

## 계약 테스트 (tests/contract/)

`examples/*.json`이 `schemas/`로 파싱되는지만 본다. 백엔드도 같은 파일로 자기 DTO 테스트를 돈다. 둘 중 하나가 깨지면 그쪽이 고칠 차례 — 규약을 어긴 쪽이 어디인지 바로 보인다.

## 필드 하나 바꾸는 절차

1. 규약 문서 수정(변경 요청 → 월요일 반영). 10/27 회의에서 결정된 것은 그 자리에서.
2. `schemas/` 수정 → `examples/` 수정 → `pytest tests/contract` 녹색.
3. 백엔드에 `examples/` 파일 전달(또는 백엔드 리포 PR). 백엔드 DTO 테스트가 깨지면 백엔드가 맞춤.
4. 응답 필드가 바뀌었으면 `04_versioning_logging.md`의 버전 표기가 그대로인지 확인.

## 공통 타입 규칙 (`schemas/common.py`)

- 금액: 소수 2자리 **숫자**(JSON number). 문자열 아님. `Money = Decimal(decimal_places=2)`. (안건 19 권장안. STR `facts.total_amount`만 예외로 문자열 — `str/04_facts.md`.)
- 통화: ISO 4217 코드 문자열.
- 날짜·시각: ISO 8601, 초 단위, 시간대 없음(IBM 원본 그대로).
- 거래 ID: 백엔드 `transactions.transaction_id`(bigint). 학습 쪽 ID와 다르다 — 안건 1.
- 계좌 키: `account_key` = `{bank_id}_{account_id}`.

## 10/27 회의 뒤 바뀔 것

안건 2·3·4·5·7·8·9가 점수·검증 JSON을 건드린다. 회의 끝나고 `schemas/scores.py`(`score`+`threshold`, `reasons[]`, `data_quality_status`, `feature_version`), `schemas/str.py`(`evidence_transaction_ids`/`context_transaction_ids` 분리, `typology_source` RULE만, `passed`·`status`), `schemas/errors.py`(에러 코드 2개)를 한 번에 고친다.
