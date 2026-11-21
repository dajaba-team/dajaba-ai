"""SCRUM-308-2 리랭커 — 초안 경로 후보 → LLM(rerank_v1) 1회 → 순서 검사 → 앞 k (docs/str/10 "리랭커").

후보가 `RERANK_MIN_CANDIDATES` 보다 적거나 질의 신호·업종이 등록 목록 V1 밖이면 호출 0. 부르기 전 `release()`(DB 연결 반납, SCRUM-122).
fail-open: 시간 초과·공급자 오류·형식 오류·순서 검사 실패 → **원래 순서**, 경고 1줄(이유 낱말만 — 질의·본문·응답 0).
리랭커 만들기 실패도 리랭커 없이(기본 검색) 계속. 템플릿은 프롬프트 바이트를 한 번 읽어 동결 해시와 대조한 것(캐시).
`Reference.score` 는 그대로 cosine(순서만 바뀜).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from functools import cache
from typing import Protocol

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.infrastructure.llm_client import LlmClient, make_llm_client
from aml_ai.shared.schemas.str import Reference
from aml_ai.shared.schemas.str.rerank_llm import RerankOut
from aml_ai.str.domain.constants_rag_query import (
    RAG_RERANK_MAX_TOKENS,
    RAG_RERANK_TIMEOUT_MAX_S,
    RERANK_MIN_CANDIDATES,
    RERANK_PROMPT,
)
from aml_ai.str.domain.frozen_prompts import FROZEN_PROMPTS
from aml_ai.str.domain.rag_rerank import render_user, reorder

log = logging.getLogger(__name__)


class RerankFailed(Exception):
    """응답은 받았지만 쓸 수 없음(스키마·순열 아님·마감 지남). 메시지 = 이유 낱말 · `response_model` = 응답 본문 `model`."""

    response_received = True  # 하네스 응답 모델 집계 — 본문을 받은 뒤의 실패(검토 4)

    def __init__(self, reason: str, response_model: str | None = None) -> None:
        super().__init__(reason)
        self.response_model = response_model


class Reranker(Protocol):
    def order(self, query: str, refs: list[Reference]) -> list[Reference]: ...


@cache
def rerank_prompt() -> tuple[str, str, str]:
    """(system, user 템플릿, sha256) — 바이트를 한 번 읽어 `FROZEN_PROMPTS` 와 대조. 다르면 ValueError."""
    from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR, parse_prompt  # 순환 import 피함

    raw = (PROMPTS_DIR / f"{RERANK_PROMPT}.md").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FROZEN_PROMPTS[RERANK_PROMPT]:
        raise ValueError("rerank prompt hash mismatch")
    system, user = parse_prompt(raw.decode("utf-8"))
    return system, user, digest


class LlmReranker:
    def __init__(
        self,
        llm: LlmClient,
        *,
        model: str,
        allowed_model: str,
        timeout_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._model = model
        self._allowed = allowed_model.strip()
        self._timeout_s = timeout_s
        self._clock = clock
        self._system, self._user_tpl, self.prompt_sha256 = rerank_prompt()

    def order(self, query: str, refs: list[Reference]) -> list[Reference]:
        """운영 — LLM 1회. 형식·순서가 틀리거나 응답 모델이 허용 ID(`RAG_RERANK_RESPONSE_MODEL`)와 다르거나 없으면 예외
        → 원래 순서는 `rerank_first`(검토 5). 하네스는 `order_with_model` 로 응답 모델을 모아 따로 판정."""
        ordered, response_model = self.order_with_model(query, refs)
        if not self._allowed or response_model != self._allowed:
            raise RerankFailed("response_model_mismatch", response_model)
        return ordered

    def order_with_model(self, query: str, refs: list[Reference]) -> tuple[list[Reference], str | None]:
        """`order` + 응답 본문 `model`(`LlmResult.response_model`, 없으면 None) — 하네스가 회차별로 모음(추가 검토 2·3).

        마감 = 진입 + `RAG_RERANK_TIMEOUT_S`(단조 시계). 순열을 돌려주기 직전에 지났으면 `deadline` 실패 → 원래 순서(검토 4).
        """
        deadline = self._clock() + self._timeout_s
        res = self._llm.complete_json(
            system=self._system,
            user=render_user(self._user_tpl, query, [r.text for r in refs]),
            model=self._model,
            max_tokens=RAG_RERANK_MAX_TOKENS,
            tag=RERANK_PROMPT,
            timeout_s=self._timeout_s,
            total_timeout_s=self._timeout_s,  # 호출 전체 — 응답 조각이 늘어져도 한도 안에서 끊음
        )
        try:
            out = RerankOut.model_validate_json(res.text)
        except ValidationError:
            raise RerankFailed("schema_invalid", res.response_model) from None
        ordered = reorder(refs, out.order)
        if ordered is None:
            raise RerankFailed("not_permutation", res.response_model)
        if self._clock() > deadline:
            raise RerankFailed("deadline", res.response_model)
        return ordered, res.response_model


def rerank_first(
    reranker: Reranker | None,
    query: str | None,
    refs: list[Reference],
    *,
    k: int,
    release: Callable[[], None],
) -> list[Reference]:
    """리랭커 꺼짐·후보 부족이면 앞 k 그대로. 질의가 등록 목록 밖(None)이면 호출 0. 켜졌으면 다시 줄 세운 앞 k, 실패면 원래 앞 k."""
    if reranker is None or len(refs) < RERANK_MIN_CANDIDATES:
        return refs[:k]
    if query is None:
        log.warning("rerank_failed", extra={"reason": "unregistered_signal"})
        return refs[:k]
    try:
        release()
        return reranker.order(query, refs)[:k]
    except Exception as exc:  # noqa: BLE001 — 리랭커 어떤 실패든 원래 순서(fail-open, str/10)
        reason = str(exc) if isinstance(exc, RerankFailed) else type(exc).__name__
        log.warning("rerank_failed", extra={"reason": reason})
        return refs[:k]


def rerank_model(settings: Settings) -> str:
    """`RAG_RERANK_MODEL` 을 strip 해 비면 `LLM_MODEL_JUDGE`(strip) — 둘 다 비면 "". 사전 검사·호출·결과가 같은 값(추가 검토 2)."""
    return settings.rag_rerank_model.strip() or settings.llm_model_judge.strip()


def rerank_timeout_problem(settings: Settings) -> str | None:
    """기동 검사(추가 검토 3) — 리랭커를 켰으면 `RAG_RERANK_TIMEOUT_S` 가 0 초과·8 이하여야. 꺼져 있으면 안 봄.

    남은 요청 예산은 보지 않음(v4 는 검색이 맨 앞 — str/10 "리랭커" 켜기 전 확인).
    """
    if not settings.rag_rerank_enabled:
        return None
    timeout = settings.rag_rerank_timeout_s
    if timeout <= 0 or timeout > RAG_RERANK_TIMEOUT_MAX_S:
        return f"RAG_RERANK_TIMEOUT_S {timeout:g} — 0 초과 {RAG_RERANK_TIMEOUT_MAX_S:g} 이하여야"
    return None


def rerank_response_model_problem(settings: Settings) -> str | None:
    """기동 검사(검토 5) — 리랭커를 켰으면 `RAG_RERANK_RESPONSE_MODEL`(strip)이 있어야. 꺼져 있으면 안 봄."""
    if settings.rag_rerank_enabled and not settings.rag_rerank_response_model.strip():
        return "RAG_RERANK_RESPONSE_MODEL 빈 값 — 판정 결과의 응답 모델 ID 를 넣어야"
    return None


def make_reranker(settings: Settings, llm: LlmClient | None = None) -> LlmReranker:
    return LlmReranker(
        llm or make_llm_client(settings),
        model=rerank_model(settings),
        allowed_model=settings.rag_rerank_response_model,
        timeout_s=settings.rag_rerank_timeout_s,
    )


def safe_reranker(settings: Settings, llm: LlmClient) -> LlmReranker | None:
    """초안 서비스용 — 만들기 실패(템플릿·해시 등)도 fail-open: 리랭커 없이 기본 검색(추가 검토 1)."""
    try:
        return make_reranker(settings, llm)
    except Exception as exc:  # noqa: BLE001
        log.warning("rerank_failed", extra={"reason": f"init_{type(exc).__name__}"})
        return None
