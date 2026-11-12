"""SCRUM-207 Codex adversarial — 성공 <2·BudgetExceeded 때도 judge_meta 보존.

SCRUM-144·92 규칙("응답 받은 호출 토큰은 실패해도 합산해 judge_meta 로 예외에 붙임") 과 같은 원칙을
N 중앙값에도 적용. verify_service 가 `getattr(exc, "judge_meta", None)` 으로 저장하므로 null 로 끊기지
않게.

케이스:
- 성공 1 + 연결 실패 2 → `judge_meta.tokens_in=1000·attempts=3`
- 성공 1 + 스키마 실패(재시도까지) 1 + 연결 실패 1 → 토큰·attempts 합산
- 성공 0 (전부 스키마 2연속 실패) → 응답 받은 호출 토큰 합산 + attempts = submit 수 + 재시도
- BudgetExceeded 가 늦게 완료 → 그때까지 받은 두 성공 토큰 합산
"""

from __future__ import annotations

import threading
import time

import pytest

from aml_ai.shared.errors import BudgetExceeded, LlmInvalidOutput, LlmUnavailable
from aml_ai.str.infrastructure import judge_vote as judge_vote_mod
from tests.str.judge_votes_support import (
    ThreadSafeStub,
    VoteCall,
    dummy_narrative,
    make_judge,
    v3_payload,
)


def _run(stub: ThreadSafeStub, **judge_kw: int):
    judge = make_judge(stub, **judge_kw)
    return judge.run(facts_masked={}, narrative=dummy_narrative(), fact_keys=[])


def _force_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    """ThreadSafeStub idx 가 ballot 과 1:1 로 매핑되게 ThreadPoolExecutor max_workers=1 강제.

    병렬이면 세 ballot 이 동시에 complete_json lock 을 잡고 idx 가 ballot 과 섞인다 — 테스트
    비결정적. 집계 로직 자체는 run_votes 입력 측에서 완결이라 직렬 실행도 같은 코드 경로.
    """
    from concurrent.futures import ThreadPoolExecutor as _RealTPE

    monkeypatch.setattr(judge_vote_mod, "ThreadPoolExecutor", lambda max_workers: _RealTPE(max_workers=1))


def test_one_success_two_unavailable_preserves_meta() -> None:
    """성공 1 + 연결 실패 2 → raise 되는 예외에 judge_meta 붙음, tokens_in=1000·attempts=3."""
    stub = ThreadSafeStub([
        VoteCall(text=v3_payload([5, 5, 5, 5, 5]), tokens_in=1000, tokens_out=400),
        VoteCall(exc=LlmUnavailable("down-1")),
        VoteCall(exc=LlmUnavailable("down-2")),
    ])  # fmt: skip
    with pytest.raises(LlmUnavailable) as excinfo:
        _run(stub)
    jm = getattr(excinfo.value, "judge_meta", None)
    assert jm is not None, "성공 1 의 토큰 보존 안 됨 (Codex finding 1 회귀)"
    assert jm.tokens_in == 1000
    assert jm.tokens_out == 400
    assert jm.attempts == 3  # submit 수 (각 재시도 1 호출)


def test_success_plus_schema_fail_plus_unavailable_preserves_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """성공 1 + 스키마 2연속 실패(Judge._call_with_retry 가 exc.judge_meta 붙임) + 연결 실패 1 —
    성공<2 라 raise, 하지만 합산된 meta.tokens_in=1000+200=1200·attempts=4."""
    _force_serial(monkeypatch)
    good = v3_payload([5, 5, 5, 5, 5])
    bad = "not-json"
    stub = ThreadSafeStub([
        VoteCall(text=good, tokens_in=1000, tokens_out=400),  # ballot 1 성공
        VoteCall(text=bad, tokens_in=100, tokens_out=50),     # ballot 2 1차 스키마
        VoteCall(text=bad, tokens_in=100, tokens_out=50),     # ballot 2 재시도 스키마
        VoteCall(exc=LlmUnavailable("down")),                  # ballot 3 연결 실패
    ])  # fmt: skip
    with pytest.raises((LlmInvalidOutput, LlmUnavailable)) as excinfo:
        _run(stub, schema_retry=1)
    jm = getattr(excinfo.value, "judge_meta", None)
    assert jm is not None
    assert jm.tokens_in == 1000 + 200  # 성공 + 스키마 두 호출
    assert jm.tokens_out == 400 + 100
    assert jm.attempts == 3 + 1  # submit 3 + 스키마 ballot 재시도 추가 1


