# 03. 처리 순서 — 세 엔드포인트 (규약 v0.4)

정본: `str/api/router.py`, `str/application/draft_service.py`·`verify_service.py`·`summary_service.py`, `str/infrastructure/*_repository.py`. 규약 5·6절을 함수 순서로 적은 것. 10/27 반영: `draft_id` 중복 방지(PROCESSING 선점), `generation_id`, AI 내부 재시도 삭제, 시간 예산, FAILED 행, cites → evidence_ids.

**트랜잭션 경계 규칙 (SCRUM-122, 2026-11-0x)** — 외부 호출 중 DB 연결 반납.

> "LLM 호출 바로 앞에는 반드시 `end_read`, `end_read` 와 LLM 호출 사이에는 DB 읽기 금지."

임베딩 호출도 같은 규칙(외부 호출). `shared/db.end_read(session)` 가 "읽기만 한 트랜잭션" 을 `commit()` 으로 닫아 연결을 풀로 돌려줌 — `expire_on_commit=False` 라 읽은 값 그대로 유지. 쓰기(`new/dirty/deleted`) 가 섞여 있으면 `RuntimeError` 로 멈춤(의도 노출, `python -O` 안전). 요약(`summary_service`, SCRUM-129) 도 이 규칙을 따른다. 펜싱은 DB 조건(`status='PROCESSING'`)이라 연결을 놓아도 유지됨(`shared/03`).

## `POST /v1/str/drafts`

요청(규약 5.1): `draft_id`(백엔드 시퀀스 선발급), `case_no`, `alert`(2절 경보), `evidence_transaction_ids`(**= `alert.transaction_ids` 전체** — 점수의 근거 부분집합 아님, `str/04`), `reasons`(3절 그대로), `prior_alert_count`, `investigator_notes`, `reporting_institution`.

