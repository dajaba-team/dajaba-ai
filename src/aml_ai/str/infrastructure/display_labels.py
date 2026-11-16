"""표기 사전 읽기 — `contracts/display_labels_v1.json` (docs/str/05 narrative_v4 "표기 사전").

domain 은 파일을 만지지 않는다 — 여기서 dict 로 읽어 넘긴다(01). v4 생성기를 만들 때 한 번 읽음.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from aml_ai.str.domain.constants_v4 import DISPLAY_LABELS_VERSION, LABEL_FIELDS
from aml_ai.str.domain.display_labels_check import Labels

LABELS_PATH = Path(__file__).resolve().parents[4] / "contracts" / "display_labels_v1.json"


@lru_cache(maxsize=1)
def load_display_labels(path: Path = LABELS_PATH) -> Labels:
    """사전 dict. 버전·칸 이름이 다르면 ValueError(기동이 아니라 v4 생성기 생성 때)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != DISPLAY_LABELS_VERSION:
        raise ValueError("display labels version mismatch")
    missing = [f for f in LABEL_FIELDS if not isinstance(data.get(f), dict)]
    if missing:
        raise ValueError(f"display labels missing fields: {missing}")
    return {f: dict(data[f]) for f in LABEL_FIELDS}
