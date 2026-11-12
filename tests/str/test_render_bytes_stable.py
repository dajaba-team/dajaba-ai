"""SCRUM-225 — v2·rewrite_v1 프롬프트 렌더링이 develop(8d13b89)과 바이트 단위로 같은지.

녹화 키 = sha256(system, user) 라서 1바이트라도 바뀌면 기존 녹화가 깨진다(recorded/README).
v3 REFERENCES 렌더링을 넣어도 v2·rewrite_v1 경로는 그대로여야 한다(docs/str/05 narrative_v3).
기대 해시는 develop 에서 같은 입력으로 계산한 값.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aml_ai.shared.schemas.str import Facts, NarrativeSection, Reference
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import fact_keys as fact_keys_domain
from aml_ai.str.domain import masking
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.narrative_generator import load_prompt, render_user
from aml_ai.str.infrastructure.narrative_rewriter import render_rewrite_prompts
from tests.str.test_rewrite_prompt import _one_three_judge

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "facts_fan_in.json"
LONG = "Funnel accounts receive deposits from many senders. " * 10

V2_USER_SHA = "dcfa1dbaa10359453cbe6b5fae3eb46053592e9b7169c28da20ab5f2c87bc0e4"
REWRITE_SHA = "8fae7f52b35d3e3521bf1761e52fb291b68273806b7dcc74e7dbfbf7ef6b8713"


def _inputs() -> dict:
    facts = Facts.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    refs = [
        Reference(chunk_id=f"c{i}", doc_id=f"d{i}", doc_title=f"Doc {i}", page=i, score=0.5, text=LONG[:600])
        for i in range(1, 4)
    ]
    return {
        "facts_masked": masking.mask_for_llm(facts),
        "fact_keys": list(fact_keys_domain.fact_keys(facts).keys()),
        "notes": "메모",
        "references": refs,
        "examples": FewshotStore(prompt_name="narrative_v2").pick_examples(facts.typology),
    }


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_v2_render_user_bytes_unchanged() -> None:
    _, tpl = load_prompt("narrative_v2")
    assert _sha(render_user(tpl, **_inputs())) == V2_USER_SHA


def test_rewrite_v1_render_bytes_unchanged() -> None:
    original = [
        NarrativeSection(section=s, text=f"t:{s.value}", cites=[], evidence_ids=[]) for s in SectionV2
    ]
    system, user = render_rewrite_prompts(
        **_inputs(), original_narrative=original, critique=_one_three_judge(), paths_notice=""
    )
    assert _sha(system + "\x00" + user) == REWRITE_SHA


def test_existing_v2_and_rewrite_recording_keys_still_match() -> None:
    """녹화 도구와 같은 조립으로 키를 다시 계산 — narrative_v2/a153c38a0cae1149 · rewrite_v1/40a5370c0c04218a."""
    from tools.record import _build_prompt, _load_narrative
    from tools.record_rewrite import RECORDED, _load_judge, build_rewrite_prompt, rule_id_from_facts

    from aml_ai.shared.infrastructure.llm_client import recording_key

    facts = Facts.model_validate(json.loads((FIXTURE.parent / "facts_cycle_nopaths.json").read_text()))
    system, user, _ = _build_prompt(facts, "narrative_v2")
    assert recording_key(system, user) == "a153c38a0cae1149"
    narrative = _load_narrative(RECORDED / "narrative_v2" / "a153c38a0cae1149.json", facts)
    judge = _load_judge(RECORDED / "judge_v3" / "109f737d79869e4e.json")
    assert narrative is not None and judge is not None
    s2, u2, _ = build_rewrite_prompt(facts, narrative, judge, rule_id_from_facts(facts))
    assert recording_key(s2, u2) == "40a5370c0c04218a"
    assert (RECORDED / "rewrite_v1" / "40a5370c0c04218a.json").exists()
