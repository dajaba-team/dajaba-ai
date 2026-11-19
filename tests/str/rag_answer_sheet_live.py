"""SCRUM-275-2 정답 확인 시트 (손 실행, pytest 수집 X — 진희 터미널, 호스트에서. docs/str/10 "확인 시트").

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_answer_sheet_live export --out <리포 밖 폴더>
    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_answer_sheet_live apply --csv <CSV> --check-only
    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_answer_sheet_live apply --csv <확인된 CSV> --checker <이름>

export = 초벌(`answer_draft.json`) + DB 본문(읽기 전용, 초벌이 LLM 에 보낸 그 칸) → 리포 밖 폴더에 CSV + 등급 안내 md.
본문이 든 파일은 리포 안에 쓰지 않음 — `--out` 이나 그 조상 폴더가 리포와 같은 폴더(samefile — 대소문자 변형·상대
경로·심볼릭 링크 포함)면 거절. 행마다 `초벌지문`(초벌 파일·manifest sha256 앞부분). apply = 초벌 완전성 다시 점검 +
확인된 CSV 를 초벌·DB 본문·지문과 대조 → `answers_dev.json`·`answers_holdout.json`(틀린 행이 하나라도 있으면 반영
안 함). 출력은 개수·행 번호·행 id 만(본문 없음).
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_engine
from tests.str import rag_answer_sheet as sheet
from tests.str.rag_answer_sheet_check import BLANK, FORMAT, SheetError, check, draft_problems, summarize
from tests.str.rag_answer_sheet_io import write_pair
from tests.str.rag_eval_v2_support import EVAL_DIR, load_queries

REPO = Path(__file__).resolve().parents[2]
DRAFT_FILE = EVAL_DIR / "answer_draft.json"
SHEET_NAME = "rag_answer_sheet.csv"
GUIDE_NAME = "rag_answer_sheet_guide.md"
SPLITS = ("dev", "holdout")
MAX_ERRORS_SHOWN = 30
CHECK_ONLY_ROWS_SHOWN = 5  # --check-only 종류마다 앞 몇 행
INSIDE_REPO = "--out 이 리포 안(또는 리포와 같은 폴더) — 본문이 든 시트는 리포 밖 폴더에만"
Db = tuple[dict[str, tuple[str, int]], dict[str, str]]


def inside_repo(path: Path) -> bool:
    """`path` 와 존재하는 조상 폴더 중 하나라도 리포와 같은 폴더면 True(문자열이 아니라 파일 시스템으로 비교)."""
    lexical = Path(os.path.abspath(path.expanduser()))  # 글자로 정리(상대 경로·`..`)
    real = path.expanduser().resolve()  # 링크를 따라간 실제 경로(`링크/..` 가 리포 안으로 가는 경우)
    for candidate in (lexical, real):
        for folder in (candidate, *candidate.parents):
            if folder.exists() and os.path.samefile(folder, REPO):
                return True
    return False


def read_db() -> Db:
    """읽기 전용 — {chunk_id: (doc_id, page)}, {chunk_id: 본문}."""
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        rows = session.execute(text("SELECT chunk_id, doc_id, page, text FROM ai.reference_chunks")).all()
    return {r.chunk_id: (r.doc_id, r.page) for r in rows}, {r.chunk_id: r.text for r in rows}


def _draft_ok(draft: dict, db: Db, out: Callable[[str], None]) -> bool:
    problems = draft_problems(draft, db[0])
    if problems:
        out("\n".join(["초벌이 전체 초벌이 아님:", *problems]))
    return not problems


def export(out_dir: Path, draft: dict, db: Db, fp: str, out: Callable[[str], None] = print) -> int:
    if inside_repo(out_dir):
        out(INSIDE_REPO)
        return 2
    if not _draft_ok(draft, db, out):
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    records = sheet.sheet_records(draft, db[1], fp)
    try:
        sheet.write_csv(out_dir / SHEET_NAME, records)
    except FileExistsError:
        out(f"{SHEET_NAME} 이 이미 있음 — 확인 중인 시트를 덮지 않음")
        return 1
    (out_dir / GUIDE_NAME).write_text(sheet.GUIDE_MD, encoding="utf-8")
    counts = Counter(r["유형"] for r in records)
    out(f"rows={len(records)} " + " ".join(f"{t}={counts[t]}" for t in sheet.TYPOLOGY_ORDER))
    return 0


def sheet_errors(
    csv_path: Path, draft: dict, texts: dict[str, str], fp: str
) -> tuple[list[dict], list[SheetError]]:
    """CSV 읽기(머리글·칸 수) + 행 대조. 형식이 틀리면 행 대조 없이 `시트 형식` 오류만."""
    try:
        records = sheet.read_csv(csv_path)
    except sheet.SheetFormatError as exc:
        return [], [SheetError(FORMAT, row, "", detail) for row, detail in exc.problems]
    if not records:
        return [], [SheetError(FORMAT, None, "", "시트에 행이 없음")]
    return records, check(records, draft, texts, fp)


def report_check_only(errors: list[SheetError], out: Callable[[str], None]) -> int:
    """종류별 개수 + 앞 몇 행. 종류가 확인등급 빈 칸뿐이면 0(확인 전 시트 왕복 점검), 그 밖 종류가 있으면 1."""
    groups = summarize(errors)
    out(f"점검만 — 틀린 곳 {len(errors)}" + ("" if errors else " (반영 가능)"))
    for kind, labels in groups.items():
        out(f"  {kind}: {len(labels)} — {labels[:CHECK_ONLY_ROWS_SHOWN]}")
    return 1 if {e.kind for e in errors} - {BLANK} else 0


def apply(
    csv_path: Path,
    checker: str,
    checked_at: str,
    draft: dict,
    db: Db,
    fp: str,
    out: Callable[[str], None] = print,
    *,
    check_only: bool = False,
) -> int:
    if not check_only and not checker.strip():
        out("--checker 비어 있음")
        return 2
    if not _draft_ok(draft, db, out):
        return 1
    records, errors = sheet_errors(csv_path, draft, db[1], fp)
    if check_only:  # 파일은 안 씀
        return report_check_only(errors, out)
    if errors:
        out(f"반영 안 함 — 틀린 곳 {len(errors)}:")
        out("\n".join(str(e) for e in errors[:MAX_ERRORS_SHOWN]))
        return 1
    return _write_answers(draft, records, checker.strip(), checked_at, out)


def _write_answers(
    draft: dict, records: list[dict], checker: str, checked_at: str, out: Callable[[str], None]
) -> int:
    docs = {}
    for split in SPLITS:
        target = EVAL_DIR / f"answers_{split}.json"
        existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
        problem = sheet.existing_problem(existing, draft, load_queries(split))
        if problem:
            out(f"{target.name}: {problem}")
            return 1
        docs[split] = sheet.build_answers(
            draft, records, load_queries(split), checker=checker, checked_at=checked_at
        )
    # 두 파일 다 점검이 끝난 뒤, 둘 다 바뀌거나 둘 다 그대로(중간 실패면 되돌리고 다시 던짐)
    write_pair(
        {
            EVAL_DIR / f"answers_{s}.json": json.dumps(d, ensure_ascii=False, indent=2) + "\n"
            for s, d in docs.items()
        }
    )
    for split, doc in docs.items():
        out(f"answers_{split}.json: queries={len(doc['queries'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--out", type=Path, required=True, help="리포 밖 폴더")
    ap = sub.add_parser("apply")
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--checker", default="", help="반영 때 필수(--check-only 면 안 씀)")
    ap.add_argument("--check-only", action="store_true", help="점검만 — 파일 안 씀")
    ap.add_argument("--checked-at", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args(argv)
    if args.cmd == "export" and inside_repo(args.out):  # DB 를 읽기 전에 먼저 막음
        print(INSIDE_REPO)
        return 2
    draft_bytes = DRAFT_FILE.read_bytes()
    manifest_bytes = (get_settings().corpus_dir / "manifest.json").read_bytes()
    draft, fp, db = json.loads(draft_bytes), sheet.fingerprint(draft_bytes, manifest_bytes), read_db()
    if args.cmd == "export":
        return export(args.out, draft, db, fp)
    return apply(args.csv, args.checker, args.checked_at, draft, db, fp, check_only=args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())
