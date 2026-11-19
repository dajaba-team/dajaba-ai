"""test_ask_service 공용 — 가짜 LLM·저장소·서비스 조립 (SCRUM-290)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult
from aml_ai.shared.schemas.str import AskRequest
from aml_ai.str.application.ask_service import AskService
from aml_ai.str.infrastructure.ask_llm import AskLlm
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from tests.conftest import EXAMPLES, load_json
from tests.str.summary_service_support import StubReader


@dataclass
class StubLlm:
    """complete_json 한 메서드 — 받은 인자를 그대로 남긴다."""

    responses: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def complete_json(
        self, *, system, user, model, max_tokens, tag, timeout_s=None, total_timeout_s=None
    ) -> LlmResult:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "tag": tag,
                "timeout_s": timeout_s,
                "total_timeout_s": total_timeout_s,
            }
        )
        return LlmResult(
            text=self.responses[len(self.calls) - 1],
            model="stub-ask",
            tokens_in=120,
            tokens_out=30,
            latency_ms=900,
        )


@dataclass
class RecordingRepo(SummaryRepository):
    saved: list[dict] = field(default_factory=list)

    def save(self, **kw) -> None:
        self.saved.append(kw)


def plan_text(
    kind: str = "OUT_OF_SCOPE", reason: str | None = "JUDGMENT", bundles: list | None = None
) -> str:
    return json.dumps({"kind": kind, "out_of_scope_reason": reason, "bundles": bundles or []})


def ask_request(question: str = "이거 자금세탁 맞지?") -> AskRequest:
    body = load_json(EXAMPLES / "ask_request.json")
    return AskRequest.model_validate({**body, "question": question})


def build_service(llm: LlmClient, *, clock=None) -> tuple[AskService, RecordingRepo]:
    s = get_settings()
    clk = clock or time.monotonic
    repo = RecordingRepo(session=None)
    svc = AskService(
        settings=s,
        session=None,
        reader=StubReader(),
        llm=AskLlm(llm, s, clock=clk),
        repo=repo,
        labels=load_display_labels(),
        clock=clk,
    )
    return svc, repo
