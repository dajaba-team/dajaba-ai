"""SCRUM-147 — rewrite_v1 프롬프트 조립 단위.

- {{paths_notice}} 조건부 3분기
- {{critique}} 평가자 순서 유지 + score < JUDGE_PASS_SCORE 항목만
- {{original_narrative}} 에 evidence_ids 키·거래 ID 숫자 없음
- rewrite_v1.md 파일 안에 FAN_IN·CYCLE 등 typology 이름 글자 그대로 없음
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.verify import LlmCheckName
from aml_ai.str.domain import fact_keys as fact_keys_domain
from aml_ai.str.domain.fact_keys import attach_evidence

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_FILE = REPO_ROOT / "src" / "aml_ai" / "str" / "prompts" / "rewrite_v1.md"
FIXTURE_CYCLE = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_cycle_nopaths.json"
FIXTURE_FAN_IN = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_fan_in.json"


def _facts(path: Path) -> Facts:
    return Facts.model_validate(json.loads(path.read_text()))


def test_rewrite_prompt_file_has_no_typology_name_hardcoded() -> None:
    """rewrite_v1.md 파일에 FAN_IN·FAN_OUT·CYCLE·STACK·PASS_THROUGH 등 enum 이름이 글자 그대로 없어야 한다.

    LLM 본문 출력에서 유형 이름 쓰는 것은 OK (narrative_v2·judge TYPOLOGY_CONSISTENT 전제).
    프롬프트 파일 안에 박으면 SCRUM-182 (R05_STACK → R05_SCATTER_GATHER) 에서 재동결 필요.
    """
    text = PROMPT_FILE.read_text()
    for name in ("FAN_IN", "FAN_OUT", "CYCLE", "STACK", "PASS_THROUGH"):
        assert name not in text, f"rewrite_v1.md 안에 typology 이름 '{name}' 박지 말 것"


def test_paths_notice_empty_for_non_path_rule() -> None:
    """경로형 룰 아님(fan_in) → paths_notice 빈 문자열."""
    from aml_ai.str.application.draft_rewrite import build_paths_notice

    facts = _facts(FIXTURE_FAN_IN)
    notice = build_paths_notice(alert_rule_id="R01_LARGE_CASH", facts=facts)
    assert notice == ""


def test_paths_notice_empty_for_verified_paths() -> None:
    """경로형 룰이어도 paths.status==VERIFIED 면 빈 문자열."""
    from aml_ai.shared.schemas.str.facts import PathFacts, PathKind
    from aml_ai.str.application.draft_rewrite import build_paths_notice

    facts = _facts(FIXTURE_CYCLE)
    verified = PathFacts(
        kind=PathKind.CYCLE, status="VERIFIED", count=2, max_hops=3, max_accounts=3, transaction_ids=[1, 2, 3]
    )
    facts = facts.model_copy(update={"paths": verified})
    notice = build_paths_notice(alert_rule_id="R04_CYCLE", facts=facts)
    assert notice == ""


def test_paths_notice_filled_for_path_rule_without_verified() -> None:
    """경로형 룰 + paths None → 안내 블록 치환."""
    from aml_ai.str.application.draft_rewrite import build_paths_notice

    facts = _facts(FIXTURE_CYCLE)
    assert facts.paths is None
    notice = build_paths_notice(alert_rule_id="R04_CYCLE", facts=facts)
    assert "10a" in notice
    assert "경로는 확인 필요" in notice
    # 유형 이름 자체는 LLM 본문에서 쓰므로 안내 블록에도 "facts.typology 값" 이라고만
    assert "facts.typology" in notice


def test_critique_only_below_pass_score_in_judge_order() -> None:
    """평가자 순서 그대로, score < JUDGE_PASS_SCORE 항목만."""
    from aml_ai.shared.schemas.str import JudgeOutV2, LlmCheck
    from aml_ai.str.application.draft_rewrite import assemble_critique
    from aml_ai.str.domain.constants import JUDGE_PASS_SCORE

    # 평가자가 낸 순서: FIVE_W → TYPOLOGY → NO_UNSUPPORTED → NO_SPECULATION → NO_INSTRUCTION
    checks = [
        LlmCheck(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE, comment="OPINION 이 METHOD 반복", score=3),
        LlmCheck(check=LlmCheckName.TYPOLOGY_CONSISTENT, comment="FAN_IN 일반론", score=3),
        LlmCheck(check=LlmCheckName.NO_UNSUPPORTED_CLAIM, comment="", score=5),
        LlmCheck(check=LlmCheckName.NO_SPECULATION, comment="", score=5),
        LlmCheck(check=LlmCheckName.NO_INSTRUCTION_TEXT, comment="", score=5),
    ]
    judge = JudgeOutV2(checks=checks, sections=[])
    critique = assemble_critique(judge, pass_score=JUDGE_PASS_SCORE)
    # 통과 항목은 빠짐
    assert "NO_UNSUPPORTED_CLAIM" not in critique
    assert "NO_SPECULATION" not in critique
    # 지적 항목만 (평가자 순서)
    assert critique.index("FIVE_W_ONE_H_COMPLETE") < critique.index("TYPOLOGY_CONSISTENT")
    assert "score 3" in critique


def test_critique_empty_when_all_pass() -> None:
    """전부 통과 — critique 는 빈 문자열(그러나 try_rewrite 는 이 분기에 들지 않음, not_triggered)."""
    from aml_ai.shared.schemas.str import JudgeOutV2, LlmCheck
    from aml_ai.str.application.draft_rewrite import assemble_critique
    from aml_ai.str.domain.constants import JUDGE_PASS_SCORE

    checks = [LlmCheck(check=name, comment="", score=5) for name in LlmCheckName]
    judge = JudgeOutV2(checks=checks, sections=[])
    critique = assemble_critique(judge, pass_score=JUDGE_PASS_SCORE)
    assert critique.strip() == ""


def test_original_narrative_serialization_omits_evidence_ids() -> None:
    """original_narrative 에 evidence_ids 키·거래 ID 숫자 모두 없음 (05 '거래 ID LLM에 안 줌' 유지)."""
    from aml_ai.str.application.draft_rewrite import serialize_original_narrative

    facts = _facts(FIXTURE_FAN_IN)
    # 섹션 하나만 만들어 attach_evidence 로 evidence_ids 가 붙은 상태를 재현
    from aml_ai.shared.schemas.str import NarrativeSection
    from aml_ai.shared.schemas.str.narrative import SectionV2

    sec = NarrativeSection(
        section=SectionV2.SUBJECT,
        text="보고 대상자 ...",
        cites=["subject.entity_type", "customer.industry"],
    )
    attached = attach_evidence([sec], facts)
    # 전제: attach_evidence 뒤 섹션에 evidence_ids 가 비어 있지 않을 수도 있음(cites 로부터 계산)
    serialized = serialize_original_narrative(attached)
    assert "evidence_ids" not in serialized
    # 거래 ID 숫자 1·2·3 이 직렬화에 숫자로도 들어가지 않아야 함
    # (cites 에 "inbound.by_currency.USD" 같은 fact 키는 등장 가능 — 숫자는 안 됨)
    assert not re.search(r"\b1\b|\b2\b|\b3\b", serialized)


def test_rewriter_assembles_user_with_all_blocks() -> None:
    """NarrativeRewriter.render_user 가 facts·fact_keys·notes·references·original_narrative·critique·paths_notice 전부 넣는다."""
    from aml_ai.shared.schemas.str import JudgeOutV2, LlmCheck, NarrativeSection
    from aml_ai.shared.schemas.str.narrative import SectionV2
    from aml_ai.str.application.draft_rewrite import render_rewrite_user

    facts = _facts(FIXTURE_CYCLE)
    masked = facts  # 테스트 단위라 masking 대신 facts 원본
    keys = list(fact_keys_domain.fact_keys(facts).keys())
    original = [
        NarrativeSection(
            section=s, text=f"t:{s.value}", cites=["subject.entity_type"], evidence_ids=[]
        )
        for s in SectionV2
    ]
    checks = [
        LlmCheck(check=LlmCheckName.TYPOLOGY_CONSISTENT, comment="경로 일반론", score=3),
        LlmCheck(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE, comment="", score=5),
        LlmCheck(check=LlmCheckName.NO_UNSUPPORTED_CLAIM, comment="", score=5),
        LlmCheck(check=LlmCheckName.NO_SPECULATION, comment="", score=5),
        LlmCheck(check=LlmCheckName.NO_INSTRUCTION_TEXT, comment="", score=5),
    ]
    user = render_rewrite_user(
        facts_masked=masked,
        fact_keys=keys,
        examples=[],
        references=[],
        notes=None,
        original_narrative=original,
        critique=JudgeOutV2(checks=checks, sections=[]),
        paths_notice="10a. ... 경로는 확인 필요",
    )
    assert "FACTS:" in user
    assert "FACT_KEYS" in user
    assert "<investigator_notes>" in user
    assert "REFERENCES" in user
    assert "<original_narrative>" in user
    assert "<critique>" in user
    assert "TYPOLOGY_CONSISTENT" in user
    assert "경로는 확인 필요" in user
    assert "evidence_ids" not in user
