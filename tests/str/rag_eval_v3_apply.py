"""SCRUM-306 정답 확인 시트 ① 반영 — 돌아온 FAN 25행 시트 → `answer_candidates.json` FAN 행 `grade` (docs/str/10 "평가 세트 v3").

행·유형·chunk_id·문서·쪽 = 내보낸 순서 그대로 · 본문 = DB 원본 · 등급 칸 = `ID=0|1|2`(ID 는 유형·chunk_id 계산값).
하나라도 틀리면 반영 0. 이미 반영된 파일은 덮지 않음. 출력은 행ID·개수만(본문·메모 0).
잠금·원자 교체는 `rag_eval_v3_store` — 순서는 ①(이 파일) → ②③(`rag_eval_v3_apply_new`), ① 은 `FAN_태그` 출처 행만.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from tools.rag2_io import SheetError, read_rows

from tests.str import rag_calibration_sheet as cal
from tests.str.rag_answer_sheet_check import body_matches
from tests.str.rag_eval_v3_candidates import CANDIDATES_FILE, FAN_TYPES, SOURCE_FAN
from tests.str.rag_eval_v3_sheet import Db, fan_rows, grade_key, source_problems
from tests.str.rag_eval_v3_store import Busy, atomic_write, locked

GRADE_CELL = re.compile(r"(?P<key>[A-Z]{2}-[0-9a-f]{8})=(?P<grade>[012])")
CHECKED_BY = "fan_checked_by"
CHECKED_AT = "fan_checked_at"
LATER_STAGE = "consensus_checked_by"  # ②③ 반영 표식 — 있으면 ① 은 순서가 어긋난 것


Row = tuple[str, str, str, str, int]  # (행ID, 유형, chunk_id, 문서, 쪽)


def read_grades(
    path: Path, candidates: Mapping[str, list[dict]], db: Db
) -> tuple[dict[tuple[str, str], int], list[str]]:
    """돌아온 FAN 시트 → ({(유형, chunk_id): 등급}, 문제 목록)."""
    want = fan_rows(candidates)
    grades, problems = check_grades(path, want, db, grade_key)
    return grades, [f"DB 원본과 다른 행: {bad}" for bad in [source_problems(want, db)] if bad] + problems


def check_grades(
    path: Path, want: list[Row], db: Db, key_of: Callable[[str, str], str]
) -> tuple[dict[tuple[str, str], int], list[str]]:
    """돌아온 시트를 내보낸 행(want)·DB 본문·등급 칸 `ID=0|1|2`(ID = key_of(유형, chunk_id))와 대조."""
    try:
        fields, got = read_rows(path)  # 셀 수 = 머리글(쉼표로 칸이 밀린 행 거절)
    except SheetError as exc:
        return {}, [str(exc)]
    if fields != cal.COLUMNS:
        return {}, [f"{path.name}: 머리글이 다름"]
    problems = []
    if len(got) != len(want):
        problems.append(f"행 수 {len(got)} ≠ {len(want)}")
    grades = {}
    for r, (rid, typ, cid, doc, page) in zip(got, want, strict=False):
        if (r["행"], r["유형"], r["chunk_id"], r["문서"], r["쪽"].strip()) != (rid, typ, cid, doc, str(page)):
            problems.append(f"{rid}: 행·유형·chunk_id·문서·쪽이 내보낸 시트와 다름(순서·값)")
            continue
        if cid in db and not body_matches(r["본문"], db[cid][2]):
            problems.append(f"{rid}: 본문이 DB 원본과 다름")
        m = GRADE_CELL.fullmatch(r["확인등급"].strip())
        if m is None or m["key"] != key_of(typ, cid):
            problems.append(f"{rid}: 등급 칸은 `{key_of(typ, cid)}=0|1|2`")
            continue
        grades[(typ, cid)] = int(m["grade"])
    return grades, problems


def _fan(doc: Mapping[str, Any], typ: str) -> list[dict]:
    return [r for r in doc["candidates"][typ] if r.get("source", SOURCE_FAN) == SOURCE_FAN]


def applied(doc: Mapping[str, Any]) -> bool:
    return CHECKED_BY in doc or any(r["grade"] is not None for t in FAN_TYPES for r in _fan(doc, t))


def bad_args(checker: str, checked_at: str) -> str | None:
    try:
        date.fromisoformat(checked_at)
    except ValueError:
        return "--checked-at 은 YYYY-MM-DD"
    return None if checker.strip() else "--checker 비어 있음"


def apply_fan(
    sheet: Path, checker: str, checked_at: str, db: Db,
    target: Path = CANDIDATES_FILE, out: Callable[[str], None] = print,
) -> int:  # fmt: skip
    bad = bad_args(checker, checked_at)
    if bad:
        out(bad)
        return 2
    try:
        with locked(target):
            return _apply_locked(sheet, checker.strip(), checked_at, db, target, out)
    except Busy as exc:
        out(str(exc))
        return 1


def _apply_locked(
    sheet: Path, checker: str, checked_at: str, db: Db, target: Path, out: Callable[[str], None]
) -> int:
    doc = json.loads(target.read_text(encoding="utf-8"))  # 잠금 안에서 최신 상태
    if LATER_STAGE in doc:
        out(f"{target.name}: ②③ 반영이 이미 있음 — 순서는 ① → ②③")
        return 1
    if applied(doc):
        out(f"{target.name}: FAN 등급이 이미 반영됨 — 덮지 않음")
        return 1
    grades, problems = read_grades(sheet, doc["candidates"], db)
    if problems:
        out("\n".join([f"반영 안 함 — 틀린 곳 {len(problems)}:", *problems[:10]]))
        return 1
    for typ in FAN_TYPES:
        for r in _fan(doc, typ):
            r["grade"] = grades[(typ, r["chunk_id"])]
    doc[CHECKED_BY], doc[CHECKED_AT] = checker, checked_at
    atomic_write(target, doc)
    for typ in FAN_TYPES:
        g = [grades[(typ, r["chunk_id"])] for r in _fan(doc, typ)]
        out(f"{typ}: rows={len(g)} " + " ".join(f"{n}={g.count(n)}" for n in (0, 1, 2)))
    return 0
