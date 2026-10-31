"""FROZEN_PROMPTS 동결 강제 — 파일 해시가 다르면 기동 실패."""

from __future__ import annotations

import pytest

from aml_ai.shared.versioning import file_sha256
from aml_ai.str.domain import constants as const
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR
from aml_ai.str.infrastructure.prompt_index import FrozenPromptMismatch, check_frozen_prompts


@pytest.mark.parametrize("name", ["narrative_v1", "narrative_v2"])
def test_narrative_prompt_is_registered_in_frozen_prompts(name: str) -> None:
    """녹화 커밋 뒤 상태 — FROZEN_PROMPTS 에 활성 프롬프트 반드시 등록 (SCRUM-15 M4, SCRUM-20 v2 동결)."""
    from aml_ai.str.domain.constants import FROZEN_PROMPTS

    assert name in FROZEN_PROMPTS, f"녹화를 커밋했으면 FROZEN_PROMPTS 에 {name} sha256 을 박아야 한다"
    assert len(FROZEN_PROMPTS[name]) == 64, "sha256 hex 는 64자"


def test_empty_dict_passes_but_narrative_v1_required_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    """FROZEN_PROMPTS 가 통째로 비면 check_frozen_prompts 는 조용히 통과 — 그래서 위 테스트가 등록을 강제."""
    monkeypatch.setattr(const, "FROZEN_PROMPTS", {})
    check_frozen_prompts()  # 비어 있으면 돌 게 없어서 통과


def test_check_fails_when_hash_mismatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """파일 해시가 FROZEN_PROMPTS 값과 다르면 FrozenPromptMismatch."""
    monkeypatch.setattr(const, "FROZEN_PROMPTS", {"narrative_v1": "deadbeef" * 8})
    with pytest.raises(FrozenPromptMismatch):
        check_frozen_prompts()


def test_check_passes_when_hash_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """지금 파일 해시로 FROZEN_PROMPTS 를 세팅하면 통과(녹화 커밋 뒤 상태)."""
    actual = file_sha256(PROMPTS_DIR / "narrative_v1.md")
    monkeypatch.setattr(const, "FROZEN_PROMPTS", {"narrative_v1": actual})
    check_frozen_prompts()


def test_check_fails_when_file_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(const, "FROZEN_PROMPTS", {"nonexistent_v9": "x" * 64})
    with pytest.raises(FrozenPromptMismatch, match="missing"):
        check_frozen_prompts()
