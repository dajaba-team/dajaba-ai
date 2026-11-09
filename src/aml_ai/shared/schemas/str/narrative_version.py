"""LLM 호출의 프롬프트 이름 → 출력 스키마 모델 매핑 (SCRUM-47·91·129).

생성기 `_validate_result`·`shared/infrastructure/llm_client.complete_json`·`tools/record` 가
같은 함수를 쓴다 — tag 문자열 비교를 여러 자리에 흩지 않음. 초안(narrative)·평가자(judge)·
요약(summary) 셋 다 여기에 등록.
"""

from __future__ import annotations

from pydantic import BaseModel

from aml_ai.shared.schemas.str.narrative import NarrativeOutV1, NarrativeOutV2
from aml_ai.shared.schemas.str.summary import SummaryOut
from aml_ai.shared.schemas.str.verify import JudgeOut, JudgeOutV2

_LLM_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "narrative_v1": NarrativeOutV1,
    "narrative_v2": NarrativeOutV2,
    "judge_v1": JudgeOut,
    "judge_v2": JudgeOutV2,
    "judge_v3": JudgeOutV2,  # SCRUM-127 — 06 표 4칸 루브릭, 스키마는 v2 와 같음
    "summary_v1": SummaryOut,  # SCRUM-129 — HttpLlmClient 가 Structured Output 스키마로 씀
    "rewrite_v1": NarrativeOutV2,  # SCRUM-147 — 섹션 7개 재사용 (초안 안 고쳐 쓰기 전용)
}


def llm_output_model(prompt_name: str) -> type[BaseModel]:
    """LLM 호출의 프롬프트 이름 `prompt_name` 에 맞는 출력 스키마 모델. 알 수 없는 이름은 ValueError.

    LLM 호출 지점에서 프롬프트 이름에 맞는 출력 스키마를 선택한다.
    """
    try:
        return _LLM_OUTPUT_MODELS[prompt_name]
    except KeyError:
        raise ValueError(f"unknown prompt name: {prompt_name}") from None
