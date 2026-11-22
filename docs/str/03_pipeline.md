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
7v4 (SCRUM-228, NARRATIVE_PROMPT=narrative_v4 — 11/18 부터 기본값(09 "v4 기본값 전환 확정"). 05 narrative_v4 절) 7(LLM) 대신 코드 조립, **LLM 호출 0**. 6 검색은 그대로 돌아 references 는 응답에만(본문 반입 없음):
      a  표기 사전 검사          facts_llm 의 코드값이 contracts/display_labels_v1.json 에 다 있는지 — 없으면 500 INTERNAL, 행 FAILED
                                 (로그 display_label_missing 에 칸 이름·코드값만). 사전은 생성기를 만들 때 infrastructure 가 한 번 읽음
      b  flags = domain.derived_flags.derive_flags(facts_llm)              순수 — 참이면 코드 문장으로만
         slots = domain.display_slots.build_slots(facts_llm, labels, flags) 순수 — 숫자·날짜·금액·건수·계좌·플래그 문장
      c  plan  = domain.narrative_plan.default_plan(facts_llm, flags)       순수 — 사유 카탈로그 상위 3 · 종합의견(첫 문장 + 필수 + 선택 상위 2)
         (편집자를 붙이면: LLM 이 같은 모양 plan(id 배열만)을 내고 validate_plan 통과 시 사용, 실패면 default_plan — v2 로 자동 전환 안 함)
      d  조립 domain.narrative_assembly.assemble(slots, plan) — 7섹션(NarrativeOutV2 와 같은 모양). 섹션 1,200자 넘으면 500 INTERNAL
      gen = GenerationResult(llm_model="code", tokens 0, latency 0, few_shot_ids=[], prompt_version="narrative_v4")   (★A-8)
      그 뒤 8 부터 v2 와 같음. 8b 고쳐 쓰기는 v2 전용이라 v4 는 건너뜀(rewrite=None). 조사역 메모는 v4 에서 안 씀(05)
