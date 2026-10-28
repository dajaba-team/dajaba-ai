# 05. 로컬 실행

## 위치 — 별도 리포

`dajaba-AI`는 백엔드 `dajaba`와 **다른 리포, 다른 폴더**(`/Users/parkjinhee/AI/dajaba-AI`). 코드·문서·설정을 섞지 않는다. 만나는 곳은 둘: ① HTTP(규약 JSON) ② PostgreSQL — DB는 백엔드 compose가 띄우고(`db/init`이 `app_ai` 계정·`ai` 스키마를 만든다), AI 서버는 거기 붙는다. `.env`는 리포마다 따로지만 변수 이름은 노션 한 페이지에서 같이 관리(`APP_AI_PASSWORD`, `AI_INTERNAL_KEY`는 양쪽 같은 값). 준영 ML 리포 `aml-ml`도 별도.

## 도구

- **Python 3.12** (10/26 결정 — 3.11은 보안 패치만 받는 단계, 3.13은 shap·numba 조합 위험. 준영 `aml-ml`도 3.12로 맞춘다. `.python-version` 파일이 고정), **uv**(`pyproject.toml` + `uv.lock`). poetry 아님.
- FastAPI, pydantic v2 + pydantic-settings, SQLAlchemy 2(동기, `psycopg`), Alembic, pgvector(파이썬 패키지), httpx, pymupdf(코퍼스 적재), pytest + testcontainers(또는 compose db).
- LLM SDK는 설정으로 1종 선택(`LLM_PROVIDER`). LangChain 안 씀 — 이유는 `str/07_llm_strategy.md`.

## 처음

```bash
# 1) 백엔드 리포에서 DB 만 띄운다
cd ../dajaba && docker compose up db        # app_ai 계정·ai 스키마는 db/init/01_roles.sh 가 만든다
# 2) 이 리포
cd ../dajaba-AI
# .env — 노션 「다자바 환경변수」의 AI 서버 부분 (아래 표). 커밋 금지
uv sync                                     # aml-ml 은 tag 가 생긴 뒤 pyproject 에 추가
uv run alembic upgrade head
uv run uvicorn aml_ai.main:app --reload --port 8000
open http://localhost:8000/docs
```

`GET /v1/health` → `{status, server_version, model_version|null, llm: ok|missing_key, db: ok}`. 백엔드는 기동 시 이걸 한 번 부른다(`AiHealthCheck`).

pgvector(W4, RAG 전): 확장 생성은 superuser만 된다(`shared/03`). 백엔드 compose db 이미지가 `pgvector/pgvector:pg16`으로 바뀐 뒤, **이미 만들어 둔 DB 볼륨**에는 손으로 1회:

```bash
cd ../dajaba && docker compose exec db psql -U postgres -d aml -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

새로 만드는 DB는 `db/init/00_extensions.sql`이 해 준다. `alembic upgrade head`가 "pgvector 확장 없음"으로 멈추면 이 명령.

compose로: 이 리포의 `compose.yaml`은 `ai` 서비스 하나이고 백엔드 compose의 네트워크(`dajaba_default`, external)에 붙는다. 백엔드에서 `docker compose up db` → 여기서 `docker compose up --build`. 백엔드 `.env`의 `AI_BASE_URL=http://ai:8000`.

## `.env` 변수 (값은 노션)

| 변수 | 내용 |
|---|---|
| `APP_AI_PASSWORD` | DB 계정 `app_ai` (백엔드 `.env`와 같은 변수) |
| `DATABASE_URL` | `postgresql+psycopg://app_ai:${APP_AI_PASSWORD}@localhost:5432/aml` (compose 안에서는 host `db`) |
| `AI_INTERNAL_KEY` | 백엔드와 같은 값. `X-Internal-Key` 검사 |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL_GENERATE`, `LLM_MODEL_JUDGE` | 생성·평가자 모델. 평가자는 다른 모델이면 좋고, 같으면 프롬프트에서 역할 분리 |
| `LLM_TIMEOUT_S` (기본 **35**), `DRAFT_BUDGET_S` (기본 80), `REGEN_MIN_REMAINING_S` (기본 40), `LLM_DAILY_TOKEN_BUDGET` | 시간 예산(`str/03`) — W2 수 실측 전 가정값 |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | RAG(W4). 멀티링구얼 1종 |
| `AI_SCORING_MOCK` | `true`면 `aml_ml` 없이 고정 점수(W2~W3) |
| `AI_LLM_MOCK` | `true`면 LLM 호출 대신 녹화된 응답(`tests/str/recorded/`). 백엔드 로컬 연동용 |
| `RAG_ENABLED` | `true`면 retriever 가 pgvector 검색 (W4). `false`면 references=[] — 안건 22 되돌림 스위치 |
| `SERVER_VERSION` | 빌드 시 git 짧은 해시 주입 (Dockerfile ARG). 로컬은 `dev` |
| `INDEX_PROMPTS_ON_STARTUP` | 기동 시 prompts/*.md 해시를 prompt_versions 에 색인. 테스트에서 false |
| `CORPUS_DIR` | 코퍼스 PDF 위치(리포 밖) |

## 테스트

```bash
uv run pytest                      # 단위 + 계약 (LLM 호출 없음, 녹화 응답)
uv run pytest -m db                # Alembic + 저장 (Docker 필요)
uv run pytest tests/str/test_injection.py -m deterministic   # 오류 주입 1~6, 13
```

LLM을 실제로 부르는 테스트(7~12, 14)와 검색 평가(hit@3)는 `-m live`로만, CI에서는 안 돈다.

## 코드 스타일

ruff(format + lint), 설정은 `pyproject.toml`. 커밋 전 `uv run ruff check . && uv run ruff format .`. 타입 힌트 필수(`mypy --strict`는 `shared/`와 `str/domain/`에만 — 순수 함수라 비용이 작다). 예외 이름은 규약 에러 코드를 따르므로 ruff N818은 끈다.
