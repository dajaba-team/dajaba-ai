"""SCRUM-207 — Judge N 중앙값 테스트 공용 helper (test_judge_votes·deadline 공용)."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.schemas.str import LlmCheckName, NarrativeSection, SectionV2
from aml_ai.str.infrastructure.judge import Judge

CHECK_NAMES = [n.value for n in LlmCheckName]
SECTIONS_V2 = [s.value for s in SectionV2]


def v3_payload(
    scores: list[int],
    *,
    sections: list[dict] | None = None,
    comment_tag: str = "a",
) -> str:
    """judge_v3 JudgeOutV2 payload. sections 지정 없으면 빈 cites 7 섹션."""
    secs = sections if sections is not None else [{"section": s, "cites": []} for s in SECTIONS_V2]
    checks = [
        {"check": n, "comment": f"{comment_tag}-{n}", "score": s}
        for n, s in zip(CHECK_NAMES, scores, strict=True)
    ]
    return json.dumps({"checks": checks, "sections": secs})


def dummy_narrative() -> list[NarrativeSection]:
    """verify 경로가 Judge.run 에 넘기는 7 섹션 narrative (최소한, cites·evidence_ids 비움)."""
    return [NarrativeSection(section=SectionV2(s), text=f"t-{s}", cites=[]) for s in SECTIONS_V2]


@dataclass
class VoteCall:
    text: str | None = None
    tokens_in: int = 1000
    tokens_out: int = 400
    latency_ms: int = 5000
    exc: Exception | None = None
    wait_event: threading.Event | None = None  # 대기 후 반환 (deadline 테스트)
    model: str = "stub-judge"


class ThreadSafeStub:
    """스레드 안전 StubLlm — 세 스레드가 공유해도 call_specs 를 인덱스 순서로 소비."""

    def __init__(self, call_specs: list[VoteCall]) -> None:
        self._specs = list(call_specs)
        self._lock = threading.Lock()
        self.calls: list[dict] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        tag: str,
        timeout_s: float | None = None,
    ) -> LlmResult:
        with self._lock:
            idx = len(self.calls)
            self.calls.append({"idx": idx, "tag": tag, "model": model})
            spec = self._next_spec(idx)
        if spec.wait_event is not None:
            spec.wait_event.wait(timeout=10.0)
        if spec.exc is not None:
            raise spec.exc
        assert spec.text is not None
        return LlmResult(
            text=spec.text,
            model=spec.model,
            tokens_in=spec.tokens_in,
            tokens_out=spec.tokens_out,
            latency_ms=spec.latency_ms,
        )

    def _next_spec(self, idx: int) -> VoteCall:
        return self._specs[idx]


class PerVoterStub(ThreadSafeStub):
    """평가자별 응답 묶음 — 평가자(스레드)가 첫 호출에 묶음 하나를 집고 재시도는 그 묶음에서 이어 씀(11/25 전체 점검 QA-AI-01).

    `ThreadSafeStub` 은 호출 순서대로 꺼내 평가자 셋이 동시에 돌면 한 평가자가 다른 평가자의 재시도 응답을 가져갈 수 있다.
    스레드가 재사용돼도 집은 묶음을 다 쓰면 다음 묶음을 집는다.
    """

    def __init__(self, scripts: list[list[VoteCall]]) -> None:
        super().__init__([c for script in scripts for c in script])
        self._scripts = [list(s) for s in scripts]
        self._next_script = 0
        self._local = threading.local()

    def _next_spec(self, idx: int) -> VoteCall:  # noqa: ARG002 — 순서 대신 평가자별 묶음
        script = getattr(self._local, "script", None)
        if not script:
            script = self._local.script = self._scripts[self._next_script]
            self._next_script += 1
        return script.pop(0)


def make_judge(stub: ThreadSafeStub, *, votes: int = 3, schema_retry: int = 1) -> Judge:
    get_settings.cache_clear()
    settings = get_settings()
    return Judge(stub, settings, prompt_name="judge_v3", votes=votes, schema_retry=schema_retry)
