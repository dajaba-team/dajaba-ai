"""LLM 호출의 프롬프트 이름 → 출력 스키마 모델 매핑 (SCRUM-47·91·129).

생성기 `_validate_result`·`shared/infrastructure/llm_client.complete_json`·`tools/record` 가
같은 함수를 쓴다 — tag 문자열 비교를 여러 자리에 흩지 않음. 초안(narrative)·평가자(judge)·
요약(summary)·질문 답변(ask) 모두 여기에 등록.
"""

from __future__ import annotations

from pydantic import BaseModel

from aml_ai.shared.schemas.str.ask_llm import AskAnswerOut, AskAnswerOutV3, AskPlanOut
from aml_ai.shared.schemas.str.narrative import NarrativeOutV1, NarrativeOutV2
from aml_ai.shared.schemas.str.rerank_llm import RerankOut
from aml_ai.shared.schemas.str.summary import SummaryOut
from aml_ai.shared.schemas.str.verify import JudgeOut, JudgeOutV2

_LLM_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "narrative_v1": NarrativeOutV1,
    "narrative_v2": NarrativeOutV2,
    "narrative_v3": NarrativeOutV2,  # SCRUM-225 — 7섹션 그대로, 규칙 8·12 만 다름
    "judge_v1": JudgeOut,
    "judge_v2": JudgeOutV2,
    "judge_v3": JudgeOutV2,  # SCRUM-127 — 06 표 4칸 루브릭, 스키마는 v2 와 같음
    "judge_v4": JudgeOutV2,  # SCRUM-268 — 판정 근거 블록, 스키마는 v3 와 같음
    "summary_v1": SummaryOut,  # SCRUM-129 — HttpLlmClient 가 Structured Output 스키마로 씀
    "summary_v2": SummaryOut,  # SCRUM-340 — 금액 표기만 다름, 스키마 같음
    "rewrite_v1": NarrativeOutV2,  # SCRUM-147 — 섹션 7개 재사용 (초안 안 고쳐 쓰기 전용)
    "ask_plan_v1": AskPlanOut,  # SCRUM-290 — 질문 답변 계획
    "ask_plan_v2": AskPlanOut,  # SCRUM-362 — WHY 경계 두 줄만 다름, 스키마 같음
    "ask_plan_v3": AskPlanOut,  # SCRUM-362 추가 검토 1 — WHY 기본값 좁힘·복합 허용, 스키마 같음
    "ask_answer_v1": AskAnswerOut,  # SCRUM-290 — 질문 답변 답
    "ask_answer_v2": AskAnswerOut,  # SCRUM-358·359 — 답 규칙 9·10 만 다름, 스키마 같음
    "ask_answer_v3": AskAnswerOutV3,  # SCRUM-362 — 자리표, cites 없음
    "ask_answer_v4": AskAnswerOutV3,  # SCRUM-362 — v3 규칙 5·9 만 다름, 스키마 같음
    "ask_answer_v5": AskAnswerOutV3,  # SCRUM-362 (B1) — 비교 자리표 규칙만 다름, 스키마 같음
    "ask_answer_v6": AskAnswerOutV3,  # SCRUM-362 추가 검토 3 — 끝맺음 허용 목록 규칙만 다름, 스키마 같음
    "rerank_v1": RerankOut,  # SCRUM-308-2 — 참고 사례 후보 재정렬(표지 순서만)
}


def llm_output_model(prompt_name: str) -> type[BaseModel]:
    """LLM 호출의 프롬프트 이름 `prompt_name` 에 맞는 출력 스키마 모델. 알 수 없는 이름은 ValueError.

    LLM 호출 지점에서 프롬프트 이름에 맞는 출력 스키마를 선택한다.
    """
    try:
        return _LLM_OUTPUT_MODELS[prompt_name]
    except KeyError:
        raise ValueError(f"unknown prompt name: {prompt_name}") from None
