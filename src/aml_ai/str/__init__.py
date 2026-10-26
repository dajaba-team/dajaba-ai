"""str — STR 초안·검증·케이스 요약 파이프라인. 담당 진희.

api/             router.py — POST /v1/str/drafts, /v1/str/verify, /v1/cases/summary. 로직 없음
application/     draft_service, verify_service, summary_service — 처리 순서 조립 (docs/str/03)
domain/          facts, masking, verification, models, constants — 순수. DB·LLM·시계·설정 모름
infrastructure/  transaction_reader(ops 읽기), generation_repository·verification_repository(ai 쓰기),
                 orm, narrative_generator(LLM), judge(LLM), retriever(RAG), fewshot_store, prompt_index
prompts/         narrative_v1.md, judge_v1.md — 쓰고 나면 수정 금지
fewshot/         유형별 예시 json (정본). DB fewshot_examples 는 사본

의존 방향: api → application → domain.  infrastructure 는 application 이 부른다.
scoring/ 을 import 하지 않는다.
"""
