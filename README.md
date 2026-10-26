# dajaba-AI — AML AI 서버

다자바 AML 프로젝트의 AI 서버. 백엔드(`dajaba`, Spring)가 HTTP로 부르는 FastAPI 한 대에 파이프라인 두 개가 산다.

| 파이프라인 | 폴더 | 담당 | 하는 일 |
|---|---|---|---|
| 점수 | `src/aml_ai/scoring/` | 준영 | 경보 500건 → 트리 모델 점수 + SHAP 이유. 모델·피처는 `aml-ml` 패키지(준영 ML 리포) |
| STR | `src/aml_ai/str/` | 진희 | 경보 1건 → facts → LLM 서술 6섹션 → 코드 4종 + LLM 평가자 5종 검증, 참고 사례 검색(RAG), 케이스 요약 |

리포 세 개: `dajaba`(백엔드) · **`dajaba-AI`(이것)** · `aml-ml`(ML). 백엔드와는 규약 JSON(HTTP)과 같은 PostgreSQL(`ops` 스키마 읽기, `ai` 스키마 쓰기)로만 만난다. 설계 문서는 `docs/`(먼저 `docs/README.md`), 팀 공유 문서는 Claude Docs 「AML AI 설계 문서」.

## 처음 받았을 때 (5분)

```bash
git clone <repo> dajaba-AI && cd dajaba-AI
# 1. .env — 노션 「다자바 환경변수」의 AI 서버 부분을 .env 로 저장 (변수 이름은 docs/shared/05_dev_setup.md). 커밋 금지
# 2. DB — 백엔드 리포에서 docker compose up db  (app_ai 계정·ai 스키마는 백엔드 db/init 이 만든다)
# 3. 기동
uv sync
uv run alembic upgrade head
uv run uvicorn aml_ai.main:app --reload --port 8000
open http://localhost:8000/docs
```

`GET /v1/health` → `{"status":"ok", "db":"ok", "llm":"ok|missing_key", "model_version":null, ...}` 이면 준비 끝. 백엔드는 기동 시 이걸 한 번 부른다.

compose로: `docker compose up` — 이 리포의 `compose.yaml`이 백엔드 compose의 네트워크(`dajaba_default`)에 `ai` 서비스를 붙인다. 백엔드 `.env`의 `AI_BASE_URL=http://ai:8000`.

## 구조 — 백엔드와 같은 모양

```
src/aml_ai/
├─ main.py                     FastAPI 생성, 라우터 등록, /v1/health
├─ shared/                     설정·에러·로그·인증·버전·DB + 규약 Pydantic 한 벌(schemas/) + LLM·임베딩 클라이언트
├─ str/     api/ application/ domain/ infrastructure/ prompts/ fewshot/     진희
└─ scoring/ api/ application/ domain/ infrastructure/                       준영
```

| 백엔드(Spring) | 여기(FastAPI) |
|---|---|
| Controller | `api/router.py` |
| DTO | `shared/schemas/` (Pydantic) |
| Service / UseCase | `application/*_service.py` |
| Entity·도메인 로직 | `domain/` — dataclass + **순수 함수** |
| Repository · 외부 클라이언트 | `infrastructure/` |

의존 방향 `api → application → domain`, `infrastructure`는 `application`이 부른다. `str` ↔ `scoring` 서로 모름. 자세히는 `docs/str/02_structure.md`.

## 규칙 세 줄

1. **폴더끼리 import 금지.** `str/`과 `scoring/`은 `shared/`로만 만난다.
2. **규약 JSON은 `shared/schemas/` 한 벌.** 바꾸는 절차는 `docs/shared/01_contracts.md`.
3. **ML 로직은 이 리포에 없다.** `aml_ml`을 import만 한다(`docs/shared/02_ml_package.md`).

더: `CLAUDE.md`(작업 루프), `docs/str/01_code_rules.md`.

## 지금 들어 있는 것 (뼈대, 10/26)

| 묶음 | 상태 |
|---|---|
| `shared/` config·errors·logging·auth·versioning·db, `schemas/` 5파일, `llm_client`·`embedding_client` 틀 | 진짜 (LLM 호출은 녹화 모드 포함) |
| `main.py` + `/v1/health` | 진짜 |
| `str/` 4계층 파일 전부 — 시그니처·docstring·TODO(정본 md 번호) | 뼈대. `domain/`은 W2~W3에 채움 |
| `str/prompts/narrative_v1.md`, `judge_v1.md` | 진짜 (docs/str/05) |
| `scoring/` — 라우터 + `AI_SCORING_MOCK` 고정 점수 service | 목업. `aml-ml` tag 후 교체 |
| `migrations/versions/0001_str_tables.py` | generations·prompt_versions·fewshot_examples |
| `contracts/examples/` | 규약 예시 JSON (백엔드와 같은 파일) |
| `tests/` | 계약 테스트·health·schemas 통과. domain 테스트는 skip(W3) |

## 테스트

```bash
uv run pytest                 # LLM 호출 없음 (녹화)
uv run pytest -m db           # Alembic·저장 (Docker 필요)
uv run pytest -m live         # 실제 LLM — W4 수동
uv run ruff check . && uv run ruff format .
```

## 다음

`docs/README.md` 상태표. W2: `str/domain` facts·masking 구현 + `POST /v1/str/drafts`. W3: 검증·오류 주입 1~6. W4: RAG·안정화.
