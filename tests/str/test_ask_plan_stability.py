"""계획 흔들림 재기 도구 — 대상 48 · 녹화는 읽기만 · 다름/실패 세기 (SCRUM-362 ★B4, 정본 docs/str/08). LLM 없음."""

from __future__ import annotations

import hashlib
import json

import pytest
from tools import ask_plan_sig as plan_sig
from tools import ask_plan_stability as stab
from tools import record, record_ask_answer

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult, RecordedLlmClient
from aml_ai.str.domain.constants_ask import ASK_PLAN_PROMPT
from tests.conftest import load_json


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch):
    """도구는 AI_LLM_MOCK=false 에서만 돈다 — 실제 클라이언트 대신 주입한 가짜만 쓰므로 호출 0."""
    monkeypatch.setenv("AI_LLM_MOCK", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _snapshot() -> dict[str, str]:
    return {
        str(p.relative_to(record.RECORDED)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(record.RECORDED.rglob("*"))
        if p.is_file()
    }


def test_targets_are_48_with_unique_ids_and_no_code_blocked() -> None:
    it = stab.items()
    ids = [i["id"] for i in it]
    assert len(it) == 48 and len(set(ids)) == 48  # 44 + 복합 WHY K1~K4(추가 검토 1)
    assert sum(i["expected_kind"] == "OUT_OF_SCOPE" for i in it) == 6  # 18개 범위 밖 6 포함
    assert "359:C2" not in ids and {"18:O1", "359:O1", "18:W2", "359:X1", "362:K1", "362:K4"} <= set(ids)


def test_recordings_are_read_only(live_mode, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """녹화 폴더 전체가 실행 전후 바이트 그대로 · 저장 함수는 안 불림 · 녹화와 같은 계획이면 48/48 같음."""
    monkeypatch.setattr(record, "_save", lambda *a, **k: pytest.fail("녹화 저장"))
    monkeypatch.setattr(record_ask_answer, "_save", lambda *a, **k: pytest.fail("녹화 저장"))
    before = _snapshot()
    code = stab.main(["--n", "2"], client=lambda _s: RecordedLlmClient(record.RECORDED))
    assert _snapshot() == before
    out = capsys.readouterr().out
    assert code == 0 and "다름 문항 0/48 · 기대와 같음 48/48 · 실패 0 · 호출 96" in out
    assert "reasoning_effort=" in out and f"{ASK_PLAN_PROMPT} sha256 " in out


class _Flip:
    """홀수 번째 호출은 녹화 그대로, 짝수 번째는 범위 밖으로 바꿔 돌려줌."""

    def __init__(self) -> None:
        self.inner, self.n = RecordedLlmClient(record.RECORDED), 0

    def complete_json(self, **kw) -> LlmResult:
        self.n += 1
        res = self.inner.complete_json(**kw)
        if self.n % 2:
            return res
        flipped = {"kind": "OUT_OF_SCOPE", "out_of_scope_reason": "JUDGMENT", "bundles": []}
        return LlmResult(text=json.dumps(flipped), model=res.model, tokens_in=1, tokens_out=1, latency_ms=1)


def test_differences_are_counted_with_field_summary(live_mode, capsys) -> None:
    code = stab.main(["--n", "2", "--only", "18:F1"], client=lambda _s: _Flip())
    out = capsys.readouterr().out
    assert code == 3
    assert "| 18:F1 | 1/2 | 1/2 | 0 | 2회 kind FACT→OUT_OF_SCOPE · 사유 null→JUDGMENT · 묶음 -flows |" in out
    assert "다름 문항 1/1 · 기대와 같음 0/1 · 실패 0" in out


class _Broken:
    def complete_json(self, **_kw) -> LlmResult:
        return LlmResult(text="not json", model="m", tokens_in=0, tokens_out=0, latency_ms=0)


def test_schema_failure_is_counted_apart_from_difference(live_mode, capsys) -> None:
    code = stab.main(["--n", "3", "--only", "358:P1"], client=lambda _s: _Broken())
    out = capsys.readouterr().out
    assert code == 3 and "| 358:P1 | 0/3 | 0/3 | 3 |" in out and "실패 3" in out


def test_refuses_in_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_LLM_MOCK", "true")
    get_settings.cache_clear()
    try:
        assert stab.main(["--n", "1"], client=lambda _s: pytest.fail("호출")) == 2
    finally:
        get_settings.cache_clear()


def test_eval_sets_unchanged_question_count() -> None:
    """대상은 세트 파일에서만 — 18 · 11 · 16(C2 빼고 15)."""
    sets = [load_json(p)["items"] for p in (stab.EVAL_SET, stab.judge.PREMISE_SET, stab.judge.GAPS_SET)]
    assert [len(s) for s in sets] == [18, 11, 16]


class _AddFlows:
    """녹화 계획에 flows 를 더해 돌려줌 — 359:X1 꼴(질문의 `입금` 으로 코드가 어차피 flows 를 붙임)."""

    def __init__(self) -> None:
        self.inner = RecordedLlmClient(record.RECORDED)

    def complete_json(self, **kw) -> LlmResult:
        res = self.inner.complete_json(**kw)
        plan = json.loads(res.text)
        plan["bundles"] = [*plan["bundles"], "flows"] if "flows" not in plan["bundles"] else plan["bundles"]
        return LlmResult(text=json.dumps(plan), model=res.model, tokens_in=1, tokens_out=1, latency_ms=1)


def test_extra_flows_covered_by_code_is_same(live_mode, capsys) -> None:
    """★B4-2 (가) — 다름 = 코드가 실제로 꺼낸 묶음이 다를 때. X1 은 같음, W2(방향 낱말 없음)는 다름."""
    code = stab.main(["--n", "1", "--only", "359:X1,18:W2"], client=lambda _s: _AddFlows())
    out = capsys.readouterr().out
    assert "| 359:X1 | 1/1 | 1/1 | 0 | - |" in out
    assert "| 18:W2 | 0/1 | 0/1 | 0 | 1회 묶음 +flows |" in out and code == 3


def test_expected_fixture_has_48_and_matches_active_recordings() -> None:
    """기대 계획 = report ★B4-3 표 44 + 복합 K1~K4 — 활성 계획 프롬프트 녹화가 기대와 같음(v1·v2 명시 비교는 test_ask_review_362_1b)."""
    from aml_ai.str.domain.ask_question import mask_question
    from aml_ai.str.infrastructure.ask_llm import AskLlm

    plans = load_json(stab.EXPECTED)["plans"]
    assert set(plans) == {i["id"] for i in stab.items()}
    llm = AskLlm(RecordedLlmClient(record.RECORDED), get_settings())
    for it in stab.items():
        q = mask_question(it["question"])
        got = llm.plan(q, deadline=float("inf")).out
        assert plan_sig._plan_sig(got, q) == stab.expected_sig(it["id"]), it["id"]


class _Expected:
    """질문마다 기대 계획 픽스처 그대로 돌려주는 가짜(계획 녹화 도구 `--all` 시험용)."""

    def __init__(self, _settings) -> None:  # noqa: ANN001
        from aml_ai.str.domain.ask_question import mask_question
        from aml_ai.str.infrastructure.ask_llm import isolate_question

        plans = load_json(stab.EXPECTED)["plans"]
        self.by_q = {isolate_question(mask_question(i["question"])): plans[i["id"]] for i in stab.items()}

    def complete_json(self, **kw) -> LlmResult:
        q = kw["user"].split("<question>\n")[1].split("\n</question>")[0]
        return LlmResult(text=json.dumps(self.by_q[q]), model="m", tokens_in=1, tokens_out=1, latency_ms=1)


def test_plan_recorder_all_records_48_including_out_of_scope(
    tmp_path, monkeypatch, live_mode, capsys
) -> None:
    """`record_ask --plan --all` — 48문항(범위 밖 6 · 복합 4 포함) 녹화 · 맞음 = 기대 계획과 같음 · 저장은 지정 폴더에만."""
    from tools import record_ask

    from aml_ai.str.domain.constants_ask import ASK_PLAN_PROMPT

    monkeypatch.setattr(record, "RECORDED", tmp_path)
    monkeypatch.setattr(record_ask, "HttpLlmClient", _Expected)
    assert record_ask.main(["--plan", "--all"]) == 0
    out = capsys.readouterr().out
    assert len(list((tmp_path / ASK_PLAN_PROMPT).glob("*.json"))) == 48
    assert "범위 밖 OUT_OF_SCOPE 6/6 · 분류 틀림 0/48" in out
    assert "| 18:W2 | WHY [rule_facts] | WHY [rule_facts] | O |" in out
