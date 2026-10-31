"""커밋된 v1 녹화를 서비스 경로 그대로 재생 — RecordedLlmClient 에서 LlmUnavailable 안 뜨는지.

Codex adversarial 지적(SCRUM-47) — facts 칸 추가로 v1 녹화 키가 바뀌었다. 재녹화한 파일이
`tools.record --case fan_in` 과 같은 조립 경로에서 매칭되는지 **파일 자체로** 확인하는 회귀 테스트.
test_record_matches_service 는 조립끼리 비교라 저장된 녹화와의 키 불일치는 놓친다.

v1 녹화는 PR 머지 전 커밋에 포함돼야 한다 — 녹화 파일이 없으면 테스트가 **fail**(skip 아님).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.record import _build_prompt

from aml_ai.shared.infrastructure.llm_client import RecordedLlmClient
from aml_ai.shared.schemas.str import Facts, llm_output_model

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FAN_IN = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_fan_in.json"


@pytest.mark.parametrize("prompt_name", ["narrative_v1", "narrative_v2"])
def test_recorded_fan_in_replays_in_service_path(prompt_name: str) -> None:
    """fan_in facts 로 조립한 user·system 이 커밋된 녹화 파일의 키와 매칭 → RecordedLlmClient 가 응답을 돌려줌.

    서비스 경로에서 쓰이는 `tools.record._build_prompt` 를 써서 "녹화 당시 조립 == 지금 조립" 을 보장.
    v1·v2 둘 다(SCRUM-20).
    """
    facts = Facts.model_validate(json.loads(FIXTURE_FAN_IN.read_text(encoding="utf-8")))
    system, user, _ = _build_prompt(facts, prompt_name)
    client = RecordedLlmClient(REPO_ROOT / "tests" / "str" / "recorded")
    res = client.complete_json(system=system, user=user, model="recorded", max_tokens=0, tag=prompt_name)
    # 응답 자체도 활성 버전 스키마로 통과해야 — 녹화가 섹션 집합 어긋나면 안 됨
    assert llm_output_model(prompt_name).model_validate_json(res.text)
