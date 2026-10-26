"""공통 픽스처. LLM 은 녹화 모드, DB 는 -m db 에서만."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "contracts" / "examples"
FIXTURES = ROOT / "tests" / "str" / "fixtures"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_INTERNAL_KEY", "test-key")
    monkeypatch.setenv("AI_LLM_MOCK", "true")
    monkeypatch.setenv("AI_SCORING_MOCK", "true")
    monkeypatch.setenv("INDEX_PROMPTS_ON_STARTUP", "false")
    from aml_ai.shared.config import get_settings

    get_settings.cache_clear()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
