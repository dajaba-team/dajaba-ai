"""tools.record — v4 는 녹화 대상 아님(코드 조립, 프롬프트 파일 없음). 11/18 기본값 v4 뒤 조용한 무동작·트레이스백 대신 바로 멈춤.

생성 녹화(기본 모드)만 막음 — 평가자·고쳐 쓰기·요약 녹화는 narrative_prompt 를 안 씀. LLM·DB 0.
"""

from __future__ import annotations

import pytest
import tools.record as record

from aml_ai.shared.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AI_LLM_MOCK", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _no_call(*a, **kw):  # type: ignore[no-untyped-def]
    raise AssertionError("v4 에서 녹화 경로로 들어감")


def test_v4_narrative_record_stops_with_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v4")
    monkeypatch.setattr(record, "_record_narrative", _no_call)
    monkeypatch.setattr(record, "_load_facts", _no_call)
    assert record.main(["--case", "fan_in"]) == 2
    assert "v4 는 녹화 대상 아님 — NARRATIVE_PROMPT 로 v1~v3 지정" in capsys.readouterr().err


def test_default_settings_also_stop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`.env`·env 에 NARRATIVE_PROMPT 가 없으면 기본값 v4 — 같은 메시지로 멈춤."""
    monkeypatch.delenv("NARRATIVE_PROMPT", raising=False)
    monkeypatch.setattr(record, "get_settings", lambda: record.Settings(_env_file=None))
    monkeypatch.setattr(record, "_record_narrative", _no_call)
    assert record.main(["--case", "fan_in"]) == 2
    assert "v4 는 녹화 대상 아님 — NARRATIVE_PROMPT 로 v1~v3 지정" in capsys.readouterr().err


@pytest.mark.parametrize("prompt", ["narrative_v1", "narrative_v2", "narrative_v3"])
def test_v1_to_v3_still_reach_record(prompt: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", prompt)
    seen: list[str] = []
    monkeypatch.setattr(record, "_record_narrative", lambda s, f: seen.append(s.narrative_prompt) or 0)
    assert record.main(["--case", "fan_in"]) == 0 and seen == [prompt]


def test_judge_mode_is_not_blocked_by_v4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v4")
    monkeypatch.setattr(record, "_record_judge", lambda s, f, r: 0)
    assert record.main(["--case", "fan_in", "--judge"]) == 0
