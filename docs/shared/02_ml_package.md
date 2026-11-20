# 02. `aml-ml` 패키지 계약 — 준영 리포 ↔ AI 서버

**10/26 확정(진희 제안, 준영 동의)**: 학습 코드는 준영의 별도 리포. AI 서버는 그 리포를 `pip install`되는 패키지 `aml-ml`로 받아 채점 어댑터의 호출 시점에 불러온다. 이유 — 학습할 때 쓴 피처 코드와 서빙할 때 쓰는 피처 코드가 한 벌이어야 train/serve skew가 안 생긴다. 모델 파일만 넘기는 방식(A)이나 준영이 서버를 따로 띄우는 방식(C)은 쓰지 않는다.

**10/28 상태**: 안건 2·4·7·10은 회의 확정. **안건 3·5·6은 준영 제안서(10/27, 「ML 입력·설명·피처 버전 AI 인터페이스 규약 설계 제안서」)와 10/28 답변(이력 부족·조회 범위·coverage)으로 확정** — 아래에 반영. **10/29**: 점수 항목별 실패·`failure_code`·DB 장애 503·적재 범위 **준혁 확인으로 확정**(SCRUM-41). 남은 것: 실제 첫 거래 시각(준혁 적재 후), `reasons` 정렬·기여 척도·버전 이름은 모델 검증 뒤 고정.

## 패키지가 내놓는 것

```python
# aml_ml/__init__.py 가 export 하는 것 (이것만 AI 서버가 쓴다)
MODEL_VERSION: str  # 예: "xgb-2026-11-05"  → 응답 model_version, predictions.model_version
FEATURE_VERSION: str  # 응답 feature_version. 피처 정의·전처리(SHA-256)·입력 열 순서 묶음의 이름(안건 5)
THRESHOLD: float  # 추천 임계값 (안건 2 확정: 응답에 score와 threshold 둘 다, 등급은 백엔드 CasePolicy)


def score(
    alerts: list[AlertInput], transactions: pd.DataFrame, *, coverage: list[Coverage]
) -> list[ScoreResult]: ...
def features(
    alerts: list[AlertInput], transactions: pd.DataFrame, *, coverage: list[Coverage]
) -> pd.DataFrame: ...  # alert_features 기록용 (선택)


# account_aliases 인자는 없다(10/28) — 서비스는 HI-Small 하나라 account_key로 통일. 학습용 원본 계좌 대응은 패키지 안에서 따로
```

