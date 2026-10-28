# 04. facts — 정본 JSON과 계산 규칙 (규약 v0.2, 10/27)

정본: `str/domain/facts.py` `build_facts(req, txs, subject) -> Facts`, `attach_evidence(narrative, facts)`, `fact_keys(facts)`, `str/domain/masking.py` `mask_for_llm(facts) -> Facts`, `shared/schemas/str.py` `Facts`. 입력 dataclass(`Transaction`, `Subject`)는 `str/domain/models.py`, 읽기는 `str/infrastructure/transaction_reader.py`.

**순수 함수.** 같은 입력에 항상 같은 facts. LLM은 facts만 보고 쓰고, 검증은 facts와 대조한다 — facts가 틀리면 전부 틀리므로 여기 규칙이 제일 촘촘하다.

10/27에 바뀐 것 — 1차 검토 지적 반영: ① "기준 통화 1개 + 총액" → **대상 계좌 관점 `inbound/outbound/internal`, 통화별 집계, 환산 없음**. ② `top_reasons` 문자열(SHAP 값을 관측값처럼 쓰던 것) → **`observations[]`(관측값) + `model_signals[]`(이름만)** 분리. ③ 각 집계에 `transaction_ids`를 붙이고 **fact 키 → 거래 ID**를 코드가 연결. ④ 뼈대 `facts.py`는 전부 다시 쓴다(W2 수).

10/28에 바뀐 것 — 준혁 답(경로형 경보): ⑤ 대상 계좌가 안 낀 거래 묶음 `path` → **`indirect`**로 이름 변경(새 `paths`와 헷갈리지 않게). ⑥ R04_CYCLE·R05_STACK 경보가 주는 `rule_facts.paths`(경로별 거래 ID, 시간순)를 AI가 **확인만** 해서 **`paths`** fact로. 확인되면 인용 가능, 아니면 인용·LLM 전달 없음(아래 "경로" 절).

## 정본 JSON (응답 `facts`와 같다, 규약 5.2)

```json
{
  "reporting_institution": "Portugal Bank #4507",
  "subject": { "entity_id": "80062E240", "entity_name": "Sole Proprietorship #50438", "account_key": "010_8000EBD30" },
  "period": { "start": "2022-09-02T00:14:00", "end": "2022-09-02T22:51:00" },
  "inbound":  { "count": 47, "by_currency": [ { "currency": "USD", "total": "320000000.00", "count": 47, "transaction_ids": [104221, 104233, 104301] } ], "transaction_ids": [104221, 104233, 104301] },
  "outbound": { "count": 0,  "by_currency": [], "transaction_ids": [] },
  "internal": { "count": 0,  "transaction_ids": [] },
  "indirect": { "count": 0,  "transaction_ids": [] },
  "paths":    null,
  "excluded_self_transfer_count": 0,
  "direction": "INBOUND",
  "counterparties": { "count": 31, "transaction_ids": [104221, 104233, 104301] },
  "payment_formats": ["ACH"],
  "typology": "FAN_IN",
  "typology_source": "RULE",
  "customer": { "industry": "RETAIL", "risk_level": "LOW", "account_purpose": "SALES_DEPOSIT", "onboarded_at": "2021-03-14", "country_code": "PT" },
  "prior_alert_count": 1,
  "observations": [ { "name": "account_in_counterparties_24h", "value": 31, "unit": "count", "window_start": "2022-09-02T00:00:00", "window_end": "2022-09-03T00:00:00", "basis": "distinct_inbound_counterparties", "baseline": null } ],
  "model_signals": ["distinct_senders_24h", "outflow_ratio_2h"]
}
```

예시의 `transaction_ids`는 **축약**이다 — 입금 47건이면 실제로는 ID 47개. 계약 예시(`contracts/examples/`)·테스트 픽스처로 옮길 때는 건수와 ID 개수를 맞춘다.

## 계산 규칙 (코드가 전부 정한다)

