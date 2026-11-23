"""질문 답변 계획 같음 정의 — 녹화 도구·재기 도구 공용 (SCRUM-362 ★B4-2, docs/str/08 "계획 흔들림 재기")."""

from __future__ import annotations

from aml_ai.shared.schemas.str.ask_llm import AskPlanKind
from aml_ai.str.domain.ask_bundles import with_flows


def _plan_sig(out, question: str) -> tuple:  # noqa: ANN001
    """계획 같음 = kind + 사유 + 코드가 **실제로 꺼낸 묶음**(`plan_bundles`) 집합이 같음(SCRUM-362 ★B4-2).

    답 LLM 입력이 같으면 같은 계획 — 계획 LLM 이 스스로 `flows` 를 붙여도 질문에 방향 낱말이 있으면 코드가 어차피
    붙이므로 같음. 묶음 순서는 조각·키 순서와 무관 — 집합으로 비교.
    """
    return out.kind, out.out_of_scope_reason, frozenset(plan_bundles(out, question))


def plan_bundles(out, question: str) -> list[str]:  # noqa: ANN001
    """서비스와 같음 — 범위 밖은 묶음을 꺼내지 않음(빈 목록), 범위 안은 계획 보강 `with_flows` 뒤(03 7·8단계)."""
    if out.kind is AskPlanKind.OUT_OF_SCOPE:
        return []
    return with_flows([b.value for b in out.bundles], question)
