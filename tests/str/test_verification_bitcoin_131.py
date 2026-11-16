"""SCRUM-131 (4/n) — 결제 방식 Bitcoin 건수 현재 동작 기록 (알고 남긴 한계, 06 "포함·집합 판정" 7 참조).

COUNT ⑥ 별칭에 Bitcoin 을 넣지 않는다(11.6 시도 뒤 되돌림, 09 2026-11-17). Bitcoin 결제 방식 건수는 방향 없는
거래 건수 집합과 대조 → 틀린 건수가 그 집합 안이면 통과. v4 는 Bitcoin 을 건수 없이 이름만 써서 해당 없음.
facts_multi_currency: payment_format_counts ACH 2 · Bitcoin 1 · Wire 1, 입금 4건.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import PAYMENT_FORMAT_ALIASES, VERIFIER_VERSION
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.v4_slot_support import load_fixture
from tests.str.verification_support import count

FACTS = load_fixture("facts_multi_currency.json")


def _results(text: str) -> list[tuple[str, bool, str]]:
    return [(c.draft_value, c.match, c.source_value or "") for c in count(FACTS, SectionV2.INSTRUMENT, text)]


def test_bitcoin_is_not_a_count_alias() -> None:
    assert VERIFIER_VERSION == "verify-2026.11.5"
    assert "Bitcoin" not in PAYMENT_FORMAT_ALIASES


def test_wrong_bitcoin_count_passes_silently_known_limit() -> None:
    """알고 남긴 한계 — 실제 Bitcoin 1건인데 `비트코인 2건` 이 거래 건수 집합 {0,1,2,4} 안이라 match."""
    assert _results("비트코인 2건이 있음.") == [("2건", True, "{0,1,2,4}")]


def test_v4_slot_writes_bitcoin_name_only() -> None:
    sections = {s.section: s.text for s in build_v4(masking.mask_for_llm(FACTS), load_display_labels())}
    assert "비트코인(Bitcoin)," in sections[SectionV2.INSTRUMENT]
    assert "비트코인(Bitcoin) 1건" not in sections[SectionV2.INSTRUMENT]