대상 계좌 `S` = `alert.account_key` **하나**(규약 2절: 경보 단위는 계좌). 대상 거래 `T` = `evidence_transaction_ids`로 읽은 행. 규약 5.1에서 이 목록은 **`alert.transaction_ids` 전체**다 — 점수 응답의 `evidence_transaction_ids`(SHAP 근거 부분집합)로 계산하면 건수·금액이 경보와 달라지므로 쓰지 않는다(그건 화면 표시용).

| 필드 | 규칙 |
|---|---|
| `subject` | `S`와 `accounts.entity_id` → `entities`. 이름 없으면 `entity_name: null` |
| 제외 | `is_self_transfer = true`(from = to = S) 행은 **모든 집계에서 제외**, 건수만 `excluded_self_transfer_count`. 제외 후 남은 거래가 **0건**(self-transfer만)이면 facts를 만들지 않고 400 `INVALID_REQUEST`("no reportable transactions") — 기간·금액이 전부 비는 초안은 쓸 게 없다(가정, 축소본 확인) |
| `inbound` | `to_account_key = S`인 행. 금액은 **받은 쪽** `amount_received`·`currency_received`. `by_currency`는 통화별 `{currency, total, count, transaction_ids}`, 통화 코드 정렬. 바깥 `transaction_ids`는 그 행 전부, 항목 안 `transaction_ids`는 그 통화 행만 |
| `outbound` | `from_account_key = S`인 행. 금액은 **보낸 쪽** `amount_paid`·`currency_paid` |
| `internal` | **S가 낀 거래** 중 상대 계좌의 `entity_id`가 S의 `entity_id`와 같은 것(S의 법인이 가진 다른 계좌와의 이동). S 없이 같은 법인 계좌끼리 오간 거래는 `indirect`. S의 `entity_id`가 없으면 internal 0건. inbound/outbound에 **넣지 않는다**. 금액 집계 없음(법인 안 이동이라 "입금"도 "출금"도 아님) — 건수와 ID만 |
| `indirect` | **대상 계좌가 직접 참여하지 않은 경보 거래**(S가 from·to 어디에도 없음). 예: R04_CYCLE A→B→C→A, 대상 A일 때 B→C. `count`와 `transaction_ids`만 남긴다 — 버리지도 400으로 막지도 않고, 대상 계좌 관점 집계(inbound/outbound/counterparties/direction)에는 **섞지 않는다**. 금액 집계 없음. 인용 키 없음, LLM에 보내지 않음(마스킹에서 제거). 쓰임은 `period` 계산과 근거 범위뿐. **이 거래들이 어떤 순서로 이어진 경로인지는 여기서 다루지 않는다** — 그건 `paths`(아래 "경로" 절). (10/27 이름 `path`, 10/28 `indirect`로 변경) |
| `paths` | `alert.rule_facts.paths`가 있을 때만. 확인 규칙·값은 아래 "경로" 절. 없거나 빈 배열이면 `null` |
| `by_currency[].total` | Decimal 합, **문자열**, 소수 2자리 고정, 천 단위 구분 없음. 통화 간 **환산 없음**. (0절 "금액은 숫자"의 유일한 예외 — LLM·백엔드가 다르게 반올림하지 않도록) |
| `currency` | ISO 4217 코드(`USD`, `EUR`, …). IBM 원천은 이름(`US Dollar`, `Euro`, …)이라 **`transaction_reader`가 읽을 때** 고정 표 `domain/constants.CURRENCY_CODES`로 바꾼다 — domain은 코드만 본다. HI-Small 15종(가정, 축소본 만들 때 `SELECT DISTINCT`로 확인): US Dollar→USD, Euro→EUR, Yuan→CNY, Shekel→ILS, Canadian Dollar→CAD, UK Pound→GBP, Ruble→RUB, Australian Dollar→AUD, Swiss Franc→CHF, Yen→JPY, Mexican Peso→MXN, Rupee→INR, Brazil Real→BRL, Saudi Riyal→SAR, **Bitcoin→BTC**(ISO 4217에 없음 — 규약 0절 예외). **표에 없는 이름은 `UnknownCurrency`(500)** — 원문을 그대로 흘리면 검증의 통화 대조가 깨진다 |
| `direction` | `inbound.count ≥ 2 × outbound.count` → `INBOUND`, 반대 → `OUTBOUND`, 그 밖 → `MIXED`. 둘 다 0이면(internal만) `INTERNAL` |
| `period` | 제외 후 대상 거래 `ts`의 min / max(**indirect 포함** — 경로 전체가 일어난 기간). ISO 8601 초 단위. 룰 창이 아니라 **실제 거래 범위** |
| `counterparties` | 상대 `account_key` distinct 수(internal 제외). `transaction_ids` = inbound ∪ outbound |
| `payment_formats` | distinct, 원본 문자열 그대로(ACH, Wire, Cash, …), 정렬 |
| `typology` / `typology_source` | 요청 `alert.typology_hint` 그대로. `typology_source`는 `RULE` 고정(안건 8) |
| `customer` | `customer_attributes` 행. 없으면 `null`. `onboarded_at`은 날짜(검증 `DATE_MATCH`가 "개설일"로 허용) |
| `prior_alert_count` | 요청 그대로. 내용은 오지도 않는다 |
| `observations[]` | 요청 `reasons`(안건 3 확정 구조)에서 **관측값만**: `{name, value, unit, window_start, window_end, basis, baseline}` ← `reasons[].name`, `observation.*`, `baseline.value`. `observation.value`가 `null`인 항목은 넣지 않는다. `contribution`(기여값·방법·척도)은 **넣지 않는다**. 관측 기간이 경보 창보다 넓어도 쓸 수 있지만 근거 거래는 붙이지 않고(인용 키 → `evidence_ids` 없음), 본문에는 "모델 관측값(24시간 기준)"처럼 기간을 밝혀 쓴다(05 규칙 11, 10/28 준영). `context_transaction_ids`는 facts에 넣지 않는다 |
| `model_signals[]` | 요청 `reasons` 상위 3개의 피처 **이름만**. "모델이 주목한 점" 한 줄의 재료. 숫자 없음 |
| 없는 값 | `null`. LLM에는 "확인되지 않음"으로 전달, 모르는 걸 지어내지 말라는 규칙(05)이 받는다 |

