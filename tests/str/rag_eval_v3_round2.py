"""SCRUM-306 확인 ② — 불일치 결정 목록(`본문` 칸) + 합의 새 행 등급 시트 (docs/str/10 "평가 세트 v3" · rag2/03 5절).

합의 새 행 = 두 사람이 같은 태그를 붙였고 지금 `answer_candidates.json` 에 없는 (유형, 청크). 정답 파일엔 안 넣음.
본문은 DB 읽기 전용 → 행마다 DB 문서·쪽·본문 해시(= chunk_id) 대조가 맞을 때만, 리포 밖 폴더에만. 출력은 개수만.

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_eval_v3_round2 export A.csv B.csv --out <리포 밖 폴더>
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tools.corpus_chunks import compute_content_hash
from tools.rag2_agreement import Tagged, expected_rows
from tools.rag2_consensus import disagreement_rows, load_pair, write_disagreement
from tools.rag2_io import merged_note, out_dir_problem, place_problem
from tools.rag2_proposal import SHEET_TO_TYPE

from tests.str import rag_calibration_sheet as cal
from tests.str.rag_eval_v3_candidates import CANDIDATES_FILE
from tests.str.rag_eval_v3_sheet import CHECKER_FILES, NOTE_NAME, Db, note_problem, read_db

DISAGREE_NAME = "disagree.csv"
CONSENSUS_SHEET = "consensus_grade_sheet.csv"
KEY_PREFIX = {"FAN_IN": "FI", "FAN_OUT": "FO", "CYCLE": "CY", "SCATTER_GATHER": "SG", "GATHER_SCATTER": "GS"}
ROW_ID = "{group}-{prefix}-{n:03d}"  # C = 합의 새 행 · D = 결정 행
NOTE_MARK = "# SCRUM-306 확인 ②"
NOTE = """
{mark} — 불일치 결정 {disagree}행 + 합의 새 행 등급 {rows}행

**가. 불일치 결정 — `{disagree_name}`** (두 사람 A·B 가 다르게 붙인 행, 이름 대신 A·B)
- `본문` 칸은 그 청크 원문(DB) — 그 안 문장만 근거로. 기준은 `00_tagging_criteria.md` 만.
- 행마다 칸 셋을 다 채움. 다른 칸·행 순서는 고치지 않음.
  - `결정태그`: `FAN_IN`·`FAN_OUT`·`CYCLE`·`SG`·`GS` 중 해당하는 것 전부(여러 개면 `;` 로, 예 `FAN_IN;FAN_OUT`), 없으면 `없음`.
  - `근거줄`: 어느 기준 줄에 따라 정했는지 한 줄(예 `00 조건 2`) — 원문 문장은 옮기지 않음.
  - `이유분류`: `기준 모호`·`용어 오해`·`단순 실수` 중 하나(두 사람이 왜 갈렸는지).
- 다수결 아님(두 명뿐) — 확인자 결정이 합의 태그.
- 결정태그가 붙는 행의 등급(0·1·2)은 이 시트가 돌아온 뒤 작은 시트로 따로 보냄.

