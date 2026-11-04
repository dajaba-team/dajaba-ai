"""SCRUM-92 — 평가자 모델 폴백 경고 (docs/str/06 "모델", 09 11/4).

조건: `AI_LLM_MOCK=false` 이고 (`LLM_MODEL_JUDGE` 가 비었거나 `LLM_MODEL_GENERATE` 와 같을 때)
→ `(model, reason)` 반환하는 순수 함수 `judge_model_decision(settings)` 가 reason 을 돌려준다.
`reason` 이 있으면 `main.lifespan` 이 `log.warning("judge_model_fallback", extra=...)` 한 번.

앱 기동 없이 함수만 부르는 단위 테스트 — fixture 동기 문제 없음.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.config import Settings
from aml_ai.str.infrastructure.judge import judge_model_decision


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "AI_LLM_MOCK": False,
        "LLM_MODEL_GENERATE": "gpt-5-generate",
        "LLM_MODEL_JUDGE": "gpt-5-judge",
    }
    base.update(over)
    return Settings(**base)


def test_decision_different_models_no_warning() -> None:
    s = _settings(LLM_MODEL_JUDGE="gpt-5-judge")
    model, reason = judge_model_decision(s)
    assert model == "gpt-5-judge"
    assert reason is None


def test_decision_empty_judge_warns_empty() -> None:
    s = _settings(LLM_MODEL_JUDGE="")
    model, reason = judge_model_decision(s)
    assert model == "gpt-5-generate"  # 폴백은 유지
    assert reason == "EMPTY"


def test_decision_same_model_warns_same() -> None:
    s = _settings(LLM_MODEL_JUDGE="gpt-5-generate")  # == LLM_MODEL_GENERATE
    model, reason = judge_model_decision(s)
    assert model == "gpt-5-generate"
    assert reason == "SAME"


def test_decision_mock_mode_no_warning_even_if_empty() -> None:
    """녹화 재생일 땐 모델을 안 쓰므로 경고 안 함 — 테스트·CI 로그 덮임 방지."""
    s = _settings(AI_LLM_MOCK=True, LLM_MODEL_JUDGE="")
    model, reason = judge_model_decision(s)
    assert reason is None


def test_decision_mock_mode_no_warning_even_if_same() -> None:
    s = _settings(AI_LLM_MOCK=True, LLM_MODEL_JUDGE="gpt-5-generate")
    model, reason = judge_model_decision(s)
    assert reason is None


def test_lifespan_emits_warning_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """main.lifespan 이 조건 만족 시 `judge_model_fallback` 한 번만 찍고 기동은 성공.

    기동 실패 아님(Jira "경고 한 줄"). `setup_logging` 이 root 핸들러를 교체하므로
    pytest caplog 대신 `main.log.warning` 을 직접 가로챈다(`judge_log` fixture 패턴).
    """
    from fastapi.testclient import TestClient

    import aml_ai.main as main_module
    from aml_ai.shared.config import get_settings

    monkeypatch.setenv("AI_LLM_MOCK", "false")
    monkeypatch.setenv("LLM_MODEL_GENERATE", "gpt-5-generate")
    monkeypatch.setenv("LLM_MODEL_JUDGE", "")
    monkeypatch.setenv("INDEX_PROMPTS_ON_STARTUP", "false")
    monkeypatch.setenv("LLM_API_KEY", "x")  # HttpLlmClient 생성이 터지지 않게
    get_settings.cache_clear()

    calls: list[tuple[str, dict]] = []

    class _Spy:
        def warning(self, msg: str, extra: dict | None = None) -> None:
            calls.append((msg, dict(extra or {})))

    monkeypatch.setattr(main_module, "log", _Spy())

    with TestClient(main_module.app):
        pass

    fallbacks = [(m, e) for (m, e) in calls if m == "judge_model_fallback"]
    assert len(fallbacks) == 1
    _, extra = fallbacks[0]
    assert extra["reason"] == "EMPTY"
    assert extra["judge"] == ""
    assert extra["generate"] == "gpt-5-generate"