### 결정 사항 (바꾸려면 `09_decisions.md`에 적고)

- 통화별 집계, 환산 없음. "총액 1개"는 버림 — 15종 통화가 섞인 데이터에서 기준 통화 하나는 사실을 지운다(1차 검토 1번).
- 받은 돈은 `amount_received`, 보낸 돈은 `amount_paid`. IBM 원본에서 둘이 다른 건 환전 거래라 대상 계좌 관점에서 실제 움직인 쪽을 쓴다.
- 허용 오차 0. `"320,000,000"`과 `"3억 2천만"`은 같은 Decimal이라 통과, `"약 3억"`은 fail(06).
- 거래 행 원본은 LLM에 안 준다. facts 요약만. 거래 ID 목록도 안 준다(아래 fact 키).
- `direction` 2배 규칙은 진희 가정값 — 축소본 경보로 분포를 본 뒤(W2) 바꿀 수 있다. 축소본에서 볼 경계: 입금만 · 출금만 · 정확히 2:1(`≥`라 `INBOUND`) · internal만(`INTERNAL`) · self-transfer만(위 0건 → 400).
- 통화는 코드로(`USD`). 원천 이름 → 코드 변환은 로더 한 곳, 본문 표기(`달러`, `US Dollar`, `$`) 인식은 검증의 `CURRENCY_ALIASES`(06).
- 경로는 detection이 준 순서 그대로 **확인만** 한다. 하나라도 어긋나면 전체 `UNVERIFIED` — AI가 경로를 다시 정렬하거나 이어 붙이지 않는다(10/28).

## 경로 (`paths`) — 경로형 경보 R04·R05 (10/28 준혁 답)

