"""SCRUM-126 ★L-2 · SCRUM-225 2차 — RAG 켬/끔 비교 공용 (초안 생성·verify 평가자 조립).

규칙 (10_rag "RAG 켬/끔 비교" + INTENT Q4):
- facts 5건 × `rag=True/False` 각 1회 = 10 초안
- **RAG 만 다르고** `.env` 모델·few-shot·프롬프트 버전·온도 전부 같음
- **고쳐 쓰기 안 돌림** — RAG 효과·고쳐 쓰기 효과 섞임 방지 (★L-2 는 첫 생성만)
- 평가자는 **207 verify 경로 Judge(votes=JUDGE_VOTES=3) 중앙값**
- 결과 JSON 레코드에 두 쪽 다 `llm_model_generate`·`llm_model_judge`·`prompt_version`·
  `judge_prompt_version`·`retrieval_version`·`few_shot_ids` — 사후 변수 통제 확인
- 본문 text 는 결과 JSON 에 안 넣음 (관문 6). 블라인드 md 에만.
- SCRUM-225: 참고 사례는 서비스와 같은 `prompt_references` 로 자름(v3 2건) · 규칙 12 `fact_coverage` 지표 추가
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from aml_ai.shared.schemas.str import Facts, Reference, RevisedNarrativeSection
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_VOTES
from aml_ai.str.domain.fact_keys import attach_evidence
from aml_ai.str.domain.fact_keys import fact_keys as _fact_keys_fn
from aml_ai.str.domain.verification import run_code_checks
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.judge import Judge
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from aml_ai.str.infrastructure.reference_snippet import prompt_references
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.rag_onoff_coverage import fact_coverage
from tests.str.rag_onoff_unsupported import unsupported_candidate_count

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "str" / "fixtures"
MANIFEST = REPO / "corpus" / "manifest.json"

FIXTURE_FILES = [
    ("case_1_fan_in", "facts_fan_in.json"),
    ("case_2_fan_in", "facts_fan_in_b.json"),
    ("case_3_fan_out", "facts_fan_out.json"),
    ("case_4_cycle", "facts_cycle_nopaths.json"),
    ("case_5_scatter_gather", "facts_scatter_gather.json"),  # SG — 대조군, references=[]
]


def load_fixtures() -> list[tuple[str, Facts]]:
    out: list[tuple[str, Facts]] = []
    for case_id, name in FIXTURE_FILES:
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        out.append((case_id, Facts.model_validate(data)))
    return out


def retrieval_version(settings: Any) -> str:
    man_sha = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:8] if MANIFEST.exists() else "unknown"
    return f"{settings.embedding_model}@{man_sha}"


def _grounds_mentions_count(narrative: list, signals: list[str]) -> int:
    """GROUNDS(v2) · WHY_SUSPICIOUS(v1) 섹션에서 model_signals 이름 언급 수. 유형 지표 반영 측정."""
    target = None
    for s in narrative:
        if s.section.value in ("GROUNDS", "WHY_SUSPICIOUS"):
            target = s.text
            break
    if target is None or not signals:
        return 0
    return sum(target.count(sig) for sig in signals)


def _get_references(facts: Facts, embedder: Any, session: Any, rag: bool) -> tuple[list[Reference], str]:
    """`(references, retrieval_status)` — status ∈ {`disabled`,`ok`,`empty`,`failed`}.

    `failed`: 임베딩·DB 예외. 집계 시 invalid 로 제외.
    `empty`: 정상 빈 결과(SG 같은 대조군). 포함.
    """
    if not rag:
        return [], "disabled"
    try:
        refs = Retriever(session, embedder, enabled=True).retrieve(facts)
    except Exception as exc:
        print(f"[warn] retrieve failed: {type(exc).__name__}")
        return [], "failed"
    return refs, ("ok" if refs else "empty")


def _run_generate(facts: Facts, references: list[Reference], llm: Any, settings: Any):  # type: ignore[no-untyped-def]
    facts_masked = masking.mask_for_llm(facts)
    fact_keys = list(_fact_keys_fn(facts).keys())
    examples = FewshotStore(prompt_name=settings.narrative_prompt).pick_examples(facts.typology)
    generator = NarrativeGenerator(llm, settings, prompt_name=settings.narrative_prompt)
    gen = generator.generate(
        facts_masked=facts_masked, fact_keys=fact_keys, examples=examples,
        references=references, notes=None,
        deadline=time.monotonic() + settings.draft_budget_s,
    )  # fmt: skip
    narrative = attach_evidence(gen.narrative, facts)
    return facts_masked, fact_keys, examples, gen, narrative


def _run_judge(facts_masked: dict, narrative: list, fact_keys: list[str], llm: Any, settings: Any):
    revised = [RevisedNarrativeSection.model_validate(s.model_dump()) for s in narrative]
    judge = Judge(llm, settings, prompt_name="judge_v3", votes=JUDGE_VOTES, schema_retry=1)
    return judge.run(
        facts_masked=facts_masked, narrative=revised, fact_keys=fact_keys,
        deadline=time.monotonic() + settings.verify_budget_s,
    )  # fmt: skip


def _build_result(
    *, facts, references, retrieval_status, narrative, code_checks, judge_result, gen, examples
):  # type: ignore[no-untyped-def]
    """결과 dict 조립 — generate_one 길이 가드."""
    scores = {c.check.value: c.score for c in judge_result.checks}
    passed = min(scores.values()) >= JUDGE_PASS_SCORE
    return {
        "narrative": narrative,  # 블라인드 md 전용 (JSON 결과엔 안 담음)
        "references_count": len(references),
        "references": [
            {"chunk_id": r.chunk_id, "doc_id": r.doc_id, "page": r.page} for r in references
        ],  # chunk_id 64자·doc_id·page 만 — 본문 text 는 담지 않음 (관문 6)
        "retrieval_status": retrieval_status,
        "code_checks_all_match": all(c.match for c in code_checks),
        "code_checks_failed": [
            {"check": c.check.value, "section": c.section.value if c.section else None}
            for c in code_checks
            if not c.match
        ],
        "judge_scores_median": scores,
        "typology_consistent": scores["TYPOLOGY_CONSISTENT"],
        "no_unsupported_claim": scores["NO_UNSUPPORTED_CLAIM"],
        "grounds_signal_mentions": _grounds_mentions_count(narrative, list(facts.model_signals)),
        "unsupported_candidate_count": unsupported_candidate_count(narrative, facts),
        "fact_coverage": fact_coverage(narrative, facts),  # SCRUM-225 규칙 12
        "status": "PASSED" if passed else "LLM_FAILED",
        "few_shot_ids": [e.example_id for e in examples],
        "prompt_version": gen.prompt_version,
        "judge_prompt_version": judge_result.meta.prompt_version,
        "llm_model_generate": gen.llm_model,
        "llm_model_judge": judge_result.meta.llm_model,
    }


def generate_one(
    *,
    facts: Facts,
    rag: bool,
    llm: Any,
    embedder: Any,
    session: Any,
    settings: Any,
) -> dict[str, Any]:
    """한 사건 × RAG on/off 1회 — 생성·코드검사·verify 평가자(votes=3) 집계."""
    references, retrieval_status = _get_references(facts, embedder, session, rag)
    references = prompt_references(settings.narrative_prompt, references)  # 서비스 _references 와 같게
    facts_masked, fact_keys, examples, gen, narrative = _run_generate(facts, references, llm, settings)
    scope = list({*facts.inbound.transaction_ids, *facts.outbound.transaction_ids})
    code_checks = run_code_checks(facts, narrative, scope)
    judge_result = _run_judge(facts_masked, narrative, fact_keys, llm, settings)
    return _build_result(
        facts=facts, references=references, retrieval_status=retrieval_status, narrative=narrative,
        code_checks=code_checks, judge_result=judge_result, gen=gen, examples=examples,
    )  # fmt: skip
