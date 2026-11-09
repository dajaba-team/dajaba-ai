"""SCRUM-147 — rewrite_code_failed 시 log.warning 에 실패 check 세 필드만 (본문·값 금지)."""

from __future__ import annotations

import logging

from tests.str.rewrite_support import (
    FakeJudge,
    FakeRewriter,
    JudgeOut,
    broken_narrative,
    call_try_rewrite,
    good_narrative,
)  # noqa: E501


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_rewrite_code_failed_logs_checks() -> None:  # caplog 안 씀 — full 세션에서 handler 교란 회피
    from aml_ai.shared.schemas.str.verify import LlmCheckName

    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    handler = _ListHandler()
    rw_logger = logging.getLogger("aml_ai.str.application.draft_rewrite")
    rw_logger.addHandler(handler)
    rw_logger.setLevel(logging.WARNING)
    rw_logger.disabled = False
    try:
        meta, _, _ = call_try_rewrite(
            original_narrative=good_narrative(),
            judge=FakeJudge(JudgeOut(scores=scores, comments={})),
            rewriter=FakeRewriter(narrative=broken_narrative()),
            clock=lambda: 0.0,
            deadline=80.0,
        )
    finally:
        rw_logger.removeHandler(handler)
    assert meta.skipped_reason == "rewrite_code_failed"
    events = [r for r in handler.records if r.msg == "rewrite_code_failed"]
    assert len(events) == 1
    assert all(set(c) == {"check", "section", "reason"} for c in events[0].checks)
