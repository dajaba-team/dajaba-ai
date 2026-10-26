# 03. `ai` 스키마 — 테이블 8개와 Alembic 규칙

같은 PostgreSQL, `ai` 스키마, `app_ai` 계정. 백엔드 테이블과 FK 없이 `prediction_id`·`draft_id` 값으로만 이어진다. 마이그레이션은 Alembic(`migrations/`). AI 설계 문서 7절의 표를 코드 기준으로 다시 적은 것.

## 테이블

| 테이블 | 쓰는 쪽 | 핵심 컬럼 | 왜 |
|---|---|---|---|
| `model_versions` | 준영, 학습 끝날 때 | `model_version` PK, `feature_version`, `algorithm`, `train_period`, `input_hash`, `threshold`, `metrics jsonb`, `artifact_path`, `is_serving`, `created_at` | 서빙되는 버전은 여기 등록된 것만. `aml_ml.MODEL_VERSION`과 같은 문자열 |
| `alert_features` | scoring, 추론마다 | `alert_id`, `as_of`, `feature_version`, `features jsonb`, `data_quality_status`, `computed_at` | W4 정합성(같은 경보에 같은 특징이 나왔나), 설명 재계산 |
| `predictions` | scoring | `prediction_id` PK, `alert_id`, `model_version`, `score`, `threshold`, `reasons jsonb`, `evidence_transaction_ids bigint[]`, `request_id`, `created_at` | 백엔드 `alert_scores.prediction_id`가 가리키는 것 |
| `prompt_versions` | 진희, 프롬프트 바꿀 때 | `prompt_name`, `version`, `file_hash`, `created_at` — PK(`prompt_name`,`version`) | 파일이 정본, 여기는 색인 |
| `generations` | str, 호출마다 | `generation_id` PK, `kind`(DRAFT/VERIFY/SUMMARY), `draft_id`, `case_no`, `facts jsonb`, `request jsonb`, `response jsonb`, `llm_model`, `prompt_version`, `few_shot_ids int[]`, **`references jsonb`**(10/26), `retrieval_version`, `tokens_in`, `tokens_out`, `latency_ms`, `status`, `error`, `request_id`, `created_at` | verify가 원래 facts를 여기서 꺼낸다. 비용·시간. 재현 |
| `verification_runs` | str | `verification_id` PK, `generation_id`, `draft_id`, `revision_no`, `code_checks jsonb`, `llm_checks jsonb`, `passed`, `status`, `verifier_version`, `created_at` | 백엔드 `verification_results.verification_id`가 가리키는 것 |
| `fewshot_examples` | 진희 | `example_id` PK, `typology`, `facts jsonb`, `narrative jsonb`, `is_active` | 파일(`str/fewshot/*.json`)이 정본, 여기는 서빙용 사본 |
| `reference_chunks` **(10/26 추가)** | 진희, `tools/ingest_corpus.py` | `chunk_id` PK, `doc_id`, `doc_title`, `publisher`, `year`, `page`, `section`, `lang`, `typologies text[]`, `text`, `embedding vector(N)`, `embedding_model`, `content_hash` UNIQUE, `created_at`. 인덱스 HNSW(cosine) on `embedding`, GIN on `typologies` | RAG 코퍼스 청크. PDF가 정본, 여기는 검색용 |

없는 것: 학습표(`alert_training_table`)는 Parquet 파일로 준영 리포에. 서빙 DB에 실험 데이터를 넣지 않는다.

## pgvector

- `reference_chunks.embedding`은 pgvector 확장이 필요하다. DB는 백엔드 리포(`dajaba`)의 compose가 띄우므로 확장 생성은 **백엔드 리포 `db/init/`**에서: `CREATE EXTENSION IF NOT EXISTS vector;` — 그리고 compose의 db 이미지를 `postgres:16` → `pgvector/pgvector:pg16`으로. 준혁 W2 적재가 끝난 뒤(W3 초)에 바꾸고 알린다. 그 전엔 `reference_chunks` 마이그레이션을 돌리지 않는다.
- 차원 N은 임베딩 모델에 따라 `.env`의 `EMBEDDING_DIM`. 모델을 바꾸면 테이블을 비우고 전부 재적재(마이그레이션이 아니라 스크립트).

## Alembic 규칙 (백엔드 Flyway 규칙과 같은 모양)

1. 파일 하나 = 변경 하나. `migrations/versions/0001_generations_prompt_versions_fewshot.py` 처럼 번호 + 내용.
2. 번호는 팀 채팅에 예약. 준영 점수 쪽(`model_versions`·`alert_features`·`predictions`)은 준영이 W3에 필요할 때 자기 파일로.
3. 적용된 파일은 안 고친다. 고치려면 다음 번호.
4. `alembic upgrade head`가 CI에서 빈 DB에 돈다(Testcontainers 또는 compose db).
5. 컬럼 추가는 nullable로 먼저. NOT NULL은 데이터 채운 뒤 다음 파일에서.

## W2에 만드는 것

`0001`: `generations`, `prompt_versions`, `fewshot_examples` — 뼈대에 들어 있음(`migrations/versions/0001_str_tables.py`). ORM은 `str/infrastructure/orm.py`. 점수 쪽 셋은 준영 `0002`(W3). `verification_runs` `0003`(W3, 진희). `reference_chunks` `0004`(W4, 진희, pgvector 뒤).