8  narrative = domain.facts.attach_evidence(gen.narrative, facts)            순수 — cites의 fact 키 → 거래 ID 합집합 = evidence_ids
8b (SCRUM-147) rewrite_meta, narrative, gen = draft_rewrite.try_rewrite(req, facts, facts_masked, fact_keys, examples, references, notes,
      original_narrative=narrative, original_gen=gen, judge=judge, rewriter=rewriter, clock=clock, deadline=deadline, settings=settings)
      **v2 전용** — `gen.prompt_version != "narrative_v2"` 면 `try_rewrite` 가 `None` 반환해 고쳐 쓰기 skip·`generation_meta.rewrite=None` (rewrite_v1 출력 스키마가 v2 7섹션이라 v1 초안엔 쓰면 섹션 집합이 바뀜).
      초안 생성 안에서 작성자–비평가 고쳐 쓰기 1회. 단계:
        ① 원본 코드 검사(`run_code_checks`) 실패 → skipped_reason="code_failed", 원본 반환 (평가자 안 부름 — 비용)
        ② 남은 < LLM_TIMEOUT_S → skipped_reason="budget", 원본 반환
        ③ 평가자(judge_v3) 1회 — 입력 (facts_masked, narrative). 예외(연결·스키마·기타) → skipped_reason="critique_error", 원본
        ④ 모든 점수 ≥ JUDGE_PASS_SCORE → skipped_reason="not_triggered", critique_scores 채움, 원본
        ⑤ 남은 < LLM_TIMEOUT_S → skipped_reason="budget", critique_scores 채움, 원본
        ⑥ 고쳐 쓰기(rewrite_v1) 1회 — 입력 (facts_masked, fact_keys, examples, references, notes, original_narrative(evidence_ids 제외), critique(score < JUDGE_PASS_SCORE 항목만, 평가자 순서 유지), paths_notice(경로형 룰 + paths 미확인일 때만 코드가 채움, 05)).
            스키마 실패 재생성 **0회** → skipped_reason="schema", 원본 반환
            **연결·타임아웃·BudgetExceeded·기타 예외 → skipped_reason="rewrite_error", 원본 반환** (고쳐 쓰기는 덤 단계라 호출 실패해도 원본은 멀쩡함 — 초안 전체를 502 로 만들지 않음. critique_scores 는 채움, 평가자는 돌았음). **실패한 고쳐 쓰기 호출의 토큰은 최상위 `tokens_in/out/latency_ms` 합에 안 더함** (SCRUM-45 "실패 호출 토큰 기록 안 함").
        ⑦ 고친 본문 attach_evidence 재계산 → 코드 검사. 실패 → skipped_reason="rewrite_code_failed", 원본. 통과 → rewrite applied=true, 고친 본문·합산 토큰 반환
      최대 LLM 호출 **4** (생성 2 + 평가자 1 + 고쳐 쓰기 1).
      토큰·지연 합산 규칙(★A 4, SCRUM-147 추가 검토 뒤 통일): **응답(usage) 받은 생성 모델 호출은 합산**, 예외로 usage 를 못 받은 호출만 미합산. `rewrite_code_failed` 와 **usage 가 있는** `schema` 실패는 본문만 원본·토큰은 합산. `rewrite_error`(연결·타임아웃·기타, usage 없음) 는 미합산.
      평가자는 다른 모델이라 `generation_meta.rewrite.critique_tokens_in/out·critique_latency_ms` 로 분리 — `verification_runs.judge_*`(SCRUM-92) 와 같은 패턴. **평가자 예외에 `judge_meta` 가 붙어 오면**(Judge 가 스키마 실패 때 첨부, SCRUM-144) `critique_llm_model·critique_tokens_*·critique_latency_ms` 는 보존, `critique_scores=None`.
      **초안용 Judge 는 `schema_retry=0`** — verify 경로(1회) 와 분리해 생성 2 + 평가자 1 + 고쳐 쓰기 1 = **최대 4** 호출 상한 유지.
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
   facts_llm = summary_amounts.with_display_amounts(facts_masked, labels)  (SCRUM-340, summary_v2) 순수 — 금액 칸만 `62,992,819.38 유로(EUR)` 완성 문자열로.
                                                                           원본 facts·검사·저장 그대로. labels = 초안과 같은 표기 사전
4  examples = fewshot_store.pick_examples(facts.typology, prompt_name=SUMMARY_PROMPT)   지금 summary_v2 (few-shot FACTS 도 같은 표기)
5  shared.db.end_read(session)                                             (SCRUM-122) LLM 호출 바로 앞
6  gen = summary_generator.generate(facts_llm, fact_keys(facts), examples, deadline=deadline)
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

## `POST /v1/cases/ask` (SCRUM-290)

요청·응답 모양은 `shared/01` 질문 답변 절(규약 §5.4, `shared/schemas/str/ask.py`). 2단계 호출 — LLM 은 **계획(묶음 고르기)** 과 **답** 두 번만, 순서는 코드가 고정(09 2026-11-19). 선점·중복 방지 없음(요약과 같음, 409 없음).

