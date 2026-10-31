# 03. `ai` 스키마 — 테이블 8개와 Alembic 규칙

같은 PostgreSQL, `ai` 스키마, `app_ai` 계정. 백엔드 테이블과 FK 없이 `prediction_id`·`draft_id`·`generation_id` 값으로만 이어진다. 마이그레이션은 Alembic(`migrations/`). AI 설계 문서 7절의 표를 코드 기준으로 다시 적은 것. **10/27 회의 반영**: `generations`에 중복 방지 제약과 상태, `verification_runs`에 `revision_no`·`narrative_sha256`, `predictions`에 `data_quality_status`·`context_transaction_ids`.

## 테이블

| 테이블 | 쓰는 쪽 | 핵심 컬럼 | 왜 |
|---|---|---|---|
| `model_versions` | 준영, 학습 끝날 때 | `model_version` PK, `feature_version`, `algorithm`, `train_period`, `input_hash`, `threshold`, `metrics jsonb`, `artifact_path`, `is_serving`, `created_at` | 서빙되는 버전은 여기 등록된 것만. `aml_ml.MODEL_VERSION`과 같은 문자열. 추천 임계값도 여기 |
| `alert_features` | scoring, 추론마다 | `alert_id`, `as_of`, `feature_version`, `features jsonb`, `data_quality_status`, `computed_at` | W4 정합성(같은 경보에 같은 특징이 나왔나), 설명 재계산. `as_of`의 의미는 준영 안건 6 뒤 |
| `predictions` | scoring | `prediction_id` PK, `alert_id`, `batch_run_id`, `model_version`, `feature_version`, `score numeric \| null`, `threshold`, **`data_quality_status`**(OK/SHORT_HISTORY/MISSING_INPUT/FAILED), `reasons jsonb`, `evidence_transaction_ids bigint[]`, **`context_transaction_ids bigint[]`**, `request_id`, `created_at` | 백엔드 `alert_scores.prediction_id`가 가리키는 것. FAILED도 행을 남긴다(재처리 추적) |
| `prompt_versions` | 진희, 프롬프트 바꿀 때 | `prompt_name`, `version`, `file_hash`, `frozen_at`, `created_at` — PK(`prompt_name`,`version`) | 파일이 정본, 여기는 색인. `frozen_at`은 첫 녹화 커밋 시각(`str/05` 동결 규칙) |
| `generations` | str, 호출마다 | `generation_id` PK, `kind`(DRAFT/VERIFY/SUMMARY), `draft_id`, `case_no`, **`status`**(PROCESSING/SUCCEEDED/FAILED), **`request_hash`**, `facts jsonb`, `request jsonb`, `response jsonb`, `llm_model`, `prompt_version`, `few_shot_ids int[]`, `references jsonb`, `retrieval_version`, `tokens_in`, `tokens_out`, `latency_ms`, `error`, `request_id`, `created_at`, `finished_at` | verify가 facts를 여기서 꺼낸다(`generation_id`로). **중복 방지 — 장치 둘**: ① 선점 전 `request_hash` 비교(상태 무관 — 내용이 다른 재사용 차단) ② `UNIQUE (draft_id) WHERE kind='DRAFT' AND status <> 'FAILED'`(동시 진입 차단). 하는 일이 달라서 둘 다 필요하다 — 아래 "같은 `draft_id` 재요청". `request_hash`는 5.1 요청 본문 sha256, FAILED 행에도 남는다 |
| `verification_runs` | str | `verification_id` PK, `generation_id`, `draft_id`, **`revision_no`**, **`narrative_sha256`**, `code_checks jsonb`, `llm_checks jsonb`, `passed`, `status`, `verifier_version`, `request_id`, `created_at` | 백엔드 `verification_results.verification_id`가 가리키는 것. 백엔드도 `generation_id`·`revision_no`·`narrative_sha256`을 같이 저장(채영 V009) → `ApprovalGate`가 `generation_id` + 해시로 "이 생성본·이 본문의 검증"을 찾는다(`str/03`) |
| `fewshot_examples` | 진희 | `example_id` PK, `typology`, `facts jsonb`, `narrative jsonb`, `is_active` | 파일(`str/fewshot/*.json`)이 정본, 여기는 서빙용 사본 |
| `reference_chunks` | 진희, `tools/ingest_corpus.py` | `chunk_id` PK, `doc_id`, `doc_title`, `publisher`, `year`, `page`, `section`, `lang`, `typologies text[]`, `text`, `embedding vector(N)`, `embedding_model`, `content_hash` UNIQUE, `created_at`. 인덱스 HNSW(cosine) on `embedding`, GIN on `typologies` | RAG 코퍼스 청크. PDF가 정본, 여기는 검색용. 평가는 `chunk_id` 단위(`str/10`) |

