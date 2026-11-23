"""test_ask_service 공용 — 가짜 LLM·저장소·서비스 조립 (SCRUM-290)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from tools.ask_fixture_scope import fixture_scope

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult
from aml_ai.shared.schemas.str import AskRequest, Facts
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
        if kw.get("before_commit") is not None:
            kw["before_commit"]()  # 커밋 직전 확인이 raise 하면 남기지 않음(실제 저장소와 같음)
        self.saved.append(kw)


def plan_text(
    kind: str = "OUT_OF_SCOPE", reason: str | None = "JUDGMENT", bundles: list | None = None
) -> str:
    return json.dumps({"kind": kind, "out_of_scope_reason": reason, "bundles": bundles or []})


def answer_text(
    answerable: bool = True, answer: str | None = "이 케이스에는 {{inbound.count|이}} 있어요."
) -> str:
    """ask_answer_v3 출력 — answerable·answer 둘(v3·v4 같은 모양 — cites 는 코드가 자리표에서, SCRUM-362)."""
    return json.dumps({"answerable": answerable, "answer": answer}, ensure_ascii=False)


def ask_request(question: str = "이거 자금세탁 맞지?", *, rule_id: str | None = None) -> AskRequest:
    body = load_json(EXAMPLES / "ask_request.json")
    if rule_id is not None:
        body["alert"] = {**body["alert"], "rule_id": rule_id}
    return AskRequest.model_validate({**body, "question": question})


FIXTURE = object()  # build_service 기본 — 픽스처에서 범위 계산


def build_service(
    llm: LlmClient, *, clock=None, facts: Facts | None = None, scope: object = FIXTURE
) -> tuple[AskService, RecordingRepo]:
    """facts 를 주면 거래 읽기 대신 그 facts 로(평가 세트 픽스처 주입, 08)."""
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
    if facts is not None:
        # 범위는 서비스와 같은 ask_scope 로 픽스처에서 셈(04 ★B8) — scope=None 이면 범위 모름 경로
        svc._load_facts = lambda req: (facts, fixture_scope(facts, req) if scope is FIXTURE else scope)  # type: ignore[method-assign]
    return svc, repo
