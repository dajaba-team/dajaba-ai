"""재블라인드 기존 회귀 3건 — 228 사건을 SCRUM-264 이후 형식으로 (09 2026-11-17 "SCRUM-265 1/2 — 사전 등록" ⑥).

`fan_in`(v4 우세) · `scatter_gather`(픽스처 불일치) · `customer_missing`(합성 불일치). 참고용 — 판정에 안 섞음.
관측값은 실제 피처 이름(`real_names`) + unit·window·baseline null(실제 reasons 형식).
`customer_missing` 관측값 값은 거래와 맞춤(입금 1건 → 송금인 1 · 근거 거래 2) — 지어낸 값이 불일치 단서가 되지 않게.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import Facts
from tests.str.v4_real_names import real_names
from tests.str.v4_slot_support import load_raw_fixture

REAL_FORMAT = {"unit": None, "window_start": None, "window_end": None, "baseline": None}
MISSING_VALUES = {"focal_distinct_senders": 1.0, "evidence_count": 2.0}


def _real_format(facts: Facts) -> Facts:
    real = real_names(facts)
    observations = [o.model_copy(update=REAL_FORMAT) for o in real.observations]
    return real.model_copy(update={"observations": observations})


def regression_facts() -> list[tuple[str, Facts]]:
    from tests.str.v4_claims_support import facts_for

    missing = facts_for(n_in=1, n_out=1, n_int=0, path="none", typology="FAN_IN", customer="none", obs="real")
    if missing is None:
        raise ValueError("회귀 사건 구성 실패")
    observations = [o.model_copy(update={"value": MISSING_VALUES[o.name]}) for o in missing.observations]
    missing = missing.model_copy(update={"observations": observations})
    return [
        ("reg_fan_in", _real_format(load_raw_fixture("facts_fan_in.json"))),
        ("reg_scatter_gather", _real_format(load_raw_fixture("facts_scatter_gather.json"))),
        ("reg_customer_missing", _real_format(missing)),
    ]
