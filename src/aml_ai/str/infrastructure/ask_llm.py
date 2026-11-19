"""질문 답변 LLM 호출 — 계획(ask_plan_v1)·답(ask_answer_v1) (docs/str/03·05, SCRUM-290).

호출마다 선체크(남은 < ASK_LLM_TIMEOUT_S → LlmUnavailable) 뒤 1회. 재시도·재생성 없음 —
스키마 위반은 바로 LlmInvalidOutput. 예외 메시지에 LLM 응답 본문을 넣지 않는다.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult
from aml_ai.shared.schemas.str.ask_llm import AskAnswerOut, AskPlanOut
from aml_ai.shared.versioning import stable_json
from aml_ai.str.domain.ask_bundles import AskPiece
from aml_ai.str.domain.constants_ask import (
    ASK_ANSWER_MAX_TOKENS,
    ASK_ANSWER_PROMPT,
    ASK_PLAN_MAX_TOKENS,
    ASK_PLAN_PROMPT,
)
from aml_ai.str.infrastructure.narrative_generator import load_prompt

log = logging.getLogger(__name__)


_PLACEHOLDER = re.compile(r"\{\{(question|facts|fact_keys)\}\}")


@dataclass(frozen=True)
class PlanResult:
    out: AskPlanOut
    llm_model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


@dataclass(frozen=True)
class AnswerResult:
    out: AskAnswerOut
    llm_model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


def isolate_question(question: str) -> str:
    """격리 블록 `<question>…</question>` 을 질문이 닫지 못하게 `<`·`>` 를 바꾼다(05 ask_plan_v1 규칙 4)."""
    return question.replace("<", "&lt;").replace(">", "&gt;")


def render_plan_user(template: str, question: str) -> str:
    """계획 user — 질문만 들어간다(facts 없음). 녹화 도구와 같은 함수."""
    return template.replace("{{question}}", isolate_question(question))


def render_answer_user(template: str, question: str, piece: AskPiece) -> str:
    """답 user — 질문·묶음 조각·인용 키(05). 자리표시는 한 번에 바꿔 질문 속 `{{facts}}` 를 다시 바꾸지 않는다."""
    values = {
        "question": isolate_question(question),
        "facts": stable_json(piece.content),
        "fact_keys": "\n".join(piece.keys) or "(없음)",
    }
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


class AskLlm:
    def __init__(
        self, llm: LlmClient, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self._plan_system, self._plan_user_tpl = load_prompt(ASK_PLAN_PROMPT)
        self._answer_system, self._answer_user_tpl = load_prompt(ASK_ANSWER_PROMPT)

    def plan(self, question_masked: str, *, deadline: float) -> PlanResult:
        """질문은 이미 계좌를 가린 것(04). 스키마 위반 → LlmInvalidOutput, 재시도 없음."""
        user = render_plan_user(self._plan_user_tpl, question_masked)
        res, out = self._call(
            ASK_PLAN_PROMPT, self._plan_system, user, ASK_PLAN_MAX_TOKENS, AskPlanOut, deadline
        )
        return PlanResult(out, res.model, res.tokens_in, res.tokens_out, res.latency_ms)

    def answer(self, question_masked: str, piece: AskPiece, *, deadline: float) -> AnswerResult:
        """고른 묶음 조각만 본다(05). 선체크·호출 전체 제한·마감 뒤 거부는 계획과 같음."""
        user = render_answer_user(self._answer_user_tpl, question_masked, piece)
        res, out = self._call(
            ASK_ANSWER_PROMPT, self._answer_system, user, ASK_ANSWER_MAX_TOKENS, AskAnswerOut, deadline
        )
        return AnswerResult(out, res.model, res.tokens_in, res.tokens_out, res.latency_ms)

    def _call[T: BaseModel](
        self, tag: str, system: str, user: str, max_tokens: int, model: type[T], deadline: float
    ) -> tuple[LlmResult, T]:
        total = self._preflight(deadline)
        res = self._llm.complete_json(
            system=system,
            user=user,
            model=self._s.llm_model_generate,
            max_tokens=max_tokens,
            tag=tag,
            timeout_s=total,
            total_timeout_s=total,  # 호출 전체 제한(03) — 읽기마다 다시 걸리는 작업별 제한만으론 안 끝남
        )
        self._reject_late(deadline)
        try:
            return res, model.model_validate_json(res.text)
        except ValidationError as exc:
            log.warning("ask_llm_schema_invalid", extra={"tag": tag, "errors": len(exc.errors())})
            raise LlmInvalidOutput(f"{tag} schema invalid") from None

    def _preflight(self, deadline: float) -> float:
        """남은 < 1회 제한이면 안 부름. 부를 땐 호출 전체 제한 = min(1회 제한, 남은 예산)."""
        remaining = deadline - self._clock()
        if remaining < self._s.ask_llm_timeout_s:
            raise LlmUnavailable("ask budget exceeded")
        return min(self._s.ask_llm_timeout_s, remaining)

    def _reject_late(self, deadline: float) -> None:
        """마감 뒤 돌아온 결과는 받지 않는다(녹화·다른 클라이언트도 같은 규칙, 03)."""
        if self._clock() > deadline:
            raise LlmUnavailable("ask deadline passed")