```
0  요청 검증                 schemas.str.DraftRequest — 실패 400 INVALID_REQUEST. 이어서 draft_service 가 domain.facts.request_problem: evidence == alert.transaction_ids(집합), paths ID ⊆ alert.transaction_ids → 400 (04)
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
   transaction_reader.load_subject(alert, txs)                      accounts / entities / customer_attributes — 1~3 쿼리 (관련 계좌 entity_id 포함, internal 판정용)
   없는 ID가 있으면 400 INVALID_REQUEST (message에 없는 ID 최대 10개 + 개수) → 행 FAILED
   self-transfer만 남으면(domain.facts.has_reportable) 400 INVALID_REQUEST "no reportable transactions" · 표에 없는 통화 이름은 `facts.unmapped_currencies` 로 보존(04, SCRUM-47) — 에러 아님
3  facts = domain.facts.build_facts(req, txs, subject)                       순수 (04) — observations는 req.reasons에서
4  facts_llm = domain.masking.mask_for_llm(facts)                            순수 (04) — 생성·평가자 공용
5  examples = fewshot_store.pick_examples(facts.typology)                    (05) 같은 유형 1 + 다른 유형 2
   shared.db.end_read(session)                                               (SCRUM-122) 읽기 트랜잭션 닫고 연결 반납 — 임베딩 호출 전
6  references = retriever.retrieve(facts)                                    (10) 0~3건. 임베딩은 외부 호출(연결 없음), _search 는 SCRUM-125에서 짧은 트랜잭션. RetrievalUnavailable → [] ※ 초안을 막지 않음
   shared.db.end_read(session)                                               (SCRUM-122) LLM 호출 바로 앞 — 지금 RAG 꺼져 no-op, 125에서 의미 생김
7  gen = narrative_generator.generate(facts_llm, fact_keys(facts), examples, references, notes, deadline=deadline)   (05)
      선체크 — 남은 예산 < LLM_TIMEOUT_S(35초) 이면 LLM 안 부르고 LlmUnavailable (502, 아래 "예산 초과는 LlmUnavailable")
      LLM 1회(35초) + NarrativeOut 스키마 검증(섹션 집합 각 1회 — v1 6개 또는 v2 7개, cites ⊆ fact_keys)
      스키마 실패 → 남은 예산 ≥ 40초면 1회 재생성, 아니면 바로 → 또 실패 LlmInvalidOutput (502)
      성공 시 tokens_in·tokens_out·latency_ms 는 호출한 횟수의 합(재생성 뒤 성공해도 두 호출 합)
      연결 실패·타임아웃 → LlmUnavailable (502). ★ AI 안에서 연결 재시도 없음 — 재시도는 백엔드 AiClient 1회만
8  narrative = domain.facts.attach_evidence(gen.narrative, facts)            순수 — cites의 fact 키 → 거래 ID 합집합 = evidence_ids
8b (SCRUM-147) rewrite_meta, narrative, gen = draft_rewrite.try_rewrite(req, facts, facts_masked, fact_keys, examples, references, notes,
      original_narrative=narrative, original_gen=gen, judge=judge, rewriter=rewriter, clock=clock, deadline=deadline, settings=settings)
      초안 생성 안에서 작성자–비평가 고쳐 쓰기 1회. 단계:
        ① 원본 코드 검사(`run_code_checks`) 실패 → skipped_reason="code_failed", 원본 반환 (평가자 안 부름 — 비용)
        ② 남은 < LLM_TIMEOUT_S → skipped_reason="budget", 원본 반환
        ③ 평가자(judge_v3) 1회 — 입력 (facts_masked, narrative). 예외(연결·스키마·기타) → skipped_reason="critique_error", 원본
        ④ 모든 점수 ≥ JUDGE_PASS_SCORE → skipped_reason="not_triggered", critique_scores 채움, 원본
        ⑤ 남은 < LLM_TIMEOUT_S → skipped_reason="budget", critique_scores 채움, 원본
        ⑥ 고쳐 쓰기(rewrite_v1) 1회 — 입력 (facts_masked, fact_keys, examples, references, notes, original_narrative(evidence_ids 제외), critique(score < JUDGE_PASS_SCORE 항목만, 평가자 순서 유지), paths_notice(경로형 룰 + paths 미확인일 때만 코드가 채움, 05)).
            스키마 실패 재생성 **0회** → skipped_reason="schema", 원본 반환
            연결·타임아웃·기타 LlmUnavailable → 올라와 502(원본 안 돌림; 생성 실패와 같은 모양으로 FAILED 저장)
        ⑦ 고친 본문 attach_evidence 재계산 → 코드 검사. 실패 → skipped_reason="rewrite_code_failed", 원본. 통과 → rewrite applied=true, 고친 본문·합산 토큰 반환
      최대 LLM 호출 **4** (생성 2 + 평가자 1 + 고쳐 쓰기 1).
      토큰·지연: 최상위 tokens_in/out/latency_ms = 생성 모델 호출 합(첫 생성 + 스키마 재시도 + 고쳐 쓰기).
      평가자 호출은 `generation_meta.rewrite.critique_tokens_in/out·critique_latency_ms` 로 분리 — `verification_runs.judge_*`(SCRUM-92) 와 같은 패턴. 다른 모델이기 때문.
      초안 안의 평가자는 **검증 결과 아님**(안건 17 유지) — `verification=null`, `verification_runs` 안 건드림. `generations.response`(JSON) 안 `generation_meta.rewrite` 에만 저장.
      end_read 규칙(SCRUM-122): 평가자·고쳐 쓰기 LLM 호출 앞에도 DB 읽기 없음 — `_generate` 가 이미 end_read 뒤라 그 상태 유지.
9  generation_repository.finish(generation_id, SUCCEEDED, facts, response, meta)
      UPDATE … WHERE generation_id=$1 AND status='PROCESSING' — 0행이면(STALE로 이미 닫힘) 결과 버림, 500 INTERNAL (shared/03 펜싱)
10 응답 DraftResponse: {draft_id, generation_id, facts(원본), narrative(cites+evidence_ids, 최종본), generation_meta(rewrite 포함), verification: null}
```

