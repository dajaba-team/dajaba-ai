# 04. facts — 정본 JSON과 계산 규칙 (규약 v0.4, 11/6)

정본: `str/domain/facts.py` `build_facts(req, txs, subject) -> Facts`, `attach_evidence(narrative, facts)`, `fact_keys(facts)`, `str/domain/masking.py` `mask_for_llm(facts) -> Facts`, `shared/schemas/str.py` `Facts`. 입력 dataclass(`Transaction`, `Subject`)는 `str/domain/models.py`, 읽기는 `str/infrastructure/transaction_reader.py`.

**순수 함수.** 같은 입력에 항상 같은 facts. LLM은 facts만 보고 쓰고, 검증은 facts와 대조한다 — facts가 틀리면 전부 틀리므로 여기 규칙이 제일 촘촘하다.

10/27에 바뀐 것 — 1차 검토 지적 반영: ① "기준 통화 1개 + 총액" → **대상 계좌 관점 `inbound/outbound/internal`, 통화별 집계, 환산 없음**. ② `top_reasons` 문자열(SHAP 값을 관측값처럼 쓰던 것) → **`observations[]`(관측값) + `model_signals[]`(이름만)** 분리. ③ 각 집계에 `transaction_ids`를 붙이고 **fact 키 → 거래 ID**를 코드가 연결. ④ 뼈대 `facts.py`는 전부 다시 쓴다(W2 수).

10/28에 바뀐 것 — 준혁 답(경로형 경보): ⑤ 대상 계좌가 안 낀 거래 묶음 `path` → **`indirect`**로 이름 변경(새 `paths`와 헷갈리지 않게). ⑥ R04_CYCLE·R05_STACK(v2 11/9: R05_SCATTER_GATHER) 경보가 주는 `rule_facts.paths`(경로별 거래 ID, 시간순)를 AI가 **확인만** 해서 **`paths`** fact로. 확인되면 인용 가능, 아니면 인용·LLM 전달 없음(아래 "경로" 절).

## 정본 JSON (응답 `facts`와 같다, 규약 5.2)

```json
{
  "reporting_institution": "Portugal Bank #4507",
  "subject": { "entity_id": "80062E240", "entity_name": "Sole Proprietorship #50438", "entity_type": "SOLE_PROPRIETORSHIP", "account_key": "10_8000EBD30" },
  "period": { "start": "2022-09-02T00:14:00", "end": "2022-09-02T22:51:00" },
  "inbound":  { "count": 47, "by_currency": [ { "currency": "USD", "total": "320000000.00", "count": 47, "transaction_ids": [104221, 104233, 104301] } ], "transaction_ids": [104221, 104233, 104301] },
  "outbound": { "count": 0,  "by_currency": [], "transaction_ids": [] },
  "internal": { "count": 0,  "transaction_ids": [] },
  "indirect": { "count": 0,  "transaction_ids": [] },
  "paths":    null,
  "excluded_self_transfer_count": 0,
  "direction": "INBOUND",
  "counterparties": { "count": 31, "transaction_ids": [104221, 104233, 104301] },
  "counterparty_banks": { "same_bank_accounts": 0, "other_bank_accounts": 31 },
  "payment_formats": ["ACH"],
  "payment_format_counts": [ { "format": "ACH", "count": 47 } ],
  "amount_range": [ { "currency": "USD", "min": "1500000.00", "max": "22000000.00" } ],
  "typology": "FAN_IN",
  "typology_source": "RULE",
  "customer": { "industry": "RETAIL", "risk_level": "LOW", "account_purpose": "SALES_DEPOSIT", "onboarded_at": "2021-03-14", "country_code": "PT" },
  "prior_alert_count": 1,
  "observations": [ { "name": "account_in_counterparties_24h", "value": 31, "unit": "count", "window_start": "2022-09-02T00:00:00", "window_end": "2022-09-03T00:00:00", "basis": "distinct_inbound_counterparties", "baseline": null } ],
  "model_signals": ["distinct_senders_24h", "outflow_ratio_2h"],
  "unmapped_currencies": []
}
```

예시의 `transaction_ids`는 **축약**이다 — 입금 47건이면 실제로는 ID 47개. 계약 예시(`contracts/examples/`)·테스트 픽스처로 옮길 때는 건수와 ID 개수를 맞춘다.

## 계산 규칙 (코드가 전부 정한다)

대상 계좌 `S` = `alert.account_key` **하나**(규약 2절: 경보 단위는 계좌). 대상 거래 `T` = `evidence_transaction_ids`로 읽은 행. 규약 5.1에서 이 목록은 **`alert.transaction_ids` 전체**다 — 점수 응답의 `evidence_transaction_ids`(SHAP 근거 부분집합)로 계산하면 건수·금액이 경보와 달라지므로 쓰지 않는다(그건 화면 표시용).

