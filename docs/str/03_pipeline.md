# 03. 처리 순서 — 세 엔드포인트 (규약 v0.2)

정본: `str/api/router.py`, `str/application/draft_service.py`·`verify_service.py`·`summary_service.py`, `str/infrastructure/*_repository.py`. 규약 5·6절을 함수 순서로 적은 것. 10/27 반영: `draft_id` 중복 방지(PROCESSING 선점), `generation_id`, AI 내부 재시도 삭제, 시간 예산, FAILED 행, cites → evidence_ids.

## `POST /v1/str/drafts`

요청(규약 5.1): `draft_id`(백엔드 시퀀스 선발급), `case_no`, `alert`(2절 경보), `evidence_transaction_ids`(**= `alert.transaction_ids` 전체** — 점수의 근거 부분집합 아님, `str/04`), `reasons`(3절 그대로), `prior_alert_count`, `investigator_notes`, `reporting_institution`.

```
0  요청 검증                 schemas.str.DraftRequest — 실패 400 INVALID_REQUEST. evidence_transaction_ids == alert.transaction_ids(집합)도 여기서 (04)
1  선점  generation_repository.claim(draft_id, request_hash)        규칙 정본 shared/03 "같은 draft_id 재요청"
   ── 짧은 트랜잭션 하나 (a~d), LLM 호출 전에 커밋 ──
   a  잠금                     pg_advisory_xact_lock(hashtext('draft:' || draft_id)) — 같은 draft_id는 한 번에 하나
   b  오래된 PROCESSING 정리   created_at < now − STALE_PROCESSING_S 인 PROCESSING → FAILED(STALE_PROCESSING)
   c  해시 비교                같은 draft_id 행이 (상태 무관) 있고 request_hash 다름 → 400 INVALID_REQUEST ("draft_id reused with different body")
   d  INSERT generations(kind=DRAFT, draft_id, status=PROCESSING, request_hash, request)
        ON CONFLICT (draft_id) WHERE kind='DRAFT' AND status <> 'FAILED' DO NOTHING RETURNING generation_id
      0행(충돌) → 살아 있는 행을 SELECT해서 →
        기존 행 SUCCEEDED  → 해시 같음 확인 후 저장된 response 그대로 반환 (LLM 호출 없음, 2xx)
        기존 행 PROCESSING → 409 GENERATION_IN_PROGRESS (백엔드는 재시도 안 함, "생성 중")
      충돌 없음 (처음, 또는 이전 시도가 전부 FAILED) → 새 generation_id로 계속
2  transaction_reader.load_transactions(evidence_transaction_ids)   ops.transactions WHERE transaction_id = any(...) — 1 쿼리. 대상 계좌가 없는 거래(경로형 경보의 중간 거래)도 그대로 읽는다 → facts indirect, 경로 확인은 rule_facts.paths로 (04)
   transaction_reader.load_subject(alert.account_key)               accounts / entities / customer_attributes — 1~3 쿼리
   없는 ID가 있으면 400 INVALID_REQUEST (message에 없는 ID 최대 10개 + 개수) → 행 FAILED
3  facts = domain.facts.build_facts(req, txs, subject)                       순수 (04) — observations는 req.reasons에서
4  facts_llm = domain.masking.mask_for_llm(facts)                            순수 (04) — 생성·평가자 공용
5  examples = fewshot_store.pick_examples(facts.typology)                    (05) 같은 유형 1 + 다른 유형 2
6  references = retriever.retrieve(facts)                                    (10) 0~3건. RetrievalUnavailable → [] ※ 초안을 막지 않음
7  gen = narrative_generator.generate(facts_llm, fact_keys(facts), examples, references, notes)   (05)
      LLM 1회(35초) + NarrativeOut 스키마 검증(섹션 6개 각 1회, cites ⊆ fact_keys)
      스키마 실패 → 남은 예산 ≥ 40초면 1회 재생성, 아니면 바로 → 또 실패 LlmInvalidOutput (502)
      연결 실패·타임아웃 → LlmUnavailable (502). ★ AI 안에서 연결 재시도 없음 — 재시도는 백엔드 AiClient 1회만
8  narrative = domain.facts.attach_evidence(gen.narrative, facts)            순수 — cites의 fact 키 → 거래 ID 합집합 = evidence_ids
9  generation_repository.finish(generation_id, SUCCEEDED, facts, response, meta)
      UPDATE … WHERE generation_id=$1 AND status='PROCESSING' — 0행이면(STALE로 이미 닫힘) 결과 버림, 500 INTERNAL (shared/03 펜싱)
10 응답 DraftResponse: {draft_id, generation_id, facts(원본), narrative(cites+evidence_ids), generation_meta, verification: null}
```

