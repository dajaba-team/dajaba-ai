# dajaba-AI 설계 문서 지도

읽는 순서: `shared/00` → `shared/01` → 자기 폴더(`str/` 또는 `scoring/`) → 나머지는 필요할 때.

`dajaba-AI`는 백엔드 `dajaba`와 **별도 리포**다. 코드는 `src/aml_ai/`, 백엔드와 같은 4계층(`api/application/domain/infrastructure`) — `str/02_structure.md`.

팀 공유 문서(Claude Docs)의 「AML AI 설계 문서」는 **왜**를 설명하고, 여기 md는 **정확히 무엇을** 코드로 만드는지 적는다. 둘이 다르면 여기가 정본이고, Claude Docs 쪽을 고친다. 규약은 「인터페이스 규약 v0.2」(10/27 회의 반영)가 정본이고 `shared/01`이 코드와 잇는다.

**10/27 상태**: 회의 결정과 설계 검토 2건을 문서에 먼저 반영했다(①~⑦). **코드는 아직 10/26 뼈대 그대로** — 문서와 코드가 다른 곳은 아래 상태표의 "코드 반영" 줄. 준영이 쓰는 칸(안건 3·5·6)은 비워 두고 "준영 작성"으로 표시.

## 파일

### shared/ — 둘 다 지키는 것 (진희 관리, 준영 합의)

| 파일 | 내용 | 10/27 |
|---|---|---|
| `shared/00_server_rules.md` | 폴더 경계·schemas 한 벌·버전 표기·.env·에러 JSON·내부 인증 — 세 줄 규칙 | 안건 17 문구 |
| `shared/01_contracts.md` | 규약 v0.2 ↔ `schemas/` ↔ `contracts/examples/`, 바뀐 필드 전부, **narrative 해시 규칙·테스트 벡터** | 개정 |
| `shared/02_ml_package.md` | `aml-ml` 패키지 계약 — `score()` 시그니처, 상태값 4종, **안건 3·5·6 확정**, ML 입력 범위·coverage·품질 판정 | 개정 |
| `shared/03_ai_schema.md` | `ai` 스키마 8테이블, `generations` 선점·상태, `verification_runs` 해시, **pgvector superuser 절차**, Alembic 번호 계획 | 개정 |
| `shared/04_versioning_logging.md` | 응답에 붙는 버전, 프롬프트 동결, `ai_call_logs`, request_id | 동결 규칙 |
| `shared/05_dev_setup.md` | 로컬 실행, `.env` 변수 이름, compose, 테스트 명령 | pgvector 수동 명령 추가 예정 |

### str/ — 진희

| 파일 | 정본인 코드 | 10/27 |
|---|---|---|
| `str/01_code_rules.md` | 전부 | — |
| `str/02_structure.md` | 4계층 폴더·파일·의존 방향, 백엔드 계층 대응표 | `shared/hashing.py` 추가 예정 |
| `str/03_pipeline.md` | `application/*_service.py`, `api/router.py` — 세 엔드포인트, **draft_id 선점·generation_id·예산·FAILED 행**, 에러 | 개정 |
| `str/04_facts.md` | `domain/facts.py`, `masking.py`, `transaction_reader.py` — **대상 계좌 관점 통화별 집계, observations/model_signals, fact 키 → evidence_ids** | 전면 개정 |
| `str/05_prompts.md` | `prompts/*.md`, `narrative_generator.py`, `fewshot_store.py` — **cites·FACT_KEYS, v1 동결 규칙**, 새 v1 전문 | 개정 |
| `str/06_verification.md` | `domain/verification.py`, `judge.py`, `shared/hashing.py` — **유형별 대조 5종·UNPARSED·경계 문구, 4점 기준** | 개정 |
| `str/07_llm_strategy.md` | 기법 선택과 이유(코드 아님, 발표 자료) — 관측/모델 설명 분리, 시간 가정값 | 보강 |
| `str/08_testing.md` | `tests/str/` — 오류 주입 26개, 해시 벡터, 선점 동시성 | 보강 |
| `str/09_decisions.md` | 결정 기록 — 10/27 회의·검토 줄 추가, 미결 표 | 개정 |
| `str/10_rag.md` | `retriever.py`, `ingest_corpus.py`, `manifest.json` — **0~3건, 청크 단위 평가, pgvector** | 개정 |

### scoring/ — 준영

`scoring/README.md` 하나. 준영이 자기 방식으로 쓴다. `shared/`는 같이 지킨다.

## 상태표 (작업 끝나면 여기 갱신)

