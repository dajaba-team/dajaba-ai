"""종합의견 첫 문장 — 유형별, 필수 (docs/str/05 narrative_v4 "종합의견 카탈로그"). 순수."""

from __future__ import annotations

from aml_ai.str.domain.catalog_types import CatalogItem
from aml_ai.str.domain.display_format import topic

_REVIEW = "자금세탁 의심 여부의 검토가 필요함."
_REVIEW_ALT = "자금세탁 의심 여부를 검토할 필요가 있음."
_MORE = "자금세탁 의심 여부는 추가 자료로 검토할 필요가 있음."


def _head(code: str, name: str, target: str) -> CatalogItem:
    return CatalogItem(
        f"O-HEAD-{code}",
        0,
        (
            f"{name} 유형으로 분류된 {target}에 대해 {_REVIEW}",
            f"{topic(target)} {name} 유형으로 분류되어 {_REVIEW_ALT}",
        ),
        ("typology",),
        required=True,
    )


HEADS: dict[str, CatalogItem] = {
    "FAN_IN": _head("FAN_IN", "자금 집중", "위 입금"),
    "FAN_OUT": _head("FAN_OUT", "자금 분산", "위 출금"),
    "FAN_IN_NO_FLOW": _head("FAN_IN", "자금 집중", "위 거래"),  # 입금 0 — 같은 id, 대상 낱말만 다름
    "FAN_OUT_NO_FLOW": _head("FAN_OUT", "자금 분산", "위 거래"),  # 출금 0
    "CYCLE": _head("CYCLE", "자금 순환", "위 거래"),
    "OTHER": _head("OTHER", "{typology}", "위 거래"),
    "NONE": CatalogItem(
        "O-HEAD-NONE",
        0,
        (f"분류된 유형이 없는 거래임. {_MORE}", f"유형 분류가 없는 거래임. {_MORE}"),
        (),
        required=True,
    ),
}
