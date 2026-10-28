# 06. 검증 — 코드 검사 5종(유형별 대조) + 평가자 5종 (10/27 개정)

정본: `str/domain/verification.py` `run_code_checks(facts, narrative, evidence_scope) -> list[CodeCheck]`(순수), `str/infrastructure/judge.py` `Judge.run(facts_masked, narrative) -> list[LlmCheck]`(실패는 예외 → service가 status로), `str/prompts/judge_v1.md`, `shared/hashing.py`. passed·status 계산은 `application/verify_service.py`.

원칙 두 줄: **숫자·날짜·계좌·근거는 코드가 본다**(LLM이 뭐라고 해도 코드가 잡은 건 실패). **서술 품질(완결성·일관성·추측·단정)은 LLM 평가자가 본다**, 코드가 통과한 다음에만.

코드 검사가 하는 일의 경계 (규약 5.3 문구 그대로): **지원하는 표현에서 추출한 사실값을 해당 유형의 facts와 대조한다.** 추출 못 한 표현은 `match=false, reason=UNPARSED`로 드러낸다 — 조용히 통과시키지 않는다. 의미적 타당성("이 금액이 이 문장에 맞나")은 평가자·사람 몫. "본문의 모든 숫자를 검증한다"고 말하지 않는다(2차 검토 4번).

## 코드 검사 (`domain/verification.py`) — 유형별 대조

1차 검토 2번·5번 반영: 숫자를 "금액이냐 아니냐"로 나누던 것을 버리고, **본문에서 뽑은 값의 유형**(금액+통화, 날짜, 건수, 상대 수, 계좌 식별자)마다 facts의 **해당 유형 값**과만 대조한다. 결과 하나 = `{check, section, draft_value, source_value, match, reason}` (`reason`은 `match=false`일 때만: `MISMATCH` / `UNPARSED` / `OUT_OF_SCOPE` / `MISSING`). 섹션마다 돈다. 전부 순수 함수, LLM 없음, 정규식과 Decimal. 상수(정규식·단위·허용 집합)는 `domain/constants.py`.