입력은 `alert.rule_facts.paths`(규약 2절): **거래 ID 배열의 배열**. 배열 하나가 경로 하나이고, 안의 ID는 **시간순**. `alert.transaction_ids`는 그대로 전체 근거 목록(경로 거래 포함). 준혁 확정 사항:

- R04_CYCLE: 대상 계좌 = 고리의 **시간상 첫 거래 송금 계좌**. 같은 룰·계좌·시간창의 고리 여러 개는 경보 하나로 묶이고, **묶인 고리에는 모두 대상 계좌가 있다**. 최대 3홉.
- R05_STACK: 대상 계좌 = 경로의 **시작 계좌**(A→B→C→D면 A).
- **홉 = 경로의 거래 개수.** A→B→C→A는 3홉(마지막 복귀 거래 포함). 룰의 최대 홉은 detection 기준이라 AI는 길이를 제한하지 않고 값만 보고한다.

```json
"paths": { "kind": "CYCLE", "status": "VERIFIED", "count": 2, "max_hops": 3, "max_accounts": 3, "transaction_ids": [101, 102, 103, 201, 202, 203] }
```

**확인 규칙** (`build_facts` 안, 순수 함수 — 거래 행은 이미 읽어 둔 것)

| # | 확인 | 어기면 |
|---|---|---|
| 1 | 경로의 모든 ID ∈ `alert.transaction_ids` | 400 `INVALID_REQUEST`("paths id not in transaction_ids") — 요청 안의 두 목록이 어긋난 것(위 "범위 확인"과 같은 성격) |
| 2 | `kind` = `rule_id`로 정한다: `R04_CYCLE` → `CYCLE`, `R05_STACK` → `STACK` | 그 밖 룰에 `paths`가 오면 `kind: null`, `UNVERIFIED` |
| 3 | 경로마다 거래 2개 이상, 경로 안 ID 중복 없음, self-transfer 없음 | `UNVERIFIED` |
| 4 | 시간순: 앞 거래 `ts` ≤ 다음 거래 `ts`(같은 분 허용) | `UNVERIFIED` |
| 5 | 연결: 앞 거래 `to_account_key` = 다음 거래 `from_account_key` | `UNVERIFIED` |
| 6 | 시작: 첫 거래 `from_account_key` = S | `UNVERIFIED` |
| 7 | CYCLE이면 닫힘: 마지막 거래 `to_account_key` = S | `UNVERIFIED` |

- **전부 통과해야 `VERIFIED`**, 한 경로라도 어긋나면 전체 `UNVERIFIED` — 경로 일부만 골라 쓰는 문장이 나오지 않게. 어긋난 이유(경로 번호·규칙 번호)는 `generations` 내부 기록에만, facts에는 `status`만.
- 배열 순서를 **그대로** 확인한다. 순서가 틀리면 고쳐 주지 않고 `UNVERIFIED` — 순서를 추측하지 않는다(준혁님께 말한 "모르면 미확인으로 두고 보고서에 안 쓴다").
- 값: `count` = 경로 수, `max_hops` = 가장 긴 경로의 거래 수, `max_accounts` = 경로 하나에 나오는 서로 다른 계좌 수의 최대(CYCLE A→B→C→A = 3, STACK A→B→C→D = 4), `transaction_ids` = 모든 경로 ID 합집합. `UNVERIFIED`여도 응답 facts에는 남긴다(감사·디버깅용).
- `period`·`indirect`는 그대로 — 경로 ID는 이미 `alert.transaction_ids` 안이라 기간에 들어가 있다.

## fact 키 — LLM이 인용하고 코드가 거래 ID로 바꾼다

LLM은 섹션마다 `cites`에 **fact 키**를 쓴다(05). 코드 `attach_evidence`가 키마다 정해진 `transaction_ids`를 합쳐 `evidence_ids`로 만든다. LLM이 거래 ID를 직접 고르지 않는다 — 고르게 하면 EVIDENCE_IDS 목록에서 아무 ID나 옮겨 적는다(1차 검토 4번).