| 필드 | 규칙 |
|---|---|
| `subject` | `S`와 `accounts.entity_id` → `entities.entity_name`·`entities.entity_type`. 이름 없으면 `entity_name: null` |
| `subject.entity_type` | `ops.entities.entity_type` 원값 그대로(6종 `CORPORATION·PARTNERSHIP·SOLE_PROPRIETORSHIP·INDIVIDUAL·COUNTRY·DIRECT`) 또는 null. **서식 표기(개인사업자·법인…)로 바꾸지 않는다 — 백엔드 몫.** `COUNTRY`·`DIRECT` 는 개인·법인으로 추정하지 않음(SCRUM-47 · 안건 5-6) |
| 제외 | `is_self_transfer = true`(from = to = S) 행은 **모든 집계에서 제외**, 건수만 `excluded_self_transfer_count`. 제외 후 남은 거래가 **0건**(self-transfer만)이면 facts를 만들지 않고 400 `INVALID_REQUEST`("no reportable transactions") — 기간·금액이 전부 비는 초안은 쓸 게 없다(가정, 축소본 확인) |
| `inbound` | `to_account_key = S`인 행. 금액은 **받은 쪽** `amount_received`·`currency_received`. `by_currency`는 통화별 `{currency, total, count, transaction_ids}`, 통화 코드 정렬. 바깥 `transaction_ids`는 그 행 전부, 항목 안 `transaction_ids`는 그 통화 행만 |
| `outbound` | `from_account_key = S`인 행. 금액은 **보낸 쪽** `amount_paid`·`currency_paid` |
| `internal` | **S가 낀 거래** 중 상대 계좌의 `entity_id`가 S의 `entity_id`와 같은 것(S의 법인이 가진 다른 계좌와의 이동). S 없이 같은 법인 계좌끼리 오간 거래는 `indirect`. S의 `entity_id`가 없으면 internal 0건. inbound/outbound에 **넣지 않는다**. 금액 집계 없음(법인 안 이동이라 "입금"도 "출금"도 아님) — 건수와 ID만 |
| `indirect` | **대상 계좌가 직접 참여하지 않은 경보 거래**(S가 from·to 어디에도 없음). 예: R04_CYCLE A→B→C→A, 대상 A일 때 B→C. `count`와 `transaction_ids`만 남긴다 — 버리지도 400으로 막지도 않고, 대상 계좌 관점 집계(inbound/outbound/counterparties/direction)에는 **섞지 않는다**. 금액 집계 없음. 인용 키 없음, LLM에 보내지 않음(마스킹에서 제거). 쓰임은 `period` 계산과 근거 범위뿐. **이 거래들이 어떤 순서로 이어진 경로인지는 여기서 다루지 않는다** — 그건 `paths`(아래 "경로" 절). (10/27 이름 `path`, 10/28 `indirect`로 변경) |
| `paths` | `alert.rule_facts.paths`가 있을 때만. 확인 규칙·값은 아래 "경로" 절. 없거나 빈 배열이면 `null` |
| `by_currency[].total` | Decimal 합, **문자열**, **소수 2~6자리**(아래 규칙), 천 단위 구분 없음. 통화 간 **환산 없음**. (0절 "금액은 숫자"의 유일한 예외 — LLM·백엔드가 다르게 반올림하지 않도록) |
| `currency` | ISO 4217 코드(`USD`, `EUR`, …). IBM 원천은 이름(`US Dollar`, `Euro`, …)이라 **`transaction_reader`가 읽을 때** 고정 표 `domain/constants.CURRENCY_CODES`로 바꾼다 — domain은 코드만 본다. HI-Small 15종(가정, 축소본 만들 때 `SELECT DISTINCT`로 확인): US Dollar→USD, Euro→EUR, Yuan→CNY, Shekel→ILS, Canadian Dollar→CAD, UK Pound→GBP, Ruble→RUB, Australian Dollar→AUD, Swiss Franc→CHF, Yen→JPY, Mexican Peso→MXN, Rupee→INR, Brazil Real→BRL, Saudi Riyal→SAR, **Bitcoin→BTC**(ISO 4217에 없음 — 규약 0절 예외). **표에 없는 이름**은 **에러 아님** → `unmapped_currencies` 로 보존(아래, SCRUM-47 · 미결 7) |
| `unmapped_currencies` | 표에 없는 통화 이름이 섞여 있을 때 `[{name, count, transaction_ids}]` — 원문 이름 그대로. **`by_currency`·`amount_range` 금액 집계·통화 대조에는 섞지 않는다**(통화 간 환산·합산 금지). 상대 계좌 수는 통화와 무관하므로 **`counterparties` 와 inbound/outbound `count`·`transaction_ids` 에는 포함**. 서술에는 "{원문} … 대응 미확인"(05 규칙) |
| `direction` | `inbound.count ≥ 2 × outbound.count` → `INBOUND`, 반대 → `OUTBOUND`, 그 밖 → `MIXED`. 둘 다 0이면(internal만) `INTERNAL` |
| `period` | 제외 후 대상 거래 `ts`의 min / max(**indirect 포함** — 경로 전체가 일어난 기간). ISO 8601 초 단위. 룰 창이 아니라 **실제 거래 범위** |
| `counterparties` | 상대 `account_key` distinct 수(internal 제외). `transaction_ids` = inbound ∪ outbound |
| `counterparty_banks` | `counterparties` 집합 기준(internal 제외) `{same_bank_accounts, other_bank_accounts}` — 상대 `account_key` 의 `{bank_id}` 부분이 대상 계좌와 같으면 자행(same), 아니면 타행(other). 두 합 = `counterparties.count`. `account_key` 앞자리 0 통일은 적재에서 처리(5-1) (SCRUM-47 · 안건 6-2) |
| `counterparties_by_direction` | **질문 답변 전용 — 질문 답변만 요청 때 계산해 붙임(`facts_direction.with_direction`, `ask_service._load_facts`). 초안·요약 `build_facts` 는 안 채움(늘 `null`) · 직렬화에서 빠짐(`exclude`) → 초안·요약 응답·저장 facts 는 이전 버전과 같은 모양(롤백 안전, 추가 검토 1 H3)** · LLM 마스킹본·초안 `fact_keys` 에도 없음 (SCRUM-358·359). `{inbound: {count, same_bank_accounts, other_bank_accounts}, outbound: {…}}` — inbound = 입금 거래의 보낸 쪽 `account_key` distinct, outbound = 출금 거래의 받는 쪽 distinct, 자행·타행은 `counterparty_banks` 와 같은 `{bank_id}` 비교. 한 계좌가 양쪽이면 양쪽에 셈(그래서 inbound.count + outbound.count ≥ `counterparties.count`). 질문 답변 검사에서만 쓰임(06 "질문 답변" 10번) — 초안·요약 검사(공용 COUNT_MATCH)는 방향을 안 봄 |
| `payment_formats` | distinct, 원본 문자열 그대로(ACH, Wire, Cash, …), 정렬 |
| `payment_format_counts` | `[{format, count}]` — inbound ∪ outbound(self-transfer 제외) 원본 문자열별 건수. **건수 내림차순 → 이름순**(동률 안정화). 기존 `payment_formats`(distinct 목록) 는 v1 호환으로 남김 (SCRUM-47) |
| `amount_range` | 통화별 `[{currency, min, max}]` — inbound ∪ outbound 중 **매핑된 통화만**(미등록 통화 제외), 통화 간 비교·합산 없음. min·max 는 Decimal **소수 2~6자리 문자열**(`by_currency.total` 과 같은 규칙). 통화 코드 정렬. **거래마다 그 방향 금액 기준** — 입금은 `amount_received`·`currency_received`, 출금은 `amount_paid`·`currency_paid`(`inbound`·`outbound` 와 같음) (SCRUM-47 · 안건 6-2) |
| `typology` / `typology_source` | 요청 `alert.typology_hint` 그대로. `typology_source`는 `RULE` 고정(안건 8) |
| `customer` | `customer_attributes` 행. 없으면 `null`. `onboarded_at`은 날짜(검증 `DATE_MATCH`가 "개설일"로 허용) |
| `prior_alert_count` | 요청 그대로. 내용은 오지도 않는다 |
| `observations[]` | 요청 `reasons`(안건 3 확정 구조)에서 **관측값만**: `{name, value, unit, window_start, window_end, basis, baseline}` ← `reasons[].name`, `observation.*`, `baseline.value`. `observation.value`가 `null`인 항목은 넣지 않는다. `contribution`(기여값·방법·척도)은 **넣지 않는다**. **거르기(SCRUM-264, 실제 ML reasons — 피처 31개 중 |SHAP| 상위 3, 부호 무관)** — 아래 하나라도 걸리면 뺀다(`str/domain/facts_observations.py`, 상수 `constants_ml.py`): ① `contribution.value` 가 0 이하이거나 `null`(점수를 낮췄거나 부호 모름 — 의심 근거처럼 서술되지 않게, 기여값 숫자는 여전히 안 넘김) ② 메타 피처 11개(`rule_r01`~`rule_r06`·`evidence_features_applicable`·`evidence_path_available`·`evidence_payment_known_fraction`·`evidence_paid_ratio_coverage`·`evidence_received_ratio_coverage` — 행동 관측이 아니라 룰 표시·계산 여부·데이터 품질) ③ 추가 피처 13개(`evidence_ach_fraction` 등 — 목록 `constants_ml.py`)는 경보 `rule_id` 앞 `R02`·`R04` 일 때만, 그중 경로 2개(`evidence_min_path_hops_scaled`·`evidence_path_available`)는 `R04` 만(그 밖 룰에서는 ML 이 0 채움) ④ 추가 피처 13개의 값이 0(0 채움과 진짜 0을 구분할 수 없음 — 진짜 0 도 빠짐, 09 미결). 거르기 뒤 남은 게 없으면 `observations = []`. 관측 기간이 경보 창보다 넓어도 쓸 수 있지만 근거 거래는 붙이지 않고(인용 키 → `evidence_ids` 없음), 본문에는 "모델 관측값(24시간 기준)"처럼 기간을 밝혀 쓴다(05 규칙 11, 10/28 준영). `context_transaction_ids`는 facts에 넣지 않는다 |
| `model_signals[]` | 요청 `reasons` 중 위 거르기 ①~④ 를 통과한 것의 상위 3개 피처 **이름만**(SCRUM-264 — 음수 기여 피처가 "모델이 주목한 점"으로 읽히지 않게). `observation.value` 가 `null` 이어도 이름은 남김. "모델이 주목한 점" 한 줄의 재료. 숫자 없음 |
| 없는 값 | `null`. LLM에는 "확인되지 않음"으로 전달, 모르는 걸 지어내지 말라는 규칙(05)이 받는다 |