없는 것: 학습표(`alert_training_table`)는 Parquet 파일로 준영 리포에. 서빙 DB에 실험 데이터를 넣지 않는다. `ai_call_logs`는 백엔드 테이블(`shared/04`).

## `generations.status` 전이

```
INSERT (PROCESSING, request_hash)      ← LLM 호출 전 선점 (순서는 아래)
  → SUCCEEDED (response, facts, tokens, latency, finished_at)
  → FAILED    (error = 에러 코드+메시지, finished_at)      ← 502·500 전부 행을 남긴다
```

### 같은 `draft_id` 재요청 (10/27 3·4차 검토로 다시 씀)

부분 UNIQUE만으로는 FAILED 행이 제약 밖이라 "실패 뒤 다른 내용"이 INSERT 충돌 없이 들어온다. 그래서 해시 비교를 INSERT 앞에 따로 둔다. 그리고 **비교와 INSERT 사이에 다른 요청이 끼어들면 안 되므로**(4차 검토) 1~3을 짧은 트랜잭션 하나로 묶고 맨 앞에 `draft_id`별 잠금을 건다:

0. **잠금** — `SELECT pg_advisory_xact_lock(hashtext('draft:' || $1))`. 같은 `draft_id`의 선점은 한 번에 하나씩만 돈다(다른 `draft_id`는 안 막힌다). 트랜잭션이 끝나면 저절로 풀린다. 이 트랜잭션은 1~3만 담고 **LLM 호출 전에 커밋**한다 — 잠금을 쥔 채 35초를 기다리지 않는다. 테이블을 늘리지 않으려고 고른 방식(버린 대안: `draft_requests(draft_id PK, request_hash)` 테이블 — `09`).

1. **오래된 PROCESSING 정리** — 서버가 작업 중 죽으면 PROCESSING이 남고, 그대로면 그 `draft_id`는 영원히 409다. `UPDATE generations SET status='FAILED', error='STALE_PROCESSING', finished_at=now() WHERE kind='DRAFT' AND draft_id=$1 AND status='PROCESSING' AND created_at < now() - STALE_PROCESSING_S`. `STALE_PROCESSING_S = DRAFT_BUDGET_S + 30`(110초, 가정값) — 정상 요청은 80초 예산 안에 반드시 닫히므로(`str/03`) 이보다 오래된 PROCESSING은 죽은 것.
2. **해시 비교** — 같은 `draft_id`의 행이 **상태와 상관없이** 하나라도 있고 `request_hash`가 다르면 400 `INVALID_REQUEST`("draft_id reused with different body"). 같은 `draft_id`의 행은 모두 같은 해시라 아무 행 하나만 보면 된다. FAILED 행도 해시를 남기므로 "실패 뒤 다른 내용"이 여기서 걸린다.
3. **INSERT** — 부분 UNIQUE에 걸리면 살아 있는 행의 상태로: `SUCCEEDED` → **해시를 한 번 더 확인하고**(같을 때만) 저장된 `response` 그대로(LLM 호출 없음) · `PROCESSING` → 409 `GENERATION_IN_PROGRESS`. 안 걸리면(처음이거나 이전 시도가 전부 FAILED) 새 `generation_id`로 진행. 옛 FAILED 행은 고치지 않는다 — FAILED는 "충돌 분기"가 아니라 "충돌이 안 나는 경우"다. **구현은 `INSERT … ON CONFLICT (draft_id) WHERE kind='DRAFT' AND status <> 'FAILED' DO NOTHING RETURNING generation_id`** — 0행이 돌아오면 충돌이므로 살아 있는 행을 SELECT해 상태를 본다. 그냥 INSERT하고 unique 오류를 잡는 방식은 쓰지 않는다: PostgreSQL은 오류가 난 트랜잭션을 aborted로 만들어 이어서 SELECT할 수 없다([INSERT — ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT)).

경합 — 잠금 덕분에 아래가 모두 순서대로 처리된다(4차 검토가 짚은 두 구멍):
- 내용이 다른 A·B가 동시에 처음 → A가 잠금·INSERT·커밋 → B는 잠금을 얻은 뒤 2에서 A의 해시를 보고 400. B가 A의 결과를 받아 가지 않는다.
- A가 FAILED로 끝난 뒤 다른 내용의 B → 2에서 FAILED 행의 해시와 달라 400. 다른 내용으로 생성되지 않는다.
- 내용이 같은 A·A′ 동시 → A′는 3에서 PROCESSING에 걸려 409.