| 키 (`fact_keys(facts)`가 만든다) | 가리키는 값 | → `evidence_ids` |
|---|---|---|
| `subject`, `subject.entity_name`, `subject.account_key` | 대상 | 없음 |
| `period` | 기간 | inbound ∪ outbound ∪ internal ∪ indirect |
| `inbound.count` | 입금 건수 | `inbound.transaction_ids` |
| `inbound.amount.{currency}` (통화 코드별 1개씩, 예 `inbound.amount.USD`) | 그 통화 입금 합계 | **그 통화 항목의** `by_currency[].transaction_ids`만 — 달러 합계에 유로 거래가 붙지 않게 |
| `outbound.count` | 출금 건수 | `outbound.transaction_ids` |
| `outbound.amount.{currency}` | 그 통화 출금 합계 | 그 통화 항목의 `by_currency[].transaction_ids`만 |
| `internal.count` | 법인 내 이동 | `internal.transaction_ids` |
| `counterparties.count` | 상대 수 | `counterparties.transaction_ids` |
| `direction`, `payment_formats`, `typology` | 패턴 | inbound ∪ outbound |
| `customer.industry`, `customer.risk_level`, `customer.account_purpose`, `customer.onboarded_at`, `customer.country_code` | 고객 | 없음 |
| `prior_alert_count` | 과거 경보 수 | 없음 |
| `observations.{name}` | 관측값 1개 | 없음 (거래가 아니라 피처) |
| `model_signals` | 모델 주목 피처 이름들 | 없음 |
| `paths.count`, `paths.max_hops`, `paths.max_accounts`, `paths.kind` | 경로 수·가장 긴 경로의 거래 수·거친 계좌 수·유형 — **`paths.status = VERIFIED`일 때만 키가 생긴다** | `paths.transaction_ids` |

- 존재하는 키 목록을 프롬프트 `FACT_KEYS`에 그대로 넣는다. 목록 밖 키는 `NarrativeOut` 검증에서 걸러 재생성(05).
- `null`인 fact(예: `customer`가 없음)의 키는 목록에 **넣지 않는다** — 인용할 게 없다.
- 섹션의 cites가 전부 "없음" 키(subject·customer)뿐이면 `evidence_ids = []`. CONCLUSION은 보통 `[]`.

## 마스킹 (`masking.py`) — 생성·평가자 공용

LLM에 가는 facts만 바꾼다(생성기와 평가자 **둘 다** 마스킹본 — 평가자는 숫자 대조를 안 하므로 원본이 필요 없다, 1차 검토 반영). 응답·DB·코드 검증은 원본.

| 필드 | 처리 |
|---|---|
| `subject.account_key` | 뒤 4자리만 (`010_****BD30`) |
| `reporting_institution` (은행명) | 그대로 |
| `subject.entity_name` (고객명) | 그대로 — IBM 합성 데이터라 실명이 아님. 실데이터 전환 시 여기서 가명화(MVP 정의서 8절 "한계" 4번) |
| `subject.entity_id` | 그대로 (합성) |
| `*.transaction_ids` | **제거** — LLM은 거래 ID를 보지 않는다 |
| `indirect` | **통째로 제거** — 인용 키가 없는 사실을 LLM이 문장에 쓰면 검증이 대조할 곳이 없다 |
| `paths` | `VERIFIED`면 `{kind, count, max_hops, max_accounts}`만 남기고 ID·`status` 제거. `UNVERIFIED`·`null`이면 **통째로 제거** — LLM은 확인된 경로만 본다 |
| 그 밖 | 그대로 |

마스킹은 **검증에 영향이 없다** — 코드 검증은 원본 facts와 narrative를 대조하고, narrative에는 계좌가 뒤 4자리로만 나오므로 `ACCOUNT_ID_MATCH`는 마스킹 표현(`****BD30`)과 원본 끝 4자리를 같은 것으로 본다(06).

## 코드 위치 (10/28 SCRUM-13)

