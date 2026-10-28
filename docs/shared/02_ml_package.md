# 02. `aml-ml` 패키지 계약 — 준영 리포 ↔ AI 서버

**10/26 확정(진희 제안, 준영 동의)**: 학습 코드는 준영의 별도 리포. AI 서버는 그 리포를 `pip install`되는 패키지 `aml-ml`로 받아 `scoring/application/`에서 import만 한다. 이유 — 학습할 때 쓴 피처 코드와 서빙할 때 쓰는 피처 코드가 한 벌이어야 train/serve skew가 안 생긴다. 모델 파일만 넘기는 방식(A)이나 준영이 서버를 따로 띄우는 방식(C)은 쓰지 않는다.

**10/27 회의 뒤 상태**: 안건 2·4·7·10은 확정이라 아래에 반영. **안건 3(`reasons` 구조)·5(`feature_version`)·6(학습 입력 ↔ 서비스 JSON 매핑)은 준영이 주말 전에 정리해 준다** — 그 세 칸은 비워 두고 "준영 작성"으로 표시했다. 오면 이 문서와 `shared/01`·`str/04`를 한 번에 고친다.

## 패키지가 내놓는 것

```python
# aml_ml/__init__.py 가 export 하는 것 (이것만 AI 서버가 쓴다)
MODEL_VERSION: str  # 예: "xgb-2026-11-05"  → 응답 model_version, predictions.model_version
FEATURE_VERSION: str  # 관리 방식은 준영 작성(안건 5) → 응답 feature_version
THRESHOLD: float  # 추천 임계값 (안건 2 확정: 응답에 score와 threshold 둘 다, 등급은 백엔드 CasePolicy)


def score(alerts: list[AlertInput], transactions: pd.DataFrame) -> list[ScoreResult]: ...
def features(
    alerts: list[AlertInput], transactions: pd.DataFrame
) -> pd.DataFrame: ...  # alert_features 기록용 (선택)
```

| 이름 | 내용 | 상태 |
|---|---|---|
| `AlertInput` | 규약 2절 경보 JSON과 1:1 — `alert_id`, `rule_id`, `account_key`, `reference_ts`, `window_start`, `window_end`, `transaction_ids`, `rule_facts` | **준영 작성(안건 6)**: 학습 데이터 필드명(`as_of`, `bank_id`+`account_id` 등) ↔ 이 필드명 매핑 표. 서비스 필드명은 유지, 매핑은 패키지 안에서 |
| `transactions` | 요청 500건의 경보가 가리키는 거래를 AI 서버 `transaction_reader`가 `ops.transactions`에서 한 번에 SELECT해 DataFrame으로. 컬럼은 서비스 DB 그대로(`transaction_id, ts, from_account_key, to_account_key, amount_paid, currency_paid, amount_received, currency_received, payment_format, is_self_transfer`). `is_laundering`·`pattern_*`는 **없다** | **준영 확인 — 아래 "입력 범위 질문"** |
| `ScoreResult` | `alert_id`, `score: float \| None`, `data_quality_status`, `reasons`, `evidence_transaction_ids`, `context_transaction_ids` | 아래 행별 |
| `ScoreResult.data_quality_status` | **확정(안건 4)**: `OK` / `SHORT_HISTORY`(이력 부족) / `MISSING_INPUT`(필수 입력 누락) / `FAILED`(산출 실패). `FAILED`면 `score=None`. 백엔드는 FAILED 경보를 **저위험으로 취급하지 않고** 보존·재처리 | 각 값의 **판정 조건은 준영 작성** |
| `ScoreResult.evidence_transaction_ids` | **확정(안건 7)**: 경보 안 거래 ⊆ `AlertInput.transaction_ids`. STR이 쓰는 것 | — |
| `ScoreResult.context_transaction_ids` | **확정(안건 7)**: 경보 밖 참고 거래(과거 이력·이웃). 대표만 제한 반환(상한은 상수), STR 본문에 쓰지 않음 | 상한 개수 준영 |
| `ScoreResult.reasons` | **준영 작성(안건 3)** — 관측값·계산 기간·기준값·설명 방법·기여값·기여 척도를 구분한 구조. 기여값(SHAP)을 관측값처럼 쓰지 않는다. 설명 실패 시 점수 사용 여부 상태 포함. 상위 3개 | 준영, 주말 전 |
| 실패 | 경보 하나가 실패하면 그 경보만 `score=None, data_quality_status="FAILED"`. 예외를 던져 500건 전체를 죽이지 않는다 | 준영 동의 필요 |
| 결정성 | 같은 입력 → 같은 출력. 난수 없음 | — |
| 의존성 | pandas/polars, xgboost 또는 lightgbm, shap. **torch·GNN 없음**(MVP). **Python 3.12** (`requires-python >=3.12,<3.13` — AI 서버와 같은 인터프리터) | 준영: polars를 쓰면 AI 서버도 설치. 3.12 휠 확인 |

## 입력 범위 질문 — 준영 답이 필요한 것 (안건 6과 함께)

`transaction_reader`가 어떤 거래를 DataFrame에 담아 줘야 하는지 정해져야 서버 쪽 쿼리를 짤 수 있다. 세 가지만:

1. **경보 안 거래만으로 충분한가?** `AlertInput.transaction_ids`(룰이 잡은 창 안 거래)만 주면 피처가 계산되는지, 아니면 대상 계좌의 **과거 거래**가 필요한지.
2. 과거가 필요하면 **조회 기간** — `reference_ts` 기준 며칠 전까지(7일? 30일? 전체?). 500건 묶음이면 쿼리 크기가 바로 달라진다. `reference_ts` **이후** 거래는 어떤 경우에도 주지 않는다(누수).
3. **이웃 계좌** 거래(상대 계좌의 다른 거래)가 필요한지. 필요하면 `context_transaction_ids`의 출처가 되고, 홉 수·상한을 같이.

답이 오면 `scoring/application/score_service.py`의 로더 호출과 `shared/03`의 `alert_features.as_of` 의미를 그대로 맞춘다.

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
2. 위 `score()` 시그니처와 세 상수.
3. 모델이 바뀔 때마다 tag.
4. 패키지 안에 `tests/`가 있어 `score()`가 고정 입력(축소본 `expected.json`)에 같은 결과를 내는지 확인.

노트북·실험 기록·SAML-D 학습 데이터·Parquet는 그 리포 안에서 어떻게 두든 서버와 무관하다.
