"""SCRUM-306 확인 ③ — 결정으로 태그가 붙은 청크 × 유형 중 후보에 없는 것의 등급 시트 (docs/str/10 "평가 세트 v3").

결정 시트(`disagree.csv` 돌아온 것)는 `rag2_consensus.load_decisions` 검사를 통과해야 함. 정답 파일엔 안 넣음.
본문은 DB 읽기 전용 → 문서·쪽·본문 해시(= chunk_id) 대조가 맞을 때만, 리포 밖에만. 출력은 개수만.

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_eval_v3_decided export A.csv B.csv decided.csv --out <리포 밖 폴더>
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from tools.rag2_agreement import expected_rows
from tools.rag2_consensus import disagreement_rows, load_decisions, load_pair
from tools.rag2_io import out_dir_problem, place_problem

from tests.str.rag_eval_v3_candidates import CANDIDATES_FILE
from tests.str.rag_eval_v3_round2 import KEY_PREFIX, SHEET_TO_TYPE, text_problems, write_grade_sheet
from tests.str.rag_eval_v3_sheet import CHECKER_FILES, Db, read_db

DECIDED_SHEET = "decided_grade_sheet.csv"
GROUP = "D"


def decided_new(
    decided: Mapping[str, frozenset[str]], candidates: Mapping[str, list[dict]]
) -> list[tuple[str, str, str, int]]:
    """(유형, chunk_id, 문서, 쪽) — 결정태그 중 후보에 없는 것, 유형 → 문서 → 쪽 → chunk_id 순."""
    have = {(t, r["chunk_id"]) for t, rows in candidates.items() for r in rows}
    base = {r["chunk_id"]: r for r in expected_rows()}
    out = [(SHEET_TO_TYPE[t], c, base[c]["doc_id"], int(base[c]["page"]))
           for c, tags in decided.items() for t in tags if (SHEET_TO_TYPE[t], c) not in have]  # fmt: skip
    order = list(KEY_PREFIX)
    return sorted(out, key=lambda r: (order.index(r[0]), r[2], r[3], r[1]))


def export(sheets: tuple[Path, Path, Path], out_dir: Path, candidates: Mapping[str, list[dict]],
           read: Callable[[list[str]], Db], out: Callable[[str], None] = print) -> int:  # fmt: skip
    if problem := out_dir_problem(out_dir, CHECKER_FILES):
        out(problem)
        return 2
    out_dir = Path(out_dir).expanduser().resolve()
    if problem := place_problem(out_dir / DECIDED_SHEET, None):
        out(f"{problem} — CSV 만들기 전 멈춤")
        return 1
    a, b = load_pair(sheets[0], sheets[1])
    rows = decided_new(load_decisions(sheets[2], disagreement_rows(a, b)), candidates)
    db = read([c for _, c, _, _ in rows])
    bad = text_problems({c: (d, p) for _, c, d, p in rows}, db)
    if bad:
        out(f"DB 원본과 다른 청크: {bad[:10]}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    write_grade_sheet(out_dir / DECIDED_SHEET, rows, db, GROUP)
    counts = {t: sum(r[0] == t for r in rows) for t in KEY_PREFIX if any(r[0] == t for r in rows)}
    out(f"decided_new={len(rows)} " + " ".join(f"{t}={n}" for t, n in counts.items()) + f" → {DECIDED_SHEET}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SCRUM-306 확인 ③ 결정 행 등급 시트")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export")
    for name in ("a", "b", "decided"):
        p.add_argument(name, type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    candidates = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))["candidates"]
    return export((args.a, args.b, args.decided), args.out, candidates, read_db)


if __name__ == "__main__":
    raise SystemExit(main())