### 금액 문자열 규칙 (`_money`, SCRUM-140 — 2026-11-07)

- **스키마**: `^\d+\.\d{2,6}$` (`shared/schemas/common.FactAmount`). 소수부 **최소 2자리**(법정 통화 표기 보장), 최대 6자리(DB `numeric(20,6)` 과 일치, 규약 v0.4 1번).
- **포맷 함수** `str/domain/facts._money` (의사 코드):
  1. `q = x.quantize(Decimal("0.000001"), ROUND_HALF_EVEN)` — 6자리 scale로 맞춤 (방어선 포함).
  2. `s = f"{q:f}"` — scale대로 6자리 문자열(`"42750.500000"`·`"0.000001"`). 지수 표기 안 나옴. `normalize()` 금지.
  3. 소수점 기준 분해 → **소수부 뒤쪽 0만** `rstrip("0")` → 비거나 1자리면 `ljust(2, "0")` → 다시 결합. 정수부·앞쪽은 건드리지 않는다.
- **소수부 길이 의미**: 끝에 의미 없는 0은 떼되 **법정 통화 표기(2자리)는 보장**. 입력 Decimal의 scale이 6이든 2든 결과가 같다 — DB(`numeric(20,6)`)에서 `42750.50`도 `42750.500000`도 둘 다 `"42750.50"`.
- **입력 → 문자열 벡터** (양쪽 scale이 같은 결과를 내는지까지 봄):
  - `Decimal('42750.50')` · `Decimal('42750.500000')` → `"42750.50"`
  - `Decimal('320000000')` · `Decimal('320000000.000000')` → `"320000000.00"`
  - `Decimal('0.0042')` · `Decimal('0.004200')` → `"0.0042"`
  - `Decimal('0.000001')` → `"0.000001"`
  - `Decimal('0.0000004')` → `"0.00"` (6자리 방어선, ROUND_HALF_EVEN)
  - `Decimal('0.0000005')` → `"0.00"` · `Decimal('0.0000015')` → `"0.000002"` (HALF_EVEN 확인)
- **7자리 이상 입력**: DB가 `numeric(20,6)` 이라 정상이면 안 오지만 방어선으로 6자리 `ROUND_HALF_EVEN` — 에러로 올리지 않음. 경계 확인 테스트 3건(`0.0000004`·`0.0000005`·`0.0000015`).
- **facts build 경로 테스트**: 합계가 6자리 scale Decimal(`Decimal('42750.500000')`)로 들어와도 `by_currency[].total` 이 `"42750.50"` 으로 나오는지 — `ops_seed.sql` 이 `numeric(20,6)` 로 바뀌면 fixture 금액이 전부 6자리로 읽혀서 꼭 봐야 한다.
- **이유**: 준혁님 11/5 확인 — HI-Small Bitcoin 입금 148,151건 중 25,947건(약 17.5%)이 `0.005 BTC` 미만. 소수 2자리 고정은 이 금액들을 `"0.00"` 으로 지워 보고서에 "0.00 BTC" 가 찍힘. LLM은 facts 숫자를 그대로 쓰므로 자릿수를 원본 가까이 보존해야 한다. 끝 0을 떼는 쪽을 고른 건 법정 통화 표기(`42750.50`)·계약 예시·few-shot을 안 바꾸면서 BTC 소수를 보존하기 위함(Jira "끝 0 다 떼기"는 `42750.50 → 42750.5` 로 가서 범위가 커졌음).

### 결정 사항 (바꾸려면 `09_decisions.md`에 적고)

- 통화별 집계, 환산 없음. "총액 1개"는 버림 — 15종 통화가 섞인 데이터에서 기준 통화 하나는 사실을 지운다(1차 검토 1번).
- 받은 돈은 `amount_received`, 보낸 돈은 `amount_paid`. IBM 원본에서 둘이 다른 건 환전 거래라 대상 계좌 관점에서 실제 움직인 쪽을 쓴다.
- 허용 오차 0. `"320,000,000"`과 `"3억 2천만"`은 같은 Decimal이라 통과, `"약 3억"`은 fail(06).
- 거래 행 원본은 LLM에 안 준다. facts 요약만. 거래 ID 목록도 안 준다(아래 fact 키).
- `direction` 2배 규칙은 진희 가정값 — 축소본 경보로 분포를 본 뒤(W2) 바꿀 수 있다. 축소본에서 볼 경계: 입금만 · 출금만 · 정확히 2:1(`≥`라 `INBOUND`) · internal만(`INTERNAL`) · self-transfer만(위 0건 → 400).
- 통화는 코드로(`USD`). 원천 이름 → 코드 변환은 로더 한 곳, 본문 표기(`달러`, `US Dollar`, `$`) 인식은 검증의 `CURRENCY_ALIASES`(06).
- 경로는 detection이 준 순서 그대로 **확인만** 한다. 하나라도 어긋나면 전체 `UNVERIFIED` — AI가 경로를 다시 정렬하거나 이어 붙이지 않는다(10/28).

## 경로 (`paths`) — 경로형 경보 R04·R05 (10/28 준혁 답, 룰 v2 11/9 반영)

입력은 `alert.rule_facts.paths`(규약 2절): **거래 ID 배열의 배열**. 배열 하나가 경로 하나이고, 안의 ID는 **시간순**. `alert.transaction_ids`는 그대로 전체 근거 목록(경로 거래 포함). 준혁 확정 사항:

- R04_CYCLE: 대상 계좌 = 고리의 **시간상 첫 거래 송금 계좌**. 같은 룰·계좌·시간창의 고리 여러 개는 경보 하나로 묶이고, **묶인 고리에는 모두 대상 계좌가 있다**. 최대 3홉(10/28) → **v2(11/9) 최대 4홉**(detection 보장, AI는 상한 없음).
- R05_SCATTER_GATHER(v2 11/9, `R05_STACK` 교체): 출발 S → 서로 다른 중간 계좌 Mᵢ → 도착 T. 대상 계좌 = **모이는 계좌 T**. 경로 하나 = [S→Mᵢ, Mᵢ→T] **정확히 2건**(백엔드 rules.md 2.1).
- 같은 분 거래는 앞뒤를 모른다 — "A 다음에 B"는 **B가 A보다 늦은 분**일 때만(rules.md 1절 9번, R03·R04·R05). AI 확인도 같은 기준.
- **홉 = 경로의 거래 개수.** A→B→C→A는 3홉(마지막 복귀 거래 포함). 룰의 최대 홉은 detection 기준이라 AI는 길이를 제한하지 않고 값만 보고한다.

