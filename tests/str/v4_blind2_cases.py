"""SCRUM-265 (1/2) — 재블라인드 사건 고정 (09 2026-11-17 "SCRUM-265 1/2 — 사전 등록" ③~⑥, docs/str/08 "재블라인드").

칸마다 격자 후보 → 칸 조건(facts 만 — 하한·상한 식) 통과분 → 시드로 1건(이미 쓴 고객 프로필 후보는 뺌).
정답은 칸에서(코드 판정 아님). 회귀 3건은 228 사건을 264 이후 형식으로. 결과는 `v4_blind2_cases.json` 하나.

다시 쓰기(사전 등록 뒤엔 하지 않음 — 테스트가 파일 = pick(SEED) 를 확인):
    uv run --frozen --extra dev python -m tests.str.v4_blind2_cases
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.facts_enums import PathKind, PathStatus
from tests.str.v4_blind2_grid import build, counts, grid, rows_for, subject_for
from tests.str.v4_blind2_regression import regression_facts

SEED = 265
CASES_FILE = Path(__file__).resolve().parent / "v4_blind2_cases.json"
MIN_SENDERS, MIN_RECEIVERS, MIN_INTERMEDIATES = 5, 10, 3  # 백엔드 rules.md R02·R01·R05
YES, NO_OR_UNKNOWN = ["yes"], ["no", "unknown"]
SND, RCV, MID, SRC = "020_A{:07d}", "030_R{:07d}", "050_M{:07d}", "060_P0000001"
B, C = "040_C0000001", "040_C0000002"


def sender_bounds(f: Facts) -> tuple[int, int]:
    """송금인 하한 = counterparties − outbound, 상한 = min(inbound, counterparties) (09 ③)."""
    return f.counterparties.count - f.outbound.count, min(f.inbound.count, f.counterparties.count)


def receiver_bounds(f: Facts) -> tuple[int, int]:
    return f.counterparties.count - f.inbound.count, min(f.outbound.count, f.counterparties.count)


def _verified(f: Facts, kind: PathKind) -> bool:
    return f.paths is not None and f.paths.status is PathStatus.VERIFIED and f.paths.kind is kind


def _not_verified(f: Facts) -> bool:
    return f.paths is None or f.paths.status is not PathStatus.VERIFIED


Edges = tuple[list[tuple[str, str]], Callable[[list[int]], list[list[int]] | None]]


@dataclass(frozen=True)
class Slot:
    case_id: str
    slot: str  # supported · unsupported · mixed
    typology: str
    rule_id: str
    axes: dict[str, tuple[Any, ...]]
    edges: Callable[[dict[str, Any], str], Edges]
    names: tuple[str, ...]  # 관측값 피처 이름(사전 20개 안)
    condition: Callable[[Facts], bool]

    @property
    def answer(self) -> list[str]:
        return NO_OR_UNKNOWN if self.slot == "unsupported" else YES


def _fan_in(p: dict, s: str) -> Edges:
    ins = [(SND.format(i), s) for i in range(1, p["senders"] + 1)]
    return ins + [(s, RCV.format(j)) for j in range(1, p.get("outs", 0) + 1)], lambda ids: None


def _repeat_in(p: dict, s: str) -> Edges:
    return [(SND.format(1), s)] * p["repeats"], lambda ids: None


def _fan_out(p: dict, s: str) -> Edges:
    return [(s, RCV.format(j)) for j in range(1, p["receivers"] + 1)], lambda ids: None


def _cycle(p: dict, s: str) -> Edges:
    edges = [(s, B), (B, s)] if p["hops"] == 2 else [(s, B), (B, C), (C, s)]
    if p.get("path", "verified") == "none":
        return edges, lambda ids: None
    return edges, lambda ids: [ids if p.get("path", "verified") == "verified" else [ids[1], ids[0], *ids[2:]]]


def _scatter_gather(p: dict, s: str) -> Edges:
    mids = [MID.format(i) for i in range(1, p["mids"] + 1)]
    n = len(mids)
    return [(SRC, m) for m in mids] + [(m, s) for m in mids], lambda ids: [
        [ids[i], ids[n + i]] for i in range(n)
    ]


def _gather_only(p: dict, s: str) -> Edges:
    return [(MID.format(i), s) for i in range(1, p["senders"] + 1)], lambda ids: None


SLOTS: tuple[Slot, ...] = (
    Slot("sup_fan_in", "supported", "FAN_IN", "R02_FAN_IN", {"senders": (5, 6, 7, 8)}, _fan_in,
         ("focal_distinct_senders", "focal_in_count", "evidence_count"),
         lambda f: sender_bounds(f)[0] >= MIN_SENDERS and f.outbound.count == 0),
    Slot("sup_fan_out", "supported", "FAN_OUT", "R01_FAN_OUT", {"receivers": (10, 11, 12)}, _fan_out,
         ("focal_distinct_receivers", "focal_out_count", "evidence_count"),
         lambda f: receiver_bounds(f)[0] >= MIN_RECEIVERS),
    Slot("sup_cycle", "supported", "CYCLE", "R04_CYCLE", {"hops": (2, 3)}, _cycle,
         ("evidence_account_count", "evidence_count", "focal_out_count"),
         lambda f: _verified(f, PathKind.CYCLE)),
    Slot("sup_scatter_gather", "supported", "SCATTER_GATHER", "R05_SCATTER_GATHER", {"mids": (3, 4, 5)},
         _scatter_gather, ("focal_distinct_senders", "evidence_account_count", "evidence_count"),
         lambda f: _verified(f, PathKind.SCATTER_GATHER) and f.paths.count >= MIN_INTERMEDIATES),  # type: ignore[union-attr]
    Slot("uns_cycle", "unsupported", "CYCLE", "R04_CYCLE", {"hops": (3,), "path": ("none", "unverified")},
         _cycle, ("evidence_account_count", "evidence_count", "focal_out_count"), _not_verified),
    Slot("uns_scatter_gather", "unsupported", "SCATTER_GATHER", "R05_SCATTER_GATHER", {"senders": (1, 2, 3)},
         _gather_only, ("focal_in_count", "evidence_count", "focal_distinct_senders"),
         lambda f: f.outbound.count == 0 and f.paths is None),
    Slot("uns_fan_in", "unsupported", "FAN_IN", "R02_FAN_IN", {"repeats": (1, 2, 3)}, _repeat_in,
         ("focal_in_count", "focal_distinct_senders", "evidence_account_count"),
         lambda f: f.outbound.count == 0 and sender_bounds(f)[1] < MIN_SENDERS),
    Slot("mix_fan_in", "mixed", "FAN_IN", "R02_FAN_IN", {"senders": (5, 6, 7), "outs": (1, 2)}, _fan_in,
         ("focal_distinct_senders", "focal_out_count", "evidence_count"),
         lambda f: sender_bounds(f)[0] >= MIN_SENDERS and f.outbound.count >= 1),
)  # fmt: skip


def candidates(slot: Slot, index: int) -> list[tuple[dict[str, Any], Facts]]:
    """격자 → 거래 행 → build_facts → 칸 조건 통과분. params 에 실제 송금인·수취인 수."""
    out = []
    for p in grid(slot.axes):
        subject = subject_for(index, p["profile"])
        edges, paths = slot.edges(p, subject.account_key)
        rows = rows_for(edges, p["amount"], p["currency"], p["format"])
        f = build(
            rows, subject, slot.rule_id, slot.typology, paths([r["transaction_id"] for r in rows]), slot.names
        )
        if f is not None and slot.condition(f):
            c = counts(rows, subject.account_key)
            out.append(
                (p | {"senders": c["focal_distinct_senders"], "receivers": c["focal_distinct_receivers"]}, f)
            )
    return out


def pick(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    used: set[str] = set()
    doc: dict[str, Any] = {"seed": seed, "candidate_counts": {}, "cases": []}
    for index, slot in enumerate(SLOTS, start=1):
        pool = candidates(slot, index)
        doc["candidate_counts"][slot.case_id] = len(pool)
        params, f = rng.choice([c for c in pool if c[0]["profile"] not in used])
        used.add(params["profile"])
        doc["cases"].append({"case_id": slot.case_id, "slot": slot.slot, "role": "judged", "typology": slot.typology,
                             "answer": slot.answer, "profile": params["profile"], "params": params,
                             "facts": f.model_dump(mode="json")})  # fmt: skip
    doc["control_case_id"] = rng.choice([s.case_id for s in SLOTS])
    for case_id, f in regression_facts():
        doc["cases"].append({"case_id": case_id, "slot": "regression", "role": "regression",
                             "typology": f.typology.value if f.typology else None, "answer": None,
                             "profile": None, "params": {}, "facts": f.model_dump(mode="json")})  # fmt: skip
    return json.loads(json.dumps(doc))


def load_cases(path: Path = CASES_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_facts(doc: dict[str, Any]) -> dict[str, Facts]:
    return {c["case_id"]: Facts.model_validate(c["facts"]) for c in doc["cases"]}


def main() -> int:
    CASES_FILE.write_text(json.dumps(pick(SEED), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
