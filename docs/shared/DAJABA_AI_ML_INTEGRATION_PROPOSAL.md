# 다자바 AI 서버 ML 채점 연동 제안서
**검토 요청: 박진희 님 · 관련 작업: SCRUM-130 · 상태: 범위 합의 완료 · 구현/검증 전**

## 1. 제안 요약
기존 `dajaba-ai`에 ML 채점만 연결합니다. 별도 HTTP 서버나 새 API를 만들지 않고, 기존 `POST /v1/scores`와 `scoring/` 경계를 유지합니다. 학습·피처 계산은 `aml_ml`에 두고 AI 서버는 거래 조회, 패키지 호출, 결과 저장·응답만 담당합니다.

**Agent·STR·RAG와 해당 테스트는 수정하지 않습니다.** 기존 STR 거래 조회 모듈도 재사용하지 않습니다. 이번 연결 PR의 공유 변경은 합의된 `versioning.scoring_mode()`의 model 판단과 테스트, `0005_scoring_tables` 마이그레이션으로 한정합니다. `pyproject.toml`의 rc1 의존성과 이에 따른 `uv.lock` 변경도 같은 PR에 넣습니다. 다른 공유 변경은 별도 합의가 필요합니다. **DL은 Dajaba_DL의 오프라인 분석 전용**이며 AI 서버, 서비스 DB·화면, 공식 점수와 케이스 정책에는 반영하지 않습니다.

## 2. 로컬에서 확인한 현재 구조
- 오르카 작업 루트: `C:\Dajaba\status-management\dajaba-ai`. 로컬 `.git/HEAD`는 `develop`이지만 원격과 동기화 여부는 미검증입니다. 작업 전 `git status` 및 기준 커밋을 확인합니다. AI 계약 문서는 `docs/shared/02_ml_package.md`입니다.
- `dajaba-ai/src/aml_ai/scoring/api/router.py`: `POST /v1/scores`의 요청을 `ScoreService`에 전달합니다. `shared/schemas/alerts.py`의 요청은 `batch_run_id`와 경보 1~500건입니다.
- `scoring/application/score_service.py`: 확인한 로컬 복사본은 mock을 반환하고, 모델 분기는 `NotImplementedError`입니다. `scoring/domain`과 `scoring/infrastructure`는 초기화 파일만 있었습니다. 원격 최신 상태나 배포 상태는 이 확인의 범위가 아닙니다.
- 탐지 백엔드에는 `POST /api/v1/admin/batches/score` → `RequestScores` → AI `/v1/scores` 흐름이 이미 있습니다. **탐지 엔드포인트를 ML에 맞춰 새로 만들거나 경보 데이터를 ML 피처 모양으로 바꾸지 않는 안**을 추천합니다.
- `docs/shared/02_ml_package.md`는 서버가 `ops.transactions`를 읽고 패키지의 `score(..., coverage=...)`를 호출하는 방식과 저장·오류 계약을 정의합니다.

## 3. 제안 폴더 구조
```text
dajaba-ai/
  src/aml_ai/
    scoring/
      api/router.py                         # 기존 경로와 스키마 유지, 조립만
      application/score_service.py          # 조회 → 채점 → 저장 → 응답
      domain/ports.py                       # 조회·채점·저장 인터페이스만 (필요할 때)
      infrastructure/
        aml_ml_adapter.py                   # 채점 호출 시점에만 aml_ml import
        transaction_reader.py              # 채점 전용 ops 읽기, 이력 완전성 계산
        prediction_repository.py           # 채점 결과 저장. 기존 DB 계약 준수
    shared/versioning.py                    # 합의된 scoring_mode 변경만
    str/                                    # 변경하지 않음
  migrations/                              # 0005_scoring_tables: 기존 번호와 충돌 확인
  Dockerfile                                # 의존성 설치 전에 Git 준비
  docs/shared/02_ml_package.md              # 동일 PR에 의존성 담당·흐름 반영
  pyproject.toml / uv.lock                   # rc1 의존성과 잠금 파일을 같은 PR에 포함
  tests/                                    # scoring과 scoring_mode 검증
```
파일명은 제안입니다. DB 테이블 매핑은 먼저 기존 마이그레이션과 소유자를 확인하고, 이미 정의된 스키마를 중복 생성하지 않습니다. 피처 계산·모델·SHAP은 패키지에 한 벌만 둡니다.