| check | 본문에서 뽑는 것 (지원 표현) | 정규화 | 대조 대상 | 판정 |
|---|---|---|---|---|
| `AMOUNT_MATCH` | **금액+통화 쌍**: 숫자(`\d{1,3}(,\d{3})+(\.\d+)?` 또는 `\d+(\.\d+)?`, 한국어 단위 `만·억·천만` 허용) 뒤 ±10자 안에 통화 표기(`domain/constants.CURRENCY_ALIASES` — 코드마다 `USD`·`US Dollar`·`달러`·`$` 같은 표기 목록. facts의 `currency`는 코드, `str/04`) | 쉼표 제거, 단위 ×10⁴/×10⁸/×10⁷, Decimal | `inbound.amount.{currency}`, `outbound.amount.{currency}` 중 **같은 통화**의 `total` | 값과 통화가 둘 다 맞으면 match. 통화는 맞는데 값이 다르면 `MISMATCH`, 통화가 facts에 없으면 `MISMATCH`, 숫자 뒤에 통화 단어가 있는데 숫자를 못 읽으면(`삼억`, `약 3억`) `UNPARSED`. **통화 없는 숫자는 금액으로 보지 않는다**(건수·날짜일 수 있어서 — 다른 check가 본다) |
| `DATE_MATCH` | `YYYY-MM-DD`, `YYYY년 M월 D일`, `M월 D일`, `YYYY/MM/DD`, `YYYY.M.D` | 연도 없는 날짜는 `period.start`의 연도 | 날짜마다 **용도를 먼저 정한다**: 개설 단어(`개설`·`가입`·`신규`·`거래 시작` — `ONBOARD_WORDS`)는 **±10자(`DATE_CONTEXT_WINDOW`) 안에서 가장 가까운 날짜 하나에만** 붙는다 — 그 날짜는 **개설일** → `customer.onboarded_at`, 나머지는 **거래 날짜** → `[period.start.date, period.end.date]` | 용도별 대상과만 대조한다(합집합 아님). 개설일이 onboarded_at과 다르거나 거래 날짜가 기간 밖이면 `MISMATCH` — 개설일을 거래 날짜처럼 쓰면 기간 밖이라 잡힌다. `customer`가 null인데 개설일 표현이 있으면 `MISMATCH`. **애매하면 `UNPARSED`** — 추측해서 고르지 않는다: ① 두 날짜를 잇는 **범위 표현**(`A와 B 사이`, `A~B`, `A부터 B까지`)에 개설 단어가 걸린 경우("2021년 3월 14일과 2022년 9월 2일 사이 개설") ② 개설 단어에서 앞뒤 두 날짜까지 글자 거리가 같은 경우. 개설 단어가 없는 범위 표현("9월 2일부터 9월 10일까지 47건")은 평소대로 둘 다 거래 날짜. 한 문장에 개설일·거래 날짜가 같이 있는 경우("2021년 3월 14일 개설, 2022년 9월 2일 47건")는 가장 가까운 쪽 규칙으로 갈린다(오류 주입 21). 날짜 형태인데 못 읽으면(`9월 초`) `UNPARSED`. **WHAT_WHEN_WHERE에 거래 날짜가 하나도 없으면 그 섹션 `MISSING`**(기간 빠진 보고서) |
| `COUNT_MATCH` | 숫자마다 **종류를 먼저 정한다**(10/29 최종 점검 — 모든 건수를 한 집합에 넣으면 "과거 경보 3건"이 거래 건수와 대조돼 오탐, 반대로 종류가 다른 숫자가 우연히 같으면 틀린 문장이 통과). ① **과거 경보**: `(과거|이전|앞서)\s*경보` 뒤 `(\d+)\s*(건|회)` (`PRIOR_ALERT_WORDS`) ② **모델 관측값**: `관측`·`모델` (`OBSERVATION_WORDS`, 05 규칙 11 표기) ③ **경로 수**: `(\d+)\s*개의?\s*(경로|고리|순환)` ④ **상대 수**: `(\d+)\s*(개|곳|명)의?\s*(계좌|상대|거래처|송금인|수취인)` 또는 단어가 앞에 오는 `(계좌|상대|거래처|송금인|수취인)\s*(\d+)\s*(개|곳|명)`("상대 31개") ⑤ 그 밖의 `(\d+)\s*건`·`(\d+)\s*회` → **거래 건수**. **문맥 범위 = 숫자가 들어 있는 절**(문장을 `,`·`.`·`;`·줄바꿈으로 나눈 조각, `COUNT_CLAUSE_SPLIT`). 단 **숫자 안의 천 단위 쉼표·소수점은 구분자가 아니다** — 양옆이 숫자인 `,`·`.`(`1,000`, `3.5`)는 자르지 않고, 숫자는 `\d{1,3}(,\d{3})+|\d+`로 쉼표째 읽는다 — 그 절 안의 종류 단어만 그 숫자에 붙는다. 날짜용 ±10자 창은 쓰지 않는다("모델 관측값(24시간 기준) 31개 상대"처럼 단어와 숫자가 10자 넘게 떨어질 수 있음). 거래 건수는 같은 절의 **방향 단어**로 집합을 한 번 더 좁힌다: `입금`·`받은`·`수취` → 입금 집합, `출금`·`보낸`·`송금` → 출금 집합, `법인 내`·`내부` → `internal.count`, 방향 단어 없음 → 거래 건수 전체 집합 (`DIRECTION_WORDS`) | int | 종류별로 **자기 집합하고만**: 과거 경보 ↔ {`prior_alert_count`} · 모델 관측값 ↔ {같은 단위의 `observations[].value`} · 경로 수 ↔ {`paths.count`\*} · 상대 수 ↔ {`counterparties.count`, `paths.max_accounts`\*} · 거래 건수 ↔ 입금 {`inbound.count`, `inbound.by_currency[].count`} · 출금 {`outbound.count`, `outbound.by_currency[].count`} · 내부 {`internal.count`} · 방향 없음 {위 전부, `inbound+outbound`, `paths.max_hops`\*}. \* = `paths.status = VERIFIED`일 때만(`str/04` "경로") — 확인 안 된 경로의 숫자("3개 계좌를 거쳐", "순환 경로 2개")는 맞출 값이 없어 `MISMATCH` | 뽑힌 값이 **그 종류의** 집합에 있으면 match, 없으면 `MISMATCH`. 숫자 표현이 없으면 검사 없음. **종류를 정할 수 없으면 `UNPARSED`**(예: 과거 경보 단어와 관측 단어가 같이 걸림) — 추측해서 아무 집합에나 맞추지 않는다. **한글 수사 + 단위**(`두`~`아홉`, `열`~`아흔` 조합 + `건·회·개·곳·명` — `KOREAN_NUMERAL_COUNT`)는 읽지 않고 `UNPARSED`(예: `서른한 개 계좌`). `한`(1)은 "한 계좌로", "한 곳에" 같은 관용 표현이 많아 감지에서 뺀다. 정상 문장 오탐 테스트(`08` 단위): "과거 경보 3건"(prior 3, 거래 건수에 3 없음) → match · "모델 관측값(24시간 기준) 31개 상대"(관측 31, 근거 상대 수 12) → match · "모델 관측 상대 31개, 입금 47건"(관측 31, inbound 47) → 둘 다 match(47건은 쉼표 뒤 절이라 관측값이 아님) · "출금 2건"(outbound USD 2건) → match · "입금 1,000건"(inbound 1000) → match(천 단위 쉼표에서 절이 갈리지 않음). 잡아야 하는 것: "과거 경보 47건"(prior 1, inbound 47) → `MISMATCH` · "입금 3건"(inbound 47, outbound 3) → `MISMATCH`(방향이 다른 숫자). 방향·종류를 코드가 정하지 못한 문장은 `UNPARSED` — `match=false`라 **코드 검사 실패(`CODE_FAILED`)로 표시되고 평가자는 부르지 않는다**(`03` 4단계). 조사역이 그 문장을 숫자·단어가 분명한 형태로 고친 뒤 다시 검증한다 |
| `ACCOUNT_ID_MATCH` | 계좌 식별자 표현: `\d{3}_[0-9A-F*]{9}`, `\*{4}[0-9A-F]{4}`, `끝자리 ([0-9A-F]{4})` | 마스킹 형태(`****BD30`)와 원본 끝 4자리를 같은 것으로 | `subject.account_key` 끝 4자리 | 대상 계좌만 통과. 그 밖의 계좌 식별자(상대 계좌 — facts에 없음)가 본문에 있으면 `MISMATCH` — 상대 계좌번호를 본문에 쓰지 않는 게 규칙 |
| `EVIDENCE_IN_SCOPE` | 섹션마다 `cites`·`evidence_ids` | — | `cites ⊆ fact_keys(facts)`, `evidence_ids ⊆ evidence_scope`(요청의 `evidence_transaction_ids`) | 하나라도 밖이면 `OUT_OF_SCOPE`. **6개 섹션 전부 cites가 비면 `MISSING`**(근거 없는 초안). 생성본은 코드가 만들어 늘 통과하고, **조사역 수정본**(백엔드가 보낸 narrative)에서 의미가 있다 |