| 이름 | 내용 | 상태 |
|---|---|---|
| `AlertInput` | 규약 2절 경보 JSON과 1:1 — `alert_id`, `rule_id`, `account_key`, `reference_ts`, `window_start`, `window_end`, `transaction_ids`, `rule_facts` | **확정(안건 6)**: 서비스 필드명 유지, 매핑은 패키지 안에서 — 아래 "학습 ↔ 서비스 필드". `alert_id`는 문자열 |
| `transactions` | 요청 500건의 경보가 가리키는 거래를 AI 서버 `transaction_reader`가 `ops.transactions`에서 한 번에 SELECT해 DataFrame으로. 컬럼은 서비스 DB 그대로(`transaction_id, ts, from_account_key, to_account_key, amount_paid, currency_paid, amount_received, currency_received, payment_format, is_self_transfer`). `is_laundering`·`pattern_*`는 **없다** | **확정 — 아래 "입력 범위"**(대상 계좌 24h + 근거 거래) |
| `ScoreResult` | `alert_id`, `score: float \| None`, `data_quality_status`, `failure_code`, `reasons`, `evidence_transaction_ids`, `context_transaction_ids` | 아래 행별 |
| `ScoreResult.failure_code` | **확정(10/29 준혁)**: `FAILED`일 때만 `HISTORY_NOT_SUPPORTED` / `RULE_NOT_SUPPORTED` / `REQUIRED_INPUT_MISSING` / `COMPUTE_ERROR` 중 하나, 그 밖엔 `None`. `TRANSACTION_NOT_FOUND`는 패키지가 아니라 AI 서버가 정한다(없는 ID가 있는 경보는 패키지에 안 넘김). 백엔드 재처리는 `COMPUTE_ERROR`만 — 다시 돌려도 같은 결과가 나올 실패는 나머지 셋으로 | 준영: 패키지 안 사유 → 네 코드 대응표 |
| `ScoreResult.data_quality_status` | **확정(안건 4)**: `OK` / `SHORT_HISTORY`(지원·검증된 이력 부족, 점수 있음) / `MISSING_INPUT`(지원·검증된 입력 결측, 점수 있음) / `FAILED`(점수 산출 불가). `FAILED`면 `score=None`. 백엔드는 FAILED 경보를 **저위험으로 취급하지 않고** 보존·재처리 | 판정은 아래 "품질 판정"(10/28 준영) |
| `ScoreResult.evidence_transaction_ids` | **확정(안건 7)**: 경보 안 거래 ⊆ `AlertInput.transaction_ids`. STR이 쓰는 것 | — |
| `ScoreResult.context_transaction_ids` | **확정(안건 7)**: 경보 밖 참고 거래(과거 이력·이웃). 대표만 제한 반환(상한은 상수), STR 본문에 쓰지 않음 | 상한 개수 준영 |
| `ScoreResult.reasons` | **확정(안건 3)** — `name` + `observation{value, unit, window_start, window_end, basis}` + `baseline{value, definition}` + `contribution{method, value, scale}`. 기여값(SHAP)을 관측값처럼 쓰지 않는다. 확인 못 한 값은 `null`. 상위 3개, 설명만 실패하면 `[]`이고 점수·품질 상태는 그대로(새 상태값 없음) | 정렬·동률·척도는 모델 검증 뒤 |
| 실패 | 경보 하나가 실패하면 그 경보만 `score=None, data_quality_status="FAILED"`, `failure_code`, `reasons=[]`, `threshold`는 모델 값 유지. 예외를 던져 500건 전체를 죽이지 않는다. 요청 전체 503은 모델 미로드(`MODEL_UNAVAILABLE`)와 AI 서버 DB 조회 장애(`DB_UNAVAILABLE`) 둘뿐 | 확정(준영 10/28, 준혁 10/29) |
| 결정성 | 같은 입력 → 같은 출력. 난수 없음 | — |
| 의존성 | pandas/polars, xgboost 또는 lightgbm, shap. **torch·GNN 없음**(MVP). **Python 3.12** (`requires-python >=3.12,<3.13` — AI 서버와 같은 인터프리터) | 준영: polars를 쓰면 AI 서버도 설치. 3.12 휠 확인 |

**rc1 실패 코드 대응**: `InputError`(6룰 밖 `rule_id` 포함) → `REQUIRED_INPUT_MISSING` · `HistoryError` → `HISTORY_NOT_SUPPORTED` · `UnsupportedRuleError`(R03·R05·R06) → `RULE_NOT_SUPPORTED` · 그 밖 예외·추론 실패 → `COMPUTE_ERROR`. `reasons`(TreeSHAP) 계산 실패는 FAILED 아님(OK + `reasons=[]`). 지원 룰은 R01·R02·R04이며, R03·R05·R06은 `FAILED` + `RULE_NOT_SUPPORTED`.

## 입력 범위 (10/28 확정, 준영 답)

`transaction_reader`가 경보마다 **넘기는** 거래와, 그중 **피처 계산에 쓰는** 거래를 나눠 적는다(10/29 최종 점검 — 둘을 한 문장으로 적어 "전체를 넘긴다"와 "이후 거래는 안 준다"가 부딪혔다).

넘기는 거래:

