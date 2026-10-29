# 01. 규약과 코드를 맞추는 법 — 규약 v0.2 (10/27) 기준

규약(「AML·STR 인터페이스 규약」 v0.2, Claude Docs)이 백엔드 ↔ AI 서버 사이의 JSON을 정한다. 코드에서 그 규약이 사는 자리는 세 곳이고, 셋이 항상 같아야 한다.

| 자리 | 무엇 | 누가 |
|---|---|---|
| 규약 문서 | 사람이 읽는 정본. 필드 이름·타입·예시·에러 코드 | 진희 관리, 변경은 "규약 변경 요청" → 월요일 |
| `src/aml_ai/shared/schemas/` | Pydantic 모델. `common.py`(ID·금액·통화·날짜 타입), `alerts.py`(점수 요청), `scores.py`(점수 응답), `str.py`(초안·검증 요청·응답), `errors.py` | 진희 — 바뀌면 준영에게 알림 |
| `contracts/examples/*.json` | 규약의 예시 JSON 그대로 + 해시 테스트 벡터 | 백엔드 리포와 **같은 파일** — 한 곳에서 복사 |

## 계약 테스트 (tests/contract/)

`examples/*.json`이 `schemas/`로 파싱되는지, `narrative_hash.json`의 입력이 적힌 해시를 내는지 본다. 백엔드도 같은 파일로 자기 DTO·해시 테스트를 돈다. 둘 중 하나가 깨지면 그쪽이 고칠 차례 — 규약을 어긴 쪽이 어디인지 바로 보인다.

## 필드 하나 바꾸는 절차

1. 규약 문서 수정(변경 요청 → 월요일 반영).
2. `schemas/` 수정 → `examples/` 수정 → `pytest tests/contract` 녹색.
3. 백엔드에 `examples/` 파일 전달(또는 백엔드 리포 PR). 백엔드 DTO 테스트가 깨지면 백엔드가 맞춤.
4. 응답 필드가 바뀌었으면 `04_versioning_logging.md`의 버전 표기가 그대로인지 확인.

## 공통 타입 규칙 (`schemas/common.py`, 규약 0절)

- ID: 원칙 **문자열**. 예외 하나 — `transaction_id`는 **bigint, JSON 숫자**(안건 1). 적재 시 부여하는 순번이라 안전. 원본 파일 추적은 준혁의 `source_files` 테이블.
- 금액: 소수 2자리 **숫자**(JSON number), 항상 `currency`와 쌍. `Money = Decimal(decimal_places=2)`. **facts 안의 금액만 문자열** — `str/04`.
- 통화: ISO 4217 **코드** 문자열(`USD`). IBM 원천 이름(`US Dollar`)은 AI 로더가 고정 표로 바꾼다(`str/04`). **예외 `BTC`**(Bitcoin, ISO 4217에 없음). 표에 없는 이름은 에러 — 원문을 그대로 흘리지 않는다. (안건 19는 회의 제외, 현값 유지)
- 날짜·시각: ISO 8601, 초 단위, 시간대 없음(IBM 원본 그대로).
- 계좌 키: `account_key` = `{bank_id}_{account_no}`.
- `null`은 생략하지 않고 보낸다. 빈 배열은 `[]`.
- 열거값: 대문자 스네이크. `StrictModel(extra="forbid")` — 모르는 키가 오면 400.

## 10/27 회의로 확정된 스키마 (코드 반영 W2 수요일)

### 점수 응답 `schemas/scores.py` (규약 3절)