- 어느 단계든 예외 → `generation_repository.finish(generation_id, FAILED, error=code+message)` 뒤 에러 응답(같은 `status='PROCESSING'` 조건). **FAILED 행은 지우지 않는다**(재처리·비용 추적).
- LLM에는 **마스킹한 facts**와 **fact 키 목록**이 가고, 응답에는 **원본 facts**가 돌아간다. 거래 행 원본·거래 ID 목록은 LLM에 주지 않는다 — LLM은 거래 ID를 고르지 않는다(안건 23 세부, 2차 검토 반영).
- `verification`은 항상 `null`(안건 17). 초안 직후 자동 검증은 하지 않는다 — 조사역이 "검증" 버튼.

## `POST /v1/str/verify`

요청(규약 5.3): `generation_id`, `revision_no`, `narrative`(조사역 수정본, **섹션 집합 각 1회** — v1 6개 또는 v2 7개, 생성본과 같은 스키마).

```
0  요청 검증                  NarrativeOut 과 같은 섹션 제약 (섹션 중복·누락 → 400). 수정본은 섹션당 5,000자(NFC 뒤 UTF-16 — 06 "수정본 길이", 미결 24 확정 10/30)
1  gen = generation_repository.load(generation_id)        kind=DRAFT, status=SUCCEEDED — 없으면 404 DRAFT_NOT_FOUND
   facts, evidence_scope = gen.facts, gen.request.evidence_transaction_ids
   deadline = clock() + VERIFY_BUDGET_S                   (SCRUM-92) judge 재시도 조건에만 씀 — 시간 예산 표
2  sha = shared.hashing.narrative_sha256(narrative)      규약 5.3 해시 규칙 (shared/01)
3  code_checks = domain.verification.run_code_checks(facts, narrative, evidence_scope)   순수 (06) — 유형별 대조
   shared.db.end_read(session)                                               (SCRUM-122) LLM 호출 바로 앞 — CODE_FAILED 경로에서도 호출(저장은 autobegin 으로 새 트랜잭션)
4  if all(c.match):
       judge_result = judge.run(mask_for_llm(facts), narrative, deadline=deadline)   (06) checks 5개 + meta
       평가자 호출 중 **어떤 예외든** → llm_checks=None, judge_meta=None(응답), status=VERIFY_UNAVAILABLE (자동 재시도 없음, 200·행 저장).
       스키마 실패(LlmInvalidOutput) 는 남은 예산 ≥ LLM_TIMEOUT_S 일 때만 1회 다시 부름(06 "1회 재시도"). 그 외 예외는 재시도 없음(남은 예산 < LLM_TIMEOUT_S 는 LlmUnavailable("verify budget exceeded") — draft 와 같은 모양)
       평가자 밖(facts 로드·해시·코드 검사·저장)의 예외는 500 INTERNAL — 안건 9 "실패가 아니라 못 함" (SCRUM-91)
   else:
       llm_checks=None, judge_meta=None, status=CODE_FAILED        ※ 코드가 틀렸으면 평가자를 부르지 않는다 (비용, 어차피 fail)
5  passed = all(code match) AND llm_checks is not None AND all(score >= JUDGE_PASS_SCORE=4)    (안건 9)
   status = PASSED | LLM_FAILED | CODE_FAILED | VERIFY_UNAVAILABLE
5b narrative_refs = llm_checks 가 있으면 섹션별 judge cites → FACT_KEYS 밖 키 버림 → attach_evidence(cites, facts)   (06 "수정본의 cites")
   CODE_FAILED · VERIFY_UNAVAILABLE 이면 narrative_refs = None  → 백엔드는 기존 cites·evidence_ids 유지
6  verification_repository.save(generation_id, draft_id, revision_no, sha, code_checks, llm_checks, narrative_refs, passed, status, verifier_version, judge_meta)
   judge 호출 메타는 `verification_runs` 같은 행의 `judge_*` 5칸(shared/03, SCRUM-92). PASSED·LLM_FAILED 는 채우고 CODE_FAILED·VERIFY_UNAVAILABLE 은 null — 단 VERIFY_UNAVAILABLE 로 끝났어도 1번째 시도가 토큰을 썼으면 그 값까지 합산해 DB 에는 남긴다(응답은 null, 비용 추적). `generations(kind=VERIFY)` 행은 이번에 안 남김(09 미결 — SCRUM-61 결정)
7  응답 VerifyResponse: {verification_id, generation_id, revision_no, narrative_sha256, passed, status, code_checks, llm_checks, narrative_refs, judge_meta, verifier_version, produced_at}
```

