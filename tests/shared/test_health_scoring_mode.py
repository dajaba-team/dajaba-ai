"""SCRUM-130 (1/2) — `/v1/health` 최상위 `scoring_mode` (docs/shared/02 「설치·버전」·05).

값: `AI_SCORING_MOCK=true` → `mock`. `false` → `score_service` 가 `aml_ml` 을 실제로 부르기 전까지는
패키지 유무와 상관없이 `unavailable`. `model` 판단과 그 테스트는 연결 PR(SCRUM-130 나머지)에서.
`status` 는 `scoring_mode` 와 상관없이 `ok`. `.env` 영향을 막으려고 설정은 `_env_file=None` 으로 고정.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.config import Settings, get_settings

EXISTING_KEYS = {
    "status",
    "db",
    "llm",
    "server_version",
    "model_version",
    "feature_version",
    "retrieval_version",
}


@pytest.fixture()
def health(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """`health(scoring_mock=...)` → (status_code, body). 인증 헤더 없이 부른다."""
    monkeypatch.delenv("AI_SCORING_MOCK", raising=False)

    def call(**overrides: object) -> tuple[int, dict]:
        settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
        app.dependency_overrides[get_settings] = lambda: settings
        with TestClient(app) as c:
            r = c.get("/v1/health")
        return r.status_code, r.json()

    yield call
    app.dependency_overrides.pop(get_settings, None)


def test_default_settings_is_mock(health) -> None:  # type: ignore[no-untyped-def]
    code, body = health()
    assert code == 200
    assert body["scoring_mode"] == "mock"
    assert body["status"] == "ok"


def test_mock_false_without_package_is_unavailable(health, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(sys.modules, "aml_ml", None)  # import aml_ml → ImportError
    code, body = health(AI_SCORING_MOCK=False)
    assert code == 200
    assert body["scoring_mode"] == "unavailable"
    assert body["status"] == "ok"  # 기동 판단은 그대로
    assert body["model_version"] is None and body["feature_version"] is None


def test_mock_false_with_package_is_still_unavailable_before_wiring(  # type: ignore[no-untyped-def]
    health, monkeypatch: pytest.MonkeyPatch
) -> None:
    """패키지만 먼저 들어간 상태(연결 전) — health 버전은 패키지 값, 모드는 unavailable."""
    fake = ModuleType("aml_ml")
    fake.MODEL_VERSION = "fake-model-1"  # type: ignore[attr-defined]
    fake.FEATURE_VERSION = "fake-feat-1"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aml_ml", fake)
    code, body = health(AI_SCORING_MOCK=False)
    assert code == 200
    assert body["scoring_mode"] == "unavailable"
    assert body["model_version"] == "fake-model-1"
    assert body["feature_version"] == "fake-feat-1"
    assert body["status"] == "ok"


def test_existing_keys_unchanged_and_no_auth(health) -> None:  # type: ignore[no-untyped-def]
    code, body = health()
    assert code == 200
    assert set(body) == EXISTING_KEYS | {"scoring_mode"}
    assert body["llm"] in {"ok", "missing_key"}
    assert body["db"] == "ok" or body["db"].startswith("down:")