설계 선택:
- **거짓 양성을 감수한다.** 못 읽은 표현을 `UNPARSED`로 떨어뜨리면 조사역이 문장을 숫자 형태로 고치면 된다. 놓치는 쪽(지어낸 금액 통과)이 훨씬 비싸다.
- **허용 오차 0.** `320,000,000 US Dollar`와 `3억 2천만 US Dollar`는 같은 Decimal이라 통과, `약 3억 US Dollar`은 `UNPARSED`.
- 뽑는 표현이 늘면(`천만 원` 등) 표에 한 줄 추가 + 테스트 한 줄. 표에 없는 표현은 "지원 안 함"이고 그걸 숨기지 않는다.
- **감지 못 하는 표현은 코드 검사 범위 밖이다.** 숫자도 한글 수사 패턴도 아닌 것(`수십 개`, `열댓 건`, `대부분`, `한 주 동안`)은 코드가 보지 않는다 → `NO_UNSUPPORTED_CLAIM` 평가자와 조사역·승인자 몫. 위 경계 문구("지원하는 표현에서 추출한…")가 이 뜻이다.
- 뼈대에는 `evidence_in_scope`만 있다. 다섯 개 전부 W3(README 상태표).

## 평가자 (`infrastructure/judge.py`, `prompts/judge_v1.md`)

입력 **마스킹한 facts** + narrative(`text`만). 출력 5개 `{check, comment, score 1~5}` — comment가 score보다 앞. 온도 0. 통과선이 4점이므로 **4점의 뜻을 적는다**(2차 검토 반영 — 기준 없는 4점은 5와 3 사이 임의값이 된다).

| check | 5 | **4 (통과선)** | 3 | 1 |
|---|---|---|---|---|
| `FIVE_W_ONE_H_COMPLETE` | 6개 섹션이 각자 할 말을 하고 비거나 겹치지 않음 | 한 섹션이 짧거나(1문장) 다른 섹션 내용을 한 문장 반복 — 정보는 빠지지 않음 | 한 섹션이 다른 섹션을 대부분 반복, 또는 기간·금액·상대 중 하나가 어디에도 없음 | 섹션이 비었거나 "해당 없음"만 있음 |
| `TYPOLOGY_CONSISTENT` | HOW·WHY_SUSPICIOUS 설명이 `facts.typology`와 맞음(FAN_IN이면 "여러 계좌에서 한 계좌로") | 유형과 맞되 설명이 facts 숫자를 안 쓰고 일반적임 | 유형 이름은 맞는데 설명이 다른 유형에도 통하는 일반론 | 다른 유형을 설명함 |
| `NO_UNSUPPORTED_CLAIM` | 모든 사실 서술이 facts에서 나옴 | facts에서 바로 따라오는 완곡한 표현 1곳("짧은 시간에 집중") — 새 사실은 없음 | facts에 없는 정황 1개("급하게", "정기적으로") | facts에 없는 숫자·이름·장소 |
| `NO_SPECULATION` | 범죄 종류·의도·배후를 추측하지 않음, "의심된다" 화법 | "~로 보인다"를 넘는 표현 1곳이나 유형 설명 안에서 그침("구조화 거래로 보임") | "~일 것이다" 단정 1곳, 또는 의도 추측 1곳 | "자금세탁이다", "범죄 수익" 등 단정, 범죄 종류 지정 |
| `NO_INSTRUCTION_TEXT` | 본문에 지시문·메타 발화 없음 | 보고서 관용구 수준의 메타 표현 1곳("본 보고서는") | "위 규칙에 따라" 같은 모델 메타 문장 | 조사역 메모의 지시문이 본문에 섞임, 또는 모델에게 말하는 문장 |

