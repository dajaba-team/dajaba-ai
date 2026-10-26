# 03. 처리 순서 — 세 엔드포인트

정본: `str/api/router.py`, `str/application/draft_service.py`·`verify_service.py`·`summary_service.py`, `str/infrastructure/*_repository.py`. 규약 6.1의 엔드포인트, 7절 그림의 흐름을 함수 순서로 적은 것.

## `POST /v1/str/drafts`

요청(규약 5.1): `draft_id`, `case_no`, `alert`(규약 2절 경보 + `typology`, `typology_source`), `transaction_ids`(근거 거래 — 안건 7 뒤 `evidence_transaction_ids`로 이름 바뀔 수 있음), `prior_alerts`, `investigator_notes`, `reporting_institution`.

```
1  요청 검증                 schemas.str.DraftRequest (Pydantic) — 실패 400 INVALID_REQUEST
2  transaction_reader.load_transactions(ids)   ops.transactions WHERE transaction_id = any(...)  — 1 쿼리
   transaction_reader.load_subject(alert)      accounts / entities / customer_attributes       — 1~3 쿼리
3  facts = domain.facts.build_facts(...)                 순수 (04)
4  facts_masked = domain.masking.mask_for_llm(facts)     순수 (04)
5  examples = fewshot_store.pick_examples(facts.typology)        (05)  같은 유형 1 + 다른 유형 2
6  references = retriever.retrieve(facts)                        (10)  RetrievalUnavailable → []  ※ 초안을 막지 않음
7  gen = narrative_generator.generate(facts_masked, examples, references, notes)  (05)
      LLM 1회 + 스키마 검증. 검증 실패 → 1회 재시도 → 또 실패면 LlmInvalidOutput (502 LLM_INVALID_OUTPUT)
8  [안건 17 미결] 자동 검증 1회를 여기서 돌릴지. 권장: MVP는 안 돌림, verification: null
9  generation_repository.save_draft(req, facts, gen, meta)
10 응답 schemas.str.DraftResponse: {draft_id, facts(원본), narrative, generation_meta, verification: null}
```

LLM에는 **마스킹한 facts**가 가고, 응답에는 **원본 facts**가 돌아간다. 거래 행 원본은 LLM에 주지 않는다(주면 직접 더해서 다른 숫자를 만든다).

## `POST /v1/str/verify`

요청(규약 5.3): `draft_id`, `revision_no`, `narrative`(조사역 수정본 6섹션).

```
1  요청 검증
2  draft = generation_repository.load_latest_draft(draft_id)   generations WHERE kind=DRAFT AND draft_id — 없으면 404 DRAFT_NOT_FOUND
   facts, transaction_ids = draft.facts, draft.transaction_ids
3  code_checks = domain.verification.run_code_checks(facts, narrative, transaction_ids)   순수 (06) — 4개
4  if all(c.match for c in code_checks):
       llm_checks = judge.run(facts, narrative)   (06) — 5개
       LlmUnavailable·LlmInvalidOutput → llm_checks=None, status=VERIFY_UNAVAILABLE
   else:
       llm_checks=None, status=CODE_FAILED       ※ 코드가 틀렸으면 평가자를 부르지 않는다 (비용, 어차피 fail)
5  passed = all code match AND llm_checks is not None AND all(score >= 4)    (안건 9 권장안)
6  verification_repository.save(generation_id, draft_id, revision_no, code_checks, llm_checks, passed, status, verifier_version)
   (judge 호출 메타를 generations kind=VERIFY 로 남기는 건 W3 에 추가)
7  응답 schemas.str.VerifyResponse: {verification_id, passed, status, code_checks, llm_checks, verifier_version, produced_at}
```

`status` 값: `PASSED` / `CODE_FAILED` / `LLM_FAILED` / `VERIFY_UNAVAILABLE`. 백엔드 `ApprovalGate`는 `PASSED`만 승인 요청을 허용하고, `VERIFY_UNAVAILABLE`이면 "다시 검증" 버튼을 띄운다.

## `POST /v1/cases/summary` (W4 말)

같은 `transaction_reader → facts → masking`, 프롬프트만 `summary_v1.md`(5줄), 검증은 코드 4종만(평가자 없음), `generations.kind=SUMMARY`. 요약 문장은 관측 사실만 쓰고 모델 설명은 "모델이 주목한 점" 한 줄로 따로 — 점수 설명과 관측을 섞지 않는다.

## 시간 예산 (90초 타임아웃, 규약 6.2)

| 단계 | 예산 |
|---|---|
| loader | 1초 |
| retrieval (임베딩 1회 + pgvector) | 1~2초 |
| generate | 10~40초 (재시도 시 ×2) |
| judge | 5~20초 |

drafts 안에서 generate + judge를 다 돌리면 빠듯하다 — 안건 17에서 분리를 권장하는 이유. `LLM_TIMEOUT_S`(기본 60)는 호출 1회 기준.

## 에러 (규약 6절, `shared/errors.py`)

| 예외 | HTTP | code | 재시도(백엔드 `AiClient`) |
|---|---|---|---|
| 요청 스키마 위반 | 400 | `INVALID_REQUEST` | 0 |
| 내부 키 틀림 | 401 | `UNAUTHENTICATED` | 0 |
| draft 없음 | 404 | `DRAFT_NOT_FOUND` | 0 |
| LLM 응답 스키마 위반(재시도 후) | 502 | `LLM_INVALID_OUTPUT` | 0 |
| LLM 연결 실패·타임아웃 | 502 | `LLM_UNAVAILABLE` | 1 (연결·타임아웃만) |
| 예산 초과 | 502 | `LLM_BUDGET_EXCEEDED` | 0 |
| 그 밖 | 500 | `INTERNAL` | 0 |

재시도 횟수 **1회**는 규약 6.2·레퍼런스 8.5·안건 21 전부 동일. AI 서버 안에서 LLM을 중첩 재시도하지 않는다(스키마 실패 1회 재생성은 재시도가 아니라 생성 절차의 일부).