- `VERIFY_UNAVAILABLE`은 검증 실패가 아니다 — 백엔드는 한 줄로 저장해 "검증 못 함"이 보이게 하고 "다시 검증" 버튼(채영). 승인 불가.
- 백엔드 `ApprovalGate`: 승인 요청은 **이 생성본·이 본문의 passed 검증**이 있을 때만(규약 4절 DRAFTED → PENDING_APPROVAL 조건과 같은 말). 세 조건: ① 검증의 `generation_id` == 현재 활성 초안의 `generation_id` ② 검증의 `narrative_sha256` == 현재 본문 해시 ③ `passed = true`. 해시만 보면 다른 생성본(다른 facts)에서 같은 문장이 나온 검증이 통할 수 있어서 ①을 둔다. `revision_no`는 **맞추지 않는다** — 같은 생성본에 본문이 같으면 대조한 facts도 같으니, 되돌린 수정본(rev 3 본문 = rev 1 본문)은 rev 1 검증으로 승인할 수 있다. **단 보완 요청(NEED_REVISION) 반려 뒤에는** 본문 해시가 반려 당시 해시와 같으면 백엔드가 409 `NARRATIVE_UNCHANGED`로 막는다(안건 24) — AI 서버는 할 일 없음. 수정 저장과 승인 요청이 동시에 오는 경우는 백엔드가 승인 트랜잭션 안에서 현재 본문 해시를 다시 읽어 비교(채영 V009에서 정함 — 미결 `09`). "최신 검증"이 아니라 "이 본문의 검증".
- 수정본의 `cites`·`evidence_ids`는 **다시 계산해 응답 `narrative_refs`로 돌려준다**(안건 23 세부 (a), 10/28 확정 — 위 5b). 평가자가 섹션별 cites를 내고 코드가 `attach_evidence`를 다시 돌린다. `CODE_FAILED`·`VERIFY_UNAVAILABLE`이면 `null` → 백엔드는 기존 값 유지. 백엔드는 현재 `draft_id`·`generation_id`·본문 해시가 검증 요청과 모두 같을 때만 반영(백엔드 docs `06_features/str.md`).

## `POST /v1/cases/summary` (SCRUM-129)

요청(규약 §6.1): `case_no`, `alert`, `evidence_transaction_ids`(min 1), **`reasons`**(초안과 같은 타입·점수 응답 그대로), **`prior_alert_count`**(int ge=0), **`reporting_institution`**(선택, 없으면 `subject.bank_name` 폴백 — 초안과 같은 규칙). `reasons`·`prior_alert_count` 는 **필수** — 규약 §6.1 11/6 반영(v0.4 추가 20번). (SCRUM-129)

