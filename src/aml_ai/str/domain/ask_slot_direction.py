"""질문 답변 방향 자리표 이름표 (docs/str/04 "답 자리표" `direction`, SCRUM-362 추가 검토 1 H1 · 2 H1 · 3 H3). 순수 함수.

배타·부재(`대외 입금만`·`대외 출금만`·`대외 입출금 없음`)는 근거가 경보 전체이고 소유 정보가 있을 때만(`exclusive_ok`).
"""

from __future__ import annotations

from typing import Any

_DIRECTION = {
    "INBOUND": "입금 우세",
    "OUTBOUND": "출금 우세",
    "MIXED": "입금·출금 모두",
    "INTERNAL": "대외 입출금 없음",  # 입출금 둘 다 0 — 간접 거래만일 수도 있어 "내부 거래만" 아님(추가 검토 2 H1)
}
_ONLY = {
    "INBOUND": ("outbound", "대외 입금만"),
    "OUTBOUND": ("inbound", "대외 출금만"),
}  # 범위(대외)를 이름표에(추가 검토 2 H1)
_EVIDENCE_SCOPE = " (근거 거래 기준)"


def direction_label(c: dict[str, Any], exclusive_ok: bool) -> str:
    """배타·부재(`대외 입금만`·`대외 입출금 없음`)는 근거 범위가 확인될 때만, 아니면 `(근거 거래 기준)` 을 붙인 우세 꼴."""
    value = c["direction"]
    other, only = _ONLY.get(value, (None, None))
    if exclusive_ok:
        return only if other is not None and (c.get(other) or {}).get("count") == 0 else _DIRECTION[value]
    if value == "INTERNAL":
        return f"대외 입출금 확인 안 됨{_EVIDENCE_SCOPE}"
    return _DIRECTION[value] + ("" if value == "MIXED" else _EVIDENCE_SCOPE)