1. 대상 계좌(`account_key`)가 보내거나 받은 **`[reference_ts − 24h, reference_ts)`** 거래 — 서비스 경보 모델은 24시간 피처 중심, 7일 피처를 안 쓰는 모델에 7일 이력을 요구하지 않는다.
2. 경보 `transaction_ids` **전체**(근거 거래). CYCLE·STACK의 중간 경로 거래도 포함하되 대상 계좌 입출금 집계와는 분리한다. 근거 창을 24시간 피처 창에 맞춰 자르지 않는다.
3. 상대 계좌의 다른 거래로 넓혀 조회하지 **않는다**(초기 모델).

**피처 계산은 `ts < reference_ts`인 거래만** 쓴다(누수 방지). 1번은 조회 단계에서 이미 이 조건이고, 2번 근거 거래 중 `reference_ts`와 같거나 늦은 거래는 **넘어와도 근거로만 보존하고 점수·그래프 피처에는 넣지 않는다**(보통 `reference_ts` = `window_end`라 드묾). 경계 테스트: 근거 거래 `ts = reference_ts − 1분`(피처 포함)·`= reference_ts`(제외)·`= reference_ts + 1분`(제외, 근거로는 보존). 500건·동기는 유지, 조회·피처·추론·설명·저장 시간은 W2~W4에 실측. 서비스 DB는 **HI-Small 전체 5,078,345건 적재로 확정**(10/29 준혁) — DB 안의 24시간 조회 결과가 곧 전체 이력. 문서상 시작은 2022-09-01 00:00, **실제 첫 거래 시각은 준혁 적재 후** 여기에 적는다. 그 시각부터 24시간 안의 경보는 창이 잘려 coverage `PARTIAL`.

### coverage (패키지 내부 메타데이터, API 필드 아님)

경보마다 하나: 요청한 조회 시작·종료, DB 최소·최대 거래 시각(확인 불가면 `null`), 이력 확보 상태 `COMPLETE / PARTIAL / UNKNOWN`. 적재 검증으로 전체 이력을 확보했다고 확인한 범위를 공용 설정 `AI_SCORING_HISTORY_START`와 `AI_SCORING_HISTORY_END`에 원본 시각(시간대 없는 ISO 8601)으로 지정한다. 실채점 모드에서 값이 누락되거나 형식이 잘못됐거나 시작이 종료보다 이르지 않으면 요청 전체가 `MODEL_UNAVAILABLE`(503)이며 설정 오류 사유를 로그에 남긴다. 유효한 설정에서 DB 거래가 비어 있으면 `UNKNOWN`이다. 24시간 창이 검증 범위를 벗어나거나 DB 첫 거래보다 앞서면 `PARTIAL`이다. 마지막 거래 이후에도 적재 검증 범위 안에서 조회한 구간은 거래가 0건일 수 있다. 전체 이력의 근거는 적재 검증이며, 조회 장애는 요청 전체 `DB_UNAVAILABLE`(503)이다.

### 품질 판정 (coverage → `data_quality_status`, 1:1 아님)

| coverage | 결과 |
|---|---|
| `COMPLETE` | 다른 입력·계산도 정상 → `OK` + 점수. 지원·검증된 입력 결측만 있고 점수 산출 가능 → `MISSING_INPUT` + 점수. 필수 입력 누락·추론 실패 → `FAILED` |
| `PARTIAL` | 그 부족 조건을 모델이 지원·검증했으면 `SHORT_HISTORY` + 점수, 아니면 `FAILED` |
| `UNKNOWN` | 충분한 이력으로 보지 않음 → `FAILED` |

- 이력 부족 + 지원되는 결측이 같이 있고 점수가 나오면 대표 상태는 `MISSING_INPUT`, 이력 부족은 AI 내부 기록에.
- baseline만 없으면 `baseline.value=null`, 그것만으로 점수를 막지 않는다.
- 실패 코드는 `ai.predictions`에 기록한다. AI develop은 `RULE_NOT_SUPPORTED`를 지원한다. 백엔드 develop의 실패 코드 검증과 DB 제약에는 아직 이 값이 없다.

### 학습 ↔ 서비스 필드 (안건 6)

