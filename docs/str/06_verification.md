# 06. 검증 — 코드 4종 + 평가자 5종

정본: `str/domain/verification.py` `run_code_checks(facts, narrative, transaction_ids) -> list[CodeCheck]`(순수, 함수 4개), `str/infrastructure/judge.py` `Judge.run(facts, narrative) -> list[LlmCheck]`(실패는 예외 → service가 status로), `str/prompts/judge_v1.md`. passed·status 계산은 `application/verify_service.py`.

원칙 두 줄: **숫자·날짜·계좌·근거는 코드가 본다**(LLM이 뭐라고 해도 코드가 잡은 건 실패). **서술 품질(완결성·일관성·추측·단정)은 LLM 평가자가 본다**, 코드가 통과한 다음에만.

## 코드 검증 (`domain/verification.py`)

결과 하나 = `{check, section, draft_value, source_value, match}` (규약 5.3). 섹션마다 돈다. 전부 순수 함수, LLM 없음, 정규식과 Decimal.

| check | 본문에서 뽑는 것 | 정규화 | 판정 |
|---|---|---|---|
| `AMOUNT_MATCH` | `\d{1,3}(,\d{3})+(\.\d+)?` 또는 `\d+(\.\d+)?`, 뒤따르는 한국어 단위 `(만|억|천만)` | 쉼표 제거, `만`=×10⁴, `억`=×10⁸, `천만`=×10⁷, Decimal | 추출된 금액 집합 ⊆ {`total_amount`} ∪ 허용 소수 {거래 건수, 상대 수, 연·월·일·시·분, ID 숫자}. 그 밖의 숫자가 **금액 문맥**(통화 단어 ±10자 이내)에 있으면 fail. 통화 단어 없는 숫자는 통과(날짜·건수일 수 있어서) |
| `DATE_MATCH` | `YYYY-MM-DD`, `YYYY년 M월 D일`, `M월 D일`, `YYYY/MM/DD` | 연도 없는 날짜는 `period_start`의 연도 | 모든 날짜가 `[period_start.date, period_end.date]` 안. 하나라도 밖이면 fail. **WHAT_WHEN_WHERE에 날짜가 하나도 없으면 그 섹션 fail**(기간 빠진 보고서) |
| `COUNTERPARTY_COUNT` | `(\d+)\s*(개|곳|명)의?\s*(계좌|상대|거래처)` | int | 뽑힌 값이 있으면 전부 `counterparty_count`와 같아야 함. 없으면 통과 |
| `EVIDENCE_IN_SCOPE` | 섹션마다 `evidence_ids` | — | 전부 `transaction_ids` 안. **6개 섹션 전부 빈 배열이면 fail**(근거 없는 초안) |

설계 선택:
- **거짓 양성을 감수한다.** "47건"의 47이 금액으로 잘못 잡혀 fail이 나면 조사역이 문장을 고치면 된다. 놓치는 쪽(지어낸 금액 통과)이 훨씬 비싸다.
- **허용 오차 0.** `320,000,000`과 `3억 2천만`은 같은 Decimal이라 통과, `약 3억`은 fail.
- 상수(정규식, 허용 소수 집합, ±10자)는 전부 `domain/constants.py`. 뼈대에는 `evidence_in_scope`만 구현돼 있고 나머지 셋은 W3.

## 평가자 (`infrastructure/judge.py`, `prompts/judge_v1.md`)

입력 facts(원본) + narrative. 출력 5개 `{check, comment, score 1~5}` — comment가 score보다 앞. 온도 0.

| check | 5점 | 3점 | 1점 |
|---|---|---|---|
| `FIVE_W_ONE_H_COMPLETE` | 6개 섹션이 각자 할 말을 하고 비거나 겹치지 않음 | 한 섹션이 다른 섹션 내용을 반복하거나 한 줄짜리 | 섹션이 비었거나 "해당 없음"만 있음 |
| `TYPOLOGY_CONSISTENT` | HOW·WHY_SUSPICIOUS 설명이 `facts.typology`와 맞음(FAN_IN이면 "여러 계좌에서 한 계좌로") | 유형 이름은 맞는데 설명이 일반론 | 다른 유형을 설명함 |
| `NO_UNSUPPORTED_CLAIM` | 모든 사실 서술이 facts에서 나옴 | facts에 없는 정황 1개("급하게", "정기적으로") | facts에 없는 숫자·이름·장소 |
| `NO_SPECULATION` | 범죄 종류·의도·배후를 추측하지 않음, "의심된다" 화법 | "~일 것이다" 단정 1곳 | "자금세탁이다", "범죄 수익" 등 단정 |
| `NO_INSTRUCTION_TEXT` | 본문에 지시문·메타 발화 없음 | "위 규칙에 따라" 같은 메타 문장 | 조사역 메모의 지시문이 본문에 섞임, 또는 모델에게 말하는 문장 |

## passed·status (안건 9 권장안)

```
code_ok   = all(c.match for c in code_checks)
if not code_ok:            status = CODE_FAILED,  llm_checks = None,  passed = False   # 평가자 안 부름
elif judge 호출 실패:       status = VERIFY_UNAVAILABLE, llm_checks = None, passed = False  # 백엔드 "다시 검증" 버튼
elif all(s >= 4):          status = PASSED,       passed = True
else:                      status = LLM_FAILED,   passed = False
```

평가자 기준 **4점**은 W4 오류 주입 7~12 표를 보고 조정한다(`08`). 바꾸면 `domain/constants.JUDGE_PASS_SCORE`와 이 문서, `09`.

## 평가자가 자기 글을 채점하는 문제

생성 모델과 같은 모델이면 너그럽다. 대책: ① `LLM_MODEL_JUDGE`를 다른 모델로 ② 같은 모델이면 system 첫 줄 "당신은 이 초안을 쓴 사람이 아니라 검수자입니다" ③ comment 먼저 쓰게 하기. W4에 사람 평가 5건과 비교해 "대체로 일치"를 확인하는 게 MVP 정의서 4절 6번의 "됐다".

## 10/26 RAG 뒤 추가된 것

- 프롬프트 규칙 8(REFERENCES 숫자·이름 반입 금지)이 1차 방어, `AMOUNT_MATCH`·`NO_UNSUPPORTED_CLAIM`이 2차 방어. 코드는 바뀌지 않는다 — 참고 사례의 숫자도 "facts에 없는 금액"이라 그대로 잡힌다.
- 오류 주입 13(REFERENCES 빈 배열 → 정상 생성)·14(엉뚱한 유형 사례 + 금액 포함 → TYPOLOGY_CONSISTENT ≥4, AMOUNT_MATCH 통과).