| 필드 | 상태 | 코드 |
|---|---|---|
| `score: float \| None`, `threshold: float` | 확정 (안건 2) — `score_band` 삭제. 등급은 백엔드 `CasePolicy` | `ScoreItem` |
| `data_quality_status` | 확정 (안건 4, 판정 10/28 준영) — **`OK` / `SHORT_HISTORY` / `MISSING_INPUT` / `FAILED`**. `SHORT_HISTORY`(모델이 지원·검증한 이력 부족)와 `MISSING_INPUT`(모델이 지원·검증한 입력 결측)은 **점수가 있는 정상 결과**. 필수 입력 누락·지원 안 되는 이력 부족·계산 실패는 `FAILED` → `score=None`, `prediction_id=None`. 판정표는 `shared/02` "품질 판정". 현재 코드의 `PARTIAL/INSUFFICIENT`는 틀림 → 교체 | `DataQualityStatus` |
| `evidence_transaction_ids: list[int]` ⊆ `alert.transaction_ids`, `context_transaction_ids: list[int]` | 확정 (안건 7) | `ScoreItem` |
| `reasons: list[Reason]` | **확정 (안건 3, 10/28)** — 항목마다 `name: str` + `observation{value: float\|None, unit, window_start, window_end, basis}` + `baseline{value: float\|None, definition}` + `contribution{method, value: float\|None, scale}`(문자열은 전부 `str\|None`). 확인 못 한 값은 `null`, 0은 실제 0을 확인했을 때만. 상위 3개가 기본, 설명만 실패하면 `[]`(점수·품질 상태는 유지). 정렬·동률·기여 척도는 모델 검증 뒤 고정 → 그때까지 순서는 받은 그대로. facts `observations` 매핑은 `str/04` | `Reason`, `Observation`, `Baseline`, `Contribution` |
| `scoring_meta.feature_version` | **확정 (안건 5, 10/28)** — 응답은 문자열 하나. 피처 정의·전처리 파일(SHA-256)·입력 열 순서·모델 버전 묶음 관리는 `aml_ml` 내부(`shared/02`). 실제 이름은 구현·검증 뒤 고정 | `ScoringMeta` |
| `alert_id: str` | **확정 (안건 6)** — 규약 2절 `ALT-{YYYYMMDD}-{6자리}` 문자열, 요청값 그대로 반환. 뼈대 `schemas/alerts.py`의 `int`는 틀림 → 교체(SCRUM-12) | `Alert`, `ScoreItem` |
| 응답 최상위 `produced_at` | 규약 0절 "AI 응답에 produced_at" — 점수 응답에도 최상위에(3절 예시에 빠져 있던 것, 준영) | `ScoreResponse` |
| 실패 항목 | `score=None`, `prediction_id=None`, `reasons=[]`, `evidence/context_transaction_ids=[]`, `threshold`는 로드된 모델 값 유지. 모델 미로드는 요청 전체 503 `MODEL_UNAVAILABLE` | `ScoreItem` |
| `failure_code: FailureCode \| None` | **확정 (10/29 준혁)** — `FAILED`일 때만 채우고 그 밖엔 `null`(키는 항상 있음). `TRANSACTION_NOT_FOUND`(경보 `transaction_ids` 중 서비스 DB에 없는 ID — AI 서버 `transaction_reader`가 판정, 그 경보는 `aml_ml`에 넘기지 않음) · `HISTORY_NOT_SUPPORTED`(모델이 지원하지 않는 이력 부족) · `REQUIRED_INPUT_MISSING`(필수 입력 누락) · `COMPUTE_ERROR`(피처·추론 계산 오류). 뒤 셋은 `aml_ml`이 정한다. **다시 보내서 달라질 수 있는 건 `COMPUTE_ERROR`뿐** — 백엔드는 이걸로 재처리 대상을 거른다(아래) | `FailureCode`, `ScoreItem` |
| 항목별 실패 (규약 6.3 예외) | `/v1/scores`만: 경보 하나의 문제(없는 거래 ID 등)는 400으로 요청 전체를 거절하지 않고 **그 경보만 `FAILED`**, 나머지는 정상 처리하고 HTTP 200. JSON 형식·필드 오류는 기존대로 요청 전체 400 `INVALID_REQUEST` | `score_service` |
| 요청 전체 실패 | 모델 미로드 503 `MODEL_UNAVAILABLE`, **AI 서버 DB 조회 장애 503 `DB_UNAVAILABLE`**(10/29). 요청 하나 = 트랜잭션 하나라 일부만 저장되는 일 없음. 백엔드는 1회 재시도 후 그 묶음을 실패로 두고 배치 재실행 | `DbUnavailable` |
| 백엔드 저장 (참고, 준혁) | 성공: `score_status=SCORED` + `alert_scores` 1행(`alert_id` UNIQUE — 경보당 점수 1건, 모델 버전별 이력은 AI `ai.predictions`). `data_quality_status`는 `alert_scores.payload` jsonb. 실패: `score_status=FAILED` + `alerts.score_failure_code`, `alert_scores` 행 없음. **재처리 대상 = `FAILED` 중 `score_failure_code`가 NULL(묶음 503 — 응답 자체가 없음)이거나 `COMPUTE_ERROR`** | — |

