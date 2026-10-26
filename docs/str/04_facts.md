# 04. facts — 정본 JSON과 계산 규칙

정본: `str/domain/facts.py` `build_facts(req, txs, subject, reasons) -> Facts`, `str/domain/masking.py` `mask_for_llm(facts) -> Facts`, `shared/schemas/str.py` `Facts`. 입력 dataclass(`Transaction`, `Subject`)는 `str/domain/models.py`, 읽기는 `str/infrastructure/transaction_reader.py`.

**순수 함수.** 같은 입력에 항상 같은 facts. LLM은 facts만 보고 쓰고, 검증은 facts와 대조한다 — facts가 틀리면 전부 틀리므로 여기 규칙이 제일 촘촘하다.

## 정본 JSON (응답 `facts`와 같다)

```json
{
  "reporting_institution": "Portugal Bank #4507",
  "subject_entity_id": "80062E240",
  "subject_entity_name": "Sole Proprietorship #50438",
  "subject_account_keys": ["010_8000EBD30"],
  "period_start": "2022-09-02T00:14:00",
  "period_end": "2022-09-02T22:51:00",
  "transaction_count": 47,
  "total_amount": "320000000.00",
  "currency": "US Dollar",
  "mixed_currency": false,
  "direction": "INBOUND",
  "counterparty_count": 31,
  "payment_formats": ["ACH"],
  "typology": "FAN_IN",
  "typology_source": "RULE",
  "customer": {"industry": "RETAIL", "risk_level": "LOW", "account_purpose": "SALES_DEPOSIT", "onboarded_at": "2021-03-14", "country_code": "PT"},
  "prior_alert_count": 1,
  "top_reasons": ["distinct_senders_24h = 31 (평소 3.4)", "outflow_ratio_2h = 0.95"]
}
```

## 계산 규칙 (코드가 전부 정한다)

| 필드 | 규칙 |
|---|---|
| `subject_account_keys` | 경보의 대상 계좌. 룰에 따라 1개(대부분) 또는 여러 개(CYCLE·BIPARTITE) |
| `direction` | 대상 계좌가 `to_account_key`인 거래가 과반이면 `INBOUND`, 아니면 `OUTBOUND`, 반반이면 `MIXED` |
| `currency` (기준 통화) | 대상 거래 중 **건수가 가장 많은 `currency_paid`**. 동률이면 금액 합이 큰 쪽 |
| `total_amount` | 기준 통화 거래의 `amount_paid` 합. **문자열**, 소수 2자리 고정, 천 단위 구분 없음. float 금지 — JSON number로 주면 백엔드·LLM이 다르게 반올림한다. (규약 공통 타입은 숫자지만 facts만 예외 — `shared/01`) |
| `mixed_currency` | 기준 통화 외 거래가 1건이라도 있으면 `true`. 이때 프롬프트에 "다른 통화 거래 N건은 금액 합계에서 제외됨" 한 줄이 들어간다 |
| `period_start` / `period_end` | 대상 거래 `ts`의 min / max. ISO 8601 초 단위, 시간대 없음(IBM 원본). 룰 창이 아니라 **실제 거래 범위** |
| `transaction_count` | 대상 거래 수(`is_self_transfer` 제외 후) |
| `counterparty_count` | 상대 `account_key` distinct. `is_self_transfer` 거래는 집계 전체에서 제외 |
| `payment_formats` | distinct, 원본 문자열 그대로(ACH, Wire, Cash, …) |
| `typology` / `typology_source` | 요청 JSON 그대로. `typology_source`는 `RULE`만(안건 8 권장) |
| `customer` | `customer_attributes` 행. 없으면 `null` |
| `prior_alert_count` | 요청 `prior_alerts` 길이. **내용(과거 룰 ID·결과)은 LLM에 주지 않는다** — "전에도 걸렸다"는 추측의 근거가 되기 쉽다 |
| `top_reasons` | 점수 JSON `reasons` 상위 3개를 `"이름 = 값 (평소 기준값)"` 문자열로. 점수가 없으면 빈 배열 — 초안은 만든다 |
| 없는 값 | `subject_entity_name`·`customer` 등은 `null`. LLM에는 "정보 없음"으로 전달, 모르는 걸 지어내지 말라는 규칙(05)이 받는다 |

### 결정 사항 (바꾸려면 `09_decisions.md`에 적고)

- 기준 통화 = 건수 최다(금액 최다 아님). 이유: 소수 고액 외화 1건이 전체 보고서 통화를 바꾸면 안 된다. 10/26 진희 판단, 준영 이견 가능.
- 허용 오차 0. `"320,000,000"`과 `"3억 2천만"`은 같은 Decimal이라 통과, `"약 3억"`은 fail. "약"을 쓰고 싶으면 facts에 반올림 값을 따로 넣는 게 맞고 MVP는 안 넣는다.
- 거래 행 원본은 LLM에 안 준다. facts 요약만.

## 마스킹 (`masking.py`)

LLM에 가는 facts만 바꾼다. 응답·DB는 원본.

| 필드 | 처리 |
|---|---|
| `subject_account_keys`, 상대 계좌 | 뒤 4자리만 (`010_****BD30`) |
| `reporting_institution` (은행명) | 그대로 |
| `subject_entity_name` (고객명) | 그대로 — IBM 합성 데이터라 실명이 아님. 실데이터 전환 시 여기서 가명화 (MVP 정의서 8절 "한계" 4번) |
| `subject_entity_id` | 그대로 (합성) |
| 그 밖 | 그대로 |

마스킹은 **검증에 영향이 없다** — 검증은 원본 facts와 narrative를 대조하고, narrative에는 계좌번호가 뒤 4자리로만 나오므로 `COUNTERPARTY_COUNT`·`AMOUNT_MATCH`는 그대로 성립.

## 입력 (transaction_reader)

- `transactions`: 요청 `transaction_ids`로 `ops.transactions` 1 쿼리. 컬럼 `transaction_id, ts, from_account_key, to_account_key, amount_paid, currency_paid, amount_received, currency_received, payment_format, is_self_transfer`. `is_laundering`·`pattern_*` 컬럼은 **SELECT 목록에 없다** — 정답 라벨이 서빙에 새면 안 된다.
- `accounts`/`entities`/`customer_attributes`: 대상 계좌 키로.
- 요청의 ID가 DB에 없으면 400 `INVALID_REQUEST`에 없는 ID(최대 10개)와 개수 포함.