```json
"paths": { "kind": "CYCLE", "status": "VERIFIED", "count": 2, "max_hops": 3, "max_accounts": 3, "transaction_ids": [101, 102, 103, 201, 202, 203] }
```

**확인 규칙** (`build_facts` 안, 순수 함수 — 거래 행은 이미 읽어 둔 것)

| # | 확인 | 어기면 |
|---|---|---|
| 1 | 경로의 모든 ID ∈ `alert.transaction_ids` | 400 `INVALID_REQUEST`("paths id not in transaction_ids") — 요청 안의 두 목록이 어긋난 것(위 "범위 확인"과 같은 성격) |
| 2 | `kind` = `rule_id`로 정한다: `R04_CYCLE` → `CYCLE`, `R05_SCATTER_GATHER` → `SCATTER_GATHER`(v2 11/16, `R05_STACK`·`STACK` 삭제) | 그 밖 룰(`R03_FX_RELAY`·옛 `R05_STACK` 포함)에 `paths`가 오면 `kind: null`, `UNVERIFIED` |
| 3 | 경로마다 거래 2개 이상, 경로 안 ID 중복 없음, self-transfer 없음 | `UNVERIFIED` |
| 4 | 시간순: 앞 거래 `ts` **<** 다음 거래 `ts`(**늦은 분만**, 같은 분 불인정 — 11/16, 이전 `≤`) | `UNVERIFIED` |
| 5 | 연결: 앞 거래 `to_account_key` = 다음 거래 `from_account_key` | `UNVERIFIED` |
| 6 | CYCLE: 시작 = 첫 거래 `from_account_key` = 대상 계좌 | `UNVERIFIED` |
| 7 | CYCLE: 닫힘 = 마지막 거래 `to_account_key` = 대상 계좌 | `UNVERIFIED` |
| 8 | SCATTER_GATHER 경로 하나: 거래 **정확히 2건**, 둘째 거래 `to_account_key` = 대상 계좌(T). 첫 수신 = 둘째 송신 = Mᵢ는 규칙 5 | `UNVERIFIED` |
| 9 | SCATTER_GATHER 경보 전체: 첫 거래 `from_account_key`(S)가 **모든 경로에서 같음**, Mᵢ가 **경로끼리 서로 다름** — 경로 하나로는 못 봐서 경로 검사 뒤 한 번 | `UNVERIFIED` |

- **전부 통과해야 `VERIFIED`**, 한 경로라도 어긋나면 전체 `UNVERIFIED` — 경로 일부만 골라 쓰는 문장이 나오지 않게. 어긋난 이유(경로 번호·규칙 번호)는 `generations` 내부 기록에만, facts에는 `status`만.
- 배열 순서를 **그대로** 확인한다. 순서가 틀리면 고쳐 주지 않고 `UNVERIFIED` — 순서를 추측하지 않는다(준혁님께 말한 "모르면 미확인으로 두고 보고서에 안 쓴다").
- 값: `count` = 경로 수, `max_hops` = 가장 긴 경로의 거래 수, `max_accounts` = 경로 하나에 나오는 서로 다른 계좌 수의 최대(CYCLE A→B→C→A = 3, SCATTER_GATHER S→M→T = 3), `transaction_ids` = 모든 경로 ID 합집합. `UNVERIFIED`여도 응답 facts에는 남긴다(감사·디버깅용).
- `period`·`indirect`는 그대로 — 경로 ID는 이미 `alert.transaction_ids` 안이라 기간에 들어가 있다.
- SCATTER_GATHER의 facts 분류는 따로 안 바꾼다: S→Mᵢ는 대상 T가 안 낀 거래라 `indirect`, Mᵢ→T는 `inbound`(상대 = Mᵢ). 경보 거래가 경로 합집합뿐이면 `counterparties.count` = Mᵢ 수 = `paths.count`.

## fact 키 — LLM이 인용하고 코드가 거래 ID로 바꾼다

LLM은 섹션마다 `cites`에 **fact 키**를 쓴다(05). 코드 `attach_evidence`가 키마다 정해진 `transaction_ids`를 합쳐 `evidence_ids`로 만든다. LLM이 거래 ID를 직접 고르지 않는다 — 고르게 하면 EVIDENCE_IDS 목록에서 아무 ID나 옮겨 적는다(1차 검토 4번).

| 키 (`fact_keys(facts)`가 만든다) | 가리키는 값 | → `evidence_ids` |
|---|---|---|
| `subject`, `subject.entity_name`, `subject.account_key`, `subject.entity_type` | 대상 (entity_type 는 null 이면 키 안 생김) | 없음 |
| `period` | 기간 | inbound ∪ outbound ∪ internal ∪ indirect |
| `inbound.count` | 입금 건수 | `inbound.transaction_ids` |
| `inbound.amount.{currency}` (통화 코드별 1개씩, 예 `inbound.amount.USD`) | 그 통화 입금 합계 | **그 통화 항목의** `by_currency[].transaction_ids`만 — 달러 합계에 유로 거래가 붙지 않게 |
| `outbound.count` | 출금 건수 | `outbound.transaction_ids` |
| `outbound.amount.{currency}` | 그 통화 출금 합계 | 그 통화 항목의 `by_currency[].transaction_ids`만 |
| `internal.count` | 법인 내 이동 | `internal.transaction_ids` |
| `counterparties.count` | 상대 수 | `counterparties.transaction_ids` |
| `counterparty_banks.same_bank_accounts`, `counterparty_banks.other_bank_accounts` | 자행·타행 상대 계좌 수 | `counterparties.transaction_ids` (facts 에 bank 별 거래 세분이 없음 — 세분화는 후속) |
| `payment_format_counts.{format}` (원본 문자열별 1개씩) | 그 결제 방식 건수 | inbound ∪ outbound 거래 ID 전체 (facts 에 format 별 거래 세분이 없음 — 세분화는 후속) |
| `amount_range.{currency}.min`, `amount_range.{currency}.max` | 통화별 min/max 금액 | 그 통화의 `by_currency[].transaction_ids` (매핑된 그 통화 거래 전체) |
| `direction`, `payment_formats`, `typology` | 패턴 | inbound ∪ outbound |
| `customer.industry`, `customer.risk_level`, `customer.account_purpose`, `customer.onboarded_at`, `customer.country_code` | 고객 | 없음 |
| `prior_alert_count` | 과거 경보 수 | 없음 |
| `observations.{name}` | 관측값 1개 | 없음 (거래가 아니라 피처) |
| `model_signals` | 모델 주목 피처 이름들 | 없음 |
| `paths.count`, `paths.max_hops`, `paths.max_accounts`, `paths.kind` | 경로 수·가장 긴 경로의 거래 수·거친 계좌 수·유형 — **`paths.status = VERIFIED`일 때만 키가 생긴다** | `paths.transaction_ids` |
| `unmapped_currencies.{name}` (원문 통화 이름별 1개씩, 예 `unmapped_currencies.Dogecoin`) | 그 미등록 통화가 섞인 거래들 — **건수·근거만**, 금액 없음(통화 대조가 깨짐) → 서술에 **미등록 통화 금액은 쓰지 않는다**(그래서 06 `AMOUNT_MATCH` 규칙은 안 건드림) | 그 `unmapped_currencies[].transaction_ids` |

