"""SCRUM-207 — N 중앙값 병렬 호출의 deadline 처리 (docs/str/06·09).

한 호출이 deadline 넘게 걸리는 가짜 LLM — verify 응답이 **deadline 근처** 에서 돌아옴.
돌고 있는 호출은 `future.cancel()` 로 안 멈추므로 **httpx 타임아웃에 맡김**(09 알고 남김) —
테스트에서는 `threading.Event` 로 가짜 LLM 쪽을 테스트 끝에 풀어 리소스 회수.

executor 는 `with ThreadPoolExecutor(...)` 가 아니라 **직접 만들고 finally 에서
`shutdown(wait=False, cancel_futures=True)`** — `with` 는 블록을 나갈 때 돌고 있는 스레드를
기다려 deadline 을 넘긴다.

assert 로 확인하는 것: ① 걸린 시간 ≤ deadline + 0.5s · ② 느린 호출 결과를 기다리지 않음
(tokens_in = 두 호출 합, 세 호출 합 아님) · ③ `shutdown(wait=False, cancel_futures=True)` 호출.

develop 에서는 votes 자체가 없어 TypeError — 실패해야 정상.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor as _RealTPE

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.str.infrastructure import judge_vote as judge_vote_mod
from aml_ai.str.infrastructure.judge import Judge
from tests.str.judge_votes_support import (
    ThreadSafeStub,
    VoteCall,
    dummy_narrative,
    v3_payload,
)


def _make_spy_tpe(shutdown_calls: list[dict]) -> type[_RealTPE]:
    class SpyTPE(_RealTPE):
        def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:  # type: ignore[override]
            shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    return SpyTPE


def _build_stub(slow: threading.Event) -> ThreadSafeStub:
    return ThreadSafeStub([
        VoteCall(text=v3_payload([5, 5, 5, 5, 5]), tokens_in=1000),
        VoteCall(text=v3_payload([3, 5, 5, 5, 5]), tokens_in=1000),
        VoteCall(text=v3_payload([5, 5, 5, 5, 5]), tokens_in=1000, wait_event=slow),
    ])  # fmt: skip


def test_slow_call_does_not_block_response_past_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 호출 즉시 응답 + 한 호출 Event 대기 — Judge.run 이 deadline 안에 끝난 2개로 집계 결정.

    assert: ① 시간 ≤ deadline + 0.5s · ② tokens_in = 2000 (느린 호출 미섞임) · ③ shutdown 호출.
    """
    shutdown_calls: list[dict] = []
    monkeypatch.setattr(judge_vote_mod, "ThreadPoolExecutor", _make_spy_tpe(shutdown_calls))

    slow = threading.Event()
    try:
        stub = _build_stub(slow)
        get_settings.cache_clear()
        judge = Judge(stub, get_settings(), prompt_name="judge_v3", votes=3, schema_retry=0)
        deadline_offset = 0.5
        started = time.monotonic()
        result = judge.run(
            facts_masked={}, narrative=dummy_narrative(), fact_keys=[],
            deadline=time.monotonic() + deadline_offset,
        )  # fmt: skip
        elapsed = time.monotonic() - started
    finally:
        slow.set()  # 백그라운드 스레드 회수

    assert elapsed <= deadline_offset + 0.5, f"응답 대기 {elapsed:.2f}s (deadline + 0.5s 초과)"
    assert result.meta.tokens_in == 2000, (
        f"tokens_in={result.meta.tokens_in} (세 호출 합이면 느린 호출 기다림)"
    )
    assert any(c["wait"] is False and c["cancel_futures"] is True for c in shutdown_calls), (
        f"shutdown(wait=False, cancel_futures=True) 호출 안 됨 — 기록: {shutdown_calls}"
    )
    assert {c.check.value: c.score for c in result.checks}["FIVE_W_ONE_H_COMPLETE"] == 3
