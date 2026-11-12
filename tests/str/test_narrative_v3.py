"""SCRUM-225 — narrative_v3 등록·few-shot (docs/str/05 narrative_v3).

v3 는 v2 와 같은 7섹션 스키마. 기본값은 v2 그대로. few-shot v3 예시는 규칙 12 필수 항목을 전부 씀.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import NarrativeOutV1, NarrativeOutV2, llm_output_model
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.infrastructure.fewshot_store import FEWSHOT_ROOT, FewshotStore
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from tests.str.rag_onoff_coverage import fact_coverage

V2_DIR = FEWSHOT_ROOT / "narrative_v2"
V3_DIR = FEWSHOT_ROOT / "narrative_v3"


def test_v3_prompt_loads_with_rule_12_and_narrowed_rule_8() -> None:
    system, user = load_prompt("narrative_v3")
    assert "12." in system
    assert "GROUNDS" in system.split("8.", 1)[1].split("9.", 1)[0]
    for var in (
        "{{facts_json}}",
        "{{fact_keys}}",
        "{{investigator_notes}}",
        "{{references}}",
        "{{few_shot}}",
    ):
        assert var in user


def test_v3_maps_to_v2_output_schema() -> None:
    assert llm_output_model("narrative_v3") is NarrativeOutV2
    assert llm_output_model("narrative_v3") is not NarrativeOutV1


def test_config_accepts_v3_but_default_stays_v2() -> None:
    assert Settings(_env_file=None, NARRATIVE_PROMPT="narrative_v3").narrative_prompt == "narrative_v3"
    assert Settings(_env_file=None).narrative_prompt == "narrative_v2"


def _files(d):  # type: ignore[no-untyped-def]
    return sorted(p.name for p in d.glob("*.json"))


def test_v3_fewshot_same_ids_and_facts_as_v2() -> None:
    assert _files(V3_DIR) == _files(V2_DIR)
    for name in _files(V2_DIR):
        v2 = json.loads((V2_DIR / name).read_text(encoding="utf-8"))
        v3 = json.loads((V3_DIR / name).read_text(encoding="utf-8"))
        assert v3["example_id"] == v2["example_id"]
        assert v3["facts"] == v2["facts"]


@pytest.mark.parametrize("name", _files(V3_DIR) or ["(missing)"])
def test_v3_fewshot_covers_rule_12_and_cites_in_scope(name: str) -> None:
    examples = {e.example_id: e for e in FewshotStore(prompt_name="narrative_v3").all()}
    raw = json.loads((V3_DIR / name).read_text(encoding="utf-8"))
    ex = examples[raw["example_id"]]
    keys = set(fact_keys(ex.facts))
    for s in ex.narrative:
        assert set(s.cites) <= keys, (name, s.section, set(s.cites) - keys)
    cov = fact_coverage(ex.narrative, ex.facts)
    assert cov["missing"] == [], (name, cov)
