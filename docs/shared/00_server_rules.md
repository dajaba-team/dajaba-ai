# 00. AI 서버 공통 규칙

백엔드의 "규칙 세 줄"과 같은 역할. 두 사람이 각자 폴더를 만지면서도 서버가 하나로 돌아가게 하는 최소 규칙.

## 세 줄

1. **폴더끼리 import 금지.** `src/aml_ai/scoring/`과 `src/aml_ai/str/`은 서로를 모른다. 둘이 같이 쓰는 건 `src/aml_ai/shared/`에만 둔다. 기능 폴더 안은 `api → application → domain`, `infrastructure`는 `application`이 부른다(`str/02`). 공유 코드를 추가하려면 상대에게 먼저 말한다 — 상대 코드가 깨지는 유일한 경로가 여기다.
2. **규약 JSON은 `shared/schemas/` 한 벌.** 요청·응답 Pydantic 모델을 다른 곳에 다시 만들지 않는다. 필드를 바꾸는 절차는 `01_contracts.md`.
3. **ML 로직은 이 리포에 없다.** 피처·모델·predict는 전부 `aml_ml` 패키지(준영 리포). 여기서는 import하고 호출만 한다. 계약은 `02_ml_package.md`.

## 그 밖에 둘 다 지키는 것

- **버전 표기** — 모든 응답에 `model_version`·`feature_version`·`prompt_version`·`verifier_version`(해당 없는 것은 null)이 들어간다. 모아 붙이는 코드는 `shared/versioning.py`. 어떤 응답이 어떤 코드·모델·프롬프트에서 나왔는지 재현할 수 있어야 한다.
- **에러 JSON** — 규약 6절 형식 `{code, message, request_id}`. 예외 → HTTP 상태·코드 매핑은 `shared/errors.py` 한 곳. 라우터에서 `HTTPException`을 직접 만들지 않는다.
- **내부 인증** — 백엔드가 보내는 `X-Internal-Key` 헤더를 `shared/auth.py`가 검사한다. 키는 `.env`의 `AI_INTERNAL_KEY`, 백엔드와 같은 값. `/v1/health`만 예외.
- **request_id** — 백엔드가 보낸 `X-Request-Id`를 그대로 받아 로그·`ai_call_logs`·응답에 넣는다. 없으면 만든다. `shared/logging.py`.
- **설정은 코드가 아니라 `.env`** — 모델 이름, 키, DB 주소, 임베딩 모델, 타임아웃. `shared/config.py`의 pydantic-settings가 읽는다. `.env`는 커밋 금지(노션 「다자바 환경변수」).
- **로그에 안 찍는 것** — 계좌번호, 금액, narrative·summary 본문, 프롬프트 전문. ID·건수·길이·소요 시간만. 디버깅용 전문은 `generations.request/response`(DB)에 있다.
- **DB 계정** — `app_ai` 하나. `ops` 스키마는 원천 4테이블(`transactions`, `accounts`, `entities`, `customer_attributes`) SELECT만, `ai` 스키마는 읽기·쓰기. `alerts`·`cases`·`str_drafts`는 읽지 않는다 — 필요한 값은 요청 JSON에 담겨 온다.
- **시간** — 백엔드가 90초 기다린다(규약 6.2). 그 안에 안 끝나면 502다. 긴 작업은 요청 안에서 끝내지 말고 설계를 다시 본다 — 초안·검증을 별도 호출로 나눈 이유(안건 17 확정). AI 안 예산은 80초(`str/03`).

## 바꾸고 싶으면

이 문서를 고치는 PR에 상대를 리뷰어로. 둘이 동의하면 바뀐다.
