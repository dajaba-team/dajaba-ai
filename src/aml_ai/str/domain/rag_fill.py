"""SCRUM-275 빈칸만 채우기 규칙 (docs/str/10 "빈칸만 채우기"). 순수 — DB·LLM·설정 0.

① 지금 경로 결과를 그대로 앞에 ② `k` 건이 안 찼을 때만 남는 칸을 채움 ③ 0건이면 채우지 않음.
"""

from __future__ import annotations


def needs_fill(found: int, k: int) -> bool:
    """규칙 ②·③ — 1건 이상, k 건 미만일 때만."""
    return 0 < found < k


def fill_order(first_ids: list[str], fused_ids: list[str]) -> list[str]:
    """합친 순서에서 1차 결과에 이미 있는 `chunk_id` 를 건너뛴 채울 후보 순서(중복 한 번)."""
    seen = set(first_ids)
    order: list[str] = []
    for chunk_id in fused_ids:
        if chunk_id not in seen:
            order.append(chunk_id)
            seen.add(chunk_id)
    return order
