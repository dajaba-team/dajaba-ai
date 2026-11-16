"""SCRUM-60 — 녹화 두 개·draft_response·narrative_ok 전부 `run_code_checks` 통과.

61 verify 녹화 통합 테스트 PASSED 의 전제. docs/str/08 "오탐 테스트(정상 본문 통과)".
녹화 두 개 본문에 있는 모든 숫자가 COUNT_MATCH·DATE_MATCH·AMOUNT_MATCH·ACCOUNT_ID_MATCH·
EVIDENCE_IN_SCOPE 를 전부 통과해야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import (
    Facts,
    LlmNarrativeSection,
    NarrativeOutV1,
    NarrativeOutV2,
    RevisedNarrativeSection,
)
from aml_ai.str.domain import verification
from aml_ai.str.domain.fact_keys import attach_evidence
from tests.conftest import EXAMPLES, FIXTURES, load_json

_REPO = Path(__file__).resolve().parents[2]
_RECORDED_V1 = _REPO / "tests/str/recorded/narrative_v1/6e76c5d81cb3b522.json"
_RECORDED_V2 = _REPO / "tests/str/recorded/narrative_v2/a976ae216c7fb1bb.json"


def _recorded_narrative(path: Path, is_v2: bool) -> tuple[list[RevisedNarrativeSection], list[int]]:
    """녹화 LLM 출력을 꺼내 수정본 섹션으로. evidence_ids 는 attach_evidence 로 채운다."""
    recorded = json.loads(path.read_text(encoding="utf-8"))
    out_payload = json.loads(recorded["text"])
    sections = [LlmNarrativeSection.model_validate(s) for s in out_payload["narrative"]]
    model = NarrativeOutV2 if is_v2 else NarrativeOutV1
    model.model_validate({"narrative": [s.model_dump() for s in sections]})  # 스키마 통과 확인
    facts = _facts_from_fixture()
    attached = attach_evidence(sections, facts)
    revised = [RevisedNarrativeSection.model_validate(s.model_dump()) for s in attached]
    scope = sorted({tid for s in revised for tid in s.evidence_ids})
    return revised, scope


def _facts_from_fixture() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def _draft_response_narrative() -> tuple[list[RevisedNarrativeSection], list[int]]:
    data = json.loads((EXAMPLES / "draft_response.json").read_text(encoding="utf-8"))
    sections = [RevisedNarrativeSection.model_validate(s) for s in data["narrative"]]
    scope = sorted({tid for s in sections for tid in s.evidence_ids})
    return sections, scope


def _narrative_ok() -> tuple[list[RevisedNarrativeSection], list[int]]:
    data = load_json(FIXTURES / "narrative_ok.json")
    sections = [RevisedNarrativeSection.model_validate(s) for s in data["narrative"]]
    scope = sorted({tid for s in sections for tid in s.evidence_ids})
    return sections, scope


@pytest.mark.parametrize(
    ("name", "loader"),
    [
        ("narrative_v2_recorded", lambda: _recorded_narrative(_RECORDED_V2, is_v2=True)),
        ("draft_response_example", _draft_response_narrative),
        ("narrative_ok_fixture", _narrative_ok),
    ],
)
def test_run_code_checks_passes_recorded_narratives(
    name: str,
    loader,
) -> None:
    """녹화 두 개·규약 예시·fixture — 전부 `run_code_checks` 를 통과(평가자까지 가야 함)."""
    narrative, scope = loader()
    facts = _facts_from_fixture()
    checks = verification.run_code_checks(facts, narrative, scope)
    bad = [c for c in checks if not c.match]
    assert not bad, f"{name} 에서 {len(bad)} 개 실패: " + str(
        [(c.check, c.section, c.draft_value, c.source_value, c.reason) for c in bad[:10]]
    )


def test_v1_recorded_only_unbracketed_observation_dates_fail() -> None:
    """v1 녹화 — SCRUM-140 의 DATE 3건 중 WHO `등록일` 은 SCRUM-131 2/n 에서 개설일 match.

    WHY_SUSPICIOUS 괄호 없는 관측 기간 2건은 거래 날짜 → 기간 밖 MISMATCH 로 **고정**(06 — 괄호 없는 관측 범위는
    인정 안 함, 추가 검토 2차. 프롬프트 v4 SCRUM-228 에서 괄호 표기로). 그 밖은 전부 통과.
    """
    narrative, scope = _recorded_narrative(_RECORDED_V1, is_v2=False)
    checks = verification.run_code_checks(_facts_from_fixture(), narrative, scope)
    bad = [
        (c.check.value, c.section.value if c.section else None, c.draft_value, c.match)
        for c in checks
        if not c.match
    ]
    assert bad == [
        ("DATE_MATCH", "WHY_SUSPICIOUS", "2022-09-02T00:00:00", False),
        ("DATE_MATCH", "WHY_SUSPICIOUS", "2022-09-03T00:00:00", False),
    ]