| 항목 | 상태 | 날짜 | 비고 |
|---|---|---|---|
| 설계 md 세트 | 완료 | 10/26 | 3A·3A.7에서 옮김 |
| 리포 뼈대 (`src/aml_ai` 4계층, shared, schemas, Alembic 0001, 계약 예시, 테스트 21) | 완료 | 10/26 | `uv run pytest`·`ruff check` 통과 |
| ML 패키지 연결 방식 | 확정(B 패키지) | 10/26 | 준영 동의 |
| 규약 v0.2 (Claude Docs) | **완료** | 10/28 | 3·5·6절 교체, 0·4절·미결 표. 준영 칸(3·5·6) 대기 |
| **문서 ①~⑦ 10/27 반영** | **완료** | 10/28 | 이 표 위 "10/27" 열. 코드 전 문서 먼저 |
| 3차 설계 검토 반영 — 중복 방지 해시 비교·STALE 정리, ApprovalGate 세 조건, 통화별 근거·통화 코드, DATE 용도 분리, 한글 수사 UNPARSED, RAG 켬/끔 비교, 오류 주입 20개 | 완료 | 10/27 | 문서만(코드는 W2 수~목 반영 때). `shared/01·03`, `str/03·04·05·06·08·09·10` + 규약 Claude Docs 4절 전이·5.1 근거 범위·5.3 코드 5종·ApprovalGate·미결 표 통화 |
| 4차 설계 검토 반영 — 선점 advisory lock·해시 재확인·finish 펜싱, 경로 거래 `path`, DATE 가까운 날짜 규칙, 예시 축약 표시, 오류 주입 22개 | 완료 | 10/27 | 문서만. `shared/03`, `str/03·04·06·08·09`. path 세부는 준혁 확인 대기 |
| 5차 설계 검토 반영 — `path` 최소화(인용·LLM 전달 없음), evidence = alert.transaction_ids 확인, `ON CONFLICT` 선점, 펜싱 범위, 범위 표현 날짜 `UNPARSED` | 완료 | 10/27 | 문서만. 다음 확인은 리뷰 대신 W2 수 코드 + DB 테스트 5가지 |
| 준혁 답 반영(10/28) — 경로형 경보 `rule_facts.paths` 확인 → `paths` fact(VERIFIED일 때만 인용), `path` → `indirect`, 규칙 10, COUNT_MATCH 경로 수·계좌 수, 오류 주입 26개 | 완료 | 10/28 | 문서만. `shared/01`, `str/03·04·05·06·08·09`. SCRUM-28 |
| 준영 답·안건 23 세부 반영(10/28) — 안건 3·5·6 확정(`reasons` 구조, `feature_version`, 필드 매핑·`alert_id` 문자열), 입력 범위 24h·coverage·품질 판정, 관측값 표기 규칙 11, 수정본 `narrative_refs`(a) | 완료 | 10/28 | 문서만. `shared/01·02`, `scoring/README`, `str/04·05·06·08·09`. 점수 항목별 실패·`failure_code`·503은 준혁 대기. SCRUM-28 |
| **코드 반영 — schemas** (`DataQualityStatus` 4값, `Reason` 3단, `alert_id` 문자열·`rule_facts.paths`, `DraftRequest`/`DraftResponse`/`VerifyRequest`/`VerifyResponse`, 코드 검사 5종·`reason`, `GenerationInProgress`·`ModelUnavailable`, `Facts` 새 구조, `examples/` 갱신) | 완료 | 10/28 | SCRUM-12. 마스킹(dict 반환)·서비스 필드명·점수 목업도 맞춤. `facts.py`·`hashing.py`는 자리만(SCRUM-13·16). 점수 `failure_code`는 준혁 대기 |
| 코드 반영 — `facts.py` 재작성(inbound/outbound/internal, 통화별 `transaction_ids`, 통화 코드 변환, fact_keys, attach_evidence) + 단위 테스트 | 미착수 | | W2 수 |
| 코드 반영 — `draft_service` 선점(해시 비교·STALE 정리)·generation_id·예산·FAILED, `llm_client` 연결 재시도 삭제, `0001` status·request_hash·UNIQUE | 미착수 | | W2 수~목 |
| 코드 반영 — `shared/hashing.py` + `narrative_hash.json` 테스트 벡터 | 미착수 | | W2 목 (Java 쪽은 W3) |
| `narrative_v1.md` 새 전문으로 교체, few-shot 예시 새 facts 구조로 | 미착수 | | W2 목 |
| `llm_client` provider 1종 구현 + `tools/record.py` 녹화 → **v1 동결** | 미착수 | | W2 목 |
| Alembic 0001 적용 확인 (`-m db`) | 미착수 | | W2 |
| `POST /v1/str/drafts` 백엔드 ↔ AI 왕복 ("됐다") | 미착수 | | W2 금 |
| `POST /v1/str/verify` (유형별 코드 검사 5 + 평가자 5 + 해시) | 미착수 | | W3 |
| 오류 주입 1~6·15~22 CI | 미착수 | | W3 |
| 준영 안건 3·5·6 반영 (`Reason` 모델, `observations` 매핑, `AlertInput`) | 문서 완료 | 10/28 | 코드는 SCRUM-12(schemas)·13(facts) |
| Alembic — `reference_chunks` (+pgvector superuser 절차) | 미착수 | | W4 |
| RAG — 코퍼스 적재 → retrieval(0~3건) → REFERENCES → hit@3 표 | 미착수 | | W4 전반, 11/11 기준 |
| 오류 주입 7~14·23 수동 표 | 미착수 | | W4 |
| `/v1/cases/summary` | 미착수 | | W4 말 |
| `aml_ml` 설치 + `scoring/` 스텁 교체 | 미착수 | | 준영 첫 tag 후 |
