# 02. `aml-ml` 패키지 계약 — 준영 리포 ↔ AI 서버

**10/26 확정(진희 제안, 준영 동의)**: 학습 코드는 준영의 별도 리포. AI 서버는 그 리포를 `pip install`되는 패키지 `aml-ml`로 받아 `scoring/application/`에서 import만 한다. 이유 — 학습할 때 쓴 피처 코드와 서빙할 때 쓰는 피처 코드가 한 벌이어야 train/serve skew가 안 생긴다. 모델 파일만 넘기는 방식(A)이나 준영이 서버를 따로 띄우는 방식(C)은 쓰지 않는다.

아래는 진희 제안이다. **"확인 필요"**로 표시한 칸은 준영이 정한다 — 정해지면 이 문서를 고치고 상태표를 갱신한다.

## 패키지가 내놓는 것

```python
# aml_ml/__init__.py 가 export 하는 것 (이것만 AI 서버가 쓴다)
MODEL_VERSION: str  # 예: "xgb-2026-11-05"  → 응답 model_version, predictions.model_version
FEATURE_VERSION: str  # 예: "f1"               → 응답 feature_version, alert_features.feature_version
THRESHOLD: float  # 서빙 임계값 (안건 2: 응답에 score와 threshold 둘 다)


def score(alerts: list[AlertInput], transactions: pd.DataFrame) -> list[ScoreResult]: ...
def features(
    alerts: list[AlertInput], transactions: pd.DataFrame
) -> pd.DataFrame: ...  # alert_features 기록용 (선택)
```

| 이름 | 내용 | 확인 필요 |
|---|---|---|
| `AlertInput` | 규약 2절 경보 JSON과 1:1 — `alert_id`, `rule_id`, `account_key`, `reference_ts`, `window_start`, `evidence_transaction_ids` | 준영: 학습 데이터의 `as_of`·`bank_id`+`account_id`를 여기서 분해(안건 6 권장) |
| `transactions` | 요청 500건의 경보가 가리키는 거래를 AI 서버 `loader`가 `ops.transactions`에서 한 번에 SELECT해 DataFrame으로. 컬럼은 서비스 DB 그대로(`transaction_id, ts, from_account_key, to_account_key, amount_paid, currency_paid, amount_received, currency_received, payment_format, is_self_transfer`) | 준영: 이 컬럼으로 피처 계산이 되는지. 더 필요하면(계좌 속성 등) 여기 적는다 |
| `ScoreResult` | `alert_id`, `score`(0~1), `reasons`(상위 3개 — `{name, value, method:"SHAP"}` , 안건 3), `data_quality_status`(OK/PARTIAL/INSUFFICIENT, 안건 4), `evidence_transaction_ids` | 준영: reasons 개수(3 고정?) |
| 실패 | 경보 하나가 실패하면 그 경보만 `score=None, data_quality_status="INSUFFICIENT"`. 예외를 던져 500건 전체를 죽이지 않는다 | 준영 동의 필요 |
| 결정성 | 같은 입력 → 같은 출력. 난수 없음 | — |
| 의존성 | pandas/polars, xgboost 또는 lightgbm, shap. **torch·GNN 없음**(MVP). **Python 3.12** (`requires-python >=3.12,<3.13` — AI 서버와 같은 인터프리터) | 준영: polars를 쓰면 AI 서버도 설치. 3.12 휠 확인 |

## 설치·버전

- AI 서버 `pyproject.toml`: `aml-ml @ git+https://github.com/<org>/aml-ml.git@v0.1.0` — **tag로 고정**. `main` 브랜치를 가리키지 않는다.
- 준영이 새 모델을 내면: 리포에 tag → 진희가 `pyproject.toml` 한 줄 바꾸는 PR → `MODEL_VERSION`이 바뀐 것을 `/v1/health`에서 확인 → `ai.model_versions`에 행 추가(준영).
- 모델 파일(`.json`/`.pkl`)은 **패키지 안에** 넣는다(수 MB). 패키지 import 시 로드. 100 MB를 넘기면 그때 릴리스 첨부 + 기동 시 다운로드로 바꾼다.
- `MODEL_VERSION`과 `ai.model_versions.model_version`은 같은 문자열. 서빙되는 버전은 `is_serving=true` 한 행.

## AI 서버 쪽 (`src/aml_ai/scoring/`, 준영이 만들되 얇게 — str/ 과 같은 4계층)

```
api/router.py                      POST /v1/scores — 요청 검증(schemas.alerts) → service → 응답(schemas.scores)
application/score_service.py       transaction_reader → aml_ml.score(alerts, df) → prediction_repository.save → 응답 조립 + 버전
domain/                            비어 있음 — 피처·모델 로직은 aml_ml
infrastructure/orm.py              model_versions · alert_features · predictions (Alembic 0002)
infrastructure/prediction_repository.py
```

`aml_ml`이 아직 없을 때(W2~W3)는 `score_service.py`가 `AI_SCORING_MOCK=true`면 고정 점수를 돌려준다(뼈대에 들어 있음, alert_id 로 0.05~0.95 결정적) — 백엔드 연동 테스트용. 패키지가 들어오면 플래그를 끈다.

## 준영 리포 쪽에 바라는 것 (네 가지만)

1. `pip install git+...@tag`가 되는 구조(`pyproject.toml`, `aml_ml/` 패키지).
2. 위 `score()` 시그니처와 세 상수.
3. 모델이 바뀔 때마다 tag.
4. 패키지 안에 `tests/`가 있어 `score()`가 고정 입력(축소본 `expected.json`)에 같은 결과를 내는지 확인.

노트북·실험 기록·SAML-D 학습 데이터·Parquet는 그 리포 안에서 어떻게 두든 서버와 무관하다.
