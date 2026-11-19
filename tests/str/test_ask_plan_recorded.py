"""ask_plan_v1 녹화 재생 — 평가 세트 18개 (SCRUM-290 290-1, 정본 docs/str/08 "질문 답변 평가 세트").

계획은 facts 를 안 받으므로 녹화 키 = 가린 질문. 범위 밖 6개는 서비스 끝까지 `OUT_OF_SCOPE`(목표 6/6).
범위 안 12개는 계획 출력이 스키마를 지나는지까지만 — 분류 정확도는 참고 지표라 `tools.record_ask` 표로 본다.
"""

from __future__ import annotations

import math

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import RecordedLlmClient
from aml_ai.shared.schemas.str import AskStatus
from aml_ai.str.domain.ask_question import mask_question
from aml_ai.str.infrastructure.ask_llm import AskLlm
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import ask_request, build_service

EVAL = load_json(FIXTURES / "ask_eval_set.json")["items"]
OUT_OF_SCOPE = [i for i in EVAL if i["expected_kind"] == "OUT_OF_SCOPE"]
IN_SCOPE = [i for i in EVAL if i["expected_kind"] != "OUT_OF_SCOPE"]


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _recorded() -> RecordedLlmClient:
    return RecordedLlmClient(get_settings().recorded_dir)


def test_eval_set_is_eighteen() -> None:
    assert (len(EVAL), len(OUT_OF_SCOPE), len(IN_SCOPE)) == (18, 6, 12)


@pytest.mark.parametrize("item", OUT_OF_SCOPE, ids=lambda i: i["id"])
def test_out_of_scope_replay_ends_out_of_scope(item: dict) -> None:
    svc, repo = build_service(_recorded())
    res = svc.ask(ask_request(item["question"]))
    assert res.status is AskStatus.OUT_OF_SCOPE
    if item["expected_reason"] is not None:
        assert res.out_of_scope_reason.value == item["expected_reason"]
    assert repo.saved[0]["status"] == "SUCCEEDED"


@pytest.mark.parametrize("item", IN_SCOPE, ids=lambda i: i["id"])
def test_in_scope_replay_plan_is_valid(item: dict) -> None:
    s = get_settings()
    plan = AskLlm(_recorded(), s).plan(mask_question(item["question"]), deadline=math.inf)
    assert plan.out.kind.value in {"FACT", "WHY", "OUT_OF_SCOPE"}
    assert plan.llm_model
