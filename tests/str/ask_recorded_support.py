"""질문 답변 녹화 재생 공용 — 평가 세트·픽스처 facts·오류 주입 래퍼 (SCRUM-290 2/2, 08).

래퍼는 진짜 녹화(`recorded/<ASK_ANSWER_PROMPT>/`)를 읽은 뒤 답만 바꾸거나(`AnswerRewrite`), 계획만 녹화로 두고 답을 고정 원문으로
(`FixedAnswer`, SCRUM-362 — v3 답 녹화 전) 돌린다. `recorded/` 에는 실제 LLM 출력만 둔다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult, RecordedLlmClient
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.constants_ask import ASK_ANSWER_PROMPT
from tests.conftest import FIXTURES, load_json

EVAL = load_json(FIXTURES / "ask_eval_set.json")["items"]
IN_SCOPE = [i for i in EVAL if i["expected_kind"] != "OUT_OF_SCOPE"]
_COUNT = re.compile(r"(\d+)(건|개|회)")
OUT_OF_CHECK_SENTENCE = " 거래한 은행은 7곳이에요."  # 06 — 검사 밖 문맥(은행 수), 값은 facts 에 없음


def item(item_id: str) -> dict:
    return next(i for i in EVAL if i["id"] == item_id)


def facts_for(it: dict) -> Facts:
    """질문 답변 전용 복사본(`facts_ask_<case>.json`, 새 칸 있음 — SCRUM-358·359)이 있으면 그것, 없으면 기준 픽스처."""
    return Facts.model_validate(load_json(fixture_path(it["facts_case"])))


def fixture_path(case: str):
    copy = FIXTURES / f"facts_ask_{case}.json"
    return copy if copy.exists() else FIXTURES / f"facts_{case}.json"


def recorded() -> RecordedLlmClient:
    return RecordedLlmClient(get_settings().recorded_dir)


@dataclass
class AnswerRewrite:
    """답 호출 결과의 JSON 만 `edit` 로 바꾼다. 계획 호출은 그대로."""

    inner: RecordedLlmClient
    edit: Callable[[dict], dict]

    def complete_json(self, **kw) -> LlmResult:
        res = self.inner.complete_json(**kw)
        if kw["tag"] != ASK_ANSWER_PROMPT:
            return res
        return replace(res, text=json.dumps(self.edit(json.loads(res.text)), ensure_ascii=False))


def bump_first_count(out: dict) -> dict:
    """오류 주입 ① — 답의 첫 건수 숫자를 +2. 건수가 없으면 테스트가 실패하도록 AssertionError."""
    m = _COUNT.search(out["answer"] or "")
    assert m, "녹화 답에 건수 표현이 없음"
    wrong = f"{int(m.group(1)) + 2}{m.group(2)}"
    return {**out, "answer": out["answer"][: m.start()] + wrong + out["answer"][m.end() :]}


def add_out_of_check_number(out: dict) -> dict:
    """오류 주입 ② — 검사 밖 문맥의 틀린 숫자를 덧붙임(남는 위험, 06)."""
    return {**out, "answer": (out["answer"] or "") + OUT_OF_CHECK_SENTENCE}


def not_answerable(_out: dict) -> dict:
    return {"answerable": False, "answer": None, "cites": []}


@dataclass
class FixedAnswer:
    """계획은 녹화 그대로, 답 호출만 고정 원문(v3 모양 — None 이면 answerable false). 실제 LLM 출력이 아니다(SCRUM-362)."""

    inner: RecordedLlmClient
    answer: str | None

    def complete_json(self, **kw) -> LlmResult:
        if kw["tag"] != ASK_ANSWER_PROMPT:
            return self.inner.complete_json(**kw)
        out = {"answerable": self.answer is not None, "answer": self.answer}
        return LlmResult(
            text=json.dumps(out, ensure_ascii=False), model="fixed", tokens_in=0, tokens_out=0, latency_ms=0
        )


def replay_verdict(it: dict, llm=None) -> tuple[str, str]:  # noqa: ANN001
    """(상태, 판정) — 녹화 도구와 같은 판정 함수(`tools.ask_judge_mark`). 답 문장은 돌려주지 않음."""
    from tools.ask_judge_mark import mark

    from aml_ai.str.domain.ask_bundles import extract
    from aml_ai.str.infrastructure.display_labels import load_display_labels
    from tests.str.ask_service_support import ask_request, build_service

    svc, repo = build_service(llm or recorded(), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    raw = (repo.saved[0]["response_payload"].get("llm_answer") or {}).get("answer") or ""
    labels = load_display_labels()
    from tools.ask_fixture_scope import fixture_scope

    req = ask_request(it["question"], rule_id=it["rule_id"])
    facts = facts_for(it)
    piece = extract(
        facts, it["rule_id"], res.generation_meta.bundles, labels, scope=fixture_scope(facts, req)
    )
    return res.status.value, mark(it, res, raw, piece, labels)
