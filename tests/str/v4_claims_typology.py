"""SCRUM-265 (2/2) — 주장 조합 검사에 더하는 판정 경계 조합 (docs/str/08 "유형 뒷받침 판정·문구").

기존 조합(`v4_claims_support.COMBOS`)은 입금·출금 0/1 이라 FAN_IN·FAN_OUT 뒷받침됨이 안 나옴 →
임계값 경계(하한 = 임계값 · 상한 = 임계값 − 1 · 그 사이)·혼재·내부 거래·SG 중간 계좌 수·경로 종류를 실제 거래로 만든다.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from tests.str.v4_blind2_grid import build, rows_for, subject_for

SND, RCV, MID, SRC, B, C = (
    "020_A{:07d}",
    "030_R{:07d}",
    "050_M{:07d}",
    "060_P0000001",
    "040_C0000001",
    "040_C0000002",
)


def _flow(typology: str, senders: int, receivers: int, internal: int, s: str) -> list[tuple[str, str]]:
    ins = [(SND.format(i), s) for i in range(1, senders + 1)]
    outs = [(s, RCV.format(j)) for j in range(1, receivers + 1)]
    same_entity = [("10_S9999999", s)] * internal  # 같은 법인 계좌(아래 account_entities)
    return ins + outs + same_entity


def _combos() -> list[tuple[tuple[Any, ...], Facts]]:
    out = []
    index = 0
    names = ("evidence_count",)
    for typology, senders, receivers, internal in itertools.chain(
        itertools.product(["FAN_IN"], (0, 1, 4, 5, 6), (0, 1, 2), (0, 1)),
        itertools.product(["FAN_OUT"], (0, 1, 2), (0, 1, 9, 10, 11), (0, 1)),
    ):
        if senders + receivers + internal == 0:
            continue
        index += 1
        subject = subject_for(index % 9 + 1, f"p{index % 10 + 1:02d}")
        entities = {subject.account_key: subject.entity_id or "", "10_S9999999": subject.entity_id or ""}
        subject = replace(subject, account_entities=entities)  # 내부 거래 = 같은 법인 계좌
        rows = rows_for(
            _flow(typology, senders, receivers, internal, subject.account_key), "1250.00", "USD", "ACH"
        )
        rule = "R02_FAN_IN" if typology == "FAN_IN" else "R01_FAN_OUT"
        f = build(rows, subject, rule, typology, None, names)
        if f is not None:
            out.append(((typology, senders, receivers, internal), f))
    for mids, kind in itertools.product((2, 3, 4), ("SCATTER_GATHER", "CYCLE")):
        index += 1
        subject = subject_for(index % 9 + 1, "p03")
        s = subject.account_key
        if kind == "SCATTER_GATHER":
            ms = [MID.format(i) for i in range(1, mids + 1)]
            edges = [(SRC, m) for m in ms] + [(m, s) for m in ms]
            rows = rows_for(edges, "1250.00", "USD", "Wire")
            ids = [r["transaction_id"] for r in rows]
            paths = [[ids[i], ids[mids + i]] for i in range(mids)]
            rule = "R05_SCATTER_GATHER"
        else:
            rows = rows_for([(s, B), (B, C), (C, s)], "1250.00", "USD", "Wire")
            paths = [[r["transaction_id"] for r in rows]]
            rule = "R04_CYCLE"
        f = build(rows, subject, rule, "SCATTER_GATHER", paths, names)  # SG 유형 + 경로 종류 둘
        if f is not None:
            out.append((("SCATTER_GATHER", kind, mids), f))
    return out


def _multi_currency() -> list[tuple[tuple[Any, ...], Facts]]:
    """다중 통화 축(추가 검토 1차) — mixed 픽스처 거래 묶음: 통화별 최소 = 최대 둘·하나·단일 통화."""
    from tests.str.facts_support import CASES
    from tests.str.facts_support import build as build_case

    rows = CASES["mixed"]["transactions"]
    unmapped = dict(rows[1], currency_paid="Dogecoin", currency_received="Dogecoin")  # 등록 1 + 미등록 1(2차)
    picks = {"two_equal": rows[:2], "one_equal": rows[:3], "single": rows[:1], "eur_out": rows[1:3],
             "one_plus_unmapped": [rows[0], unmapped]}  # fmt: skip
    return [
        (("multi_currency", key, typology), build_case({"transactions": tx}).model_copy(
            update={"typology": Typology(typology) if typology else None}))
        for key, tx in picks.items()
        for typology in ("FAN_IN", "FAN_OUT", None)
    ]  # fmt: skip


TYPOLOGY_COMBOS = _combos() + _multi_currency()