**나. 합의 새 행 등급 — `{sheet_name}`** (두 사람이 같은 태그를 붙였고 아직 정답 후보에 없는 청크 × 유형)
- 적는 법은 확인 ① 과 같음: `확인등급` 칸의 `ID=` 뒤에 0·1·2 하나(`checker_guide.md` 2·3·4·5절, 판단 선은 "1 이상인가").
- 두 사람 태그·근거는 보여 주지 않음 — 본문만 보고 등급.
"""


def agreed_new(
    a: list[Tagged], b: list[Tagged], candidates: Mapping[str, list[dict]]
) -> list[tuple[str, str, str, int]]:
    """(유형, chunk_id, 문서, 쪽) — 같은 태그 · 후보에 없는 것만, 유형 → 문서 → 쪽 → chunk_id 순."""
    have = {(t, r["chunk_id"]) for t, rows in candidates.items() for r in rows}
    base = {r["chunk_id"]: r for r in expected_rows()}
    out = []
    for x, y in zip(a, b, strict=True):
        if x.tags and x.tags == y.tags:
            out += [(SHEET_TO_TYPE[t], x.chunk_id, base[x.chunk_id]["doc_id"], int(base[x.chunk_id]["page"]))
                    for t in x.tags if (SHEET_TO_TYPE[t], x.chunk_id) not in have]  # fmt: skip
    order = list(KEY_PREFIX)
    return sorted(out, key=lambda r: (order.index(r[0]), r[2], r[3], r[1]))


def text_problems(where: Mapping[str, tuple[str, int]], db: Db) -> list[str]:
    """chunk_id → (문서, 쪽) 중 DB 에 없거나 문서·쪽이 다르거나 본문 해시 ≠ chunk_id 인 것(앞 8자)."""
    return [cid[:8] for cid, (doc, page) in where.items()
            if cid not in db or db[cid][:2] != (doc, page) or compute_content_hash(doc, page, db[cid][2]) != cid]  # fmt: skip


def grade_key(typ: str, cid: str) -> str:
    return f"{KEY_PREFIX[typ]}-{cid[:8]}"


def numbered(rows: list[tuple[str, str, str, int]], group: str) -> list[tuple[str, str, str, str, int]]:
    """(행ID, 유형, chunk_id, 문서, 쪽) — 행ID = 묶음 글자 · 유형 · 유형마다 001 부터."""
    counts: dict[str, int] = {}
    out = []
    for typ, cid, doc, page in rows:
        counts[typ] = counts.get(typ, 0) + 1
        out.append((ROW_ID.format(group=group, prefix=KEY_PREFIX[typ], n=counts[typ]), typ, cid, doc, page))
    return out


def write_grade_sheet(path: Path, rows: list[tuple[str, str, str, int]], db: Db, group: str = "C") -> None:
    with path.open("x", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cal.COLUMNS)
        w.writeheader()
        for rid, typ, cid, doc, page in numbered(rows, group):
            cells = (rid, typ, cid, doc, page, db[cid][2], f"{grade_key(typ, cid)}=", "")
            w.writerow(dict(zip(cal.COLUMNS, cells, strict=True)))


def export(pair: tuple[Path, Path], out_dir: Path, candidates: Mapping[str, list[dict]],
           read: Callable[[list[str]], Db], out: Callable[[str], None] = print) -> int:  # fmt: skip
    if problem := out_dir_problem(out_dir, CHECKER_FILES):
        out(problem)
        return 2
    out_dir = Path(out_dir).expanduser().resolve()
    found = [p for p in (place_problem(out_dir / DISAGREE_NAME, None), place_problem(out_dir / CONSENSUS_SHEET, None),
                         note_problem(out_dir / NOTE_NAME)) if p]  # fmt: skip
    if found:
        out(f"{found[0]} — CSV 만들기 전 멈춤")
        return 1
    a, b = load_pair(*pair)
    listed, new = disagreement_rows(a, b), agreed_new(a, b, candidates)
    where = {r["chunk_id"]: (r["doc_id"], int(r["page"])) for r in listed} | {c: (d, p) for _, c, d, p in new}
    db = read(list(where))
    bad = text_problems(where, db)
    if bad:
        out(f"DB 원본과 다른 청크: {bad[:10]}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    write_disagreement(disagreement_rows(a, b, {c: db[c][2] for c in where}), out_dir / DISAGREE_NAME)
    write_grade_sheet(out_dir / CONSENSUS_SHEET, new, db)
    note = out_dir / NOTE_NAME
    section = NOTE.format(mark=NOTE_MARK, disagree=len(listed), rows=len(new),
                          disagree_name=DISAGREE_NAME, sheet_name=CONSENSUS_SHEET)  # fmt: skip
    note.write_text(merged_note(note, section, NOTE_MARK), encoding="utf-8")
    out(f"disagree={len(listed)} → {DISAGREE_NAME} · consensus_new={len(new)} → {CONSENSUS_SHEET}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SCRUM-306 확인 ② 불일치 결정 + 합의 새 행 등급")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    candidates: dict[str, Any] = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))["candidates"]
    return export((args.a, args.b), args.out, candidates, read_db)


if __name__ == "__main__":
    raise SystemExit(main())
