"""SCRUM-275-2 시트 테스트 공용 — 가짜 초벌·DB·본문·질의(CYCLE 3 · FAN_IN LLM≥1 1 → 시트 4행). DB·LLM 0."""

from __future__ import annotations

from tests.str import rag_answer_sheet as sheet

C1, C2, C3 = "c1" * 32, "c2" * 32, "c3" * 32
_C = [(C1, "doc-a", 3, 1, 0), (C2, "doc-a", 3, 2, 2), (C3, "doc-b", 1, 1, 1)]
_F = [(C1, "doc-a", 3, 1, 0), (C2, "doc-a", 3, 2, 2), (C3, "doc-b", 1, 1, 0)]
FP = sheet.fingerprint(b"draft-bytes", b"manifest-bytes")
DB = {C1: ("doc-a", 3), C2: ("doc-a", 3), C3: ("doc-b", 1)}
TEXTS = {C1: "첫 줄\n둘째 줄", C2: "=SUM(A1) 수식처럼 시작", C3: "plain english body"}
QUERIES = [
    {"id": "H01", "typology": "CYCLE", "expect_empty": False},
    {"id": "H02", "typology": "FAN_IN", "expect_empty": False},
    {"id": "H03", "typology": "FAN_OUT", "expect_empty": False},
    {"id": "H04", "typology": "SCATTER_GATHER", "expect_empty": True},
]


def _items(rows: list[tuple]) -> list[dict]:
    return [{"chunk_id": c, "doc_id": d, "page": p, "pos": s, "grade": g} for c, d, p, s, g in rows]


def draft() -> dict:
    graded = {"CYCLE": _items(_C), "FAN_IN": _items(_F), "FAN_OUT": _items([(*r[:4], 0) for r in _F])}
    return {
        "prompt_version": "rag_answer_v1",
        "prompt_sha256": "ab" * 32,
        "chunks": 3,
        "limit": None,
        "by_typology": {t: [i for i in items if i["grade"] > 0] for t, items in graded.items()},
        "graded_by_typology": graded,
    }


def filled(grade_by_row: dict[str, str] | None = None, texts: dict[str, str] | None = None) -> list[dict]:
    """확인자가 다 채운 시트(기본 = LLM 등급 그대로)."""
    records = sheet.sheet_records(draft(), texts or TEXTS, FP)
    for r in records:
        r["확인등급"] = (grade_by_row or {}).get(r["row_id"], r["LLM등급"])
    return records


def rid(typology: str, chunk_id: str) -> str:
    return sheet.row_id(typology, chunk_id)
