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
- few-shot은 `few_shot_ids`(`fewshot_examples.example_id`)로 어떤 예시가 쓰였는지 기록.

## 로그 (`shared/logging.py`)

- JSON 한 줄 로그(stdout). 필드: `ts, level, request_id, route, status, latency_ms, alert_count|draft_id, generation_id, llm_model, tokens_in, tokens_out, error_code`.
- `request_id`: 백엔드 `X-Request-Id`를 받고, 없으면 생성. 응답 헤더로 돌려주고 에러 JSON에도 넣는다. 백엔드 `request_id`와 같아야 두 로그를 이어 볼 수 있다.
- **찍지 않는 것**: 계좌번호·금액·narrative/summary 본문·프롬프트 전문·API 키. 본문이 필요하면 `generations` 테이블에 있다.

## `ai_call_logs`는 백엔드 테이블

백엔드가 AI를 부를 때마다 자기 DB `ops.ai_call_logs`에 요청·응답 메타(상태, 시간, request_id, 버전들, `generation_id`)를 남긴다(백엔드 레퍼런스 8.5, W2~W3 진희, V007). AI 서버는 그걸 모른다. AI 서버 쪽 기록은 `generations`·`predictions`가 하고, 둘은 `request_id`로 이어진다. 테이블을 양쪽에 중복으로 만들지 않는다.

## 비용 기록

`generations.tokens_in/out`과 `llm_model`로 호출당 비용을 계산한다. 하루 한도는 `.env`의 `LLM_DAILY_TOKEN_BUDGET`, 넘으면 `LLM_BUDGET_EXCEEDED`(502)로 거절 — 재시도 없음(규약 6.2: 4xx·예산 초과는 0회).
