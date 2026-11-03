"""LLM 호출의 프롬프트 이름 → 출력 스키마 모델 매핑 (SCRUM-47·91).

생성기 `_validate_result`·`shared/infrastructure/llm_client.complete_json`·`tools/record` 가
같은 함수를 쓴다 — tag 문자열 비교를 세 자리에 흩지 않음.
"""

from __future__ import annotations

from pydantic import BaseModel

from aml_ai.shared.schemas.str.narrative import NarrativeOutV1, NarrativeOutV2
from aml_ai.shared.schemas.str.verify import JudgeOut

_LLM_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "narrative_v1": NarrativeOutV1,
    "narrative_v2": NarrativeOutV2,
    "judge_v1": JudgeOut,
}


def llm_output_model(prompt_name: str) -> type[BaseModel]:
    """LLM 호출의 프롬프트 이름 `prompt_name` 에 맞는 출력 스키마 모델. 알 수 없는 이름은 ValueError.

    LLM 호출 지점에서 프롬프트 이름에 맞는 출력 스키마를 선택한다.
    """
    try:
        return _LLM_OUTPUT_MODELS[prompt_name]
    except KeyError:
        raise ValueError(f"unknown narrative prompt: {prompt_name}") from None
