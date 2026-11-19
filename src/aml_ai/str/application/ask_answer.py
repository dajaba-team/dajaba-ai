"""질문 답변 응답 조립 — 범위 밖·NO_DATA·UNVERIFIED·ANSWERED (docs/str/03 7·9 단계, SCRUM-290).

토큰·지연은 계획+답 두 호출 합, 범위 밖은 계획분만(shared/01). 답 본문은 ANSWERED 일 때만 응답에 나간다.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import (
    AskGenerationMeta,
    AskKind,
    AskRequest,
    AskResponse,
    AskStatus,
    Facts,
)
from aml_ai.shared.time_utils import utc_now
from aml_ai.str.domain import ask_checks
from aml_ai.str.domain.ask_bundles import AskPiece
from aml_ai.str.domain.ask_public import public_checks
from aml_ai.str.domain.constants_ask import ASK_ANSWER_PROMPT, ASK_PLAN_PROMPT
from aml_ai.str.infrastructure.ask_llm import AnswerResult, PlanResult


def out_of_scope_response(
    req: AskRequest, generation_id: str, plan: PlanResult, server_version: str
) -> AskResponse:
    """LLM 1회로 끝 — 답 프롬프트 null·묶음 []."""
    meta = AskGenerationMeta(
        llm_model=plan.llm_model,
        prompt_version=None,
        plan_prompt_version=ASK_PLAN_PROMPT,
        bundles=[],
        server_version=server_version,
        tokens_in=plan.tokens_in,
        tokens_out=plan.tokens_out,
        latency_ms=plan.latency_ms,
    )
    return AskResponse(
        produced_at=utc_now(),
        case_no=req.case_no,
        generation_id=generation_id,
        status=AskStatus.OUT_OF_SCOPE,
        kind=None,
        out_of_scope_reason=plan.out.out_of_scope_reason,
        answer=None,
        cites=[],
        evidence_ids=[],
        code_checks=[],
        generation_meta=meta,
    )


def in_scope_response(
    req: AskRequest,
    generation_id: str,
    facts: Facts,
    plan: PlanResult,
    piece: AskPiece,
    ans: AnswerResult,
    server_version: str,
) -> AskResponse:
    """answerable=false → NO_DATA · 검사 하나라도 실패 → UNVERIFIED · 전부 통과 → ANSWERED (06)."""
    out = ans.out
    checks = ask_checks.run(facts, out.answer, out.cites, piece.keys) if out.answerable else []
    if not out.answerable:
        status = AskStatus.NO_DATA
    elif all(c.match for c in checks):
        status = AskStatus.ANSWERED
    else:
        status = AskStatus.UNVERIFIED
    answered = status is AskStatus.ANSWERED
    return AskResponse(
        produced_at=utc_now(),
        case_no=req.case_no,
        generation_id=generation_id,
        status=status,
        kind=AskKind(plan.out.kind.value),
        out_of_scope_reason=None,
        answer=out.answer if answered else None,
        cites=list(out.cites) if answered else [],
        evidence_ids=ask_checks.cited_evidence_ids(facts, out.cites) if answered else [],
        code_checks=public_checks(checks),  # 06 7번 — 응답엔 허용 모양만, 원문은 저장 행 llm_answer
        generation_meta=_meta(plan, ans, piece, server_version),
    )


def _meta(plan: PlanResult, ans: AnswerResult, piece: AskPiece, server_version: str) -> AskGenerationMeta:
    return AskGenerationMeta(
        llm_model=ans.llm_model,
        prompt_version=ASK_ANSWER_PROMPT,
        plan_prompt_version=ASK_PLAN_PROMPT,
        bundles=list(piece.bundles),
        server_version=server_version,
        tokens_in=plan.tokens_in + ans.tokens_in,
        tokens_out=plan.tokens_out + ans.tokens_out,
        latency_ms=plan.latency_ms + ans.latency_ms,
    )