```
0  요청 검증                  AskRequest 스키마(question 1~300 NFC·UTF-16, 공백만 거부) + evidence_transaction_ids ⊆ alert.transaction_ids → 400 INVALID_REQUEST
1  deadline = clock() + ASK_BUDGET_S  (20초 — ASK_LLM_TIMEOUT_S 이상, 설정 불변식)
2  transaction_reader.load_transactions·load_subject   요약과 같음, 없는 ID·보고 대상 거래 없음 → 400
3  facts = domain.facts.build_facts(req.to_facts_input(), txs, subject)   요약과 같은 함수
4  shared.db.end_read(session)                                             (SCRUM-122) LLM 호출 앞
5  question_llm = domain.ask_question.mask_question(req.question)          (04 "질문 속 계좌") — LLM 에 가는 질문만. 저장은 원문
6  plan = ask_llm.plan(question_llm, deadline=deadline)                    ask_plan_v1, facts 값 안 줌
      선체크: 남은 < ASK_LLM_TIMEOUT_S → LlmUnavailable(502). LLM 1회 — 재시도·재생성 없음
      호출 전체 제한 total = min(ASK_LLM_TIMEOUT_S, deadline − clock()) 를 complete_json(total_timeout_s=) 로 넘김(SCRUM-290 추가 검토 1):
        HttpLlmClient 가 이 호출만 비동기 클라이언트(호출마다 새로 만들고 닫음)로 보내고 total 이 지나면 요청 작업을 취소 —
        연결·요청 쓰기·응답 헤더 대기·본문 읽기 어디서든 마감 시각에 연결을 닫고 LlmUnavailable(502). 작업 스레드 없음,
        마감 뒤 도착한 응답은 쓰지 않음, 재시도 0(SCRUM-322 — 헤더가 조각으로 오면 연결·작업 스레드가 마감 뒤에도 남던 것 고침)
        (httpx timeout 은 읽기마다 다시 걸리는 작업별 제한이라, 조각이 10초 안 간격으로 오면 호출 전체는 끝없이 늘 수 있음 — 헤더 조각도 같음)
      호출이 돌아온 뒤에도 clock() > deadline 이면 결과를 받지 않고 LlmUnavailable — 녹화·다른 클라이언트도 같은 규칙. 마감 뒤 결과는 SUCCEEDED 로 저장하지 않음(FAILED)
      AskPlanOut 스키마 위반(목록 밖·0개·4개·중복 묶음, kind 와 사유·묶음 짝 어긋남) → LlmInvalidOutput(502)
7  plan.kind == OUT_OF_SCOPE → 응답 조립(kind=null·out_of_scope_reason·answer=null·cites=[]·evidence_ids=[]·code_checks=[]·
      prompt_version=null·bundles=[]·토큰·지연 = 계획 호출분) → 10 으로. LLM 1회로 끝
8  piece = domain.ask_bundles.extract(facts, rule_id, plan.bundles)   (04 "질문 답변 묶음") — 마스킹 조각 + 인용 키 목록
   ans = ask_llm.answer(question_llm, piece, deadline=deadline)       ask_answer_v1 (05) — 계획과 같은 선체크(남은 < ASK_LLM_TIMEOUT_S → 502)·
      호출 전체 제한 min(ASK_LLM_TIMEOUT_S, 남은)·마감 뒤 도착 거부, 1회·재시도 없음
      answerable=true + cites 빈 · answer 400자 초과·빈 문자열 → LlmInvalidOutput(502)
9  answerable=false → NO_DATA (answer·cites 무시, code_checks=[])
   answerable=true → code_checks = domain.ask_checks.run(facts, answer, cites, piece.keys)  (06 "질문 답변에 도는 코드 검사")
      하나라도 match=false → UNVERIFIED (answer=null·cites=[]·evidence_ids=[]) / 전부 match → ANSWERED
      evidence_ids = cites 의 fact 키 → 거래 ID 합집합(attach_evidence 와 같은 방식, 거래 없는 키는 기여 0)
10 generations 신규 행 (kind=ASK·draft_id=null·case_no·status=SUCCEEDED·request(질문 원문)·facts(원본)·
      response = API 응답 + "plan"{kind, out_of_scope_reason, bundles} + "llm_answer"{answerable, answer, cites}(답 호출 때만)·
      llm_model·prompt_version(답, OUT_OF_SCOPE 면 null)·tokens·latency = 두 호출 합)
   성공 저장 시간 제한(SCRUM-290 2/2 추가 검토 1): 남은 = deadline − clock() ≤ 0 이면 성공 저장 안 함 → LlmUnavailable(502).
      남았으면 같은 트랜잭션에 set_config(statement_timeout·lock_timeout = 남은 ms, 트랜잭션 한정) 뒤 INSERT·flush,
      커밋 직전 다시 clock() > deadline 이면 rollback → LlmUnavailable. **커밋이 시작되면 결과를 그대로 씀**(추가 검토 2 — 커밋 중 마감을 넘겨도
      SUCCEEDED·응답 그대로. 20초 예산이 백엔드 30초보다 10초 짧은 여유가 이 몫, 시간 값 안 바꿈). 시간 제한·잠금 대기로 취소(57014·55P03)도 rollback → LlmUnavailable
      (풀 연결 대기는 엔진 공통 pool_timeout 이라 이 호출만 못 묶음 — 09 알고 남김). 요약 저장은 시간 제한 없음 그대로
   예외 → status=FAILED·error="<code>: <메시지 앞 48자>" 저장 후 그대로 raise (요약과 같음). FAILED 저장은 시간 제한 없음 — 백엔드 30초가 바깥 제한(09 알고 남김)
11 응답 AskResponse — 상태 4종 모두 200
```

