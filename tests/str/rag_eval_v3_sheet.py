"""SCRUM-306 정답 확인 시트 ① — FAN_IN·FAN_OUT 후보 25행 (docs/str/10 SCRUM-306 "평가 세트 v3" 줄).

305 확인 시트와 같은 방식: 칸 = 기준서 04 와 같은 이름 · 행ID 미리 채움 · 등급 칸 `ID=`(ID = 유형·chunk_id 계산값) ·
본문은 DB 읽기 전용으로 가져와 리포 밖 시트에만. 행마다 DB 문서·쪽·태그와 본문 해시(= chunk_id)를 대조.

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_eval_v3_sheet export-fan --out <리포 밖 폴더>
    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_eval_v3_sheet apply-fan --sheet <돌아온 시트> --checker <이름> --checked-at YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import text
from tools.corpus_chunks import compute_content_hash
from tools.rag2_io import merged_note, out_dir_problem, place_problem, place_text

from tests.str import rag_calibration_sheet as cal
from tests.str.rag_eval_v3_candidates import CANDIDATES_FILE, FAN_TYPES, SOURCE_FAN

SHEET_NAME = "fan_grade_sheet.csv"
NOTE_NAME = "README_306.md"
# 확인자 폴더에 있어도 되는 파일 — ①②③ 단계 시트·안내만(03 5절 출력 줄). 다른 파일이 있으면 본문 쓰기 전 거절
CHECKER_FILES = frozenset({SHEET_NAME, NOTE_NAME, cal.GUIDE_NAME, cal.CRITERIA_NAME,
                           "disagree.csv", "consensus_grade_sheet.csv", "decided_grade_sheet.csv"})  # fmt: skip
ROW_PREFIX = {"FAN_IN": "FI", "FAN_OUT": "FO"}
Db = Mapping[str, tuple[str, int, str, list[str]]]  # chunk_id → (문서, 쪽, 본문, 태그)
NOTE_MARK_1 = "# SCRUM-306 확인 ① —"
NOTE = """# SCRUM-306 확인 ① — FAN_IN·FAN_OUT {rows}행 (청크 × 유형)

- 이번 확인: 개발용 평가 세트(SCRUM-306)의 FAN_IN·FAN_OUT 정답 후보. 질의·검색 결과·다른 사람 등급은 보지 않음.
- 기준: `checker_guide.md` 2·3·4·5절(등급 0·1·2, 판단 선은 "1 이상인가"). 1절의 holdout_v2·기준 맞추기 25행은
  SCRUM-305 때 것 — 이번에는 기준 맞추기 없음(305 에서 통과한 같은 잣대).