| 파일 | 하는 일 |
|---|---|
| `domain/facts.py` | `build_facts` — 위 계산 규칙 표. `request_problem`(요청 안 목록 확인)·`has_reportable`(self-transfer만인지)·`currency_code` |
| `domain/fact_paths.py` | `paths_problem`(경로 규칙 1) · `build_paths`(규칙 2~7 → `VERIFIED`/`UNVERIFIED`) |
| `domain/fact_keys.py` | `fact_keys`(아래 표) · `attach_evidence`(cites → evidence_ids) |
| `infrastructure/transaction_reader.py` | `load_transactions`(통화 이름 → 코드, 없는 ID 400) · `load_subject`(대상 + 관련 계좌들의 `entity_id`) |

400 판정은 **domain 순수 함수가 메시지를 돌려주고 `application/draft_service`가 `InvalidRequest`로 올린다** — 라우터는 스키마만 본다. 순서: `request_problem`(DB 전) → `load_transactions` → `has_reportable` → `load_subject` → `build_facts`.

## 입력 (transaction_reader)

- `transactions`: 요청 `evidence_transaction_ids`로 `ops.transactions` 1 쿼리. 컬럼 `transaction_id, ts, from_account_key, to_account_key, amount_paid, currency_paid, amount_received, currency_received, payment_format, is_self_transfer`. `is_laundering`·`pattern_*` 컬럼은 **SELECT 목록에 없다** — 정답 라벨이 서빙에 새면 안 된다.
- **범위 확인**: 요청 `evidence_transaction_ids`가 요청 `alert.transaction_ids`와 **집합으로 같아야** 한다(규약 5.1 "목록 전체"). 다르면 400 `INVALID_REQUEST`("evidence must equal alert.transaction_ids") — 요청 안의 두 목록이 어긋난 경우를 막는다. `alert.transaction_ids` **자체에** 무관한 거래가 묶였는지는 증명하지 못한다 — 경보의 거래 구성은 detection(룰) 책임이다. 경로형 경보의 연결·순서는 위 "경로" 절이 확인한다.
- `accounts`(`S` + 상대 계좌들의 `entity_id` — internal 판정용) / `entities` / `customer_attributes`: 대상 계좌 키로.
- 요청의 ID가 DB에 없으면 400 `INVALID_REQUEST`에 없는 ID(최대 10개)와 개수 포함.

## 단위 테스트 (`tests/str/test_facts.py` 분류·집계·입력, `test_fact_paths.py` 경로·fact 키) — 규칙 표 한 줄 = 테스트 하나

입력·기대값은 `tests/str/fixtures/facts_cases.json` 한 파일(공용 변환은 `tests/str/facts_support.py`).

inbound/outbound/internal 분류 · self_transfer 제외 · self_transfer만 → 400 · 통화 이름 → 코드(표 밖 이름 에러) · 통화 2종 합계 문자열과 통화별 `transaction_ids` · `inbound.amount.USD` → USD 거래 ID만 · direction 네 값 · period min/max · counterparties distinct · S 없는 거래 → `indirect`(400 아님, 집계에 안 섞임) · R04 고리 A→B→C→A 픽스처(indirect 1건, LLM용 facts에 indirect 없음) · evidence ≠ alert.transaction_ids → 400 · period에 indirect 포함 · **paths**(10/28): 고리 2개 정상 → `VERIFIED`(count 2·max_hops 3·max_accounts 3) · STACK A→B→C→D → `VERIFIED`(max_accounts 4) · 끊긴 경로(to ≠ 다음 from) → `UNVERIFIED` · 시간 역순 → `UNVERIFIED` · CYCLE인데 S로 안 돌아옴 → `UNVERIFIED` · paths에만 있는 ID → 400 · R04·R05 밖 룰의 paths → `UNVERIFIED` · `UNVERIFIED`면 fact 키·LLM용 facts에 paths 없음 · `fact_keys` 목록(null customer 제외) · `attach_evidence` 합집합과 `[]`.
