"""`NARRATIVE_PROMPT` 기본값 전환 (SCRUM-62, 2026-11-06).

env 미지정이면 `Settings(_env_file=None).narrative_prompt == "narrative_v2"`.
한 값 하나로 프롬프트 파일·LLM 출력 스키마·few-shot 폴더가 같이 v2 를 가리킴(SCRUM-47 공존 규칙).
되돌릴 땐 `NARRATIVE_PROMPT=narrative_v1` 명시 — 승인본·해시 호환 경로는 그대로 열려 있음.

`_env_file=None` 은 `.env` 파일만 막음 — OS 환경변수는 그대로 읽히므로 각 테스트 앞에
`monkeypatch.delenv("NARRATIVE_PROMPT", raising=False)` 를 autouse 로 걸어 외부 env 를 차단.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import NarrativeOutV1, NarrativeOutV2, llm_output_model
from aml_ai.str.infrastructure.fewshot_store import FEWSHOT_ROOT, FewshotStore
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from tests.str.judge_support import StubLlm


@pytest.fixture(autouse=True)
def _no_narrative_prompt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """외부 환경(로컬 `.env`·CI secrets·셸 export) 영향을 차단 — 테스트는 기본값 자체를 본다."""
    monkeypatch.delenv("NARRATIVE_PROMPT", raising=False)


def test_narrative_prompt_default_is_v2() -> None:
    """env 없이 Settings → narrative_prompt == "narrative_v2"."""
    assert Settings(_env_file=None).narrative_prompt == "narrative_v2"


def test_narrative_prompt_default_maps_to_v2_output_schema() -> None:
    """기본값으로 조립되는 LLM 출력 스키마가 v2 집합(NarrativeOutV2)."""
    s = Settings(_env_file=None)
    assert llm_output_model(s.narrative_prompt) is NarrativeOutV2


def test_fewshot_store_default_directory_is_v2() -> None:
    """`FewshotStore()` 기본 디렉토리가 `fewshot/narrative_v2`."""
    assert FewshotStore()._dir == FEWSHOT_ROOT / "narrative_v2"  # noqa: SLF001


def test_narrative_generator_default_prompt_version_is_v2() -> None:
    """`NarrativeGenerator(stub, settings)` 의 `prompt_version == "narrative_v2"`."""
    gen = NarrativeGenerator(StubLlm(responses=[]), Settings(_env_file=None))
    assert gen.prompt_version == "narrative_v2"


def test_narrative_prompt_rollback_to_v1_still_works() -> None:
    """되돌림 경로 — `NARRATIVE_PROMPT=narrative_v1` 명시하면 v1 쪽을 가리킴(승인본·해시 호환)."""
    s = Settings(_env_file=None, NARRATIVE_PROMPT="narrative_v1")
    assert s.narrative_prompt == "narrative_v1"
    assert llm_output_model("narrative_v1") is NarrativeOutV1
    assert FewshotStore(prompt_name="narrative_v1")._dir == FEWSHOT_ROOT / "narrative_v1"  # noqa: SLF001


def test_fewshot_root_exists_for_both_versions() -> None:
    """버전 폴더가 리포에 있어야 설정 전환이 안전(없으면 기동 때 깨짐). v3 — SCRUM-225."""
    for v in ("narrative_v1", "narrative_v2", "narrative_v3"):
        assert (FEWSHOT_ROOT / v).is_dir(), f"{v} few-shot 폴더 없음"


def test_fewshot_root_is_under_repo() -> None:
    """FEWSHOT_ROOT 가 리포 안 경로인지 — 다른 디렉토리로 샜는지 확인."""
    assert Path("src/aml_ai").resolve() in FEWSHOT_ROOT.resolve().parents
