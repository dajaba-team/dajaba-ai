"""SCRUM-147 — GenerationMeta.rewrite 스키마·하위 호환·Literal 값·critique_scores 키 제한.

draft_rewrite 가 생기기 전에는 전부 ImportError 로 빨간 줄(의도).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str.draft import GenerationMeta  # noqa: F401 — 기존
from aml_ai.shared.schemas.str.verify import LlmCheckName


def test_rewrite_meta_literal_has_seven_values() -> None:
    """skipped_reason Literal 에 7값 모두 있어야 한다 (★B 답 반영: rewrite_error 추가)."""
    from aml_ai.shared.schemas.str.draft import RewriteMeta

    allowed = {
        "not_triggered",
        "code_failed",
        "critique_error",
        "budget",
        "schema",
        "rewrite_error",
        "rewrite_code_failed",
    }
    for value in allowed:
        m = RewriteMeta(attempted=False, applied=False, skipped_reason=value)
        assert m.skipped_reason == value
    with pytest.raises(ValidationError):
        RewriteMeta(attempted=False, applied=False, skipped_reason="unknown")


def test_rewrite_meta_defaults_all_none_applied_false() -> None:
    """기본값 — attempted=false·applied=false·skipped_reason=None·critique_* None."""
    from aml_ai.shared.schemas.str.draft import RewriteMeta

    m = RewriteMeta()
    assert m.attempted is False
    assert m.applied is False
    assert m.skipped_reason is None
    assert m.critique_llm_model is None
    assert m.critique_scores is None
    assert m.critique_tokens_in is None
    assert m.critique_tokens_out is None
    assert m.critique_latency_ms is None


def test_critique_scores_keys_restricted_to_judge_five() -> None:
    """critique_scores 의 키는 LlmCheckName enum 5개만 허용."""
    from aml_ai.shared.schemas.str.draft import RewriteMeta

    valid = {name.value: 5 for name in LlmCheckName}
    m = RewriteMeta(
        attempted=False,
        applied=False,
        skipped_reason="not_triggered",
        critique_llm_model="gpt-test",
        critique_scores=valid,
    )
    assert set(m.critique_scores or {}) == {name.value for name in LlmCheckName}
    with pytest.raises(ValidationError):
        RewriteMeta(
            attempted=False,
            applied=False,
            skipped_reason="not_triggered",
            critique_scores={"UNKNOWN_CHECK": 3},
        )


def test_generation_meta_rewrite_default_none_for_backward_compat() -> None:
    """옛 저장 응답(rewrite 칸 없음) 이 model_validate 통과해야 한다 (ClaimReuse 재사용)."""
    old_payload = {
        "llm_model": "gpt-generate",
        "prompt_version": "narrative_v2",
        "few_shot_ids": [1, 2, 3],
        "references": [],
        "retrieval_version": None,
        "server_version": "ai-2026.11.1",
        "tokens_in": 1200,
        "tokens_out": 400,
        "latency_ms": 5000,
    }
    meta = GenerationMeta.model_validate(old_payload)
    assert meta.rewrite is None


def test_generation_meta_roundtrip_applied_true() -> None:
    from aml_ai.shared.schemas.str.draft import RewriteMeta

    scores = {name.value: 4 for name in LlmCheckName}
    scores[LlmCheckName.TYPOLOGY_CONSISTENT.value] = 3
    meta = GenerationMeta(
        llm_model="gpt-generate",
        prompt_version="narrative_v2",
        few_shot_ids=[1],
        server_version="ai-2026.11.1",
        tokens_in=2400,
        tokens_out=800,
        latency_ms=10000,
        rewrite=RewriteMeta(
            attempted=True,
            applied=True,
            skipped_reason=None,
            critique_llm_model="gpt-judge",
            critique_scores=scores,
            critique_tokens_in=800,
            critique_tokens_out=200,
            critique_latency_ms=4000,
        ),
    )
    roundtrip = GenerationMeta.model_validate(meta.model_dump(mode="json"))
    assert roundtrip.rewrite is not None
    assert roundtrip.rewrite.applied is True
    assert roundtrip.rewrite.skipped_reason is None
    assert roundtrip.rewrite.critique_scores == scores


def test_generation_meta_roundtrip_attempted_false_not_triggered() -> None:
    from aml_ai.shared.schemas.str.draft import RewriteMeta

    scores = {name.value: 5 for name in LlmCheckName}
    meta = GenerationMeta(
        llm_model="gpt-generate",
        prompt_version="narrative_v2",
        few_shot_ids=[1],
        server_version="ai-2026.11.1",
        tokens_in=1200,
        tokens_out=400,
        latency_ms=5000,
        rewrite=RewriteMeta(
            attempted=False,
            applied=False,
            skipped_reason="not_triggered",
            critique_llm_model="gpt-judge",
            critique_scores=scores,
            critique_tokens_in=400,
            critique_tokens_out=100,
            critique_latency_ms=2000,
        ),
    )
    roundtrip = GenerationMeta.model_validate(meta.model_dump(mode="json"))
    assert roundtrip.rewrite is not None
    assert roundtrip.rewrite.attempted is False
    assert roundtrip.rewrite.skipped_reason == "not_triggered"


def test_generation_meta_rewrite_applied_true_forbids_skipped_reason() -> None:
    """applied=true 면 skipped_reason 은 None 이어야 한다."""
    from aml_ai.shared.schemas.str.draft import RewriteMeta

    with pytest.raises(ValidationError):
        RewriteMeta(
            attempted=True,
            applied=True,
            skipped_reason="not_triggered",
        )