## 4. 탐지 → AI → ML → 탐지
| 경계 | 계약 |
| --- | --- |
| 탐지 → AI | 기존 `batch_run_id`, `alerts[]` 유지. 경보 ID·대상 계좌·룰 ID/버전·창 시작/끝·`reference_ts`·전체 `transaction_ids`·`rule_facts`를 원본대로 전달합니다. R04·R05의 `paths`는 경로 표현이고 전체 근거 ID의 대체물이 아닙니다. |
| AI → DB → ML | 거래 ID로 경보 근거 전체를 조회하고, 대상 계좌 송·수신 이력 `[reference_ts−24h, reference_ts)`를 경보별로 구합니다. 이력 완전성 `COMPLETE/PARTIAL/UNKNOWN`은 내부 메타데이터이며 API 요청 필드를 늘리지 않습니다. 금액·계좌 키 등은 패키지 계약대로 넘기고, 통화는 DB 값을 그대로 전달합니다. 정답 라벨은 전달하지 않습니다. 경계 시각 이후·동일 시각의 근거는 보존할 수 있어도 피처 계산에는 쓰지 않습니다. |
| ML → AI | `score()` 결과를 경보 ID별로 검증합니다. 패키지의 `MODEL_VERSION`, `FEATURE_VERSION`, `THRESHOLD`를 사용합니다. 없는 거래 ID는 해당 경보만 `TRANSACTION_NOT_FOUND`로 실패 처리하고, 누락·실패를 0점으로 바꾸지 않습니다. |
| AI → 탐지 | 경보별 `score`, `threshold`, 품질 상태·실패 코드, 최대 3개 근거 설명, 근거/참고 거래 ID, 서버가 발급한 `prediction_id` 및 배치 버전 정보를 기존 응답 모양으로 반환합니다. 실패는 점수·prediction ID가 null이고 목록은 비웁니다. 근거 ID는 입력 경보 근거의 부분집합입니다. 전체 DB 장애·모델 미로드는 기존 503 계약을 따릅니다. |

`RULE_NOT_SUPPORTED`는 진희 님이 AI `develop`에 반영됐다고 공유했습니다. 최신 `develop`을 받아 기준 커밋과 계약을 확인하고, 백엔드는 관련 PR 상태와 실패 코드 저장·재시도 호환 여부만 확인합니다. 코드가 맞지 않아도 임의로 0점이나 다른 실패 코드로 치환하지 않습니다.

## 5. 합의된 역할 분담

| 담당 | 범위 |
| --- | --- |
| 염준영 | `dajaba-ai`의 ML 채점 연결 PR. rc1 의존성·lock 변경, 채점 전용 거래 조회·패키지 호출·저장/응답, 합의된 shared 변경과 마이그레이션, Docker 빌드·실채점 검증, 500건 응답 시간 측정과 공유. 별도로 시연용 ML 검증 결과와 경계값 후보표를 인계. |
| 박진희 | AI 연동 협의·검토. 시연용 경계값 확정, 룰별 사례 선정, 실제 경보→케이스 동작 확인. **최신 합의로 의존성 줄을 별도 PR로 올리지 않습니다.** |
| 배준혁·백엔드 | 탐지·백엔드 계약과 관련 PR, 동일 9/7 스캔 전수 자료 추출. AI 연결 PR에서는 백엔드 PR 상태만 확인하고 백엔드 코드는 수정하지 않습니다. |

## 6. 연결 PR 전에 확인할 것

1. **패키지 버전.** 공개 `dajaba-ml`의 `v0.1.0rc1`로 고정하며 비공개 인증 설정은 범위에서 뺍니다. 준영의 연동 PR에 `pyproject.toml` 의존성 줄과 `uv.lock`을 같이 넣고, `docs/shared/02_ml_package.md`의 별도 의존성 PR 담당·순서도 같은 PR에서 갱신합니다.

   ```text
   aml_ml @ git+https://github.com/dajaba-team/dajaba-ml.git@v0.1.0rc1
   ```