```
0  요청 검증                  SummaryRequest 스키마 — evidence_transaction_ids set ⊆ alert.transaction_ids set, min 1 → 400 INVALID_REQUEST
1  deadline = clock() + SUMMARY_BUDGET_S  (SCRUM-129, 40초 — LLM_TIMEOUT_S 이상, 설정 불변식)
2  transaction_reader.load_transactions·load_subject   초안과 같음, 없는 ID → 400
3  facts = domain.facts.build_facts(req.to_facts_input(), txs, subject)   순수 — FactsInput 공통 DTO 거침(초안도 같음, SCRUM-129)
   facts_masked = masking.mask_for_llm(facts)                             초안과 같은 masking
4  examples = fewshot_store.pick_examples(facts.typology, prompt_name="summary_v1")
5  shared.db.end_read(session)                                             (SCRUM-122) LLM 호출 바로 앞
6  gen = summary_generator.generate(facts_masked, fact_keys(facts), examples, deadline=deadline)
      LLM 1회(35초) + SummaryOut 스키마 검증 (summary_lines 1~6, model_focus optional string)
      스키마 실패 → 남은 예산 ≥ REGEN_MIN_REMAINING_S 면 1회 재생성, 아니면 LlmInvalidOutput (502)
7  code_checks = run_code_checks(facts, [SummarySection(section=None, text="\n".join(summary_lines), evidence_ids=req.evidence_transaction_ids)], req.evidence_transaction_ids)
      4종(AMOUNT_MATCH·DATE_MATCH·COUNT_MATCH·ACCOUNT_ID_MATCH), 한 덩어리 본문 (SCRUM-129 ★A 2)
      EVIDENCE_IN_SCOPE·OPINION_PRESENT 는 안 돌림 — 요약 줄에 cites 없음, facts 가 evidence_transaction_ids 로만 계산
8  if any(not c.match for c in code_checks) and 남은 예산 ≥ REGEN_MIN_REMAINING_S:
      재생성 1회 → 다시 code_checks → 여전히 실패면 **200 + code_checks 담아 반환**(★A 3)
      백엔드는 "검증 통과분" 만 저장(case_summaries.payload) — 틀린 요약 화면에 안 띄움
9  model_focus — LLM 출력 그대로. 숫자(0~9) 들어 있으면 null 로 버리고 log.warning("summary_model_focus_rejected", extra={"reason":"has_digit"}) (SCRUM-129 ★A 4)
10 generations 신규 행 (kind=SUMMARY·draft_id=null·case_no·status=SUCCEEDED·response·meta). 재생성 토큰·latency 합산
11 응답 SummaryResponse: {case_no, facts(원본), summary_lines[≤6], model_focus, code_checks, generation_meta}
```

- `cites`·평가자(LLM 검사) 없음. 요약은 관측 사실만 쓰고 model_focus 에 model_signals 이름만.
- `generations.kind=SUMMARY`·`draft_id=null` — Alembic 변경 없음(`str/orm.py` 이미 nullable).
- 재시도 1회는 **스키마 실패** 또는 **코드 검사 실패** 둘 중 하나로만 — 각 경우 남은 예산 ≥ `REGEN_MIN_REMAINING_S` 일 때. 두 번 다 안 돌림.

## 시간 예산 — 실측 전 가정값, W2 수요일 측정 뒤 조정

