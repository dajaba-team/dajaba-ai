# 02. `aml-ml` 패키지 계약 — 준영 리포 ↔ AI 서버

**10/26 확정(진희 제안, 준영 동의)**: 학습 코드는 준영의 별도 리포. AI 서버는 그 리포를 `pip install`되는 패키지 `aml-ml`로 받아 `scoring/application/`에서 import만 한다. 이유 — 학습할 때 쓴 피처 코드와 서빙할 때 쓰는 피처 코드가 한 벌이어야 train/serve skew가 안 생긴다. 모델 파일만 넘기는 방식(A)이나 준영이 서버를 따로 띄우는 방식(C)은 쓰지 않는다.

**10/28 상태**: 안건 2·4·7·10은 회의 확정. **안건 3·5·6은 준영 제안서(10/27, 「ML 입력·설명·피처 버전 AI 인터페이스 규약 설계 제안서」)와 10/28 답변(이력 부족·조회 범위·coverage)으로 확정** — 아래에 반영. 남은 것: 점수 항목별 실패·`failure_code`·503·적재 범위는 **준혁 확인 대기**, `reasons` 정렬·기여 척도·버전 이름은 모델 검증 뒤 고정.

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
| `ScoreResult` | `alert_id`, `score: float \| None`, `data_quality_status`, `reasons`, `evidence_transaction_ids`, `context_transaction_ids` | 아래 행별 |
| `ScoreResult.data_quality_status` | **확정(안건 4)**: `OK` / `SHORT_HISTORY`(지원·검증된 이력 부족, 점수 있음) / `MISSING_INPUT`(지원·검증된 입력 결측, 점수 있음) / `FAILED`(점수 산출 불가). `FAILED`면 `score=None`. 백엔드는 FAILED 경보를 **저위험으로 취급하지 않고** 보존·재처리 | 판정은 아래 "품질 판정"(10/28 준영) |
| `ScoreResult.evidence_transaction_ids` | **확정(안건 7)**: 경보 안 거래 ⊆ `AlertInput.transaction_ids`. STR이 쓰는 것 | — |
| `ScoreResult.context_transaction_ids` | **확정(안건 7)**: 경보 밖 참고 거래(과거 이력·이웃). 대표만 제한 반환(상한은 상수), STR 본문에 쓰지 않음 | 상한 개수 준영 |
| `ScoreResult.reasons` | **확정(안건 3)** — `name` + `observation{value, unit, window_start, window_end, basis}` + `baseline{value, definition}` + `contribution{method, value, scale}`. 기여값(SHAP)을 관측값처럼 쓰지 않는다. 확인 못 한 값은 `null`. 상위 3개, 설명만 실패하면 `[]`이고 점수·품질 상태는 그대로(새 상태값 없음) | 정렬·동률·척도는 모델 검증 뒤 |
| 실패 | 경보 하나가 실패하면 그 경보만 `score=None, data_quality_status="FAILED"`, `reasons=[]`, `threshold`는 모델 값 유지. 예외를 던져 500건 전체를 죽이지 않는다. 모델 미로드만 요청 전체 503 | 확정(준영). 없는 거래 ID·`failure_code`·DB 장애 503은 준혁 확인 대기 |
| 결정성 | 같은 입력 → 같은 출력. 난수 없음 | — |
| 의존성 | pandas/polars, xgboost 또는 lightgbm, shap. **torch·GNN 없음**(MVP). **Python 3.12** (`requires-python >=3.12,<3.13` — AI 서버와 같은 인터프리터) | 준영: polars를 쓰면 AI 서버도 설치. 3.12 휠 확인 |

## 입력 범위 (10/28 확정, 준영 답)

`transaction_reader`가 경보마다 **넘기는** 거래와, 그중 **피처 계산에 쓰는** 거래를 나눠 적는다(10/29 최종 점검 — 둘을 한 문장으로 적어 "전체를 넘긴다"와 "이후 거래는 안 준다"가 부딪혔다).

넘기는 거래:

1. 대상 계좌(`account_key`)가 보내거나 받은 **`[reference_ts − 24h, reference_ts)`** 거래 — 서비스 경보 모델은 24시간 피처 중심, 7일 피처를 안 쓰는 모델에 7일 이력을 요구하지 않는다.
2. 경보 `transaction_ids` **전체**(근거 거래). CYCLE·STACK의 중간 경로 거래도 포함하되 대상 계좌 입출금 집계와는 분리한다. 근거 창을 24시간 피처 창에 맞춰 자르지 않는다.
3. 상대 계좌의 다른 거래로 넓혀 조회하지 **않는다**(초기 모델).

**피처 계산은 `ts < reference_ts`인 거래만** 쓴다(누수 방지). 1번은 조회 단계에서 이미 이 조건이고, 2번 근거 거래 중 `reference_ts`와 같거나 늦은 거래는 **넘어와도 근거로만 보존하고 점수·그래프 피처에는 넣지 않는다**(보통 `reference_ts` = `window_end`라 드묾). 경계 테스트: 근거 거래 `ts = reference_ts − 1분`(피처 포함)·`= reference_ts`(제외)·`= reference_ts + 1분`(제외, 근거로는 보존). 500건·동기는 유지, 조회·피처·추론·설명·저장 시간은 W2~W4에 실측. 서비스 DB는 HI-Small 전체(508만 행) 적재 전제 — 실제 범위·첫 거래 시각은 준혁 확인 뒤 여기에 적는다.