### 경보 `rule_facts.paths` (규약 2절, 10/28 준혁 답)

| 필드 | 내용 |
|---|---|
| `alert.rule_facts.paths: list[list[int]] \| None` | R04_CYCLE·R05_STACK만. 배열 하나 = 경로 하나, 안은 **시간순 거래 ID**. 모든 ID는 `alert.transaction_ids` 안(아니면 초안 요청 400). `transaction_ids`는 그대로 전체 근거 목록. 홉 = 경로의 거래 개수(A→B→C→A = 3홉). CYCLE 대상 계좌 = 첫 거래 송금 계좌, STACK = 시작 계좌. 다른 룰은 키 없음 |
| 코드 | 지금 뼈대 `schemas/alerts.py` `Alert`에는 `rule_facts`가 아직 없다. schemas 규약 v0.2 반영(SCRUM-12) 때 `rule_facts`와 그 안의 `paths: list[list[int]] \| None = None`을 같이 넣는다 — `StrictModel`(`extra="forbid"`)이라 빠뜨리면 백엔드가 보낸 경보가 400. 점수 쪽(`aml_ml`)은 받기만 하고 쓰지 않아도 됨 — 피처로 쓸지는 준영 선택 |

### 초안 요청·응답 `schemas/str.py` (규약 5.1·5.2)

| 필드 | 변경 |
|---|---|
| 요청 `evidence_transaction_ids: list[int]` | 이름 변경(← `transaction_ids`). **= `alert.transaction_ids` 전체** — 점수 응답(3절)의 같은 이름 필드(근거 부분집합)와 다르다. facts 건수·금액이 경보와 같아야 하므로. 경보 밖 거래는 오지 않는다 |
| 요청 `reasons: list[dict]` | 추가 — 3절 그대로. 빈 배열이면 facts `observations=[]`, 초안은 만든다 |
| 요청 `prior_alert_count: int` | `prior_alerts[]` 대신 **건수만** |
| 요청 `draft_id` | 백엔드가 **호출 전 시퀀스로 발급**. 재전송은 같은 id, 재생성은 새 id. AI 중복 방지 키(`str/03`) |
| 응답 `generation_id: str` | 추가. 백엔드 `str_drafts`에 저장(채영 V008). 검증 요청이 이걸 가리킨다 |
| 응답 `facts` | **구조 전면 교체** — 대상 계좌 관점 `inbound/outbound/internal` 통화별 집계 + `indirect`(대상 계좌 미참여 거래) + `paths`(경로형 경보, 10/28) + `observations[]` + `model_signals[]`. 정본 `str/04` |
| 응답 `narrative[].cites: list[str]` | 추가 — LLM이 쓴 **fact 키**. `evidence_ids`는 코드가 cites에서 합친 것 |
| 응답 `verification` | 항상 `null` (안건 17) — 타입은 `None` 고정 |
| `facts.typology_source` | `RULE`만 (안건 8) |

### 검증 요청·응답 (규약 5.3)