- 적는 법: `확인등급` 칸의 `ID=` 뒤에 0·1·2 하나(예 `FI-1a2b3c4d=2`). ID 부분·행 순서·다른 칸은 고치지 않음.
- 그 청크 `본문` 안 문장만 근거로. 원문 문장을 메모에 옮기지 않음 — 판단 이유는 짧게 한국어로, 애매하면 `?`.
- 끝나면 시트를 진희에게 돌려줌 — 반영(확인자·날짜)은 SCRUM-306.
"""


def note_problem(path: Path) -> str | None:
    """README 는 단계별 절을 덧붙이므로 내용 비교 대신 심볼릭 링크만 거절."""
    return f"{path.name}: 심볼릭 링크 — 거절" if path.is_symlink() else None


def grade_key(typology: str, chunk_id: str) -> str:
    return f"{ROW_PREFIX[typology]}-{chunk_id[:8]}"


def fan_rows(candidates: Mapping[str, list[dict[str, Any]]]) -> list[tuple[str, str, str, str, int]]:
    """(행ID, 유형, chunk_id, 문서, 쪽) — FAN 태그 출처 행만(합의·결정으로 더한 행 제외), 유형 → 문서 → 쪽 → chunk_id 순."""
    out = []
    for typ in FAN_TYPES:
        fan = (r for r in candidates[typ] if r.get("source", SOURCE_FAN) == SOURCE_FAN)
        items = sorted(fan, key=lambda r: (r["doc_id"], r["page"], r["chunk_id"]))
        out += [
            (f"{ROW_PREFIX[typ]}-{i:03d}", typ, r["chunk_id"], r["doc_id"], r["page"])
            for i, r in enumerate(items, 1)
        ]
    return out


def source_problems(rows: list[tuple[str, str, str, str, int]], db: Db) -> list[str]:
    """DB 원본과 다른 행 — 없음 · 문서·쪽 다름 · 그 유형 태그 없음 · 본문 해시 ≠ chunk_id."""
    bad = []
    for rid, typ, cid, doc, page in rows:
        src = db.get(cid)
        if (
            src is None
            or (src[0], src[1]) != (doc, page)
            or typ not in src[3]
            or compute_content_hash(doc, page, src[2]) != cid
        ):
            bad.append(rid)
    return bad


def export_fan(
    out_dir: Path, candidates: Mapping[str, list[dict]], db: Db, out: Callable[[str], None] = print
) -> int:
    if problem := out_dir_problem(out_dir, CHECKER_FILES):
        out(problem)
        return 2
    out_dir = Path(out_dir).expanduser().resolve()
    rows = fan_rows(candidates)
    bad = source_problems(rows, db)
    if bad:
        out(f"DB 원본과 다른 행: {bad[:10]}")
        return 1
    guides = {cal.GUIDE_NAME: cal.GUIDE_SOURCE.read_text(encoding="utf-8"),
              cal.CRITERIA_NAME: cal.CRITERIA_SOURCE.read_text(encoding="utf-8")}  # fmt: skip
    found = [p for p in (place_problem(out_dir / SHEET_NAME, None), *(place_problem(out_dir / n, t) for n, t in guides.items()),
                         note_problem(out_dir / NOTE_NAME)) if p]  # fmt: skip
    if found:
        out(f"{found[0]} — CSV 만들기 전 멈춤")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (out_dir / SHEET_NAME).open("x", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cal.COLUMNS)
            w.writeheader()
            for rid, typ, cid, doc, page in rows:
                cells = (rid, typ, cid, doc, page, db[cid][2], f"{grade_key(typ, cid)}=", "")
                w.writerow(dict(zip(cal.COLUMNS, cells, strict=True)))
    except FileExistsError:
        out(f"{SHEET_NAME} 이 이미 있음 — 확인 중인 시트를 덮지 않음")
        return 1
    for name, guide in guides.items():
        place_text(out_dir / name, guide)
    note = out_dir / NOTE_NAME
    note.write_text(merged_note(note, NOTE.format(rows=len(rows)), NOTE_MARK_1), encoding="utf-8")
    counts = {t: sum(1 for r in rows if r[1] == t) for t in FAN_TYPES}
    out(f"rows={len(rows)} " + " ".join(f"{t}={n}" for t, n in counts.items()) + f" → {SHEET_NAME}")
    return 0


def read_db(chunk_ids: list[str]) -> dict[str, tuple[str, int, str, list[str]]]:
    from tests.str.rag_baseline_live_db import readonly_session

    sql = text(
        "SELECT chunk_id, doc_id, page, text, typologies FROM ai.reference_chunks WHERE chunk_id = ANY(:ids)"
    )
    with readonly_session() as session:
        return {
            r.chunk_id: (r.doc_id, r.page, r.text, list(r.typologies))
            for r in session.execute(sql, {"ids": chunk_ids})
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SCRUM-306 정답 확인 시트 ① FAN 25행")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export-fan").add_argument("--out", type=Path, required=True)
    back = sub.add_parser("apply-fan")
    back.add_argument("--sheet", type=Path, required=True)
    back.add_argument("--checker", required=True)
    back.add_argument("--checked-at", required=True)
    args = parser.parse_args(argv)
    candidates = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))["candidates"]
    ids = [c for _, _, c, _, _ in fan_rows(candidates)]
    if args.cmd == "apply-fan":
        from tests.str.rag_eval_v3_apply import apply_fan

        return apply_fan(args.sheet, args.checker, args.checked_at, read_db(ids))
    return export_fan(args.out, candidates, read_db(ids))


if __name__ == "__main__":
    raise SystemExit(main())