| 단계 | 예산 | 상수 (`domain/constants.py` / `.env`) |
|---|---|---|
| 초안 요청 전체(AI 안) | **80초** — 백엔드 타임아웃 90초보다 10초 짧게 | `DRAFT_BUDGET_S=80` |
| 요약 요청 전체(AI 안) | **40초** — Jira SCRUM-129, 단 `LLM_TIMEOUT_S` 이상(기동 불변식) | `SUMMARY_BUDGET_S=40` |
| 죽은 PROCESSING 판정 | 예산 + 30초 = **110초** | `STALE_PROCESSING_S` |
| LLM 호출 1회 | **35초** | `LLM_TIMEOUT_S=35` |
| 스키마 실패 재생성 | 남은 예산 **≥ 40초**일 때만 | `REGEN_MIN_REMAINING_S=40` |
| 고쳐 쓰기 평가자 (SCRUM-147) | **≤ 35초**, 남은 ≥ `LLM_TIMEOUT_S` 일 때만. 아니면 `rewrite.skipped_reason="budget"` | `LLM_TIMEOUT_S` 공용 |
| 고쳐 쓰기 재작성 (SCRUM-147) | **≤ 35초**, 평가자 뒤 남은 ≥ `LLM_TIMEOUT_S` 일 때만. 스키마 실패 재생성 **0회** → `skipped_reason="schema"` | `LLM_TIMEOUT_S` 공용 |
| loader | 1초 | — |
| retrieval (임베딩 1회 + pgvector) | 1~2초 | `RETRIEVAL_TIMEOUT_S=3` |
| judge (verify) | 5~20초 | `LLM_TIMEOUT_S` 공용 |
| verify 요청 전체(AI 안) | **80초** — 백엔드 공유 타임아웃 90초보다 10초 짧게 (SCRUM-92) | `VERIFY_BUDGET_S=80` |
| judge 1회 재시도(스키마 실패만) | 남은 예산 **≥ `LLM_TIMEOUT_S`(35초)** 일 때만, `LlmUnavailable`·`BudgetExceeded` 는 재시도 없음 | `LLM_TIMEOUT_S` 공용 |

예산 초과는 `LlmUnavailable`(502)로 — 백엔드가 1회 재시도하면 같은 `draft_id`로 들어와 PROCESSING 선점에 걸리므로, **AI는 예산을 넘긴 생성을 반드시 FAILED로 닫고 응답한다**(닫지 않으면 재시도가 영원히 409).

**구현 위치 (SCRUM-45)** — 마감 시각 `deadline`은 `draft_service.create()`가 요청 검증(0) 직후·선점(1) 전에 `clock() + DRAFT_BUDGET_S`로 정하고 `narrative_generator.generate(..., deadline=deadline)`에 넘긴다. 앞 단계(DB·검색)가 느려 선체크가 실패해도 같은 흐름으로 `_fail`이 generations 행을 FAILED로 닫는다. 생성기는 **첫 LLM 호출 전**(남은 < `LLM_TIMEOUT_S` → `LlmUnavailable`)과 **스키마 실패 뒤**(남은 < `REGEN_MIN_REMAINING_S` → 재생성 없이 `LlmInvalidOutput`) 두 지점에서만 남은 예산을 본다 — 호출마다 LLM 타임아웃을 줄이지는 않는다(09 2026-10-31). 시계는 `Callable[[], float]`로 `draft_service`·`narrative_generator`에 주입(기본 `time.monotonic`), `domain/`은 시계를 만지지 않는다(01).

**불변식 (기동 때 검증, `shared/config.Settings._check_time_budget`)** — `DRAFT_BUDGET_S >= LLM_TIMEOUT_S` **그리고** `REGEN_MIN_REMAINING_S >= LLM_TIMEOUT_S` **그리고** `VERIFY_BUDGET_S >= LLM_TIMEOUT_S`(SCRUM-92). 어기면 `ValidationError` 로 기동 실패 — `.env` 를 잘못 적어 LLM 1회조차 못 부르는 상태로 서버가 살아 있지 않게.

**verify 구현 위치 (SCRUM-92)** — `verify_service.verify()` 가 generation 로드 직후 `deadline = clock() + VERIFY_BUDGET_S` 를 정해 `judge.run(..., deadline=deadline)` 에 넘긴다. `Judge` 는 스키마 실패 뒤 **두 번째 호출 직전**에 남은 예산을 보고 `< LLM_TIMEOUT_S` 면 재시도 없이 바로 `LlmInvalidOutput`. 첫 호출 선체크는 draft 와 달리 생략한다 — verify 흐름에서 judge 가 유일한 LLM 호출이고 앞 단계가 가벼움(코드 검사·facts 로드만). 시계는 `Callable[[], float]`(기본 `time.monotonic`) 로 주입, `domain/` 은 시계를 만지지 않는다.

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
