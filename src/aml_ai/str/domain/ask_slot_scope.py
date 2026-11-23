"""집계 값의 범위 표시 (docs/str/04 "집계 값의 범위 표시", SCRUM-362 ★B8 N-1·N-2). 순수 함수.

이름표 제목은 프롬프트(`<fact_keys>`)에 들어가 녹화 키를 만들어 안 바꾸고, **값 끝**에만 붙인다.
"""

from __future__ import annotations

# 근거 거래로 센 값 — 근거가 경보 일부이거나 범위를 모르면 표시(N-1)
_EVIDENCE_KEYS = (
    "inbound.",
    "outbound.",
    "internal.",
    "counterparties.",
    "counterparty_banks.",
    "counterparties_by_direction.",
    "payment_format_counts.",
    "amount_range.",
    "compare.",
)
_EVIDENCE_EXACT = ("period", "payment_formats")
# 대외 입출금(flows)만 센 값 — 근거에 내부·간접 거래가 있으면 표시(N-2)
_EXTERNAL_KEYS = (
    "inbound.",
    "outbound.",
    "counterparties.",
    "counterparty_banks.",
    "counterparties_by_direction.",
    "amount_range.",
    "compare.",
)
_ALWAYS_EXTERNAL = ("payment_formats", "payment_format_counts.")  # 결제 방식은 늘 대외 기준(★B7-1)


def scoped_value(key: str, value: str, *, evidence_scoped: bool, non_external: int) -> str:
    parts = []
    if evidence_scoped and (key in _EVIDENCE_EXACT or key.startswith(_EVIDENCE_KEYS)):
        parts.append("근거 거래")
    if key.startswith(_ALWAYS_EXTERNAL) or (non_external and key.startswith(_EXTERNAL_KEYS)):
        parts.append("대외 거래")
    return value + (f" ({' · '.join(parts)} 기준)" if parts else "")
