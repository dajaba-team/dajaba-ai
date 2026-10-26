# dajaba-AI — 작업 규칙 (Claude Code가 매 세션 먼저 읽는 파일)

다자바 AML 프로젝트의 **AI 서버 리포**(FastAPI, Python 3.12). 백엔드(`dajaba`, Spring)와는 **다른 리포**다 — HTTP(규약 JSON)와 같은 PostgreSQL(`ops` 읽기, `ai` 쓰기)로만 만난다. 학습 코드도 여기 없다 — 준영의 ML 리포가 `aml-ml` 패키지로 들어온다.

세 리포: `dajaba`(백엔드, 5명) · `dajaba-AI`(이 리포, 진희·준영) · `aml-ml`(ML, 준영).

## 작업 전에 읽을 것

1. `docs/README.md` — 문서 지도와 상태표.
2. 바꾸려는 코드의 정본 md. `str/domain/facts.py`를 고치려면 `docs/str/04_facts.md`, 프롬프트는 `docs/str/05_prompts.md`, 검증은 `docs/str/06_verification.md`, 처리 순서는 `docs/str/03_pipeline.md`.
3. `docs/str/01_code_rules.md` — 짧다.

## 루프 규칙 — md가 먼저, 코드가 나중

- 동작을 바꾸는 변경은 **해당 md를 먼저 고치고** 코드를 고친다. md와 코드가 다르면 코드가 틀린 것.
- 작업이 끝나면 `docs/README.md` 상태표의 해당 줄을 갱신한다(미착수 → 진행 → 완료, 날짜).
- 설계 결정은 `docs/str/09_decisions.md`에 한 줄(날짜·결정·이유·버린 대안).
- 프롬프트 파일(`src/aml_ai/str/prompts/*_v*.md`)은 한 번 쓰고 나면 수정하지 않는다. 바꾸면 새 버전 파일.

## 계층 — 백엔드와 같은 모양

기능 폴더 `str/`, `scoring/` 안에 각각 `api/ application/ domain/ infrastructure/`. 의존 방향 **`api → application → domain`**, `infrastructure`는 `application`이 부르는 구현체. `domain`은 어떤 계층도 import하지 않는다(순수). 자세히는 `docs/str/02_structure.md`.

| 백엔드 | 여기 |
|---|---|
| Controller | `api/router.py` |
| DTO | `shared/schemas/*.py` (Pydantic) |
| Service / UseCase | `application/*_service.py` |
| Entity·도메인 로직 | `domain/*.py` (dataclass + 순수 함수) |
| Repository / 외부 클라이언트 | `infrastructure/*.py` |

## 절대 규칙

- `str/`과 `scoring/`은 서로 import하지 않는다. 공유는 `shared/`로만.
- 규약 JSON 모양은 `shared/schemas/`에만. 다른 곳에 dict 모양을 다시 적지 않는다.
- `domain/`에서 DB·LLM·시계·설정을 만지지 않는다. 입력 → 출력만.
- ML 로직(피처·모델·predict)은 이 리포에 없다. `aml_ml`을 import만 한다.
- 로그에 계좌번호·금액·narrative 본문·프롬프트 전문을 찍지 않는다.
- `.env`는 커밋하지 않는다. 변수 이름은 `docs/shared/05_dev_setup.md`.
- 상수에는 이름을 붙여 `domain/constants.py` 또는 `.env`로. 코드에 매직 넘버·모델 이름 금지.

## 완료 기준

`uv run pytest` 녹색 + `uv run ruff check` 통과 + 정본 md 갱신 + 상태표 갱신. 하나 빠지면 끝난 게 아니다.
