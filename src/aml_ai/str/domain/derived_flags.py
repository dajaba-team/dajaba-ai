"""derived 플래그 — 참이면 코드가 슬롯 문장으로 쓰는 사실 (docs/str/05 narrative_v4). 순수.

facts 스키마가 아니다(04 "표시용 파생"). bool 만 — 숫자 값은 만들지 않는다.
"""

from __future__ import annotations

from typing import Any


def derive_flags(facts: dict[str, Any]) -> dict[str, bool]:
    banks = facts["counterparty_banks"]
    same, other = banks["same_bank_accounts"], banks["other_bank_accounts"]
    inbound, outbound = facts["inbound"]["count"], facts["outbound"]["count"]
    internal = facts["internal"]["count"]  # 배타 주장("입금은 없고 출금만")은 내부 거래까지 0 일 때만
    return {
        "all_other_bank": same == 0 and other > 0,
        "all_same_bank": other == 0 and same > 0,
        "single_day": facts["period"]["start"][:10] == facts["period"]["end"][:10],
        "inbound_only": inbound > 0 and outbound == 0 and internal == 0,
        "outbound_only": outbound > 0 and inbound == 0 and internal == 0,
    }  # 이름은 constants_v4.FLAG_SLOT_TEXT 와 같다(테스트로 묶음)


def true_flags(flags: dict[str, bool]) -> list[str]:
    """프롬프트 FLAGS 블록 — true 인 것만, 이름순."""
    return sorted(k for k, v in flags.items() if v)
