# 02. 폴더·파일 구조 — 백엔드와 같은 4계층

`dajaba-AI`는 **별도 리포**다(백엔드 `dajaba`, ML `aml-ml`과 다른 폴더·다른 git). 안은 백엔드 `com.team.aml.{기능} × domain/application/infrastructure/api`와 같은 모양으로 짠다. 새 파일을 만들면 **여기 먼저 한 줄 추가**하고 만든다.

## 계층 대응

| 백엔드(Spring) | 여기(FastAPI) | 규칙 |
|---|---|---|
| `@RestController` | `api/router.py` | 요청 Pydantic으로 받고 service 호출, 응답. 로직 없음 |
| Request/Response DTO | `shared/schemas/*.py` | 규약 JSON 한 벌. 기능 폴더 안에 DTO를 다시 만들지 않음 |
| `@Service` / UseCase | `application/*_service.py` | 처리 순서 조립(`03`). 로직은 domain, 부작용은 infrastructure |
| Entity + 도메인 로직 | `domain/*.py` | dataclass + **순수 함수**. DB·LLM·시계·설정 모름 |
| `@Repository` | `infrastructure/*_repository.py`, `*_reader.py` | SQLAlchemy. 얇게 |
| 외부 클라이언트(`AiClient`) | `infrastructure/narrative_generator.py`, `judge.py`, `retriever.py` + `shared/infrastructure/*_client.py` | LLM·임베딩 호출 |
| JPA Entity 매핑 | `infrastructure/orm.py` | 테이블 ↔ 객체. 도메인 모델과 분리 |

## 트리

```
dajaba-AI/
├─ CLAUDE.md · README.md · pyproject.toml · uv.lock · Dockerfile · compose.yaml · alembic.ini
├─ src/aml_ai/
│  ├─ main.py                          FastAPI 생성, 라우터 2개, /v1/health, 기동 시 prompt_versions 색인
│  ├─ shared/                          둘이 같이 쓰는 것만 (docs/shared/00)
│  │  ├─ config.py                     pydantic-settings — .env
│  │  ├─ errors.py                     예외 한 벌 + HTTP 매핑 (규약 6절)
│  │  ├─ logging.py                    JSON 로그, request_id 미들웨어
│  │  ├─ auth.py                       X-Internal-Key
│  │  ├─ versioning.py                 응답 버전 (docs/shared/04)
│  │  ├─ hashing.py                    narrative sha256 — 백엔드 NarrativeHash.java 와 같은 값 (docs/shared/01)
│  │  ├─ db.py                         SQLAlchemy 엔진·세션·Base
│  │  ├─ schemas/                      common · alerts · scores · str · errors
│  │  └─ infrastructure/               llm_client(녹화 모드 포함) · embedding_client
│  ├─ str/                             진희
│  │  ├─ api/router.py                 POST /str/drafts, /str/verify, /cases/summary
│  │  ├─ application/                  draft_service · verify_service · summary_service      (03)
│  │  ├─ domain/                       models · constants · facts · fact_paths · fact_keys · masking · verification    (04, 06)
│  │  ├─ infrastructure/               orm · transaction_reader · generation_repository · verification_repository
│  │  │                                · fewshot_store · narrative_generator · judge · retriever · prompt_index
│  │  ├─ prompts/                      narrative_v1.md · judge_v1.md — 쓰고 나면 수정 금지 (05)
│  │  └─ fewshot/                      예시 json (정본). DB fewshot_examples 는 사본
│  └─ scoring/                         준영 — 같은 4계층. domain/ 은 비어 있음(로직은 aml_ml)
│     ├─ api/router.py · application/score_service.py(AI_SCORING_MOCK) · infrastructure/
├─ migrations/versions/0001_str_tables.py        Alembic (docs/shared/03 번호 규칙)
├─ contracts/examples/                 규약 JSON 7개 — 백엔드와 같은 파일 (docs/shared/01)
├─ corpus/manifest.json                RAG 문서 목록. pdf/ 는 .gitignore (10)
├─ tools/ingest_corpus.py              PDF → 청크 → 임베딩 → reference_chunks (10)
├─ docs/                               shared/ str/ scoring/
└─ tests/                              contract/ shared/ scoring/ str/(fixtures, recorded, test_*)
```

## 의존 방향

```
api → application → domain          (한 방향. domain 은 shared/schemas 와 표준 라이브러리만)
application → infrastructure         (application 이 부른다. infrastructure 는 domain 모델을 돌려준다)
str ╳ scoring                        (서로 모름)
*   → shared                         (한 방향)
scoring/application → aml_ml         (패키지, 리포 밖)
```

`domain/`이 `infrastructure/`를 import하면 틀린 것. `infrastructure/`가 `application/`을 import해도 틀린 것. 자동 검사(import-linter)는 W3에 — 그때까지는 리뷰에서.

## 파일별 정본 md

| 파일 | 정본 |
|---|---|
| `domain/facts.py`, `domain/fact_paths.py`, `domain/fact_keys.py`, `domain/masking.py`, `infrastructure/transaction_reader.py` | `04_facts.md` |
| `prompts/*`, `infrastructure/narrative_generator.py`, `fewshot_store.py` | `05_prompts.md` |
| `domain/verification.py`, `infrastructure/judge.py` | `06_verification.md` |
| `application/*_service.py`, `api/router.py`, `*_repository.py` | `03_pipeline.md` |
| `infrastructure/retriever.py`, `tools/ingest_corpus.py`, `corpus/` | `10_rag.md` |
| `infrastructure/orm.py`, `migrations/` | `../shared/03_ai_schema.md` |
| `shared/schemas/*` | `../shared/01_contracts.md` |
| `domain/constants.py` | 상수의 정본은 각 md. 여기는 모아 둔 곳 |

## 10/26 뼈대에 들어 있는 것

`shared/` 전부(진짜), `schemas/` 5파일(규약 그대로), `str/` 4계층 파일 전부(시그니처·docstring·TODO — `facts.py`·`masking.py`·`evidence_in_scope`는 구현), 프롬프트 2개, few-shot 샘플 1, `scoring/` 목업, Alembic 0001, 계약 예시 7, 테스트(21 통과·8 skip). `ruff check` 통과.
