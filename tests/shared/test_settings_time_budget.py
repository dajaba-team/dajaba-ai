"""Settings 시간 예산 불변식 (SCRUM-45).

규칙: `draft_budget_s >= llm_timeout_s`, `regen_min_remaining_s >= llm_timeout_s`.
어긋나면 기동 때 ValidationError — `.env` 를 잘못 적어도 서버가 LLM 1회조차 못 부르는 상태로
살아 있지 않게 한다 (docs/str/03 "시간 예산", 09 2026-10-31 (SCRUM-45)).

이 파일만 `Settings(...)` 에 값을 직접 넣는다 — 다른 테스트는 설정 숫자를 안 쓴다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.config import Settings


def test_time_budget_defaults_pass() -> None:
    """기본값(`.env` 미지정) 은 `llm_timeout_s <= regen_min_remaining_s <= draft_budget_s`."""
    s = Settings(_env_file=None)
    assert s.llm_timeout_s <= s.regen_min_remaining_s
    assert s.llm_timeout_s <= s.draft_budget_s


def test_time_budget_invalid_combination_raises() -> None:
    """재생성 임계값·전체 예산 중 하나라도 `llm_timeout_s` 미만이면 ValidationError."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, LLM_TIMEOUT_S=35, REGEN_MIN_REMAINING_S=10, DRAFT_BUDGET_S=80)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, LLM_TIMEOUT_S=35, REGEN_MIN_REMAINING_S=40, DRAFT_BUDGET_S=20)
