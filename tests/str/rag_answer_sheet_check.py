"""SCRUM-275-2 정답 확인 시트 점검 (docs/str/10 "확인 시트"). 순수 — 틀린 곳 목록을 돌려줌(비면 통과).

- `draft_problems`: 초벌이 전체인지 — export·apply 둘 다(limit 없음 · 3유형 · DB 청크 전부 · 중복 없음 · 등급 0/1/2 · 위치)
- `check`: 확인된 시트가 그 초벌·그 본문 위에서 나온 것인지 — 행·chunk_id·LLM 등급·유형·문서·쪽·순번·본문·초벌지문
  대조 + 확인등급 0/1/2. 본문 비교 전 정규화: CRLF→LF · 앞뒤 공백 무시 · 원문이 `'` 로 시작하지 않으면 맨 앞 `'` 하나
  제거(수식 방지로 붙인 것). 오류 = `SheetError(종류, CSV 행 번호(머리글 = 1), row_id, 설명)` — 본문은 안 담음.
- `summarize`: `apply --check-only` 용 종류별 묶음. 종류·종료 코드는 `SheetError.kind` 로만 정함(메시지·row_id 글자를
  찾지 않음 — 추가 검토 2: row_id 를 "확인등급 빈 칸"으로 바꿔 분류를 속이는 길을 막음)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tests.str.rag_answer_sheet import GRADES, ROW_ID_CHARS, TYPOLOGY_ORDER, expected_items, row_id

_FIRST_DATA_ROW = 2  # CSV 머리글이 1행
BLANK = "확인등급 빈 칸"
BAD_GRADE = "확인등급 이상"
BODY = "본문 다름"
POSITION = "유형/위치 다름"
IDENTITY = "chunk_id/LLM등급 다름"
FINGERPRINT = "지문 다름"
MISSING = "행 빠짐"
DUPLICATE = "행 중복"
UNKNOWN = "초벌에 없는 행"
FORMAT = "시트 형식"  # 머리글·칸 수·빈 시트(rag_answer_sheet.read_csv)
_KIND_OF_COLUMN = {"chunk_id": IDENTITY, "LLM등급": IDENTITY, "유형": POSITION, "문서": POSITION, "쪽": POSITION,
                   "쪽안순번": POSITION, "초벌지문": FINGERPRINT}  # fmt: skip


@dataclass(frozen=True)
class SheetError:
    kind: str
    row: int | None  # CSV 행 번호(머리글 = 1), 행이 없는 오류(빠짐·초벌)는 None
    row_id: str
    detail: str

    def label(self) -> str:
        return f"행 {self.row} ({self.row_id})" if self.row is not None else self.row_id or "-"

    def __str__(self) -> str:
        return f"{self.label()}: {self.detail}"


def draft_problems(draft: dict[str, Any], db: dict[str, tuple[str, int]]) -> list[str]:
    """db = {chunk_id: (doc_id, page)} — DB `ai.reference_chunks` 전부."""
    if draft.get("limit") is not None:
        return [f"초벌이 limit={draft['limit']} 시험 실행 — 전체 초벌로"]
    graded = draft.get("graded_by_typology")
    if not isinstance(graded, dict):
        return ["초벌에 graded_by_typology(0 등급 포함 전 행) 없음 — 초벌을 다시"]
    problems = (
        [] if draft.get("chunks") == len(db) else [f"초벌 청크 수 {draft.get('chunks')} ≠ DB 행 수 {len(db)}"]
    )
    for typology in TYPOLOGY_ORDER:
        if typology not in graded:
            problems.append(f"{typology}: 초벌에 없음")
            continue
        problems += _typology_problems(typology, graded[typology], db)
    return problems


def _typology_problems(
    typology: str, items: list[dict[str, Any]], db: dict[str, tuple[str, int]]
) -> list[str]:
    ids = [i["chunk_id"] for i in items]
    problems = []
    if len(ids) != len(set(ids)):
        problems.append(f"{typology}: 같은 청크가 두 번 이상")
    if set(ids) != set(db):
        problems.append(f"{typology}: 초벌 청크 집합이 DB 와 다름(초벌 {len(set(ids))} · DB {len(db)})")
    if any(i.get("grade") not in (0, 1, 2) for i in items):
        problems.append(f"{typology}: 등급이 0·1·2 아닌 항목")
    moved = [
        c[:ROW_ID_CHARS]
        for c, i in zip(ids, items, strict=True)
        if c in db and db[c] != (i["doc_id"], i["page"])
    ]
    if moved:
        problems.append(f"{typology}: 위치(doc_id·page)가 DB 와 다른 청크 {len(moved)} — {moved[:5]}")
    return problems


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def body_matches(sheet_text: str, original: str) -> bool:
    body, orig = _norm(sheet_text), _norm(original)
    if not orig.startswith("'") and body.startswith("'"):
        body = body[1:]
    return body == orig


def _cell(r: dict[str, Any], key: str) -> str:
    """CSV 에서 읽은 글자와 메모리 위 값(정수·None)을 같은 기준으로."""
    value = r.get(key)
    return "" if value is None else str(value).strip()


def _row_errors(
    r: dict[str, str], typology: str, item: dict[str, Any], original: str, fp: str
) -> list[tuple[str, str]]:
    expected = {
        "chunk_id": item["chunk_id"], "LLM등급": str(item["grade"]), "유형": typology, "문서": item["doc_id"],
        "쪽": str(item["page"]), "쪽안순번": "" if item["pos"] is None else str(item["pos"]), "초벌지문": fp,
    }  # fmt: skip
    errors = [
        (_KIND_OF_COLUMN[k], f"{k} 이 초벌과 다름") for k, want in expected.items() if _cell(r, k) != want
    ]
    if not body_matches(r.get("본문") or "", original):
        errors.append((BODY, "본문 이 그 청크 원문과 다름"))
    grade = _cell(r, "확인등급")
    if grade == "":
        errors.append((BLANK, "확인등급 빈 칸"))
    elif grade not in GRADES:
        errors.append((BAD_GRADE, "확인등급 이 0·1·2 아님"))
    return errors


def check(
    records: list[dict[str, str]], draft: dict[str, Any], texts: dict[str, str], fp: str
) -> list[SheetError]:
    expected = {row_id(t, i["chunk_id"]): (t, i) for t, i in expected_items(draft)}
    errors: list[SheetError] = []
    seen: set[str] = set()
    for n, r in enumerate(records, _FIRST_DATA_ROW):
        rid = _cell(r, "row_id")
        if rid in seen:
            errors.append(SheetError(DUPLICATE, n, rid, "같은 행이 두 번"))
            continue
        seen.add(rid)
        if rid not in expected:
            errors.append(SheetError(UNKNOWN, n, rid, "초벌에 없는 행"))
            continue
        typology, item = expected[rid]
        found = _row_errors(r, typology, item, texts.get(item["chunk_id"], ""), fp)
        errors += [SheetError(kind, n, rid, detail) for kind, detail in found]
    errors += [SheetError(MISSING, None, rid, "시트에서 빠짐") for rid in expected if rid not in seen]
    return errors


def summarize(errors: list[SheetError]) -> dict[str, list[str]]:
    """오류 종류 → 그 종류가 난 행 표시. 종류는 `SheetError.kind` 그대로(글자 검색 없음)."""
    out: dict[str, list[str]] = {}
    for error in errors:
        out.setdefault(error.kind, []).append(error.label())
    return out