2. **잠금 파일과 버전 영향.** 현재 `uv.lock`을 기준으로 rc1 의존성(pandas ≥3, polars, duckdb, pyarrow, xgboost) 해석을 확인합니다. `uv lock` 전후의 추가·삭제·변경 패키지와 이전→새 버전을 PR 본문에 적습니다. 기존 패키지 업그레이드가 필요하면 반영 전에 공유합니다. STR이 참조하는 11/17 기준 31개 피처 이름 또는 지원 룰이 바뀌는 경우도 전환 전에 알려야 합니다.
3. **Dockerfile 변경 및 클린 빌드.** 현재 `python:3.12-slim` Dockerfile에 Git 설치 단계가 없습니다. VCS 의존성을 설치하는 단계 전에 Git을 넣고 클린 빌드로 확인합니다. 현재 Docker 설치 명령은 `uv.lock`을 직접 소비하지 않으므로 lock 변경과 이미지 실제 설치 버전은 별도로 확인합니다.
4. **같은 PR의 실채점과 health.** `aml_ml`은 import 시 모델을 로드하므로 어댑터의 채점 호출 시점에만 import합니다. 모듈 상단이나 공용 기동 경로에서 import하지 않습니다. 로드 실패는 기존 채점 503 계약으로 격리하고 STR 기동·health에 영향이 없는지 테스트합니다. 의존성만 먼저 머지하지 않습니다. 같은 빌드에서 실제 모델 설정으로 `/v1/scores`가 rc1 점수와 버전을 반환하고 health가 `scoring_mode: model`인지 함께 확인합니다. rc1은 R01·R02·R04 중 이력 `COMPLETE`이고 경보 창이 정확히 96시간인 유효 입력만 채점합니다. R03·R05·R06은 미지원입니다. 완전·불완전 이력, 96시간 경계, 미지원 룰을 구분해 검증합니다. 정상 경보와 미지원·누락 경보를 섞어 경보별로 실패가 분리되는지, 통화 원문과 R04·R05 전체 근거가 보존되는지, 24시간 경계·mock 모드·DB 장애 처리도 검증합니다. 테스트는 격리 환경의 미채점 경보로 시작합니다. 기존 `SCORED`나 재시도 불가 행은 재실행만으로 검증할 수 없습니다.
5. **500건 응답 시간.** 시연 전에 격리 환경에서 500건 요청을 보내 DB 조회·채점·저장·응답을 포함한 실제 총 시간을 재고, 환경·버전·성공/실패 건수와 함께 백엔드 대기 한도 **90초** 대비 결과를 공유합니다. 미측정은 통과로 표시하지 않습니다.

6. **저장 범위.** `ai.model_versions`의 rc1 행 등록은 이번 PR에 포함하는 안으로, 실제 패키지의 모델 버전·threshold와 serving 단일 행 계약을 맞추고 기존 마이그레이션과 중복되지 않게 합니다. `alert_features` 쓰기는 별도 항목이며 현재 미확정입니다. `02_ml_package.md`에서 선택 사항으로 정의하며, 진희 님에게 이번 시연의 STR이 실제 저장 행을 읽는지 확인하기 전에는 해당 쓰기를 추가하지 않습니다. 스키마 migration 포함과 피처 행 쓰기는 구분합니다.

## 7. 서로 기다릴 필요 없는 세 작업

| 작업 | 다음 단계 |
| --- | --- |
| **서버 연결** | 태그가 이미 있는 `v0.1.0rc1`로 먼저 진행. 기존 rc1 태그는 이동·삭제하지 않습니다. |
| **9/7 ML 검증 / rc2** | 로컬 `0.1.0rc2.dev0`으로 9/7 동일 스캔 1,545건 전부 채점 완료(실패 코드별 0건, 이력 COMPLETE·정확히 96시간 1,545건). 사건형 R04 409건 포함. HIGH 0.70은 룰별 6/1/11/5/2/2, 총 27건으로 두 시연 조건 충족. 0.72도 26건으로 충족, 0.74는 R02 0건. LOW→MEDIUM 0.15 / HIGH 0.70은 후보이며 시연 설정·실제 케이스는 진희 님 확인 사항입니다. **rc1은 세 룰만 시연 가능**, 여섯 룰 시연에는 rc2 원격 태그와 서버 재검증이 필요합니다. 발행일 미확정이며 이번 문서 업데이트로 태그를 발행하지 않습니다. 열흘치 사건형 R04 평가는 별도입니다. |
| **ML·DL 고도화** | HI-Medium 오프라인 최종 평가 결과와 시연용 패키지는 별개입니다. 필요하면 HI-Small에서 오프라인으로 거래 ID 연결·누락 시 ML 순위 유지 여부만 확인합니다. DL은 서버·DB·화면·케이스에 반영하지 않습니다. |

**이 문서는 합의사항과 실행 계획입니다. 코드 변경·PR·빌드·태그 발행·배포·외부 공유는 수행하지 않았습니다.**