### coverage (패키지 내부 메타데이터, API 필드 아님)

경보마다 하나: 요청한 조회 시작·종료(ISO 문자열), DB 최소·최대 거래 시각(같은 형식, 확인 불가면 `null`), 이력 확보 상태 `COMPLETE / PARTIAL / UNKNOWN`. DB 최소·최대 시각만으로 "전체 이력 확보"를 판정하지 않는다. 조회 실패·행 제한으로 잘림은 "정상 조회했는데 0건"과 구분한다 — 완전히 조회한 범위에 거래가 실제로 없을 때만 0건. 데이터 시작 직후처럼 24시간 창이 데이터 시작보다 앞서면 `PARTIAL`.

### 품질 판정 (coverage → `data_quality_status`, 1:1 아님)

| coverage | 결과 |
|---|---|
| `COMPLETE` | 다른 입력·계산도 정상 → `OK` + 점수. 지원·검증된 입력 결측만 있고 점수 산출 가능 → `MISSING_INPUT` + 점수. 필수 입력 누락·추론 실패 → `FAILED` |
| `PARTIAL` | 그 부족 조건을 모델이 지원·검증했으면 `SHORT_HISTORY` + 점수, 아니면 `FAILED` |
| `UNKNOWN` | 충분한 이력으로 보지 않음 → `FAILED` |

- 이력 부족 + 지원되는 결측이 같이 있고 점수가 나오면 대표 상태는 `MISSING_INPUT`, 이력 부족은 AI 내부 기록에.
- baseline만 없으면 `baseline.value=null`, 그것만으로 점수를 막지 않는다.
- 품질 사유(왜 FAILED인지)는 API가 아니라 `ai.predictions` 내부 기록에 — 단 재시도 판단용 `failure_code` 공개 여부는 준혁 확인 대기.

### 학습 ↔ 서비스 필드 (안건 6)

서비스 필드명은 그대로, 매핑은 패키지 안 한 곳. `reference_ts` = 내부 `as_of`(이 시각 이전만 피처). `account_key`는 **그대로** 쓴다 — `_`로 분해해 은행·계좌를 추측하지 않는다. `alert_id`는 문자열 그대로 반환(지금 `int`를 받는 로컬 입력은 패키지 어댑터에서 보완). `rule_facts`는 원본 보존, 모델 입력으로 쓸지는 따로 검증(정답으로 쓰지 않음). `created_at`은 감사 기록일 뿐 피처 기준 시각이 아니다. 금액은 `Decimal`로 받고 `float` 금액은 거부.

로더 호출(`scoring/application/score_service.py`)과 `shared/03`의 `alert_features.as_of`는 이 정의를 그대로 따른다.

## 설치·버전

- AI 서버 `pyproject.toml`: `aml-ml @ git+https://github.com/<org>/aml-ml.git@v0.1.0` — **tag로 고정**. `main` 브랜치를 가리키지 않는다.
- 준영이 새 모델을 내면: 리포에 tag → 진희가 `pyproject.toml` 한 줄 바꾸는 PR → `MODEL_VERSION`이 바뀐 것을 `/v1/health`에서 확인 → `ai.model_versions`에 행 추가(준영).
- 모델 파일(`.json`/`.pkl`)은 **패키지 안에** 넣는다(수 MB). 패키지 import 시 로드. 100 MB를 넘기면 그때 릴리스 첨부 + 기동 시 다운로드로 바꾼다.
- `MODEL_VERSION`과 `ai.model_versions.model_version`은 같은 문자열. 서빙되는 버전은 `is_serving=true` 한 행. `threshold`도 그 행에.

## AI 서버 쪽 (`src/aml_ai/scoring/`, 준영이 만들되 얇게 — str/ 과 같은 4계층)

```
api/router.py                      POST /v1/scores — 요청 검증(schemas.alerts) → service → 응답(schemas.scores)
application/score_service.py       transaction_reader → aml_ml.score(alerts, df) → prediction_repository.save → 응답 조립 + 버전
domain/                            비어 있음 — 피처·모델 로직은 aml_ml
infrastructure/orm.py              model_versions · alert_features · predictions (Alembic 0002)
infrastructure/prediction_repository.py
```

- 응답 조립: `score`·`threshold`·`data_quality_status`·`reasons`·`evidence/context_transaction_ids`를 그대로, `prediction_id`는 서버가 발급(`FAILED`면 null). 500건 **동기**, 배치 크기는 W4 실측 뒤 설정값만 조정(안건 10).
- `aml_ml`이 아직 없을 때(W2~W3)는 `score_service.py`가 `AI_SCORING_MOCK=true`면 고정 점수를 돌려준다(뼈대에 들어 있음, alert_id로 0.05~0.95 결정적, `data_quality_status="OK"`, `reasons=[]`) — 백엔드 연동 테스트용. 패키지가 들어오면 플래그를 끈다.

## 준영 리포 쪽에 바라는 것 (네 가지만)

1. `pip install git+...@tag`가 되는 구조(`pyproject.toml`, `aml_ml/` 패키지).
2. 위 `score()`·`features()` 시그니처(`coverage` 키워드 인자, `account_aliases` 없음)와 세 상수.
3. 모델이 바뀔 때마다 tag.
4. 패키지 안에 `tests/`가 있어 `score()`가 고정 입력(축소본 `expected.json`)에 같은 결과를 내는지 확인.

노트북·실험 기록·SAML-D 학습 데이터·Parquet는 그 리포 안에서 어떻게 두든 서버와 무관하다.