| 필드 | 변경 |
|---|---|
| 요청 `generation_id` | `draft_id` 대신. 저장된 facts를 그대로 쓴다 |
| 요청 `revision_no: int` | 백엔드 `str_revisions` 번호, 1 = AI 원문 |
| 요청 `narrative[]` | 섹션 6개 **각 1회** — 생성본과 같은 `NarrativeOut` 검증(현재 `VerifyRequest`에 빠져 있음 → 추가) |
| 응답 `generation_id`, `revision_no`, `narrative_sha256` | 추가 — 백엔드 `ApprovalGate`가 `generation_id` + 해시로 "이 생성본·이 본문의 검증이 passed"를 확인(채영 V009, 세 조건은 `str/03`) |
| 응답 `code_checks[].reason` | 추가 — `UNPARSED` 등. `match=false`일 때만 |
| `status` | `PASSED / CODE_FAILED / LLM_FAILED / VERIFY_UNAVAILABLE` 유지 (안건 9) |
| 응답 `narrative_refs: list[{section, cites, evidence_ids}] \| None` | **추가 (안건 23 세부 (a), 10/28)** — 검증한 본문 기준으로 다시 계산한 섹션별 근거. 평가자(`judge_v2`)가 섹션별 `cites`를 내고 코드가 `attach_evidence`로 `evidence_ids`를 만든다. 평가자를 안 돌린 경우(`CODE_FAILED`·`VERIFY_UNAVAILABLE`)는 `null` → 백엔드는 기존 값 유지. 백엔드(채영)는 값이 오면 수정본 저장에 반영. 본문 해시는 section·text만 보므로 영향 없음 |

### 에러 `schemas/errors.py` (규약 6.3)

추가 `409 GENERATION_IN_PROGRESS`(`GenerationInProgress`), `503 DB_UNAVAILABLE`(`DbUnavailable`, 점수 요청 중 AI 서버 DB 조회 실패 — 백엔드 재시도 1회, 10/29). 삭제 `TRANSACTION_NOT_FOUND`(→ 400 메시지에 없는 ID), `EVIDENCE_OUT_OF_SCOPE`(→ 검증 결과), `LLM_TIMEOUT`(→ `LLM_UNAVAILABLE`). 나머지 그대로.

## narrative 해시 — 양쪽이 같은 값 (`shared/hashing.py`, 백엔드 `NarrativeHash.java`)

1. 섹션 6개를 고정 순서 `SUMMARY, WHO, WHAT_WHEN_WHERE, HOW, WHY_SUSPICIOUS, CONCLUSION`으로 정렬.
2. 각 섹션에서 `section`·`text`만 (cites·evidence_ids 제외). `text`는 **NFC 정규화**, 앞뒤 공백 그대로(자르지 않음).
3. JSON 직렬화: 배열 안 객체, 키 순서 `section` → `text`, 구분자 `,`·`:` 공백 없음, non-ASCII 이스케이프 안 함(`ensure_ascii=False`). 예: `[{"section":"SUMMARY","text":"…"},…]`
4. UTF-8 바이트 → sha256 → hex 소문자 64자.
5. 섹션 6개가 각각 한 번씩이 아니면 해시하지 않고 오류(ValueError). 오류 메시지에 `text`를 넣지 않는다(섹션 이름·개수만). Java `NarrativeHash`도 같은 동작.

`NarrativeSection`을 쓰는 스키마(`NarrativeOut`, `DraftResponse`, `VerifyRequest`)의 `text`는 자동 strip이 꺼져 있다 — pydantic이 자르면 Java와 바이트가 어긋난다. 길이 제한(`NARRATIVE_TEXT_MAX = 1200`)은 **앞뒤 공백 포함**해서 센다. 공백만 있는 `text`는 스키마가 거부(해시까지 가지 않음).

테스트 벡터 `contracts/examples/narrative_hash.json`: `{"narrative": [...6섹션, 한글·조합형 자모·줄바꿈 포함...], "sha256": "..."}`. Python이 먼저 값을 만들고 Java가 같은 값을 내야 "됐다" (W3 ApprovalGate와 함께).

## 미결 — 규약 "미결 사항" 표와 같다

안건 3·5·6(준영), 15(지윤·채영), 23 세부(채영 → W3), 19·20·21 현값 유지. 준영 것이 오면 `scores.py`의 `Reason` 모델과 `str/04`의 `observations` 매핑을 한 번에 고친다.
