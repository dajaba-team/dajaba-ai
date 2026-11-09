"""judge_v3 (SCRUM-127) — 루브릭 5·4·3·1 4칸 · 자료 없음 예외 · VERIFIER_VERSION+judge_v3 길이.

develop 상태(judge_v2 활성)에서는 전부 실패하고, judge_v3 구현 뒤 녹색.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from aml_ai.shared.schemas.str.narrative_version import llm_output_model
from aml_ai.shared.schemas.str.verify import JudgeOutV2
from aml_ai.str.domain.constants import JUDGE_PROMPT, VERIFIER_VERSION

_PROMPT_PATH = Path(__file__).resolve().parents[1].parent / "src/aml_ai/str/prompts/judge_v3.md"


def test_judge_v3_mapped_to_judge_out_v2() -> None:
    """judge_v3 출력 스키마는 JudgeOutV2 (v2 와 같은 섹션 7개 + checks 5)."""
    assert llm_output_model("judge_v3") is JudgeOutV2
    assert issubclass(JudgeOutV2, BaseModel)


def test_judge_v3_prompt_has_four_score_column() -> None:
    """judge_v3.md 의 '항목과 기준' 5줄 전부에 `4:` 칸이 있어야 함 — 06 표와 같은 5·4·3·1."""
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    checks = (
        "FIVE_W_ONE_H_COMPLETE",
        "TYPOLOGY_CONSISTENT",
        "NO_UNSUPPORTED_CLAIM",
        "NO_SPECULATION",
        "NO_INSTRUCTION_TEXT",
    )
    for name in checks:
        # 각 체크 줄에서 "4:" 칸(= 4점 설명)이 포함돼야 함
        lines = [ln for ln in text.splitlines() if ln.startswith(name)]
        assert lines, f"{name} 줄이 없음"
        assert any("4:" in ln for ln in lines), f"{name} 줄에 '4:' 4점 칸 없음 — judge_v2 와 같음"


@pytest.mark.parametrize(
    "phrase",
    [
        "한 문장 반복",  # FIVE_W 4점 (06)
        "짧은 시간에 집중",  # NO_UNSUPPORTED_CLAIM 4점 예시 (06)
        "구조화 거래로 보임",  # NO_SPECULATION 4점 예시 (06)
        "본 보고서는",  # NO_INSTRUCTION_TEXT 4점 예시 (06)
        "facts 숫자를 안 쓰고 일반적",  # TYPOLOGY_CONSISTENT 4점 설명 (06)
    ],
)
def test_judge_v3_prompt_has_06_four_point_phrases(phrase: str) -> None:
    """06 표의 4점 칸 핵심 문장 5개가 judge_v3 프롬프트에 들어 있어야 함."""
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    assert phrase in text, f"judge_v3.md 에 06 4점 문구 '{phrase}' 없음"


def test_judge_v3_prompt_has_no_claim_absence_exception() -> None:
    """`자료 없음`·`확인되지 않음` 부재 표기 예외 한 줄이 프롬프트에 있어야 함 (SCRUM-127)."""
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    assert "자료 없음" in text
    assert "확인되지 않음" in text
    # 사실 주장 아님 / 감점하지 않 — 둘 중 하나는 반드시
    assert ("사실 주장" in text) or ("감점하지 않" in text)


def test_judge_prompt_constant_is_v3() -> None:
    assert JUDGE_PROMPT == "judge_v3"


def test_verifier_version_with_judge_suffix_fits_backend_varchar_64() -> None:
    """백엔드 V008 `verifier_version varchar(64)` — `VERIFIER_VERSION + "+judge_v3"` 가 64자 이내."""
    combined = f"{VERIFIER_VERSION}+judge_v3"
    assert len(combined) <= 64, f"{combined!r} ({len(combined)}자) 가 varchar(64) 넘음"