def test_zero_success_all_schema_fail_preserves_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """세 ballot 모두 스키마 2연속 실패 — 응답 받은 호출 6개 토큰·attempts 보존."""
    _force_serial(monkeypatch)
    bad = "not-json"
    stub = ThreadSafeStub([VoteCall(text=bad, tokens_in=100, tokens_out=50) for _ in range(6)])
    with pytest.raises(LlmInvalidOutput) as excinfo:
        _run(stub, schema_retry=1)
    jm = getattr(excinfo.value, "judge_meta", None)
    assert jm is not None, "성공 0 이어도 응답 받은 호출 토큰은 보존 (Codex finding 1)"
    assert jm.tokens_in == 600  # 6 호출 × 100
    assert jm.tokens_out == 300
    assert jm.attempts == 3 + 3  # submit 3 + 각 ballot 재시도 1 ×3 = 6


def test_budget_exceeded_preserves_prior_success_meta() -> None:
    """BudgetExceeded 가 늦게 완료되도록 Event 로 지연 — 두 성공 완료 뒤 raise.

    예외에 그때까지 받은 두 ballot 의 토큰이 judge_meta 로 붙어야 한다.
    """
    block = threading.Event()
    stub = ThreadSafeStub([
        VoteCall(text=v3_payload([5, 5, 5, 5, 5]), tokens_in=1000),
        VoteCall(text=v3_payload([5, 5, 5, 5, 5]), tokens_in=1000),
        VoteCall(exc=BudgetExceeded("quota"), wait_event=block),
    ])  # fmt: skip
    # 다른 두 ballot 완료 시간 벌어 준 뒤 BudgetExceeded 올리기.
    threading.Timer(0.15, block.set).start()
    with pytest.raises(BudgetExceeded) as excinfo:
        _run(stub)
    jm = getattr(excinfo.value, "judge_meta", None)
    assert jm is not None, "BudgetExceeded 때도 이전 성공 토큰은 보존 (Codex finding 1)"
    assert jm.tokens_in == 2000, f"두 성공 ballot tokens_in 합 기대, 실제 {jm.tokens_in}"
    assert jm.attempts == 3  # submit 수


def test_zero_response_no_meta_attached() -> None:
    """아예 응답을 받은 호출이 0 (세 ballot 다 즉시 연결 실패) → judge_meta 는 None (빈 meta 안 붙임)."""
    stub = ThreadSafeStub([VoteCall(exc=LlmUnavailable(f"down-{i}")) for i in range(3)])
    with pytest.raises(LlmUnavailable) as excinfo:
        _run(stub)
    jm = getattr(excinfo.value, "judge_meta", None)
    assert jm is None, "토큰 아무것도 없는데 meta 를 만들면 안 됨 (불필요한 null 로 저장 혼선)"


def test_ballot_workers_inherit_request_id_contextvar() -> None:
    """부모 context 의 request_id ContextVar 가 세 스레드 안에서 그대로 보임 (Codex finding 2)."""
    from aml_ai.shared.logging import _request_id, current_request_id

    captured: list[str] = []
    captured_lock = threading.Lock()

    class RecordStub:
        def complete_json(self, **kw):  # type: ignore[no-untyped-def]
            rid = current_request_id()
            with captured_lock:
                captured.append(rid)
            # 느리게 — 세 스레드가 거의 동시 진입하도록
            time.sleep(0.02)
            from aml_ai.shared.infrastructure.llm_client import LlmResult

            return LlmResult(
                text=v3_payload([5, 5, 5, 5, 5]),
                model="x",
                tokens_in=1000,
                tokens_out=400,
                latency_ms=5000,
            )

    token = _request_id.set("rid-parent-xyz")
    try:
        from aml_ai.shared.config import get_settings
        from aml_ai.str.infrastructure.judge import Judge

        get_settings.cache_clear()
        judge = Judge(RecordStub(), get_settings(), prompt_name="judge_v3", votes=3, schema_retry=0)
        judge.run(facts_masked={}, narrative=dummy_narrative(), fact_keys=[])
    finally:
        _request_id.reset(token)

    assert len(captured) == 3
    assert all(rid == "rid-parent-xyz" for rid in captured), (
        f"ballot worker 들이 부모 request_id 를 못 봄 (Codex finding 2 회귀): {captured}"
    )
