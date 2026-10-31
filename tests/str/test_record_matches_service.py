"""tools.record._build_prompt 가 draft_service._generate 와 **같은 user 프롬프트**를 만드는지.

SCRUM-15 adversarial H3 — 녹화 user 와 서비스 user 가 어긋나면 녹화 재생이 실패하고, 외부
공급자에게 서로 다른 데이터가 전달된다. 두 호출이 같은 recording_key 를 내야 한다.
SCRUM-47 — v1·v2 각 활성 버전에서도 녹화 도구와 서비스 조립이 일치해야 한다(파라미터).
v2 는 아직 녹화가 없으므로 조립 비교만.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.record import _build_prompt

from aml_ai.shared.infrastructure.llm_client import recording_key
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.narrative_generator import load_prompt, render_user

REPO_ROOT = Path(__file__).resolve().parents[2]


def _service_prompt(facts: Facts, prompt_name: str) -> tuple[str, str, list[str]]:
    """draft_service._generate 가 LLM 에 넘기는 (system, user) 를 그대로 재구성 — 활성 버전 폴더."""
    system, user_tpl = load_prompt(prompt_name)
    examples = FewshotStore(prompt_name=prompt_name).pick_examples(facts.typology)
    keys = list(fact_keys(facts).keys())
    user = render_user(
        user_tpl,
        facts_masked=masking.mask_for_llm(facts),
        fact_keys=keys,
        notes=None,
        references=[Reference.model_construct(**r) for r in []],
        examples=examples,
    )
    return system, user, keys


@pytest.mark.parametrize("prompt_name", ["narrative_v1", "narrative_v2"])
def test_record_and_service_produce_same_recording_key(prompt_name: str) -> None:
    """녹화 도구와 서비스 조립이 같은 프롬프트·키를 내야 — 활성 버전 폴더 분리 뒤에도 유지(SCRUM-47)."""
    facts = Facts.model_validate(
        json.loads((REPO_ROOT / "tests/str/fixtures/facts_fan_in.json").read_text(encoding="utf-8"))
    )
    r_system, r_user, r_keys = _build_prompt(facts, prompt_name)
    s_system, s_user, s_keys = _service_prompt(facts, prompt_name)
    assert r_system == s_system
    assert r_user == s_user
    assert r_keys == s_keys
    # 녹화 키도 같아야 — 재생이 record.py 의 녹화 파일을 찾을 수 있다는 확정 보장
    assert recording_key(r_system, r_user) == recording_key(s_system, s_user)


def test_record_masks_input_facts_transaction_ids() -> None:
    """지금 녹화하는 입력 facts 의 transaction_ids 는 masked dict 에서 사라져야 (예시 facts 는 범위 밖)."""
    facts = Facts.model_validate(
        json.loads((REPO_ROOT / "tests/str/fixtures/facts_fan_in.json").read_text(encoding="utf-8"))
    )
    masked = masking.mask_for_llm(facts)
    # 입력 facts.inbound.transaction_ids = [1, 2, 3] → masked.inbound 에는 없다
    assert "transaction_ids" not in masked["inbound"]
    assert "transaction_ids" not in masked["outbound"]