## passed·status (안건 9 확정)

```
code_ok   = all(c.match for c in code_checks)
if not code_ok:            status = CODE_FAILED,        llm_checks = None, passed = False   # 평가자 안 부름
elif judge 호출 실패:       status = VERIFY_UNAVAILABLE, llm_checks = None, passed = False   # 백엔드 "다시 검증" 버튼, 한 줄 저장
elif all(s >= 4):          status = PASSED,             passed = True
else:                      status = LLM_FAILED,         passed = False
```

평가자 기준 **4점**은 W4 오류 주입 7~12 표를 보고 조정한다(`08`). 바꾸면 `domain/constants.JUDGE_PASS_SCORE`와 이 문서, `09`.

## 본문 해시 (`shared/hashing.py`)

검증 응답의 `narrative_sha256`. 규칙은 `shared/01`(섹션 고정 순서, section·text만, NFC, 공백 없는 JSON, sha256 hex). 백엔드 `ApprovalGate`는 `generation_id` 일치 + 본문 해시 일치 + `passed` 세 조건일 때만 승인 요청 허용(`str/03`) — 해시만 같으면 다른 생성본(다른 facts)의 검증이 통할 수 있다. 테스트 벡터 `contracts/examples/narrative_hash.json`을 Python이 만들고 Java가 맞춘다(W3).

## 평가자가 자기 글을 채점하는 문제

생성 모델과 같은 모델이면 너그럽다. 대책: ① `LLM_MODEL_JUDGE`를 다른 모델로 ② 같은 모델이면 system 첫 줄 "당신은 이 초안을 쓴 사람이 아니라 검수자입니다" ③ comment 먼저 쓰게 하기. W4에 사람 평가 5건과 비교해 "대체로 일치"를 확인하는 게 MVP 정의서 4절 6번의 "됐다".

## 수정본의 cites·evidence_ids — (a) 확정 (안건 23 세부, 채영 "반영 가능", 10/28 문서 반영)

조사역이 본문을 고치면 생성 때의 `cites`는 더 맞지 않을 수 있다. 그래서 검증할 때 근거를 **다시 계산해 돌려준다**.

1. 평가자 `judge_v2`가 루브릭 5개와 함께 섹션별 `cites`(검사한 본문이 실제로 쓴 fact 키)를 낸다(`05`).
2. 코드가 `FACT_KEYS` 밖 키를 버리고 `attach_evidence(cites, facts)`로 `evidence_ids`를 만든다 — 생성 때와 같은 함수.
3. 검증 응답 `narrative_refs: [{section, cites, evidence_ids}]`(6개)에 담는다. 평가자를 안 돌린 경우(`CODE_FAILED` — 코드 검사에서 멈춤, `VERIFY_UNAVAILABLE` — 평가자 호출 실패)는 `null`.
4. 백엔드(채영)는 `narrative_refs`가 오면 그 값을 수정본 저장에 반영하고, `null`이면 기존 값을 유지한다. 조사역은 문장만 고치고 근거 번호는 서버가 관리한다.

본문 해시는 section·text만 보므로 `cites`가 바뀌어도 `ApprovalGate`에는 영향이 없다. `EVIDENCE_IN_SCOPE` 코드 검사는 그대로 요청에 담긴 수정본의 `cites`·`evidence_ids`를 본다(재계산 전 값). 테스트: 재계산 결과가 범위 안인지, 목록 밖 키가 버려지는지, `CODE_FAILED`면 `null`인지(`08` 단위).

## RAG와의 관계

프롬프트 규칙 8(REFERENCES 숫자·이름 반입 금지)이 1차 방어, `AMOUNT_MATCH`·`DATE_MATCH`·`NO_UNSUPPORTED_CLAIM`이 2차 방어. 코드는 바뀌지 않는다 — 참고 사례의 금액도 "facts에 없는 통화·금액"이라 그대로 잡힌다. 오류 주입 13·14.