- 평가자(LLM 검사) 없음 — 요약과 같은 수준. 답 문장은 코드 검사만.
- `generations.kind=ASK`·`draft_id=null` — Alembic 변경 없음(`kind` 는 `String(16)`, CHECK 없음, 부분 UNIQUE 는 `kind='DRAFT'` 만 — `shared/03`).
- 저장은 `SummaryRepository.save(..., kind="ASK")` — 기본값 `SUMMARY` 라 요약 호출은 그대로.
- 로그에는 케이스 번호·상태·질문/답 길이·시간만. 질문·답 본문·프롬프트 전문 금지(NFR-COM-04).
- 라우터 `str/api/router.py` `POST /cases/ask`(main 이 `/v1` 붙임)는 **동기 `def`** — 이벤트 루프가 도는 스레드에서 `complete_json(total_timeout_s=)` 을 부르면 500(SCRUM-322 알고 남김). 응답 조립(상태 3종)은 `application/ask_answer.py`, 검사·근거는 `domain/ask_checks.py`(순수).
- 시간(SCRUM-290 2/2 ★A): 답 선체크를 지나려면 facts 읽기 + 계획 ≤ `ASK_BUDGET_S − ASK_LLM_TIMEOUT_S`(10초). 지나면 답 끝 ≤ deadline, 그 뒤 검사·저장(ms 단위)만 — 최악 응답 ≈ 20초 + 수십 ms(백엔드 30초 안). 계획+답 합계 실측(08 "결과 — 답")이 20초를 넘어도 이 PR 에서 숫자를 바꾸지 않고 기록만(09).

## `POST /v1/references/search` (SCRUM-309)

조회 전용 — 선점·펜싱·`ai.generations` 행 없음. LLM 0, 임베딩 0~1회. 정본 노션 설계 문서 A(5.1·9절), 검색 방법 `str/10` "참고 사례 검색".

1. 스위치 — `RAG_REFERENCE_SEARCH_ENABLED` 와 `RAG_ENABLED` 가 둘 다 켜져 있어야. 아니면 400 `INVALID_REQUEST`(DB·임베딩 0). 입력 검사보다 먼저
2. 입력 — 스키마(`ReferenceSearchRequest`)가 유형 1~3·목록 안·중복 · `query` 길이·공백만 · `top_k` · `source_types` 를 봄 → 400. `X-Budget-Ms` 가 있으면 양의 정수여야(아니면 400)
3. 마감 — 요청이 들어온 시각(미들웨어 `ReceivedAtMiddleware`, 단조) + min(`REFERENCE_SEARCH_BUDGET_S`, `X-Budget-Ms`). 서비스 진입 때 이미 지났으면 502(임베딩·DB 0)
4. 질의 — 가리기(검색용 먼저: 하이픈 변형 정규화 → 은행 번호 + 나뉜 계좌 → 16진 나뉜 계좌 → 구분자 낀 숫자 8개 이상, 그다음 `mask_question` — 추가 검토 3) → 유형 영문 패턴 + 가린 검색어 한 줄(`str/domain/reference_search`). 가린 뒤 빈 값이면 유형만
5. 임베딩 — 유형만이면 프로세스 캐시 먼저(적중이면 외부 호출 0). 아니면 남은 예산이 0 이하일 때 502 `LLM_UNAVAILABLE`(호출 전), 전송·본문 전체 한도 = min(`REFERENCE_SEARCH_EMBED_TIMEOUT_S`, 남은 예산)(`reference_embedding.embed_within` 에 절대 마감으로 — 넘으면 취소, 루프 쪽도 클라이언트 만들기 전·전송 직전 확인해 전송 0). 실패 → 502 `LLM_UNAVAILABLE`, 429 본문 `error.code` 가 정확히 `insufficient_quota` 면 502 `LLM_BUDGET_EXCEEDED`. **DB 연결은 임베딩 뒤에 처음 씀**(외부 호출 중 연결 안 듦)
6. 검색 — DB 전(캐시 적중 포함) 남은 시간 확인(0 이하 502) · `ai.reference_chunks` 유형 OR 필터 · 같은 모델 · 후보 30 · 연결을 얻은 뒤 남은 시간(0 이하 502 — 검색 SQL 0) · `statement_timeout` = 그 ms(설정 왕복 뒤 다시 확인 — 지났으면 검색 SQL 0, 502) → 유사도 하한·중복 제거 · 한 문서 최대 3건 · 상위 `top_k`. SQL 오류·시간 초과 → 503 `DB_UNAVAILABLE` · 응답 조립·검증 뒤 성공 반환 직전 남은 시간 다시 확인(0 이하 502) · `retrieval_version` 은 기동 때 읽은 값
7. 응답 — `FOUND`/`EMPTY` · 응답 시작(`http.response.start`) 직전에 검색 입구 래퍼가 마감 확인 — 만료면 200 대신 502 `LLM_UNAVAILABLE`(추가 검토 3) · 로그 한 줄 `reference_search_done`(유형·검색어 길이·결과 수·후보 수·지연·캐시 적중 — 검색어·청크 본문 0)