- 어느 단계든 예외 → `generation_repository.finish(generation_id, FAILED, error=code+message)` 뒤 에러 응답(같은 `status='PROCESSING'` 조건). **FAILED 행은 지우지 않는다**(재처리·비용 추적).
- LLM에는 **마스킹한 facts**와 **fact 키 목록**이 가고, 응답에는 **원본 facts**가 돌아간다. 거래 행 원본·거래 ID 목록은 LLM에 주지 않는다 — LLM은 거래 ID를 고르지 않는다(안건 23 세부, 2차 검토 반영).
- `verification`은 항상 `null`(안건 17). 초안 직후 자동 검증은 하지 않는다 — 조사역이 "검증" 버튼.

## `POST /v1/str/verify`

요청(규약 5.3): `generation_id`, `revision_no`, `narrative`(조사역 수정본, 섹션 6개 각 1회 — 생성본과 같은 스키마).

```
0  요청 검증                  NarrativeOut 과 같은 제약 (섹션 중복·누락 → 400)
1  gen = generation_repository.load(generation_id)        kind=DRAFT, status=SUCCEEDED — 없으면 404 DRAFT_NOT_FOUND
   facts, evidence_scope = gen.facts, gen.request.evidence_transaction_ids
2  sha = shared.hashing.narrative_sha256(narrative)      규약 5.3 해시 규칙 (shared/01)
3  code_checks = domain.verification.run_code_checks(facts, narrative, evidence_scope)   순수 (06) — 유형별 대조
4  if all(c.match):
       llm_checks = judge.run(mask_for_llm(facts), narrative)      (06) 5개. 평가자도 마스킹본
       LlmUnavailable·LlmInvalidOutput → llm_checks=None, status=VERIFY_UNAVAILABLE   (자동 재시도 없음)
   else:
       llm_checks=None, status=CODE_FAILED        ※ 코드가 틀렸으면 평가자를 부르지 않는다 (비용, 어차피 fail)
5  passed = all(code match) AND llm_checks is not None AND all(score >= JUDGE_PASS_SCORE=4)    (안건 9)
   status = PASSED | LLM_FAILED | CODE_FAILED | VERIFY_UNAVAILABLE
6  verification_repository.save(generation_id, draft_id, revision_no, sha, code_checks, llm_checks, passed, status, verifier_version)
   judge 호출 메타는 generations(kind=VERIFY) 한 행 (W3)
7  응답 VerifyResponse: {verification_id, generation_id, revision_no, narrative_sha256, passed, status, code_checks, llm_checks, verifier_version, produced_at}
```

