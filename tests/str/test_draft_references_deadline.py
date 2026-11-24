"""SCRUM-413 초안 검색 마감 = 요청 deadline − `LLM_TIMEOUT_S` (docs/str/03 초안 6, ★A ⑤ (나)). DB·LLM 0.

숫자 35 에 기대지 않게 설정값을 바꿔 시험. 검색 시간 초과는 지금 검색 실패처럼 `references=[]`.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.schemas.str import DraftRequest, Reference
from aml_ai.str.application.draft_service import DraftService
from tests.conftest import EXAMPLES, load_json
from tests.str.summary_service_support import StubReader

LLM_TIMEOUT = 5.0  # 기본 35 와 다른 값 — 코드가 설정값을 쓰는지 본다


def _ref(i: int) -> Reference:
    return Reference(chunk_id=f"c{i}", doc_id="d", doc_title="t", page=1, score=0.9, text="x")


class _Retriever:
    def __init__(self, error: Exception | None = None) -> None:
        self.kwargs: list[dict] = []
        self.error = error

    def retrieve(self, _facts, **kw):  # type: ignore[no-untyped-def]
        self.kwargs.append(kw)
        if self.error is not None:
            raise self.error
        return [_ref(1)]


def _service(retriever: _Retriever, **kw) -> DraftService:  # type: ignore[no-untyped-def]
    settings = get_settings().model_copy(update={"llm_timeout_s": LLM_TIMEOUT})
    fields = dict(
        settings=settings, session=None, reader=None, fewshot=None, retriever=retriever,
        generator=SimpleNamespace(prompt_version="narrative_v2"), judge=None, rewriter=None, generations=None,
    )  # fmt: skip
    fields.update(kw)
    return DraftService(**fields)  # type: ignore[arg-type]


def test_search_deadline_is_request_deadline_minus_llm_timeout() -> None:
    r = _Retriever()
    assert [x.chunk_id for x in _service(r)._references(None, 100.0)] == ["c1"]  # type: ignore[arg-type]
    assert r.kwargs == [{"deadline": 100.0 - LLM_TIMEOUT}]


def test_no_deadline_calls_retrieve_as_before() -> None:
    """하네스·평가 도구가 부르는 `_references(facts)` — 지금 동작 그대로."""
    r = _Retriever()
    _service(r)._references(None)  # type: ignore[arg-type]
    assert r.kwargs == [{}]


def test_search_timeout_continues_without_references() -> None:
    r = _Retriever(RetrievalUnavailable("rag deadline"))
    assert _service(r)._references(None, 100.0) == []  # type: ignore[arg-type]


class _Stop(Exception):
    pass


def test_generate_passes_request_deadline_to_references(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.draft_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)
    seen: list[tuple] = []

    def capture(facts, deadline=None):  # type: ignore[no-untyped-def]
        seen.append((facts, deadline))
        raise _Stop

    svc = _service(_Retriever(), reader=StubReader(), fewshot=SimpleNamespace(pick_examples=lambda _t: []))
    svc._references = capture  # type: ignore[method-assign]
    req = DraftRequest.model_validate(load_json(EXAMPLES / "draft_request.json"))
    deadline = time.monotonic() + 80
    with pytest.raises(_Stop):
        svc._generate(req, "g" * 32, deadline)
    ((facts, got),) = seen
    assert facts is not None and got == deadline
