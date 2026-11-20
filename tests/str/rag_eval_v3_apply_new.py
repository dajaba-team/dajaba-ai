"""SCRUM-306 확인 ②·③ 반영 — 합의 새 행·결정 행 등급 시트 둘 → `answer_candidates.json` 에 더함 (docs/str/10 "평가 세트 v3").

내보낸 행은 받은 A·B·결정 시트와 지금 후보 파일로 다시 계산해 대조(행ID·유형·chunk_id·문서·쪽 · DB 본문 · 등급 칸 ID).
두 시트 모두 통과해야 반영 — 등급 ≥ 1 만 후보에 더하고 0·1·2 기록은 전부 `consensus_grades` 에(적용 제안 입력).
`db_tagged` = 같은 DB 조회의 `typologies` — 표본 청크에 동결(무태그) 뒤 태그가 생겼으면 반영 전체 중단.
잠금·원자 교체는 `rag_eval_v3_store`, 순서는 ①(`apply-fan`) → ②③(이 파일). 이미 반영됐으면 거절. 출력은 개수만.

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_eval_v3_apply_new apply A B decided C_returned D_returned --checker 이름 --checked-at YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.rag2_agreement import expected_rows
from tools.rag2_consensus import disagreement_rows, load_decisions, load_pair

from tests.str.rag_eval_v3_apply import CHECKED_AT as FAN_AT
from tests.str.rag_eval_v3_apply import CHECKED_BY as FAN_DONE
from tests.str.rag_eval_v3_apply import bad_args, check_grades
from tests.str.rag_eval_v3_candidates import CANDIDATES_FILE, FAN_TYPES, GRADE_MIN, SOURCE_FAN
from tests.str.rag_eval_v3_decided import decided_new
from tests.str.rag_eval_v3_round2 import agreed_new, grade_key, numbered, text_problems
from tests.str.rag_eval_v3_sheet import Db, read_db
from tests.str.rag_eval_v3_store import Busy, atomic_write, locked

SOURCE_AGREED = "합의_태그"
SOURCE_DECIDED = "결정_태그"
CHECKED_BY = "consensus_checked_by"
CHECKED_AT = "consensus_checked_at"
GRADES_KEY = "consensus_grades"
Graded = dict[tuple[str, str], tuple[str, int]]  # (유형, chunk_id) → (출처, 등급)


def _row(
    cid: str, where: tuple[str, int], pos: int, source: str, grade: int, db_tagged: bool
) -> dict[str, Any]:
    doc, page = where
    return {"chunk_id": cid, "doc_id": doc, "page": page, "pos": pos, "source": source, "grade": grade,
            "db_tagged": db_tagged}  # fmt: skip


def graded_rows(
    sheets: list[Path], cands: dict, read: Callable[[list[str]], Db]
) -> tuple[Graded, dict, Db, list[str]]:
    """(등급, chunk_id → (문서, 쪽), DB, 문제 목록) — 내보낸 행은 지금 후보 파일로 다시 계산."""
    a, b = load_pair(sheets[0], sheets[1])
    groups = {SOURCE_AGREED: (sheets[3], numbered(agreed_new(a, b, cands), "C")),
              SOURCE_DECIDED: (sheets[4], numbered(decided_new(load_decisions(sheets[2], disagreement_rows(a, b)), cands), "D"))}  # fmt: skip
    where = {r[2]: (r[3], r[4]) for _, rows in groups.values() for r in rows}
    sample = [r["chunk_id"] for r in expected_rows()]
    db = read(sorted(set(sample) | set(where) | {r["chunk_id"] for rs in cands.values() for r in rs}))
    problems = [f"DB 원본과 다른 청크: {bad}" for bad in [text_problems(where, db)] if bad]
    problems += db_problems(sample, cands, db)
    graded: Graded = {}
    for source, (path, rows) in groups.items():
        grades, found = check_grades(path, rows, db, grade_key)
        problems += found
        graded |= {key: (source, g) for key, g in grades.items()}
    return graded, where, db, problems


def db_problems(sample: list[str], cands: dict, db: Db) -> list[str]:
    """같은 DB 조회로 — 표본 80 전체가 있고 무태그(동결 상태) · 기존 후보마다 그 유형 DB 태그 = db_tagged."""
    gone = [c[:8] for c in sample if c not in db]
    tagged = [c[:8] for c in sample if c in db and db[c][3]]
    drift = [f"{t}:{r['chunk_id'][:8]}" for t, rs in cands.items() for r in rs
             if r["chunk_id"] not in db or (t in db[r["chunk_id"]][3]) is not r["db_tagged"]]  # fmt: skip
    found = {"DB 에 없는 표본 청크": gone, "표본 동결(무태그) 뒤 DB 태그가 생긴 청크": tagged,
             "기존 후보 db_tagged ≠ DB 태그": drift}  # fmt: skip
    return [f"{msg}: {bad[:10]}" for msg, bad in found.items() if bad]


def _order_problem(doc: dict) -> str | None:
    fan = [r for t in FAN_TYPES for r in doc["candidates"][t] if r["source"] == SOURCE_FAN]
    if FAN_DONE not in doc or FAN_AT not in doc or any(r["grade"] not in (0, 1, 2) for r in fan):
        return "① FAN 등급 반영이 끝나지 않음(확인자·날짜·FAN 행 전체 0·1·2) — 순서는 ① → ②③"
    cands = doc["candidates"]
    if CHECKED_BY in doc or any(
        r["source"] in (SOURCE_AGREED, SOURCE_DECIDED) for rs in cands.values() for r in rs
    ):
        return "합의·결정 행이 이미 반영됨 — 덮지 않음"
    return None


def apply(sheets: list[Path], checker: str, checked_at: str, read: Callable[[list[str]], Db],
          target: Path = CANDIDATES_FILE, out: Callable[[str], None] = print) -> int:  # fmt: skip
    """sheets = [A, B, 결정, 합의 새 행 등급, 결정 행 등급]."""
    bad = bad_args(checker, checked_at)
    if bad:
        out(bad)
        return 2
    try:
        with locked(target):
            return _apply_locked(sheets, checker.strip(), checked_at, read, target, out)
    except Busy as exc:
        out(str(exc))
        return 1


def _apply_locked(sheets: list[Path], checker: str, checked_at: str, read: Callable[[list[str]], Db],
                  target: Path, out: Callable[[str], None]) -> int:  # fmt: skip
    doc = json.loads(target.read_text(encoding="utf-8"))  # 잠금 안에서 최신 상태
    if order := _order_problem(doc):
        out(f"{target.name}: {order}")
        return 1
    cands = doc["candidates"]
    graded, where, db, problems = graded_rows(sheets, cands, read)
    if problems:
        out("\n".join([f"반영 안 함 — 틀린 곳 {len(problems)}:", *problems[:10]]))
        return 1
    pos = {r["chunk_id"]: int(r["쪽안_청크순번"]) for r in expected_rows()}
    added = [(typ, cid, src) for (typ, cid), (src, g) in graded.items() if g >= GRADE_MIN]
    for typ, cid, src in added:
        cands[typ].append(_row(cid, where[cid], pos[cid], src, graded[(typ, cid)][1], typ in db[cid][3]))
    for typ in cands:
        cands[typ].sort(key=lambda r: (r["doc_id"], r["page"], r["pos"]))
    doc[GRADES_KEY] = [{"typology": t, "chunk_id": c, "source": s, "grade": g}
                       for (t, c), (s, g) in sorted(graded.items())]  # fmt: skip
    doc["consensus_pending"], doc[CHECKED_BY], doc[CHECKED_AT] = False, checker, checked_at
    atomic_write(target, doc)
    for src in (SOURCE_AGREED, SOURCE_DECIDED):
        got = [t for t, _, s in added if s == src]
        seen = sum(s == src for s, _ in graded.values())
        out(
            f"{src}: graded={seen} added={len(got)} "
            + " ".join(f"{t}={got.count(t)}" for t in sorted(set(got)))
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SCRUM-306 확인 ②·③ 등급 반영")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply")
    for name in ("a", "b", "decided", "consensus_sheet", "decided_sheet"):
        p.add_argument(name, type=Path)
    p.add_argument("--checker", required=True)
    p.add_argument("--checked-at", required=True)
    args = parser.parse_args(argv)
    sheets = [args.a, args.b, args.decided, args.consensus_sheet, args.decided_sheet]
    return apply(sheets, args.checker, args.checked_at, read_db)


if __name__ == "__main__":
    raise SystemExit(main())
