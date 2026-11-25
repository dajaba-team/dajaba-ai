"""케이스 요약 — 거래 조회·성공 저장도 요청 마감 안에서 (11/25 전체 점검 QA-AI-03, docs/str/03 시간 예산). 가짜 시계. DB·LLM 0.

질문 답변(SCRUM-413)과 같은 도구를 씀 — 조회 전 `reader.bound_to_deadline` · 저장에 `timeout_s`(남은 시간)·`before_commit`(마감 재확인).
응답 칸·오류 코드 그대로 — 마감 밖은 502 `LLM_UNAVAILABLE`·FAILED 저장.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import SummaryRequest
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from tests.conftest import EXAMPLES, load_json
from tests.shared.db_deadline_support import db_error
from tests.str.summary_service_support import StubLlm, StubReader, build_service, ok_text

T0 = 1000.0
SLOW_S = 41.0  # 요약 예산 40초보다 1초 길게


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.summary_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


@pytest.fixture
def req() -> SummaryRequest:
    return SummaryRequest.model_validate(load_json(EXAMPLES / "summary_request.json"))


@dataclass
class Clock:
    now: float = T0

    def __call__(self) -> float:
        return self.now


@dataclass
class SpyReader(StubReader):
    """조회 순서 기록 — `slow_s` 만큼 거래 조회가 시계를 밀거나, 마감 설정·조회가 오류를 냄."""

    clock: Clock = field(default_factory=Clock)
    order: list[str] = field(default_factory=list)
    bound_args: list[tuple] = field(default_factory=list)
    slow_s: float = 0.0
    bound_error: Exception | None = None
    tx_error: Exception | None = None

    def bound_to_deadline(self, deadline, clock) -> None:  # type: ignore[no-untyped-def]
        self.order.append("bound")
        self.bound_args.append((deadline, clock))
        if self.bound_error is not None:
            raise self.bound_error

    def load_transactions(self, ids):  # type: ignore[no-untyped-def]
        self.order.append("load_transactions")
        self.clock.now += self.slow_s
        if self.tx_error is not None:
            raise self.tx_error
        return super().load_transactions(ids)


class SpyRepo(SummaryRepository):
    """저장 인자 기록. 성공 저장이 `slow_s` 걸리면 시계를 민 뒤 `before_commit`(있으면)을 부름 — 실제 커밋 직전 자리."""

    def __init__(self, clock: Clock, slow_s: float = 0.0) -> None:
        super().__init__(session=None)  # type: ignore[arg-type]
        self.clock, self.slow_s = clock, slow_s
        self.saved: list[dict] = []

    def save(self, **kw) -> None:  # type: ignore[no-untyped-def]
        self.saved.append(kw)
        if kw["status"] == "SUCCEEDED":
            self.clock.now += self.slow_s
            if kw.get("before_commit") is not None:
                kw["before_commit"]()


def _service(*, read_s: float = 0.0, save_s: float = 0.0, **reader_kw):  # type: ignore[no-untyped-def]
    clock = Clock()
    llm = StubLlm([ok_text(), ok_text()])
    svc = build_service(llm, clock=clock)
    svc.reader = SpyReader(clock=clock, slow_s=read_s, **reader_kw)
    svc.repo = SpyRepo(clock, save_s)
    return svc, llm


# ---------- 조회 ----------


def test_bound_runs_before_reads_with_request_deadline(req: SummaryRequest) -> None:
    svc, _ = _service()
    svc.summarize(req)
    assert svc.reader.order[:2] == ["bound", "load_transactions"]
    ((deadline, clock),) = svc.reader.bound_args
    assert deadline == T0 + svc.settings.summary_budget_s and clock is svc.clock


def test_slow_read_is_bounded_by_request_deadline(req: SummaryRequest) -> None:
    """조회 41초 — 조회 전에 마감(남은 40초)이 걸려 있어야 함. 지나서는 모델 호출 0·502·FAILED."""
    svc, llm = _service(read_s=SLOW_S)
    with pytest.raises(LlmUnavailable):
        svc.summarize(req)
    assert svc.reader.order[0] == "bound"
    assert llm.calls == []
    assert [r["status"] for r in svc.repo.saved] == ["FAILED"]


def test_expired_before_reads_is_502_without_reads_or_llm(req: SummaryRequest) -> None:
    svc, llm = _service(bound_error=LlmUnavailable("summary deadline passed"))
    with pytest.raises(LlmUnavailable):
        svc.summarize(req)
    assert svc.reader.order == ["bound"] and llm.calls == []
    (row,) = svc.repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("LLM_UNAVAILABLE: ")


@pytest.mark.parametrize("sqlstate", ["57014", "55P03"])
def test_read_timeout_is_llm_unavailable(req: SummaryRequest, sqlstate: str) -> None:
    svc, llm = _service(tx_error=db_error(sqlstate))
    with pytest.raises(LlmUnavailable):
        svc.summarize(req)
    assert llm.calls == []
    (row,) = svc.repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("LLM_UNAVAILABLE: ")


def test_other_db_error_on_read_is_not_mapped(req: SummaryRequest) -> None:
    """시간 초과가 아닌 DB 오류는 지금처럼 그대로 올라감 → 500 INTERNAL."""
    err = db_error("08006")
    svc, _ = _service(tx_error=err)
    with pytest.raises(type(err)) as caught:
        svc.summarize(req)
    assert caught.value is err
    (row,) = svc.repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("INTERNAL: ")


# ---------- 성공 저장 ----------


def test_success_save_gets_remaining_time_and_commit_check(req: SummaryRequest) -> None:
    svc, _ = _service()
    res = svc.summarize(req)
    (row,) = svc.repo.saved
    assert row["status"] == "SUCCEEDED" and res.summary_lines
    assert 0 < row["timeout_s"] <= svc.settings.summary_budget_s
    assert callable(row["before_commit"])


def test_slow_success_save_does_not_return_success(req: SummaryRequest) -> None:
    """저장 41초 — 마감 지나 커밋 직전이면 성공을 돌려주지 않고 502·FAILED."""
    svc, _ = _service(save_s=SLOW_S)
    with pytest.raises(LlmUnavailable):
        svc.summarize(req)
    assert [r["status"] for r in svc.repo.saved] == ["SUCCEEDED", "FAILED"]
    assert svc.repo.saved[1]["error"].startswith("LLM_UNAVAILABLE: ")


def test_no_time_left_before_save_is_502(req: SummaryRequest) -> None:
    """생성이 끝났을 때 이미 마감이 지났으면 성공 저장을 시작하지 않음."""
    svc, _ = _service()
    gen = svc.generator.generate

    def late(*a, **k):  # type: ignore[no-untyped-def]
        out = gen(*a, **k)
        svc.clock.now = T0 + svc.settings.summary_budget_s + 1
        return out

    svc.generator.generate = late  # type: ignore[method-assign]
    with pytest.raises(LlmUnavailable):
        svc.summarize(req)
    assert [r["status"] for r in svc.repo.saved] == ["FAILED"]
