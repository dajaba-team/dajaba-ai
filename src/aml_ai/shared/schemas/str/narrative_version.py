"""활성 서술 버전(`narrative_v1`|`narrative_v2`) → LLM 출력 스키마 모델 매핑 (SCRUM-47).

생성기 `_validate_result`·`shared/infrastructure/llm_client.complete_json`·`tools/record` 가
같은 함수를 쓴다 — tag 문자열 비교를 세 자리에 흩지 않음.
"""

from __future__ import annotations

from pydantic import BaseModel

from aml_ai.shared.schemas.str.narrative import NarrativeOutV1, NarrativeOutV2

_LLM_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "narrative_v1": NarrativeOutV1,
    "narrative_v2": NarrativeOutV2,
}


def llm_output_model(prompt_name: str) -> type[BaseModel]:
    """`prompt_name` 에 맞는 LLM 출력 스키마 모델. 알 수 없는 이름은 ValueError.

    생성기는 활성 버전과 다른 집합의 응답을 재생성 유도 후 거부(SCRUM-47).
    """
    try:
        return _LLM_OUTPUT_MODELS[prompt_name]
    except KeyError:
        raise ValueError(f"unknown narrative prompt: {prompt_name}") from None