**늦게 살아 돌아온 작업 막기(펜싱)** — 110초가 지났다고 이전 작업이 정말 죽었다는 보장은 없다. 그래서 끝낼 때도 "내가 아직 유효한 시도인지"를 조건으로 건다: `UPDATE generations SET status=…, … WHERE generation_id=$1 AND status='PROCESSING'`. 바뀐 행이 0이면(이미 STALE로 닫힘) 결과를 저장하지 않고 버린다 — 로그에 `generation_id`만 남기고 500 `INTERNAL`. 110초는 가정값 그대로. **범위를 구분해 둔다**: 펜싱은 "결과가 두 번 저장되는 것"을 막는다. "LLM 호출이 한 번만 일어난다"는 보장은 아니다 — 죽은 줄 알았던 옛 작업이 실제로 살아 있었다면 새 시도와 LLM 호출이 겹칠 수 있고, 그 비용은 MVP에서 감수한다(110초 넘게 걸리는 호출은 35초 타임아웃 때문에 드물다).

테스트는 `str/08` DB 층(5가지).

## pgvector — 확장 생성은 superuser만

`CREATE EXTENSION vector`는 **DB superuser 권한**이 필요하다. `app_migrate`(Alembic 계정)로는 안 된다. 그래서 세 갈래:

| 상황 | 절차 | 누가 |
|---|---|---|
| **새 DB**(compose 처음 띄울 때) | 백엔드 리포 `db/init/00_extensions.sql`에 `CREATE EXTENSION IF NOT EXISTS vector;` — `db/init/`은 postgres 이미지가 superuser로 1회 실행한다. compose db 이미지를 `postgres:16` → `pgvector/pgvector:pg16` | 준혁(백엔드 리포), W3 초 — 준혁 W2 적재가 끝난 뒤 |
| **이미 있는 DB**(팀원 로컬·시연 서버) | 손으로 1회: `docker compose exec db psql -U postgres -d aml -c "CREATE EXTENSION IF NOT EXISTS vector;"` — `shared/05`에 명령 그대로 | 각자 |
| Alembic `0004_reference_chunks` | 확장을 **만들지 않고 확인만**: `SELECT 1 FROM pg_extension WHERE extname='vector'` 없으면 `RuntimeError("pgvector 확장 없음 — shared/03 절차")`로 멈춘다. 조용히 넘어가지 않는다 | 진희, W4 |

차원 N은 임베딩 모델에 따라 `.env`의 `EMBEDDING_DIM`. 모델을 바꾸면 테이블을 비우고 전부 재적재(마이그레이션이 아니라 스크립트).

## Alembic 규칙 (백엔드 Flyway 규칙과 같은 모양)

1. 파일 하나 = 변경 하나. `migrations/versions/0001_str_tables.py` 처럼 번호 + 내용.
2. 번호는 팀 채팅에 예약. 준영 점수 쪽(`model_versions`·`alert_features`·`predictions`)은 준영이 W3에 필요할 때 자기 파일로.
3. 적용된 파일은 안 고친다. 고치려면 다음 번호. **예외**: `0001`은 아직 아무 DB에도 적용 전(W2)이라 10/27 변경(`status`·`request_hash`·UNIQUE)을 `0001` 안에서 고친다 — 적용 뒤부터 규칙 3.
4. `alembic upgrade head`가 CI에서 빈 DB에 돈다(compose db 서비스).
5. 컬럼 추가는 nullable로 먼저. NOT NULL은 데이터 채운 뒤 다음 파일에서.

## 번호 계획

| 파일 | 내용 | 누가·언제 |
|---|---|---|
| `0001_str_tables` | `generations`(status·request_hash·partial UNIQUE 포함), `prompt_versions`, `fewshot_examples` | 진희, W2 (뼈대에 있음 — 10/27 변경 반영 필요) |
| `0002_verification_runs` | `verification_runs`(revision_no·narrative_sha256·request_id 포함) | 진희, W3 (SCRUM-57, 2026-11-01) |
| `0003_scoring_tables` | `model_versions`, `alert_features`, `predictions` | 준영, W3 |
| `0004_reference_chunks` | pg_extension 확인 → `reference_chunks` + HNSW·GIN | 진희, W4 (pgvector 뒤) |