## `POST /v1/references/str` (SCRUM-310)

승인 STR 색인 — 선점·펜싱·`ai.generations` 행 없음. LLM 0, 임베딩 0~1회. 정본 노션 설계 문서 B(5.2·9절), 방법 `str/10` "승인 STR 색인".

1. 입력 — 스키마(`StrIndexRequest`)가 문서번호 모양·유형·섹션 한 세트·중복·글 길이를 봄 → 어긋나면 400 `INVALID_REQUEST`(DB·임베딩 0)
2. 스위치 — `STR_INDEX_ENABLED` 와 `RAG_ENABLED` 둘 다 켜져야. 아니면 200 `SKIPPED`·`DISABLED`(DB·임베딩 0)
3. 같은 번호 확인(읽기만, 계좌 검사보다 먼저 — 추가 검토 3) — 부모 행이 있고 `request_hash` 같으면 기존 행 그대로 `INDEXED`(임베딩 0) · 다르면 400
4. 명시적 계좌 키(순수) → `SKIPPED`·`RAW_ACCOUNT` · 짧음 — 공백 뺀 합 < 100 이면 `SKIPPED`·`TOO_SHORT` · 초안 facts(`draft_id`, `ai.generations`) — 없으면 `SKIPPED`·`NO_FACTS` · 케이스 계좌(대상 + 거래 ID 로 읽은 `ops.transactions` 보낸·받은 계좌 — 거래가 빠지면 503) 6자 조각·은행 번호 + 앞 4자 · `ops.accounts` 정확 일치(쿼리 한 번) → `RAW_ACCOUNT`(임베딩 0). 조회 실패 503 · 읽기 끝에 연결 반납
5. 임베딩 — 공통 `HttpEmbeddingClient` 로 섹션 n개를 한 번에(모델·수·차원 검사). 실패 → 502 `LLM_UNAVAILABLE`, 행 0. **DB 연결은 이 동안 안 듦**
6. 저장 — 한 트랜잭션: `READ COMMITTED`(첫 문장) → `pg_advisory_xact_lock(문서번호)` → 같은 번호 다시 확인(동시 요청: 같으면 기존 응답, 다르면 400) → 부모 행(문서번호 PK — PK 충돌이면 이미 있던 부모) + 섹션마다 한 행 → 커밋. SQL 오류 → 503 `DB_UNAVAILABLE`, 행 0
7. 응답 — `INDEXED`·`chunk_count` · 로그 한 줄(문서번호·섹션 세트·섹션 수·청크 수·상태·지연 — 본문 0)

