"""narrative_v4 슬롯 정상·변조 표 도우미 (docs/str/08 narrative_v4 2번).

정상: 픽스처 facts → 슬롯 + 숫자 없는 고정 자유 문장 → 조립 → run_code_checks 실패 0.
변조: 슬롯 문장 안 숫자 덩이(금액·날짜·건수·계좌의 숫자 부분)를 하나씩 ±1 바꿔 다시 돌림 →
그 섹션에 match=false 가 생기면 잡힘, 아니면 조용한 통과.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.domain.verification import run_code_checks
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.fewshot_store import FEWSHOT_ROOT
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.conftest import FIXTURES
from tests.str.v4_real_names import real_names

FIXTURE_NAMES = (
    "facts_fan_in.json",
    "facts_fan_in_b.json",
    "facts_fan_out.json",
    "facts_cycle_nopaths.json",
    "facts_scatter_gather.json",
    "facts_multi_currency.json",
)


def facts_sources() -> list[tuple[str, Facts]]:
    """픽스처 6개(다중 통화 포함) + v3 few-shot facts 5개(CYCLE 경로 확인·PASS_THROUGH·유형 없음). 관측 이름은 실제 이름."""
    out = [(n, load_fixture(n)) for n in FIXTURE_NAMES]
    for p in sorted((FEWSHOT_ROOT / "narrative_v3").glob("*.json")):  # facts 만 — 유형·경로·null 다양
        out.append(
            (
                f"fewshot/{p.name}",
                real_names(Facts.model_validate(json.loads(p.read_text(encoding="utf-8"))["facts"])),
            )
        )
    return out


def assembled(facts: Facts) -> list[LlmNarrativeSection]:
    return build_v4(masking.mask_for_llm(facts), load_display_labels())


def code_checks(facts: Facts, sections: list[LlmNarrativeSection]) -> list[Any]:
    scope = sorted({i for ids in fact_keys(facts).values() for i in ids})
    return run_code_checks(facts, attach_evidence(sections, facts), scope)


def failures(facts: Facts, sections: list[LlmNarrativeSection]) -> list[Any]:
    return [c for c in code_checks(facts, sections) if not c.match]


def load_raw_fixture(name: str) -> Facts:
    """파일 그대로(지어낸 관측 이름) — v2 표기 통일 하네스 테스트용."""
    return Facts.model_validate_json(Path(FIXTURES / name).read_text(encoding="utf-8"))


def load_fixture(name: str) -> Facts:
    """관측 이름은 실제 이름으로(SCRUM-264 — 파일은 v1~v3 녹화 키라 그대로)."""
    return real_names(load_raw_fixture(name))


def longest_case() -> Facts:
    """PR 표 — 통화 3개(입금·출금 둘 다) + 미등록 1개 + paths VERIFIED + 관측값 2개."""
    d = json.loads((FIXTURES / "facts_multi_currency.json").read_text(encoding="utf-8"))
    cur = [("EUR", "9800.25", 3), ("JPY", "1954831.63", 5), ("USD", "42750.50", 1)]
    d["inbound"] = {
        "count": 4,
        "by_currency": [{"currency": c, "total": t, "count": 1, "transaction_ids": [i]} for c, t, i in cur],
        "transaction_ids": [1, 3, 4, 5],
    }
    d["outbound"] = {
        "count": 3,
        "by_currency": [
            {"currency": c, "total": t, "count": 1, "transaction_ids": [i + 10]} for c, t, i in cur
        ],
        "transaction_ids": [11, 13, 15],
    }
    d["counterparties"] = {"count": 7, "transaction_ids": [1, 3, 4, 5, 11, 13, 15]}
    d["counterparty_banks"] = {"same_bank_accounts": 2, "other_bank_accounts": 5}
    d["amount_range"] = [{"currency": c, "min": "1000.00", "max": t} for c, t, _ in cur]
    d["paths"] = {
        "kind": "CYCLE",
        "status": "VERIFIED",
        "count": 2,
        "max_hops": 4,
        "max_accounts": 4,
        "transaction_ids": [1, 11],
    }
    d["typology"] = "CYCLE"
    return real_names(Facts.model_validate(d))