서비스 필드명은 그대로, 매핑은 패키지 안 한 곳. `reference_ts` = 내부 `as_of`(이 시각 이전만 피처). `account_key`는 **그대로** 쓴다 — `_`로 분해해 은행·계좌를 추측하지 않는다. `alert_id`는 문자열 그대로 반환(지금 `int`를 받는 로컬 입력은 패키지 어댑터에서 보완). `rule_facts`는 원본 보존, 모델 입력으로 쓸지는 따로 검증(정답으로 쓰지 않음). `created_at`은 감사 기록일 뿐 피처 기준 시각이 아니다. 금액은 `Decimal`로 받고 `float` 금액은 거부.

로더 호출(`scoring/application/score_service.py`)과 `shared/03`의 `alert_features.as_of`는 이 정의를 그대로 따른다.

## 설치·버전

- AI 서버는 공개 저장소의 태그된 버전만 설치한다. rc1 최초 연결 이후 `aml-ml @ git+https://github.com/dajaba-team/dajaba-ml.git@v0.1.0rc2`로 전환한다. 잠금 커밋은 `783007f18a07d22169da92333495a8aab04fa76f`다.
- rc2는 R01~R06을 지원한다. 패키지 목록에 없는 룰은 `RULE_NOT_SUPPORTED`, 지원하는 룰의 근거 입력 오류는 `REQUIRED_INPUT_MISSING`으로 구분한다.
- 최초 연결 PR #85에서 `python:3.12-slim`의 VCS 의존성 설치에 필요한 Git을 추가했다. 패키지 전환 시 `pyproject.toml`과 `uv.lock`을 함께 갱신하고, Docker 이미지에서 실제 설치 버전과 import를 확인한다.
- **점수 모드 `/v1/health` `scoring_mode`** (SCRUM-130, 11/12) — 점수가 고정 점수인지 실제 모델인지 밖에서 보이게. 판단은 `shared/versioning.scoring_mode(settings)`:

  | 조건 | `scoring_mode` |
  |---|---|
  | `AI_SCORING_MOCK=true` (기본) | `mock` |
  | `false` + 현재 프로세스에서 모델 점수 산출과 저장 성공 | `model` |
  | `false` + 그 밖 | `unavailable` |

  **기동 직후에는 mock이 꺼져도 `unavailable`**이다. 패키지 설치만으로 `model`을 노출하지 않는다. 전환 이미지에서 실제 `/v1/scores` rc2 점수와 `/v1/health`의 `model` 및 모델·피처 버전을 함께 확인한다. STR을 포함한 기동 판정은 유지한다.
  시연 전에는 서버 재시작 → 정상 경보의 `/v1/scores` 채점·저장 성공 → `/v1/health`의 `scoring_mode=model` 확인 순서로 점검한다.
- 모델 파일은 패키지 안에 두며 import 시 로드된다. 채점 어댑터의 호출 시점에만 `aml_ml`을 import한다. 공용 기동 경로의 모듈 상단에서 import하지 않으며, 로드 실패는 기존 채점 503 계약으로 격리한다.
- `0005_scoring_tables`가 rc1 모델·피처 버전과 패키지의 `threshold`를 등록한다. 부분 유일 인덱스로 serving 행을 한 개만 허용한다. 로드한 모델과 serving 행이 일치하지 않으면 `MODEL_UNAVAILABLE`을 반환한다. `alert_features` 저장은 선택 사항이며, STR에서 저장 행을 읽는지 진희 님 확인 전에는 쓰지 않는다.
- rc1과 rc2는 같은 모델·피처 버전을 쓰므로 `0006_serving_package_version`에서 기존 모델 행에 `serving_package_version=0.1.0rc2`를 기록한다. `0005_scoring_tables`, 모델 PK, 기존 예측의 FK, serving 플래그를 보존한다. 실채점은 설치 패키지 버전까지 serving 행과 일치해야 하며 누락 또는 불일치 시 `MODEL_UNAVAILABLE`(503)을 반환한다. 0005로 롤백하면 이 컬럼만 제거된다.

