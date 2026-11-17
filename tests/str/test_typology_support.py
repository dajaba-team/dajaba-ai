"""SCRUM-265 (2/2) — 유형 뒷받침 판정 (docs/str/05 "유형 뒷받침 판정", 09 2026-11-17 "SCRUM-265 2/2 판정"). 순수.

식은 09 사전 등록 줄 ③ 그대로(하한 = counterparties − 반대 방향, 상한 = min(그 방향, counterparties)) +
SCATTER_GATHER 경로 종류 + 내부 거래 > 0 불충족 → 미확인. 입력은 마스킹본 dict(UNVERIFIED paths 는 빠짐).
"""

from __future__ import annotations

from typing import Any

import pytest

from aml_ai.str.domain.constants_v4 import MIN_DISTINCT_RECEIVERS, MIN_DISTINCT_SENDERS, MIN_INTERMEDIATES
from aml_ai.str.domain.typology_support import Support, receiver_bounds, sender_bounds, typology_support

S, C, U = Support.SUPPORTED, Support.UNCONFIRMED, Support.UNMET


def _f(
    typology: str | None, cp: int, inn: int, out: int, internal: int = 0, paths: dict | None = None
) -> dict:
    d: dict[str, Any] = {"typology": typology, "counterparties": {"count": cp}, "inbound": {"count": inn},
                         "outbound": {"count": out}, "internal": {"count": internal}, "paths": paths}  # fmt: skip
    return d


def test_thresholds_are_backend_rule_params() -> None:
    assert (MIN_DISTINCT_SENDERS, MIN_DISTINCT_RECEIVERS, MIN_INTERMEDIATES) == (5, 10, 3)


@pytest.mark.parametrize(
    ("cp", "inn", "out", "want"),
    [
        (5, 5, 0, S),  # 하한 = 5 = 임계값
        (6, 6, 1, S),  # 혼재 — 하한 5
        (4, 4, 0, U),  # 상한 4 = 임계값 − 1
        (6, 6, 2, C),  # 하한 4 · 상한 6 — 그 사이
        (5, 3, 2, U),  # 상한 = min(3, 5) = 3
        (0, 0, 0, U),  # 입금 0 — 상한 0
    ],
)
def test_fan_in_bounds(cp: int, inn: int, out: int, want: Support) -> None:
    assert typology_support(_f("FAN_IN", cp, inn, out)) is want


@pytest.mark.parametrize(
    ("cp", "inn", "out", "want"),
    [(10, 0, 10, S), (11, 1, 11, S), (9, 0, 9, U), (11, 2, 11, C), (10, 5, 3, U)],
)
def test_fan_out_bounds(cp: int, inn: int, out: int, want: Support) -> None:
    assert typology_support(_f("FAN_OUT", cp, inn, out)) is want


def test_bounds_formula() -> None:
    f = _f("FAN_IN", 7, 6, 1)
    assert sender_bounds(f) == (6, 6) and receiver_bounds(f) == (1, 1)
    assert sender_bounds(_f("FAN_IN", 3, 5, 0)) == (3, 3)  # 같은 송금인 여러 번


def test_internal_transfer_lowers_unmet_to_unconfirmed() -> None:
    assert typology_support(_f("FAN_IN", 1, 1, 0, internal=1)) is C
    assert typology_support(_f("FAN_OUT", 1, 0, 1, internal=2)) is C
    assert typology_support(_f("FAN_IN", 5, 5, 0, internal=1)) is S  # 뒷받침됨은 그대로


@pytest.mark.parametrize(
    ("paths", "want"),
    [
        ({"kind": "CYCLE", "count": 1}, S),
        (None, C),  # 경로 없음 또는 UNVERIFIED(마스킹으로 빠짐)
        ({"kind": "SCATTER_GATHER", "count": 3}, C),  # 비순환 VERIFIED
    ],
)
def test_cycle(paths: dict | None, want: Support) -> None:
    assert typology_support(_f("CYCLE", 2, 1, 1, paths=paths)) is want


@pytest.mark.parametrize(
    ("paths", "out", "want"),
    [
        ({"kind": "SCATTER_GATHER", "count": 3}, 0, S),  # 중간 계좌 = 임계값
        ({"kind": "SCATTER_GATHER", "count": 2}, 0, C),
        (None, 0, C),  # 출금 0·경로 없음 — 모이는 쪽일 수 있음
        ({"kind": "CYCLE", "count": 5}, 1, C),  # 경로 종류가 다름
    ],
)
def test_scatter_gather(paths: dict | None, out: int, want: Support) -> None:
    assert typology_support(_f("SCATTER_GATHER", 3, 3, out, paths=paths)) is want


@pytest.mark.parametrize("typology", [None, "PASS_THROUGH", "GATHER_SCATTER", "FX_RELAY", "STACK"])
def test_no_judgment_for_other_typologies(typology: str | None) -> None:
    assert typology_support(_f(typology, 1, 1, 0)) is None
