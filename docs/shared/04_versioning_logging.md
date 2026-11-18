# 04. 버전 표기와 로그

"이 응답은 어떤 코드·모델·프롬프트·데이터에서 나왔나"를 응답 하나로 재구성할 수 있어야 한다. 그걸 위한 규칙.

## 응답에 붙는 버전 (`shared/versioning.py`)

| 필드 | 값 | 어디서 |
|---|---|---|
| `model_version` | `aml_ml.MODEL_VERSION` | 점수 응답. STR 응답은 null |
| `feature_version` | `aml_ml.FEATURE_VERSION` | 점수 응답 |
| `prompt_version` | `narrative_v1` 같은 파일명 (해시는 `prompt_versions` 테이블) | STR·요약 응답 |
| `verifier_version` | 코드 검증 로직 버전 문자열, 예 `verify-2026.11.01` + judge 프롬프트 버전 `judge_v1` | 검증 응답 |
| `retrieval_version` **(10/26)** | `{embedding_model}@{corpus_manifest_sha256[:8]}` | STR 응답 `generation_meta` |
| `llm_model` | 실제 호출한 모델 ID(설정값이 아니라 API가 돌려준 값) | STR·요약·검증 응답 |
| `server_version` | git 커밋 짧은 해시 (빌드 시 주입) | `/v1/health`와 모든 응답 |

`generation_meta`/`scoring_meta` 객체에 모아 담는다. 필드 이름은 규약 3·5절과 같다 — 규약이 바뀌면 `schemas/`와 여기를 같이.

## 프롬프트 버전

- 파일 `str/prompts/narrative_v1.md`, `judge_v1.md`, `summary_v1.md`. **첫 녹화를 커밋한 순간 동결**(`prompt_versions.frozen_at`), 그 뒤 바꾸면 `_v2` — 동결 전(지금)은 자유롭게 고친다(`str/05`).
- 기동 시 파일 해시를 계산해 `prompt_versions`에 없으면 insert. 응답에는 파일명, DB에 해시 — 동결된 버전의 파일이 바뀌어 있으면 기동 실패.
- 동결 대조 기준은 **`str/domain/constants.FROZEN_PROMPTS`** 상수 dict(`{prompt_name: sha256}`). `check_frozen_prompts()`가 기동 때 파일 해시와 비교, 다르면 `FrozenPromptMismatch`로 기동 실패(DB 없이도 걸림). 녹화 커밋에서 해시를 박는다(SCRUM-15 10/29).
- few-shot은 `few_shot_ids`(`fewshot_examples.example_id`)로 어떤 예시가 쓰였는지 기록.

## 로그 (`shared/logging.py`)

JSON 한 줄 로그(stdout). **칸 이름은 백엔드(`dajaba`)와 같다**(SCRUM-272) — Alloy 가 두 컨테이너 로그를 Loki 로 모으고, 한 요청의 백엔드·AI 로그를 `request_id` 하나로 이어 본다.

| 칸 | 뜻 | 예 |
|---|---|---|
| `ts` | UTC ISO-8601, 밀리초 | `2026-11-19T01:02:03.456Z` |
| `level` | `INFO`·`WARNING`/`WARN`·`ERROR` (언어 기본값 그대로 — AI 는 `WARNING`) | |
| `service` | `ai` · `backend` 고정 | |
| `logger` | 로거 이름 | `aml_ai.str.application.draft_service` |
| `msg` | 사건 이름(짧은 영문) 또는 `key=value` 한 줄 | `retrieval_unavailable` |
| `request_id` | 백엔드 `X-Request-Id` 그대로, 없으면 생성 | |
| 선택 칸 | `target`(화면 번호 `CASE-`·`DRF-`·`ALT-`) · `error_code` · `latency_ms` · `*_count` · 버전 칸 | |

- 필수 칸 6개는 `shared/logging.py` 포매터가 채운다(`service="ai"` 고정). `extra={...}` 로 넘긴 칸은 이름 그대로 최상위에 붙는다.
- **팀원은 자기 기능 로그를 이 형식에만 맞춘다** — 새 칸이 필요하면 선택 칸 이름 규칙(`*_count`·`*_ms`)으로. 필수 칸 이름(`ts`·`level`·`service`·`logger`·`msg`·`request_id`)을 `extra` 키로 쓰지 않는다.
- `request_id`: 백엔드 `X-Request-Id`를 받고, 없으면 생성. 응답 헤더로 돌려주고 에러 JSON에도 넣는다. 64자를 넘으면 새로 만들고 `request_id_replaced` 경고(SCRUM-58). 처리 안 된 예외(500)도 `RequestIdMiddleware` 안에서 잡아 `unhandled` 를 **한 번** 찍으므로 그 줄에도 `request_id` 가 있고, 500 응답(`INTERNAL`, 에러 JSON 같은 모양)에도 `X-Request-Id` 헤더가 붙는다(SCRUM-272).
- Loki 조회 예(Grafana Explore): `{compose_service=~"app|ai"} | json | request_id="<값>"`
- **남기지 않는 것**: 계좌번호(원본·가린 값 모두) · 금액 · narrative/summary 본문 · 프롬프트 전문 · 조사역 메모 · API 키 · 요청/응답 본문. ID·건수·길이·시간·코드값만. 본문이 필요하면 `generations` 테이블에 있다. DB 오류 메시지에는 SQL 파라미터를 싣지 않는다(`shared/db.py` `hide_parameters=True` — 처리 안 된 예외는 스택째 찍히므로). 처리 안 된 예외가 Pydantic `ValidationError` 또는 FastAPI `ValidationException` 계열(`ResponseValidationError` — 라우터 `response_model` 검증 실패)이면 메시지·스택 대신 `error_type`(클래스 이름) + `errors` 의 `loc`·`type` 만 남긴다(Pydantic 은 `include_input=False, include_url=False`). 메시지에 입력값(본문 조각·계좌)이 실리기 때문. 다른 예외는 스택 그대로. 초안·검증·점수 요청 동안 stdout 에 이 값이 없는지 테스트가 지킨다(정상·LLM 오류·DB 오류·요청/응답 검증 오류 경로 — 알려진 유출 없음, `tests/str/test_log_no_sensitive.py`·`_errors.py` · 형식은 `tests/shared/test_log_format.py`).

## `ai_call_logs`는 백엔드 테이블

백엔드가 AI를 부를 때마다 자기 DB `ops.ai_call_logs`에 요청·응답 메타(상태, 시간, request_id, 버전들, `generation_id`)를 남긴다(백엔드 레퍼런스 8.5, W2~W3 진희, V007). AI 서버는 그걸 모른다. AI 서버 쪽 기록은 `generations`·`predictions`가 하고, 둘은 `request_id`로 이어진다. 테이블을 양쪽에 중복으로 만들지 않는다.

## 비용 기록

`generations.tokens_in/out`과 `llm_model`로 호출당 비용을 계산한다. 하루 한도는 `.env`의 `LLM_DAILY_TOKEN_BUDGET`, 넘으면 `LLM_BUDGET_EXCEEDED`(502)로 거절 — 재시도 없음(규약 6.2: 4xx·예산 초과는 0회).
