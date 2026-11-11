"""SCRUM-125 — TYPOLOGY_KO 에 SCATTER_GATHER·GATHER_SCATTER (룰 v2 R05·R06, INTENT 바꿀 파일 retriever.py).

- `TYPOLOGY_KO["SCATTER_GATHER"] == "흩었다 모으기"` · `"GATHER_SCATTER" == "모았다 흩기"` — 백엔드 rules.md 이름
- `build_query(facts)` 에 유형 한국어·영문 코드 모두 들어감

develop 에서 실패: TYPOLOGY_KO 에 두 키 없음 → `build_query` 가 한국어 이름을 못 붙여 쿼리에서 빠짐.
"""

from __future__ import annotations

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import TYPOLOGY_KO, build_query


def test_typology_ko_has_v2_keys() -> None:
    """룰 v2 typology_hint 6개 중 AI enum 에 있는 다섯: FAN_IN·FAN_OUT·CYCLE·SCATTER_GATHER·GATHER_SCATTER.

    FX_RELAY 는 enum 에 없어 제외 (INTENT ★A 1(b), 182·193).
    """
    assert TYPOLOGY_KO["FAN_IN"] == "집중 입금"
    assert TYPOLOGY_KO["FAN_OUT"] == "분산 송금"
    assert TYPOLOGY_KO["CYCLE"] == "순환 거래"
    assert TYPOLOGY_KO["SCATTER_GATHER"] == "흩었다 모으기"
    assert TYPOLOGY_KO["GATHER_SCATTER"] == "모았다 흩기"


def test_build_query_scatter_gather_includes_korean_and_code(mixed: Facts) -> None:
    """SCATTER_GATHER 질의 — 한국어 이름·영문 코드 모두 포함."""
    facts = mixed.model_copy(update={"typology": Typology.SCATTER_GATHER})
    q = build_query(facts)
    assert "흩었다 모으기" in q
    assert "SCATTER_GATHER" in q


def test_build_query_gather_scatter_includes_korean_and_code(mixed: Facts) -> None:
    """GATHER_SCATTER 질의 — 한국어 이름·영문 코드 모두 포함."""
    facts = mixed.model_copy(update={"typology": Typology.GATHER_SCATTER})
    q = build_query(facts)
    assert "모았다 흩기" in q
    assert "GATHER_SCATTER" in q
