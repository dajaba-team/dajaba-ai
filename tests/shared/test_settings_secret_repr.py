"""Settings repr 에 비밀값이 안 들어가는지 (SCRUM-127, 2026-11-09).

★L 1·2 pytest 실패 출력에 `Settings(...)` repr 이 찍혀 `app_ai_password` 앞부분이 노출된 사례.
`Field(..., repr=False)` 로 세 칸을 repr 제외. SecretStr 은 사용처가 많아 이번엔 X.
"""

from __future__ import annotations

from aml_ai.shared.config import Settings


def test_settings_repr_hides_secrets(monkeypatch) -> None:
    sentinels = {
        "APP_AI_PASSWORD": "pw-sentinel-9f3c",
        "AI_INTERNAL_KEY": "ik-sentinel-9f3c",
        "LLM_API_KEY": "sk-sentinel-9f3c",
    }
    for k, v in sentinels.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.app_ai_password == sentinels["APP_AI_PASSWORD"]  # 값 자체는 정상 접근
    assert s.ai_internal_key == sentinels["AI_INTERNAL_KEY"]
    assert s.llm_api_key == sentinels["LLM_API_KEY"]
    r = repr(s)
    for v in sentinels.values():
        assert v not in r, f"repr 에 비밀값 노출: {v}"