## AI 서버 쪽 (`src/aml_ai/scoring/`, 준영이 만들되 얇게 — str/ 과 같은 4계층)

```
api/router.py                      POST /v1/scores — 요청 검증(schemas.alerts) → service → 응답(schemas.scores)
application/score_service.py       transaction_reader → 누락 ID 경보 분리 → aml_ml_adapter.score(..., coverage=...) → 저장·응답
domain/                            비어 있음 — 피처·모델 로직은 aml_ml
infrastructure/prediction_repository.py  ai.predictions 일괄 저장 (0005_scoring_tables)
infrastructure/aml_ml_adapter.py   채점 호출 시점 import
infrastructure/transaction_reader.py  STR과 분리된 채점용 ops 조회, 통화 DB 원문·전체 근거 ID 보존
```

- 응답 조립: `score`·`threshold`·`data_quality_status`·`failure_code`·`reasons`·`evidence/context_transaction_ids`를 그대로, `prediction_id`는 서버가 발급(`FAILED`면 null).
- 성공과 실패 모두 감사용 예측 행으로 저장한다. 실패 행의 내부 ID는 응답에 포함하지 않는다.
- 거래 ID가 없으면 해당 경보만 `TRANSACTION_NOT_FOUND`로 실패 처리한다. 누락·실패를 0점으로 치환하지 않는다.
- 트랜잭션: 요청 하나 = DB 트랜잭션 하나. 조회·저장 중 DB 오류면 롤백하고 `DbUnavailable`(503) — 일부 경보만 저장된 채 응답하지 않는다. 백엔드는 1회 재시도 뒤 묶음 실패, 배치 재실행(`alert_scores.alert_id` UNIQUE로 중복 막힘). 500건 **동기**, 배치 크기는 W4 실측 뒤 설정값만 조정(안건 10).
- `aml_ml`이 아직 없을 때(W2~W3)는 `score_service.py`가 `AI_SCORING_MOCK=true`면 고정 점수를 돌려준다(뼈대에 들어 있음, alert_id로 0.05~0.95 결정적, `data_quality_status="OK"`, `reasons=[]`) — 백엔드 연동 테스트용. 패키지가 들어오면 플래그를 끈다.

## rc1 제약과 시연 검증

- rc1은 R01·R02·R04 중 `COMPLETE` 이력과 정확히 96시간의 경보 창을 갖춘 유효 입력만 채점한다. R03·R05·R06은 미지원이다.
- 9/7 로컬 `0.1.0rc2.dev0` 오프라인 검증은 사건형 R04 409건을 포함해 1,545건 모두 성공했다. HIGH 0.70은 27건, 0.72는 26건이고 둘 다 여섯 룰에서 최소 1건이다. 공개 rc2 전환의 서버 검증에는 기존 여섯 룰 42건 표본을 사용한다. 실제 9/7 요청과 케이스 생성은 별도다.
- 격리 환경에서 500건 동기 요청의 DB 조회·채점·저장·응답을 모두 재고 백엔드 90초 한도에 대비한다. DL은 오프라인 전용이다.

상세 검증 항목: [연동 제안서](DAJABA_AI_ML_INTEGRATION_PROPOSAL.md).

## 준영 리포 쪽에 바라는 것 (네 가지만)

1. `pip install git+...@tag`가 되는 구조(`pyproject.toml`, `aml_ml/` 패키지).
2. 위 `score()`·`features()` 시그니처(`coverage` 키워드 인자, `account_aliases` 없음)와 세 상수.
3. 모델이 바뀔 때마다 tag.
4. 패키지 안에 `tests/`가 있어 `score()`가 고정 입력(축소본 `expected.json`)에 같은 결과를 내는지 확인.

노트북·실험 기록·SAML-D 학습 데이터·Parquet는 그 리포 안에서 어떻게 두든 서버와 무관하다.
