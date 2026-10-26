# dajaba-AI 설계 문서 지도

읽는 순서: `shared/00` → `shared/01` → 자기 폴더(`str/` 또는 `scoring/`) → 나머지는 필요할 때.

`dajaba-AI`는 백엔드 `dajaba`와 **별도 리포**다. 코드는 `src/aml_ai/`, 백엔드와 같은 4계층(`api/application/domain/infrastructure`) — `str/02_structure.md`.

팀 공유 문서(Claude Docs)의 「AML AI 설계 문서 v0.1」은 **왜**를 설명하고, 여기 md는 **정확히 무엇을** 코드로 만드는지 적는다. 둘이 다르면 여기가 정본이고, Claude Docs 쪽을 고친다. (3절·3A의 상세 내용은 10/26에 여기로 옮겼다. Claude Docs 3A는 요약과 링크만 남기는 걸 진희가 결정한다.)

## 파일

### shared/ — 둘 다 지키는 것 (진희 관리, 준영 합의)

| 파일 | 내용 | 바뀌는 때 |
|---|---|---|
| `shared/00_server_rules.md` | 폴더 경계·schemas 한 벌·버전 표기·.env·에러 JSON·내부 인증 — 세 줄 규칙 | 거의 없음 |
| `shared/01_contracts.md` | 규약 문서 ↔ `schemas/` ↔ `contracts/examples/` 관계, 필드 하나 바꾸는 절차 | 규약 v0.2 (10/27) |
| `shared/02_ml_package.md` | `aml-ml` 패키지 계약 — `score()` 시그니처, 버전 상수, git tag 고정, 모델 파일 | 준영 리포 첫 tag |
| `shared/03_ai_schema.md` | `ai` 스키마 8테이블, 누가 어디 쓰나, Alembic 규칙, pgvector | 테이블 추가 시 |
| `shared/04_versioning_logging.md` | 응답에 붙는 버전 4종, `ai_call_logs`, request_id | — |
| `shared/05_dev_setup.md` | 로컬 실행, `.env` 변수 이름, compose, 테스트 명령 | 의존성 바뀔 때 |

### str/ — 진희

| 파일 | 정본인 코드 |
|---|---|
| `str/01_code_rules.md` | 전부 |
| `str/02_structure.md` | 4계층 폴더·파일·의존 방향, 백엔드 계층 대응표 |
| `str/03_pipeline.md` | `application/*_service.py`, `api/router.py` — 세 엔드포인트 처리 순서·타임아웃·에러 |
| `str/04_facts.md` | `domain/facts.py`, `domain/masking.py`, `infrastructure/transaction_reader.py` |
| `str/05_prompts.md` | `prompts/*.md`, `infrastructure/narrative_generator.py`, `fewshot_store.py` |
| `str/06_verification.md` | `domain/verification.py`, `infrastructure/judge.py` |
| `str/07_llm_strategy.md` | 기법 선택과 이유(코드 아님, 발표 자료) |
| `str/08_testing.md` | `tests/str/` |
| `str/09_decisions.md` | 결정 기록 |
| `str/10_rag.md` | `infrastructure/retriever.py`, `tools/ingest_corpus.py`, `corpus/manifest.json` |

### scoring/ — 준영

`scoring/README.md` 하나. 준영이 자기 방식으로 쓴다. `shared/`는 같이 지킨다.

## 상태표 (작업 끝나면 여기 갱신)

| 항목 | 상태 | 날짜 | 비고 |
|---|---|---|---|
| 설계 md 세트 | 완료 | 10/26 | 3A·3A.7에서 옮김. 준영 검토 전 |
| 리포 뼈대 (`src/aml_ai` 4계층, shared 진짜, schemas, Alembic 0001, 계약 예시, 테스트 21) | 완료 | 10/26 | `uv run pytest`·`ruff check` 통과 |
| ML 패키지 연결 방식 | **확정(B 패키지)** | 10/26 | 준영 동의. 시그니처 세부는 `shared/02` "확인 필요" 칸 |
| `transaction_reader.load_subject` + `facts` 단위 테스트(규칙 표 1줄=1테스트) | 미착수 | | W2 |
| `llm_client` provider 1종 구현 + `tools/record.py` 녹화 | 미착수 | | W2 |
| Alembic 0001 적용 확인 (`-m db`) · few-shot 5개 작성 | 미착수 | | W2 |
| Alembic — `reference_chunks` (+pgvector) | 미착수 | | W4 |
| `POST /v1/str/drafts` (facts + narrative v1 + few-shot) | 미착수 | | W2~W3 |
| `POST /v1/str/verify` (코드 4 + 평가자 5) | 미착수 | | W3 |
| 오류 주입 1~6 CI | 미착수 | | W3 |
| RAG — 코퍼스 적재 → retrieval → REFERENCES → recall@3 | 미착수 | | W4 전반, 11/11 기준 |
| 오류 주입 7~14 수동 표 | 미착수 | | W4 |
| `/v1/cases/summary` | 미착수 | | W4 말 |
| `aml_ml` 설치 + `scoring/` 스텁 교체 | 미착수 | | 준영 첫 tag 후 |