- 존재하는 키 목록을 프롬프트 `FACT_KEYS`에 그대로 넣는다. 목록 밖 키는 `NarrativeOut` 검증에서 걸러 재생성(05).
- `null`인 fact(예: `customer`가 없음)의 키는 목록에 **넣지 않는다** — 인용할 게 없다.
- `counterparties_by_direction` 의 키는 이 표(초안 `fact_keys`)에 **넣지 않는다** — 초안·평가자 LLM 입력의 키 목록이 바뀌지 않게. 질문 답변만 따로 인용한다(아래 "질문 답변 묶음", SCRUM-358·359).
- 섹션의 cites가 전부 "없음" 키(subject·customer)뿐이면 `evidence_ids = []`. CONCLUSION(v1)·OPINION(v2) 은 보통 `[]`.

## 마스킹 (`masking.py`) — 생성·평가자 공용

LLM에 가는 facts만 바꾼다(생성기와 평가자 **둘 다** 마스킹본 — 평가자는 숫자 대조를 안 하므로 원본이 필요 없다, 1차 검토 반영). 응답·DB·코드 검증은 원본.

| 필드 | 처리 |
|---|---|
| `subject.account_key` | 뒤 4자리만 (`10_****BD30`, 규약 v0.4 #4 — bank_id 앞 0 없음) |
| `reporting_institution` (은행명) | 그대로 |
| `subject.entity_name` (고객명) | 그대로 — IBM 합성 데이터라 실명이 아님. 실데이터 전환 시 여기서 가명화(MVP 정의서 8절 "한계" 4번) |
| `subject.entity_id` | 그대로 (합성) |
| `*.transaction_ids` | **제거** — LLM은 거래 ID를 보지 않는다 (inbound·outbound·by_currency·counterparties·indirect·paths·**`unmapped_currencies`** 모든 집계, NFR-DRF-03) |
| `indirect` | **통째로 제거** — 인용 키가 없는 사실을 LLM이 문장에 쓰면 검증이 대조할 곳이 없다 |
| `paths` | `VERIFIED`면 `{kind, count, max_hops, max_accounts}`만 남기고 ID·`status` 제거. `UNVERIFIED`·`null`이면 **통째로 제거** — LLM은 확인된 경로만 본다 |
| `counterparties_by_direction` | **통째로 제거** — 초안·요약·평가자 LLM 입력과 그 녹화를 그대로 두려고(SCRUM-358 ★A 3). 칸이 직렬화에서 빠지고(위) 초안·요약 build_facts 는 칸을 안 채우므로 `mask_for_llm`·few-shot 은 develop 그대로(따로 빼는 코드 없음). 질문 답변 `counterparties` 묶음만 원본에서 따로 싣는다(건수만, 거래 ID 없음) |
| 그 밖 | 그대로 |

마스킹은 **검증에 영향이 없다** — 코드 검증은 원본 facts와 narrative를 대조하고, narrative에는 계좌가 뒤 4자리로만 나오므로 `ACCOUNT_ID_MATCH`는 마스킹 표현(`****BD30`)과 원본 끝 4자리를 같은 것으로 본다(06).

### 질문 속 계좌 (`ask_question.py`, SCRUM-290 — 설계 문서 13절 1번)

질문 답변의 **질문 문자열**도 LLM 에 가기 전에 계좌 모양을 가린다. 저장(`generations.request`)·응답은 원문. 순수 함수 `mask_question(text) -> str` — 돌려주는 값은 **LLM 에 가는 복사본**이다.

순서(SCRUM-290 추가 검토 1): **① NFKC 정규화 → ② 계좌 가리기 → ③ 격리**(`<`·`>` 바꾸기, `ask_llm.render_plan_user`). ① 로 전각(`１０＿８０００ＥＢＤ３０`)·전각 기호가 ASCII 가 된 뒤에 ② 가 돈다. NFKC 는 LLM 복사본에만 — 원문은 그대로 저장.

| 모양 | 정규식 (`constants_ask`, 영문은 대소문자 무관) | 바꾼 모양 |
|---|---|---|
| 은행 번호 붙은 계좌 키 | `RE_ASK_ACCOUNT_FULL` — 앞이 영숫자가 아닌 `숫자1~4_` + `[0-9A-Z*]` 이어지다 **영숫자 4자로 끝남**, 뒤가 영숫자가 아님 | `mask_account_key()` — `10_8000EBD30` → `10_****BD30` |
| 은행 번호 없는 맨 계좌 | `RE_ASK_ACCOUNT_BARE` — 앞뒤가 영숫자가 아닌 8자 이상 `[0-9A-Z]` 토큰, **숫자와 영문자를 둘 다** 포함 | `****` + 끝 4자리 — `8000EBD30` → `****BD30` |

- 앞뒤에 붙은 기호(`**8000EBD30**`·`` `8000EBD30` ``·`8000EBD30.`·`(10_8000EBD30)`)는 경계로만 보고 토큰을 건너뛰지 않는다 — 별표가 앞에 붙었다고 맨 계좌 검사에서 빠지지 않음.
- 이미 가려진 모양(`10_****BD30`·`****BD30`)만 정확히 그대로 남는다 — 앞 것은 다시 가려도 같은 값, 뒤 것은 남은 꼬리가 4자라 8자 규칙에 안 걸림.
- 숫자만인 토큰(`20220902`·금액)과 영문자만인 토큰(`ACH`·`FAN_IN`)은 맨 계좌로 보지 않는다 — 날짜·금액·코드값 질문이 깨지지 않게.
- 못 가리는 모양(알고 남김, 09): 하이픈·공백으로 끊어 쓴 계좌(`8000-EBD-30`) — 끊긴 조각이 8자 미만이라 맨 계좌 규칙에 안 걸림.

### 이어지는 질문 (`ask_question.is_follow_up`, SCRUM-359 · 추가 검토 1 M3)

질문마다 따로 처리하므로(앞 질문 칸 없음 — 설계 문서 13절 "대화형은 1차 제외") 앞 답을 가리키는 짧은 질문은 계획 호출 **전에** 코드가 범위 밖(`OUT_OF_SCOPE`·`OUTSIDE_CASE`)으로 끝낸다. LLM 호출 0. NFKC 뒤, 앞뒤 공백을 뺀 질문이 **20자 이하**(`ASK_FOLLOW_UP_MAX_CHARS`)일 때만:

1. **앞 답 집합을 가리키는 머리 낱말**로 시작 — `ASK_FOLLOW_UP_SET_HEADS` = `그 중`·`그중`·`그 다음`·`그다음`·`거기서` → **늘** 범위 밖(주제 낱말 상관없이 — "그중 3건만 합치면?" 은 어느 세 건인지 알 수 없음)
2. **접속어**로 시작 — `ASK_FOLLOW_UP_JOIN_HEADS` = `그럼`·`그러면` → 그 말을 뗀 나머지가 1번 머리 낱말로 시작하면 범위 밖, 아니면 **주제 낱말이 하나도 없을 때만** 범위 밖(추가 검토 2). 주제 낱말 `ASK_TOPIC_WORDS` = 질문 방향 낱말 · `건수`·`몇 건`·`몇건`·`거래`·`금액`·`돈`·`상대`·`계좌`·`결제`·`방식`·`기간`·`날짜`·`업종`·`위험`·`고객`·`경로`·`모델`·`룰`·`점수`·`통화`·`관측`·`경보`·`유형`·`이 케이스`, 그리고 **숫자+건**(`3건`). `건` 단독은 주제로 보지 않음
**다른 케이스 번호**(추가 검토 4 H6): 질문에 `CASE-YYYY-NNNNNN` 이 있고 요청 `case_no` 와 다르면 길이·머리 낱말과 상관없이 같은 방식으로 계획 전에 범위 밖(`OUTSIDE_CASE`, LLM 0). 답 본문에 그런 번호가 있으면 06 "질문 답변" 2번에서 UNVERIFIED.

3. `이거`·`그거` 는 머리 낱말이 아님 — "이 케이스"를 뜻할 수 있음(18개 O3 "이거 자금세탁 맞지?" 는 계획이 `JUDGMENT` 로 가름)

| 질문 | 결과 |
|---|---|
| 그 중에 제일 큰 건? (359 C2) | 막음 — 범위 밖 |
| 그중 3건만 합치면? | 막음 — 앞 답 집합(추가 검토 1) |
| 그럼 출금은? (359 C1) | 그대로 계획으로 — `출금` 이 주제 낱말 |
| 그럼 거래는 총 몇 건이야? | 그대로 계획으로 — `거래`·`몇 건`(추가 검토 1) |
| 그럼 그중 3건만 합치면? | 막음 — 접속어를 뗀 나머지가 그중류(추가 검토 2) |
| 그럼 이 케이스의 탐지 유형은? | 그대로 계획으로 — `이 케이스`·`유형`(추가 검토 2) |
| CASE-2022-000058의 입금 합계는? (요청 case_no 000057) | 막음 — 질문에 이 요청이 아닌 케이스 번호(추가 검토 4 H6, `ask_question.blocked_before_plan`) |
| 이거 자금세탁 맞지? 보고해야 해? (18개 O3) | 그대로 계획으로 — `이거` 는 머리 낱말 아님 |

## 질문 답변 묶음 (`ask_bundles.py`, SCRUM-290 — 설계 문서 6.2)

계획 LLM 이 고른 묶음(1~3개) → **마스킹 facts 조각 + 인용 키 목록**. 순수 함수 `extract(facts, rule_id, bundles, labels) -> AskPiece` (`labels` 는 `infrastructure/display_labels.load_display_labels()` 결과를 서비스가 넘김 — domain 은 파일을 안 읽음). 묶음 이름 목록은 `domain/constants.ASK_BUNDLES`(8개, 이 순서). 키 이름은 위 "fact 키" 표 그대로 — 조각에 들어간 칸 중 **이 케이스 `fact_keys(facts)` 에 실제로 있는 키만** 인용 키가 된다.

| 묶음 | 꺼내는 마스킹 facts 칸 | 인용 키 |
|---|---|---|
| `subject` | `subject`(account_key 마스킹) · `customer` · `prior_alert_count` · `reporting_institution` | `subject` · `subject.account_key` · `subject.entity_name` · `subject.entity_type` · `customer.<칸>` · `prior_alert_count` |
| `flows` | `period` · `inbound` · `outbound` · `internal` · `amount_range` · `direction` · `unmapped_currencies` | `period` · `inbound.count` · `inbound.amount.<통화>` · `outbound.count` · `outbound.amount.<통화>` · `internal.count` · `amount_range.<통화>.min/max` · `direction` · `unmapped_currencies.<이름>` |
| `counterparties` | `counterparties` · `counterparty_banks` · `counterparties_by_direction`(원본에서, 값이 있을 때만 — SCRUM-358·359) | `counterparties.count` · `counterparty_banks.same_bank_accounts` · `counterparty_banks.other_bank_accounts` · **질문 답변 전용** `counterparties_by_direction.{inbound\|outbound}.{count\|same_bank_accounts\|other_bank_accounts}` → 그 방향 `transaction_ids` |
| `formats` | `payment_formats` · `payment_format_counts` · `direction` | `payment_formats` · `payment_format_counts.<방식>` · `direction` |
| `paths` | `paths` — `VERIFIED` 면 kind·count·max_hops·max_accounts(마스킹과 같음), 아니면 **빈 조각** | `paths.count` · `paths.max_hops` · `paths.max_accounts` · `paths.kind` |
| `observations` | `observations` — name·value·unit·window_start·window_end·basis (**baseline 뺌**) | `observations.<이름>` |
| `score_reasons` | `model_signals` · `observations` — name·value·unit·**baseline** | `model_signals` · `observations.<이름>` |
| `rule_facts` | `typology` · `typology_source` · 경보 `rule_id` · `period` | `typology` · `period` |

- 조각은 마스킹본(`mask_for_llm`)에서 꺼낸다 — 거래 ID 없음, 계좌 뒤 4자리. 같은 칸이 두 묶음에 걸리면(`direction`·`period`·`observations`) 한 번만 넣는다. `observations`·`score_reasons` 를 함께 고르면 관측 항목은 두 칸 집합의 합(window·basis·baseline 모두).
- **넣지 않는 것**: `excluded_self_transfer_count`(인용 키가 없고 COUNT 검사 집합에도 없어 쓰면 MISMATCH) · `indirect`(마스킹이 이미 뺌) · 경보 `rule_facts` 숫자와 `window_start/end`(facts 밖 숫자·날짜라 검사에서 거짓 UNVERIFIED) · 기여값(SHAP 숫자 — 어느 묶음에도 없음, 규약 3절).
- `observations`·`score_reasons` 를 나눈 이유: 이유 질문의 "모델 설명"(05 `ask_answer_v1` "모델이 주목한 점:")은 `score_reasons` 에서만 나오게 하고, 관측 사실 질문은 기준값 없이 값만 본다. `score_reasons` 는 설계 문서 6.2 의 "키 없음"이 아니라 `model_signals` 키(근거 거래 없음)와 `observations.<이름>` 을 인용한다 — 키가 없으면 이유 답이 cites 를 못 채워 502 가 된다.
- 코드값 한글 표기: 조각에 나온 코드(업종·위험 등급·목적·결제 방식·유형·엔티티 유형·관측 이름·관측 단위)의 표기만 `labels` 로 함께 준다(`contracts/display_labels_v1.json`, 05 narrative_v4 "표기 사전"과 같은 파일). **통화는 표기를 주지 않고 ISO 코드 그대로** — 금액 검사가 통화 코드 짝으로 가장 안정적으로 읽는다(summary_v1 규칙 2 와 같음 — 요약은 summary_v2 부터 금액 칸만 `62,992,819.38 유로(EUR)` 완성 문자열, 05 summary_v2. 질문 답변은 그대로).
- 묶음 이름이 목록 밖이면 함수가 `ValueError` — 서비스까지 오기 전에 `AskPlanOut` 스키마가 먼저 막는다(`LLM_INVALID_OUTPUT`).
- **질문 답변 인용 키** = `fact_keys(facts)` + 위 `counterparties_by_direction.*` 키(`ask_fact_keys`, 칸이 `null` 이면 없음). `EVIDENCE_IN_SCOPE`·근거 거래(`evidence_ids`)는 이 목록 기준(06). 초안 `fact_keys` 는 그대로.

### 계획 보강 (`ask_bundles.with_flows`, SCRUM-358 ④)

질문(LLM 복사본 — NFKC·계좌 가린 것)에 방향 낱말이 있으면 코드가 계획 묶음 뒤에 `flows` 를 붙인다 — 방향 질문에 `inbound`·`outbound`·`direction` 이 조각에 들어오게.
- 방향 낱말 `ASK_DIRECTION_WORDS`(`constants_ask`) = 검사 방향 낱말(`DIRECTION_IN/OUT/INTERNAL_WORDS`, 그대로) + `들어온`·`들어오`·`나간`·`나가`·`보내`·`받았`·`유입`·`유출`·`송금`. 검사 쪽 목록은 넓히지 않는다(넓히면 초안 TX_COUNT 판정이 바뀜)
- 이미 `flows` 가 있거나 범위 밖이면 그대로. **계획이 3개를 골랐으면 붙이지 않는다** — `generation_meta.bundles` 는 계약·백엔드 검사(`requireAskResponse`)가 1~3개라 4개가 되면 502
- 붙인 `flows` 는 계획 프롬프트의 "묶음 1~3개"에 안 셈(계획 출력 뒤 코드) — `generation_meta.bundles` 에는 넣고(실제 꺼낸 묶음), 저장 행 `plan.bundles` 는 계획이 고른 그대로

### 답 자리표 (`ask_slots.py`, SCRUM-362 — `ask_answer_v3`)

답 LLM 은 숫자·금액·날짜·계좌·건수를 **직접 쓰지 않고 자리표만** 쓴다. 코드가 자리표를 **이름표 + 값**으로 바꾼다 — 숫자와 그 뜻(방향·종류)이 같은 키에서 나오므로 숫자 틀림·방향 어긋남이 구조적으로 없다(초안 v4 "숫자 문장은 코드" 원칙을 질문 답변으로 넓힘, 09 2026-11-23). 순수 함수 `render(answer, piece, labels) -> AskSlots`(렌더링한 문장 · 자리표 키 목록 · 오류 목록).

- **모양**: `{{키}}` · 조사를 붙이면 `{{키|조사}}`. 키 글자는 fact 키 그대로(`[A-Za-z0-9_.]+` — 통화·결제 방식·관측 이름 포함). 홑중괄호 `{`·`}` 는 글자 그대로.
- **허용 키 = `piece.keys`**(이 케이스 `ask_fact_keys` ∩ 이번 묶음의 인용 키 — 위 표). 값은 **`piece.content`(마스킹 조각)** 에서만 꺼낸다 — 계좌는 `10_****BD30`, 거래 ID 없음. 이름표 한글은 `labels`(표기 사전 전체, `display_labels_v1.json`).
- **cites = 답에 나온 자리표 키**(나온 순서, 중복 제거) — LLM 은 cites 를 쓰지 않는다. 근거 거래 = 그 키들의 거래 ID 합집합(06).
- 오류(전부 06 에서 UNVERIFIED — 502 아님): 허용 키 밖 · 닫힘 없음(`{{k`)·빈 키·중첩·목록 밖 조사 · 이름표·값을 못 찾는 키(예: 표기 사전에 없는 업종·결제 방식 코드) · 자리표 0개.
- `<fact_keys>`(05 v3)는 같은 표의 **이름표만**(값 없이) — `키 — 이름표`. **값을 렌더링할 수 없는 키(빈 목록 등)는 목록에서 뺀다**(추가 검토 1 M1 — 써도 자리표 오류). 코드 `ask_slot_labels.slot` 이 (이름표, 값) 쌍을 한 번에 돌려줘 렌더링과 프롬프트가 같은 표를 쓴다.
- 값 표기는 초안 v4 슬롯 도우미(`display_format`)를 그대로 쓴다 — 건수·계좌 수 천 단위 쉼표, 금액은 facts 문자열의 정수부에 쉼표만(소수 그대로), **통화는 ISO 코드**(`27,250.50 USD` — 질문 답변 v1·v2 와 같음), 날짜 `YYYY년 M월 D일`, 시각 `HH:MM`(초가 있으면 `:SS`). 합산·환산·반올림 없음(아래 "표시용 파생" 원칙).

| 키 | 렌더링 (N = 값) |
|---|---|
| `inbound.count` · `outbound.count` · `internal.count` | 입금 거래 N건 · 출금 거래 N건 · 내부 거래 N건 |
| `inbound.amount.<C>` · `outbound.amount.<C>` | 입금 합계 N C · 출금 합계 N C |
| `amount_range.<C>.max` · `.min` | 입출금 중 최대 거래 금액 N C · 입출금 중 최소 거래 금액 N C (방향 없는 값이라 이름표에 범위) |
| `counterparties.count` | 입출금 전체 상대 계좌 N개 |
| `counterparty_banks.same_bank_accounts` · `.other_bank_accounts` | 입출금 전체 상대 중 자행 계좌 N개 · 타행 계좌 N개 |
| `counterparties_by_direction.inbound.count` · `.outbound.count` | 입금 상대 계좌 N개 · 출금 상대 계좌 N개 |
| `counterparties_by_direction.<방향>.same_bank_accounts` · `.other_bank_accounts` | 입금(출금) 상대 중 자행 계좌 N개 · 타행 계좌 N개 |
| `payment_format_counts.<F>` | 결제 방식 한글(코드) N건 (입출금 합 — 결제 방식 건수는 방향 없음) |
| `payment_formats` | 결제 방식 한글(코드), 한글(코드)… **(대외 거래 기준)** — 결제 방식 집계는 입금·출금 거래만이라 **근거에 내부·간접 거래가 있으면 값 없음**(케이스 전체 결제 방식을 확인 못 함 — 추가 검토 3 H1, `payment_format_counts.*` 도 같음) — **빈 목록(내부 거래만)이면 값 없음 → 자리표 오류, `<fact_keys>` 에서도 뺌**(추가 검토 1 M1) |
| `direction` | **추가 검토 3 H3 — 배타·부재(`대외 입금만`·`대외 출금만`·`대외 입출금 없음`)는 근거가 경보 거래 전체이고(요청 `evidence_transaction_ids` = `alert.transaction_ids`) 경보 거래의 모든 계좌에 법인 매핑이 있을 때만**(서비스가 `AskScope` 로 넘김 — 녹화 도구·평가처럼 범위를 모르면 늘 아래 꼴). 그 밖에는 `입금 우세 (근거 거래 기준)`·`출금 우세 (근거 거래 기준)`·`입금·출금 모두`·`대외 입출금 확인 안 됨 (근거 거래 기준)` · 아래는 추가 검토 2 때 규칙: 거래 방향 **입금 우세 · 출금 우세** · 입금·출금 모두 · **대외 입출금 없음**(`INTERNAL` — 입출금 둘 다 0, 내부·간접만일 수도 있어 "내부 거래만"이라 하지 않음, 추가 검토 2 H1) · 반대 방향 0건이 확인되면 **대외 입금만·대외 출금만**(내부 거래는 범위 밖임을 이름표에) (`INBOUND`·`OUTBOUND`·`MIXED`·`INTERNAL` — `INBOUND` 는 입금이 출금의 2배 이상이라 출금이 있을 수 있음, 04 `_direction`). **반대 방향 0건이 조각의 `outbound.count`·`inbound.count` 로 확인될 때만 `입금만`·`출금만`**(추가 검토 1 H1 — 조각에 건수가 없는 `formats` 묶음은 늘 `우세`) |

**집계 값의 범위 표시 (SCRUM-362 ★B8 — 추가 검토 4 N-1·N-2, 진희)** — 이름표 **제목은 안 바꿈**(제목은 `<fact_keys>` 줄로 프롬프트에 들어가 녹화 키를 만듦), **값 끝**에만 붙임:
- **근거 범위(N-1)**: 서비스가 센 `AskScope.whole_alert` 가 참이 아니면(근거가 경보 일부 · 범위 모름 None) 근거 거래로 센 값 끝에 `(근거 거래 기준)` — 대상 키: `period` · `inbound.*`·`outbound.*`·`internal.*` · `counterparties.count`·`counterparty_banks.*`·`counterparties_by_direction.*` · `payment_formats`·`payment_format_counts.*` · `amount_range.*` · `compare.*`. 0건·부재가 경보 전체처럼 읽히는 것을 막음
- **대외 범위(N-2)**: 근거에 내부·간접 거래가 있으면 대외 입출금(`flows`)만 센 값 끝에 `(대외 거래 기준)` — 대상: `inbound.*`·`outbound.*` · `counterparties.count`·`counterparty_banks.*`·`counterparties_by_direction.*` · `amount_range.*` · `compare.*`(결제 방식은 ★B7-1 대로 늘 대외 기준 표시 · 내부·간접 있으면 값 없음)
- 둘 다면 `(근거 거래 · 대외 거래 기준)`. 방향(`direction`)은 위 행 규칙(배타·부재는 근거 = 경보 전체 + 소유 정보 있을 때만)
- **평가·재생·녹화 도구도 같은 `ask_scope` 로 계산**(`tools/ask_fixture_scope.py`): 근거·경보 거래 ID 는 요청 예시에서, 소유 정보는 픽스처에 있는 만큼만(대상 계좌의 법인뿐 — 상대 계좌 매핑이 픽스처에 없어 `ownership_known` 거짓). 하드코딩 True/None 안 씀
| `period` | 거래 기간 YYYY년 M월 D일 HH:MM ~ YYYY년 M월 D일 HH:MM |
| `subject.account_key` | 대상 계좌 10_****BD30 |
| `subject.entity_name` · `subject.entity_type` · `subject` | 보고 대상자 이름 · 대상자 유형 한글 · 보고 대상자 이름(유형 한글) — 유형이 없으면 이름만 |
| `customer.industry` · `.risk_level` · `.account_purpose` | 업종 한글 · 고객 위험등급 한글 · 계좌 목적 한글 |
| `customer.onboarded_at` · `.country_code` | 고객 등록일 YYYY년 M월 D일 · 고객 국가 코드 XX |
| `prior_alert_count` | 과거 경보 N건 |
| `typology` | 탐지 유형 한글(코드) |
| `paths.count` · `.max_hops` · `.max_accounts` · `.kind` | 확인된 경로 N개 · 경로 최대 N단계 · 경로 하나가 거친 계좌 최대 N개 · 경로 형태 한글(코드) (`typology` 표기 사전 — `CYCLE`·`SCATTER_GATHER` 가 있음) |
| `compare.count` | 거래 건수 비교 — 입금 N건, 출금 M건 · 입금이 더 많음 / 출금이 더 많음 / 같음 (코드가 대소 계산 — 원칙 (B), flows 조각에 입금·출금이 둘 다 있을 때, 근거 = 입금·출금 거래 합집합) |
| `compare.amount.<C>` | <C> 합계 비교 — 입금 N C, 출금 M C · 입금이 더 많음 / 출금이 더 많음 / 같음 (**그 통화가 입금·출금 둘 다 있을 때만** — 한쪽만이면 키 없음, 근거 = 두 방향 그 통화 거래) |
| `observations.<이름>.vs_baseline` | 관측 이름 한글 관측값 N · 평소 기준값 M · 기준값보다 높음 / 낮음 / 같음 (score_reasons 조각에 기준값이 있을 때만, 근거 거래 없음) |
| `observations.<이름>.baseline` | 관측 이름 한글 평소 기준값 N — **`score_reasons` 조각에 baseline 이 null 이 아닐 때만** 인용 키(질문 답변 전용, 근거 거래 없음, 추가 검토 2 M2) |
| `observations.<이름>` | 관측 이름 한글 관측값 N단위 — 관측 구간 양 끝이 있으면 뒤에 `(시작~끝 기준)`(초안 v4 GROUNDS 와 같은 표기: 값 `obs_value`, 단위 `observation_name_unit`, 없으면 `observation_unit`). **표기 사전에 없는 관측 이름은 코드값 그대로**(facts 값이라 참 — 평가 픽스처 `inflow_outflow_ratio_2h`, SCRUM-362 ★B2) |
| `model_signals` | 모델이 주목한 지표 한글, 한글… (`observation_name` 표기, 없으면 코드값) |
| `unmapped_currencies.<이름>` | <이름> 통화 거래 N건(대응 미확인) |

- **조사** `{{키|조사}}` — 쌍 은/는 · 이/가 · 을/를 · 과/와 · 으로/로 · 이에요/예요 · **이며/며 · 이고/고**(연결 조사 — 사실 주장 없음, v6 규칙 13 끝맺음과 검사 어긋남 해소, SCRUM-362 ★B7-3 · 2026-11-23), **쌍의 어느 쪽을 써도 같은 쌍**. 렌더링한 말의 끝 글자로 고른다(`display_format` 과 같은 규칙 — 한글 받침 · 숫자 0·1·3·6·7·8 받침 · 영문 끝은 받침 없음(`USD가`) · ㄹ 받침은 `로`). **닫는 괄호·마침표 같은 문장부호로 끝나면 그 앞 마지막 한글 글자 기준**(`(대외 거래 기준)이며` · `자금 분산(FAN_OUT)은` — 괄호 안이 영문이면 괄호 앞 한글, ★B7-3 진희). 조사 없이 `{{키}}` 만 쓰고 뒤에 LLM 이 조사를 붙여도 막지 않음(어색할 수 있음 — 프롬프트로 `|조사` 권장, 05).
- 자리표 밖 숫자·한 방향 질문·길이 판정은 06 "질문 답변" — 렌더링 결과에 대해 돈다.

## 표시용 파생은 facts 가 아니다 (SCRUM-228, 2026-11-17)

narrative_v4 의 **표기 사전·슬롯 문장·derived 플래그·사유/종합의견 카탈로그 선택**(05 narrative_v4 절)은 facts 에서 **표시용으로 파생한 값**이다 — facts 스키마·`fact_keys`·응답 `facts` 에 넣지 않고, 검증(06)도 대조하지 않는다. 검증은 지금처럼 조립된 본문을 facts 원값과 대조한다. 파생 함수는 `str/domain/` 순수 함수로 facts(마스킹본)를 읽기만 하고, 새 숫자를 만들지 않는다(쉼표·날짜 형식만, 합산·환산·반올림 없음). 플래그는 bool 뿐.

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
