"""Judge 단위 테스트 공용 helper (SCRUM-91·92). `test_judge.py`·`test_judge_retry.py` 공용."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.schemas.str import LlmCheckName
from aml_ai.str.infrastructure.judge import Judge

CHECK_NAMES = [n.value for n in LlmCheckName]


def judge_payload(scores: list[int], names: list[str] | None = None) -> str:
    names = names or CHECK_NAMES
    checks = [
        {"check": name, "comment": f"c{i}", "score": score}
        for i, (name, score) in enumerate(zip(names, scores, strict=True))
    ]
    return json.dumps({"checks": checks})


@dataclass
class StubCall:
    text: str
    model: str = "stub-judge"
    tokens_in: int = 1000
    tokens_out: int = 400
    latency_ms: int = 5000
    exc: BaseException | None = None


@dataclass
class StubLlm:
    """Judge 가 쓰는 LlmClient Protocol — complete_json 한 메서드."""

    responses: list[str] | None = None
    call_specs: list[StubCall] | None = None
    calls: list[dict] = field(default_factory=list)

    def complete_json(self, *, system, user, model, max_tokens, tag) -> LlmResult:
        idx = len(self.calls)
        self.calls.append(
            {"tag": tag, "model": model, "max_tokens": max_tokens, "system": system, "user": user}
        )
        if self.call_specs is not None:
            spec = self.call_specs[idx]
            if spec.exc is not None:
                raise spec.exc
            return LlmResult(
                text=spec.text,
                model=spec.model,
                tokens_in=spec.tokens_in,
                tokens_out=spec.tokens_out,
                latency_ms=spec.latency_ms,
            )
        assert self.responses is not None
        return LlmResult(
            text=self.responses[idx], model="stub-judge", tokens_in=0, tokens_out=0, latency_ms=0
        )


def make_judge(
    stub: StubLlm,
    *,
    prompt_name: str = "judge_v1",
    request_sections: list[str] | None = None,
    schema_retry: int | None = None,
) -> Judge:
    """SCRUM-91 회귀 테스트 기본값은 v1 — v2 는 호출 측에서 `prompt_name="judge_v2"` 명시(SCRUM-61)."""
    get_settings.cache_clear()
    kwargs: dict = {"prompt_name": prompt_name}
    if request_sections is not None:
        kwargs["request_sections"] = request_sections
    if schema_retry is not None:
        kwargs["schema_retry"] = schema_retry
    return Judge(stub, get_settings(), **kwargs)


def generous_deadline() -> float:
    """남은 예산 >= LLM_TIMEOUT_S 보장 — 지금 + verify_budget_s."""
    get_settings.cache_clear()
    return time.monotonic() + get_settings().verify_budget_s