## 시간 예산 — 실측 전 가정값, W2 수요일 측정 뒤 조정

| 단계 | 예산 | 상수 (`domain/constants.py` / `.env`) |
|---|---|---|
| 초안 요청 전체(AI 안) | **80초** — 백엔드 타임아웃 90초보다 10초 짧게 | `DRAFT_BUDGET_S=80` |
| 요약 요청 전체(AI 안) | **40초** — Jira SCRUM-129, 단 `LLM_TIMEOUT_S` 이상(기동 불변식) | `SUMMARY_BUDGET_S=40` |
| 질문 답변 요청 전체(AI 안) | **20초** — 설계 문서 5.5(백엔드 전체 30초). `ASK_LLM_TIMEOUT_S` 이상(기동 불변식) | `ASK_BUDGET_S=20` |
| 질문 답변 LLM 1회(계획·답 각각) | **10초 — 호출 전체**(작업별이 아님). `min(10초, 요청 deadline 남은 시간)` 이 지나면 헤더 대기·본문 읽기 중 어디서든 연결을 끊고 `LlmUnavailable`(SCRUM-322). 호출 전 남은 < 10초면 부르지 않음. 재시도·재생성 0 | `ASK_LLM_TIMEOUT_S=10` · `complete_json(total_timeout_s=)` |
| 죽은 PROCESSING 판정 | 예산 + 30초 = **110초** | `STALE_PROCESSING_S` |
| LLM 호출 1회 | **35초** — 작업별(연결·읽기마다 다시 걸림), 호출 전체 마감 없음. 초안·검증·요약에 전체 마감을 거는 건 다음 결정(09 미결, SCRUM-322) | `LLM_TIMEOUT_S=35` |
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

**불변식 (기동 때 검증, `shared/config.Settings._check_time_budget`)** — `DRAFT_BUDGET_S >= LLM_TIMEOUT_S` **그리고** `REGEN_MIN_REMAINING_S >= LLM_TIMEOUT_S` **그리고** `VERIFY_BUDGET_S >= LLM_TIMEOUT_S`(SCRUM-92) **그리고** `ASK_BUDGET_S >= ASK_LLM_TIMEOUT_S`(SCRUM-290 — 질문 답변은 전역 `LLM_TIMEOUT_S`(35)와 비교하지 않는다. 비교하면 20 < 35 로 기동 실패). 어기면 `ValidationError` 로 기동 실패 — `.env` 를 잘못 적어 LLM 1회조차 못 부르는 상태로 서버가 살아 있지 않게.

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
| AI DB 장애(점수 · 참고 사례 검색 — SCRUM-309 · 승인 STR 색인 — SCRUM-310) | 503 | `DB_UNAVAILABLE` | **1** |
| 참고 사례 검색 임베딩 실패·시간 초과·남은 예산 부족(SCRUM-309, 설계 13-3 — 새 코드 없음) | 502 | `LLM_UNAVAILABLE` | **1** |
| 승인 STR 색인 임베딩 실패(SCRUM-310 — 전부 되돌림, 행 0) | 502 | `LLM_UNAVAILABLE` | **1** |
| 승인 STR 색인 같은 문서번호 다른 본문 · 섹션 세트 섞임(SCRUM-310) | 400 | `INVALID_REQUEST` | 0 |
| 그 밖 — v4 표기 사전에 없는 코드값·조립 섹션 1,200자 초과 포함(SCRUM-228, v2 로 자동 전환 안 함) | 500 | `INTERNAL` | 0 (백엔드 `WebClientAiClient.RETRYABLE_AI_CODES` 에 없음 — 11/17 `592bf35` 확인) |

재시도는 **백엔드 `AiClient` 한 곳, 1회**. AI 서버 안에는 LLM 연결 재시도가 없다(현재 `shared/infrastructure/llm_client.py`의 1회 연결 재시도는 **삭제** — 백엔드 1회와 겹쳐 실질 4회가 되기 때문). 스키마 실패 1회 재생성은 재시도가 아니라 생성 절차의 일부이고, 예산 안에서만.
