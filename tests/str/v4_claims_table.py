"""test_v4_claims 주장 표 — 렌더된 문장 속 주장 낱말 → 원본 facts 에서 참이어야 하는 조건 (docs/str/08 narrative_v4 3번).

있음·부재·전체·집계 범위 주장(섹션 단위)과 관측값 단위 부재 주장. 키는 정규식.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aml_ai.shared.schemas.str import Facts, PathStatus


# 주장 낱말 → facts(원본) 에서 참이어야 하는 조건
def _cycle(f: Facts) -> bool:
    paths = f.paths
    return (
        paths is not None
        and paths.status is PathStatus.VERIFIED
        and paths.kind is not None
        and paths.kind.value == "CYCLE"
    )


def _sg_supported(f: Facts) -> bool:
    paths = f.paths
    return (
        paths is not None
        and paths.status is PathStatus.VERIFIED
        and paths.kind is not None
        and paths.kind.value == "SCATTER_GATHER"
        and paths.count >= 3  # R05 min_intermediates
    )


def _typ(f: Facts) -> str | None:
    return f.typology.value if f.typology else None


def _purpose(f: Facts) -> str | None:
    return f.customer.account_purpose if f.customer else None


CLAIMS: dict[str, Callable[[Facts], bool]] = {  # 키는 정규식
    "돌아온": _cycle,
    "출금만": lambda f: f.inbound.count == 0 and f.internal.count == 0 and f.outbound.count > 0,
    "입금은 없고": lambda f: f.inbound.count == 0 and f.internal.count == 0,
    "입금만": lambda f: f.outbound.count == 0 and f.internal.count == 0 and f.inbound.count > 0,
    "출금은 없고": lambda f: f.outbound.count == 0 and f.internal.count == 0,
    "모두 같은 날": lambda f: f.period.start.date() == f.period.end.date(),
    "위 입금": lambda f: f.inbound.count > 0,
    "위 출금": lambda f: f.outbound.count > 0,
    # 관측 항목 표기("서로 다른 송금인 계좌 수")는 모델 관측값 이름이라 제외 — 확인 사항 문구만
    "송금인 정보|송금인과": lambda f: f.counterparties.count > 0 and f.inbound.count > 0,
    "수취인 정보|수취인과": lambda f: f.counterparties.count > 0 and f.outbound.count > 0,
    "해당 상대 계좌": lambda f: f.counterparties.count > 0,
    "경로상 계좌": lambda f: f.paths is not None and f.paths.status is PathStatus.VERIFIED,
    "경로에 나타난": lambda f: f.paths is not None and f.paths.status is PathStatus.VERIFIED,
    "자행 계좌가 있으므로": lambda f: f.counterparty_banks.same_bank_accounts > 0,
    "과거 경보 이력이 있": lambda f: f.prior_alert_count > 0,
    "고객 정보가": lambda f: f.customer is None,
    "고객 확인 자료가": lambda f: f.customer is None,
    r"계좌 목적은 \S.*?로 등록": lambda f: _purpose(f) is not None,
    "등록된 계좌 목적": lambda f: _purpose(f) is not None,
    "매출": lambda f: _purpose(f) == "SALES_DEPOSIT",
    "사업상": lambda f: _purpose(f) == "SALES_DEPOSIT",
    # 부재·전체 주장 — 집계 전체를 볼 때만(구조 변경 뒤 추가 검토 3차)
    r"(?<!이 관측값의 )비교 기준값은 자료 없음": lambda f: (
        bool(f.observations) and all(o.baseline is None for o in f.observations)
    ),
    "입금·출금의 결제 방식은 자료 없음": lambda f: not f.payment_format_counts,
    # 집계 범위 주장 — 내부 거래를 뺀 집계를 쓰는 문장은 범위 구절 없이 나오면 실패(추가 검토 4차)
    r"(?<!입금·출금의 )거래 금액은 최소": lambda f: False,
    r"(?<!입금·출금의 )거래 통화는": lambda f: False,
    r"(?<!입금·출금의 )결제 방식은": lambda f: False,
    "모델 관측값은 자료 없음": lambda f: not f.observations,
    "모델 관측값의 관측 구간은 자료 없음": lambda f: (  # SCRUM-264 — 전부 양 끝 null 일 때만
        bool(f.observations) and all(o.window_start is None and o.window_end is None for o in f.observations)
    ),
}
# SCRUM-269 흐름 문장 — 송금인 하한(상대 − 출금) ≥ 5 · 수취인 하한(상대 − 입금) ≥ 10 · 경로 확인(05 "흐름 문장")
FLOW_CLAIMS: dict[str, Callable[[Facts], bool]] = {
    "여러 송금인 계좌": lambda f: _typ(f) == "FAN_IN" and f.counterparties.count - f.outbound.count >= 5,
    "여러 수취인 계좌": lambda f: _typ(f) == "FAN_OUT" and f.counterparties.count - f.inbound.count >= 10,
    "출발 계좌로 돌아옴": lambda f: _typ(f) == "CYCLE" and _cycle(f),
    "서로 다른 중간 계좌": lambda f: _typ(f) == "SCATTER_GATHER" and _sg_supported(f),
}
CLAIMS |= FLOW_CLAIMS
# 관측값 단위 부재 주장 — 그 관측값 문장 안에서만, 그 관측값에 대해 참
OBS_CLAIMS: dict[str, Callable[[Any, Facts], bool]] = {
    "이 관측값의 비교 기준값은 자료 없음": lambda o, f: (
        o.baseline is None and any(x.baseline is not None for x in f.observations)
    ),
    "관측 구간 자료 없음": lambda o, f: o.window_start is None and o.window_end is None,
    "관측 구간 일부 자료 없음": lambda o, f: (o.window_start is None) != (o.window_end is None),
}