- `VERIFY_UNAVAILABLE`은 검증 실패가 아니다 — 백엔드는 한 줄로 저장해 "검증 못 함"이 보이게 하고 "다시 검증" 버튼(채영). 승인 불가.
- 백엔드 `ApprovalGate`: 승인 요청은 **이 생성본·이 본문의 passed 검증**이 있을 때만(규약 4절 DRAFTED → PENDING_APPROVAL 조건과 같은 말). 세 조건: ① 검증의 `generation_id` == 현재 활성 초안의 `generation_id` ② 검증의 `narrative_sha256` == 현재 본문 해시 ③ `passed = true`. 해시만 보면 다른 생성본(다른 facts)에서 같은 문장이 나온 검증이 통할 수 있어서 ①을 둔다. `revision_no`는 **맞추지 않는다** — 같은 생성본에 본문이 같으면 대조한 facts도 같으니, 되돌린 수정본(rev 3 본문 = rev 1 본문)은 rev 1 검증으로 승인할 수 있다. **단 보완 요청(NEED_REVISION) 반려 뒤에는** 본문 해시가 반려 당시 해시와 같으면 백엔드가 409 `NARRATIVE_UNCHANGED`로 막는다(안건 24) — AI 서버는 할 일 없음. 수정 저장과 승인 요청이 동시에 오는 경우는 백엔드가 승인 트랜잭션 안에서 현재 본문 해시를 다시 읽어 비교(채영 V009에서 정함 — 미결 `09`). "최신 검증"이 아니라 "이 본문의 검증".
- 수정본에서 `cites`·`evidence_ids`를 다시 계산해 응답에 넣을지는 **W3 결정**(채영 답). 들어가면 평가자 출력에 섹션별 cites를 받아 코드가 `attach_evidence`를 다시 돌리는 자리.

## `POST /v1/cases/summary` (W4 말)

같은 `transaction_reader → facts → masking`, 프롬프트만 `summary_v1.md`(5줄), 검증은 코드만(평가자 없음), `generations.kind=SUMMARY`. 요약 문장은 관측 사실만 쓰고 모델 설명은 `model_signals`로 "모델이 주목한 점" 한 줄 따로 — 점수 설명과 관측을 섞지 않는다.

## 시간 예산 — 실측 전 가정값, W2 수요일 측정 뒤 조정

| 단계 | 예산 | 상수 (`domain/constants.py` / `.env`) |
|---|---|---|
| 초안 요청 전체(AI 안) | **80초** — 백엔드 타임아웃 90초보다 10초 짧게 | `DRAFT_BUDGET_S=80` |
| 죽은 PROCESSING 판정 | 예산 + 30초 = **110초** | `STALE_PROCESSING_S` |
| LLM 호출 1회 | **35초** | `LLM_TIMEOUT_S=35` |
| 스키마 실패 재생성 | 남은 예산 **≥ 40초**일 때만 | `REGEN_MIN_REMAINING_S=40` |
| loader | 1초 | — |
| retrieval (임베딩 1회 + pgvector) | 1~2초 | `RETRIEVAL_TIMEOUT_S=3` |
| judge (verify) | 5~20초 | `LLM_TIMEOUT_S` 공용 |

예산 초과는 `LlmUnavailable`(502)로 — 백엔드가 1회 재시도하면 같은 `draft_id`로 들어와 PROCESSING 선점에 걸리므로, **AI는 예산을 넘긴 생성을 반드시 FAILED로 닫고 응답한다**(닫지 않으면 재시도가 영원히 409).

## 에러 (규약 6.3, `shared/errors.py`)

| 예외 | HTTP | code | 백엔드 재시도 |
|---|---|---|---|
| 요청 스키마 위반, 없는 거래 ID, draft_id 재사용(다른 내용) | 400 | `INVALID_REQUEST` | 0 |
| 내부 키 틀림 | 401 | `UNAUTHENTICATED` | 0 |
| generation 없음 | 404 | `DRAFT_NOT_FOUND` | 0 |
| 같은 draft_id 생성 중 | 409 | `GENERATION_IN_PROGRESS` | 0 ("생성 중" 표시) |
| LLM 응답 스키마 위반(재생성 뒤에도) | 502 | `LLM_INVALID_OUTPUT` | 0 |
| LLM 연결 실패·타임아웃·예산 초과 | 502 | `LLM_UNAVAILABLE` | **1** |
| 일 토큰 한도 | 502 | `LLM_BUDGET_EXCEEDED` | 0 |
| 그 밖 | 500 | `INTERNAL` | 0 |

재시도는 **백엔드 `AiClient` 한 곳, 1회**. AI 서버 안에는 LLM 연결 재시도가 없다(현재 `shared/infrastructure/llm_client.py`의 1회 연결 재시도는 **삭제** — 백엔드 1회와 겹쳐 실질 4회가 되기 때문). 스키마 실패 1회 재생성은 재시도가 아니라 생성 절차의 일부이고, 예산 안에서만.
