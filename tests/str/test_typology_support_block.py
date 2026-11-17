"""SCRUM-268 — judge_v4 판정 근거 블록(docs/str/06 "judge_v4", 09 SCRUM-268 사전 기준). LLM·DB 0.

블록 판정 = `typology_support`(읽기만) · 판정 3단계 × FAN 2 + 2단계 × 경로 2 + 내부 거래 내림 ·
계좌번호·금액·이름 없음 · 판정 없는 유형은 None / `(없음)`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aml_ai.str.domain.constants_v4 import MIN_DISTINCT_RECEIVERS, MIN_DISTINCT_SENDERS, MIN_INTERMEDIATES
from aml_ai.str.domain.typology_support import typology_support
from aml_ai.str.domain.typology_support_block import NO_BLOCK, render_support_block, support_block

FLOW_KEYS = {"typology", "support", "counted", "lower_bound", "upper_bound", "threshold", "internal_count",
             "lowered_by_internal"}  # fmt: skip
PATH_KEYS = {"typology", "support", "verified_path_kind", "verified_path_count"}


def _facts(typology: str | None, *, inbound: int = 0, outbound: int = 0, cp: int = 0, internal: int = 0,
           paths: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """마스킹본 모양(판정이 읽는 칸 + 계좌·금액·이름 칸) — 블록에 계좌·금액·이름이 안 새는지 같이 봄."""
    f: dict[str, Any] = {
        "typology": typology,
        "subject": {"account_key": "10_****BD30", "entity_name": "Sole Proprietorship #50438"},
        "inbound": {"count": inbound, "by_currency": [{"currency": "USD", "amount": "42750.50"}]},
        "outbound": {"count": outbound, "by_currency": []},
        "counterparties": {"count": cp},
        "internal": {"count": internal},
    }
    if paths is not None:
        f["paths"] = paths
    return f


def _path(kind: str, count: int) -> dict[str, Any]:
    return {"kind": kind, "count": count, "max_hops": 3, "max_accounts": 3}


CASES = {
    # FAN_IN — 하한 = 상대 − 출금, 상한 = min(입금, 상대), 임계값 5
    "fan_in_supported": (_facts("FAN_IN", inbound=6, cp=5), "SUPPORTED", False),
    "fan_in_unmet": (_facts("FAN_IN", inbound=3, cp=3), "UNMET", False),
    "fan_in_unconfirmed_bounds": (_facts("FAN_IN", inbound=6, outbound=2, cp=6), "UNCONFIRMED", False),
    "fan_in_lowered": (_facts("FAN_IN", inbound=7, cp=4, internal=1), "UNCONFIRMED", True),
    # FAN_OUT — 방향 반대, 임계값 10
    "fan_out_supported": (_facts("FAN_OUT", outbound=11, cp=11), "SUPPORTED", False),
    "fan_out_unmet": (_facts("FAN_OUT", outbound=3, cp=3), "UNMET", False),
    "fan_out_unconfirmed_bounds": (_facts("FAN_OUT", inbound=3, outbound=12, cp=12), "UNCONFIRMED", False),
    "fan_out_lowered": (_facts("FAN_OUT", outbound=3, cp=3, internal=2), "UNCONFIRMED", True),
    # 경로 — 마스킹본엔 VERIFIED 만 남음
    "cycle_supported": (
        _facts("CYCLE", inbound=1, outbound=1, cp=2, paths=_path("CYCLE", 1)),
        "SUPPORTED",
        None,
    ),
    "cycle_unconfirmed": (_facts("CYCLE", inbound=3, cp=3), "UNCONFIRMED", None),
    "sg_supported": (
        _facts("SCATTER_GATHER", inbound=5, cp=5, paths=_path("SCATTER_GATHER", 5)),
        "SUPPORTED",
        None,
    ),
    "sg_unconfirmed_few": (
        _facts("SCATTER_GATHER", inbound=2, cp=2, paths=_path("SCATTER_GATHER", 2)),
        "UNCONFIRMED",
        None,
    ),  # fmt: skip
    "sg_unconfirmed_none": (_facts("SCATTER_GATHER", inbound=2, cp=2), "UNCONFIRMED", None),
}


@pytest.mark.parametrize("name", list(CASES))
def test_block_support_equals_domain_function(name: str) -> None:
    facts, expected, lowered = CASES[name]
    block = support_block(facts)
    assert block is not None
    assert block["support"] == expected == typology_support(facts).value  # type: ignore[union-attr]
    assert block["typology"] == facts["typology"]
    if lowered is not None:
        assert set(block) == FLOW_KEYS
        assert block["lowered_by_internal"] is lowered
        assert block["internal_count"] == facts["internal"]["count"]
    else:
        assert PATH_KEYS <= set(block) <= PATH_KEYS | {"threshold"}


@pytest.mark.parametrize(
    ("name", "counted", "low", "high", "threshold"),
    [
        ("fan_in_supported", "distinct_senders", 5, 5, MIN_DISTINCT_SENDERS),
        ("fan_in_unconfirmed_bounds", "distinct_senders", 4, 6, MIN_DISTINCT_SENDERS),
        ("fan_in_lowered", "distinct_senders", 4, 4, MIN_DISTINCT_SENDERS),
        ("fan_out_unconfirmed_bounds", "distinct_receivers", 9, 12, MIN_DISTINCT_RECEIVERS),
    ],
)
def test_flow_block_numbers(name: str, counted: str, low: int, high: int, threshold: int) -> None:
    block = support_block(CASES[name][0])
    assert block is not None
    assert (block["counted"], block["lower_bound"], block["upper_bound"], block["threshold"]) == (
        counted, low, high, threshold,
    )  # fmt: skip


def test_path_blocks() -> None:
    sg = support_block(CASES["sg_unconfirmed_few"][0])
    assert sg == {"typology": "SCATTER_GATHER", "support": "UNCONFIRMED", "verified_path_kind": "SCATTER_GATHER",
                  "verified_path_count": 2, "threshold": MIN_INTERMEDIATES}  # fmt: skip
    cycle = support_block(CASES["cycle_unconfirmed"][0])
    assert cycle == {"typology": "CYCLE", "support": "UNCONFIRMED", "verified_path_kind": None,
                     "verified_path_count": 0}  # fmt: skip


def test_unmet_not_lowered_when_bounds_straddle() -> None:
    """상한 ≥ 임계값이라 원래 미확인 — 내부 거래가 있어도 '내림' 아님."""
    facts = _facts("FAN_IN", inbound=6, outbound=2, cp=6, internal=1)
    block = support_block(facts)
    assert block is not None and block["support"] == "UNCONFIRMED" and block["lowered_by_internal"] is False


@pytest.mark.parametrize("name", list(CASES))
def test_no_account_amount_name(name: str) -> None:
    text = render_support_block(CASES[name][0])
    for leak in ("BD30", "account", "42750", "amount", "Sole Proprietorship", "entity_name", "USD"):
        assert leak not in text, (name, leak)


@pytest.mark.parametrize("typology", [None, "STRUCTURING"])
def test_no_block_for_types_without_judgement(typology: str | None) -> None:
    facts = _facts(typology, inbound=3, cp=3)
    assert support_block(facts) is None
    assert render_support_block(facts) == NO_BLOCK == "(없음)"


def test_render_is_indented_json() -> None:
    facts = CASES["fan_in_lowered"][0]
    assert render_support_block(facts) == json.dumps(support_block(facts), ensure_ascii=False, indent=2)
