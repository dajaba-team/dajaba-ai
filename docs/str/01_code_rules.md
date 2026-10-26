# 01. 코드 규칙 (str/)

짧게. 지키기 어려운 건 안 적었다.

## 하드코드 금지

- 숫자·문자열 상수는 **이름을 붙여** `str/domain/constants.py`에. `500`이 아니라 `CHUNK_TOKENS = 500`. 임계값(`JUDGE_PASS_SCORE = 4`), 섹션 enum, 정규식 패턴, 허용 소수 집합 전부.
- 환경에 따라 다른 값(모델 이름, 키, 주소, 타임아웃, 임베딩 차원)은 `.env` → `shared/config.py`. 코드에 모델 이름이 보이면 틀린 것.
- 프롬프트 본문은 코드 문자열이 아니라 `prompts/*.md` 파일. 코드는 파일을 읽어 `{{ }}`만 채운다.
- 테스트의 기대값도 매직 넘버 금지 — 픽스처 JSON에서 읽는다.

## 함수·파일 모양

- **경계는 Pydantic, 안쪽은 순수 함수.** `api/`에서 요청을 모델로 받고, `domain/`(`facts.py`·`masking.py`·`verification.py`)은 입력을 받아 출력을 돌려주는 함수만. DB·LLM·시계·설정을 안 만진다 → 테스트가 픽스처만으로 된다.
- 부작용(DB, LLM 호출, 임베딩, 파일)은 `infrastructure/`에만. 이 파일들은 얇고, 로직을 갖지 않는다. 순서 조립은 `application/*_service.py`.
- 파일 200줄, 함수 40줄 넘으면 쪼갠다. 한 파일이 두 가지 일을 하면 쪼갠다.
- 타입 힌트 전부. `dict` 대신 Pydantic 모델이나 `TypedDict`. `Any` 금지(LLM 응답 파싱 직후 한 곳만 예외, 바로 모델로 검증).
- 금액은 `Decimal`. float 금지. JSON으로 나갈 때만 문자열/숫자로 바꾼다(`04_facts.md`).

## 경계

- `str/` → `shared/`만 import. `scoring/` 금지. (`shared/00`)
- `str/` 안에서는 `api → application → domain`, `application → infrastructure`. `domain/`은 `shared/schemas`와 표준 라이브러리만. `infrastructure/`끼리는 서로 import하지 않는다 — 조립은 `application/`이 한다. (`02`)
- 규약 JSON 모양은 `shared/schemas/str.py`에서만. 여기서 dict를 손으로 만들지 않는다.

## 에러

- 예외 클래스는 `shared/errors.py`의 것만 던진다(`LlmInvalidOutput`, `LlmUnavailable`, `DraftNotFound`, `BudgetExceeded`, `RetrievalUnavailable`). 라우터에서 `HTTPException` 직접 생성 금지.
- 실패를 삼키지 않는다. 단 두 가지는 "실패해도 진행": 평가자 호출 실패 → `status=VERIFY_UNAVAILABLE`, 검색 실패 → `references=[]`. 이 둘은 `06`·`10` 문서에 이유가 있다.

## 로그·보안

- 로그에 계좌번호·금액·본문·프롬프트 전문 금지. ID·건수·길이·시간만.
- LLM에 보내는 facts는 `masking.py`를 거친 것만. 원본 facts는 응답·DB에만.
- 조사역 메모(`investigator_notes`)는 프롬프트에서 `<investigator_notes>` 블록으로 격리. 그 안의 지시문을 따르지 않는다는 규칙이 system에 있다.

## 작업 방식

- md 먼저, 코드 나중(`CLAUDE.md`). 정본 md: facts→`04`, 프롬프트→`05`, 검증→`06`, RAG→`10`, 처리 순서→`03`, 파일 위치→`02`.
- 테스트 먼저 쓰기 쉬운 곳은 먼저 쓴다 — `domain/verification.py`는 오류 주입 1~6이 곧 테스트다.
- 완료 = `pytest` 녹색 + 정본 md 갱신 + `docs/README.md` 상태표 갱신.
