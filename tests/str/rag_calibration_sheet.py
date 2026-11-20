"""SCRUM-305 기준 맞추기 시트 (docs/str/10 "기준 맞추기" · "305 실행 기록"). 손 실행 하위 명령의 본체 — DB 0.

export = `calibration_rows.json` 한 회차(25행) + 본문(호출 쪽이 DB 읽기 전용으로 줌) → 리포 밖 폴더에 CSV +
기준서 사본. **등급 칸은 비움**(LLM·준혁 등급 둘 다 안 넣음). check = 확인자가 채운 CSV 를 같은 25행과 대조 →
준혁 등급과 "1 이상인가" 일치 행 수(`calibration_agrees`, 20행 이상이면 같은 잣대). 출력은 개수·행 번호만.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.str.rag_answer_sheet_check import body_matches
from tests.str.rag_answer_sheet_live import INSIDE_REPO, inside_repo
from tests.str.rag_eval_corpus_draw import calibration_population
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR, calibration_agrees

REPO = Path(__file__).parents[2]
SHEET_NAME = "calibration_sheet.csv"
GUIDE_NAME = "checker_guide.md"
GUIDE_SOURCE = REPO / "docs" / "str" / "rag2" / "04_checker_guide.md"
CRITERIA_NAME = "00_tagging_criteria.md"  # 04 가 함정 목록을 이 파일로 가리킴 — 같은 이름으로 사본
CRITERIA_SOURCE = REPO / "docs" / "str" / "rag2" / CRITERIA_NAME
COLUMNS = ["행", "유형", "chunk_id", "문서", "쪽", "본문", "확인등급", "메모"]  # 기준서 04 와 같은 칸 이름
GRADES = ("0", "1", "2")
COMMANDS = ("export-calibration", "check-calibration")


def round_rows(round_no: int) -> list[dict[str, Any]]:
    doc = json.loads((CORPUS_EVAL_DIR / "calibration_rows.json").read_text(encoding="utf-8"))
    return doc["rounds"][round_no - 1]["rows"]


def export_calibration(
    out_dir: Path, round_no: int, texts: dict[str, str], out: Callable[[str], None] = print
) -> int:
    if "~" in Path(out_dir).parts:  # 따옴표로 셸이 안 푼 ~ — 검사·쓰기 경로가 갈리지 않게 거절(추가 검토 2)
        out("--out 에 풀리지 않은 ~ 가 있음 — 절대 경로로")
        return 2
    out_dir = Path(out_dir).expanduser().resolve()  # 한 번 정규화 — 검사·mkdir·쓰기 같은 값
    if inside_repo(out_dir):
        out(INSIDE_REPO)
        return 2
    rows = round_rows(round_no)
    missing = [r["row_id"] for r in rows if r["chunk_id"] not in texts]
    if missing:
        out(f"DB 에 본문이 없는 행: {missing} — 304 때 코퍼스(425)에서 뽑음")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (out_dir / SHEET_NAME).open("x", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            for r in rows:
                w.writerow({"행": r["row_id"], "유형": r["typology"], "chunk_id": r["chunk_id"], "문서": r["doc_id"],
                            "쪽": r["page"], "본문": texts[r["chunk_id"]], "확인등급": "", "메모": ""})  # fmt: skip
    except FileExistsError:
        out(f"{SHEET_NAME} 이 이미 있음 — 확인 중인 시트를 덮지 않음")
        return 1
    for name, source in ((GUIDE_NAME, GUIDE_SOURCE), (CRITERIA_NAME, CRITERIA_SOURCE)):
        (out_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    out(f"round={round_no} rows={len(rows)} → {SHEET_NAME} + {GUIDE_NAME} + {CRITERIA_NAME}")
    return 0


def read_checked(
    csv_path: Path, round_no: int, texts: dict[str, str]
) -> tuple[dict[tuple[str, str], int], list[str]]:
    """확인된 CSV → ({(유형, chunk_id): 등급}, 문제 목록). 행·유형·chunk_id·문서·쪽·본문이 원본과 다르거나 등급이 0·1·2 가 아니면 문제."""
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            return {}, ["머리글이 다름"]
        got = list(reader)
    rows = {r["row_id"]: r for r in round_rows(round_no)}
    problems = [
        f"{r['행']}: 행·유형·chunk_id·문서·쪽·본문이 회차 원본과 다름"
        for r in got
        if not _row_ok(r, rows, texts)
    ]
    if sorted(r["행"] for r in got) != sorted(rows):
        problems.append("행 목록이 회차 25행과 다름")
    problems += [f"{r['행']}: 등급은 0·1·2" for r in got if r["확인등급"].strip() not in GRADES]
    graded = {(r["유형"], r["chunk_id"]): int(r["확인등급"]) for r in got if r["확인등급"].strip() in GRADES}
    return graded, problems


def source_matches(row: dict[str, str], doc: str, page: int, text: str) -> bool:
    """시트 한 행의 문서·쪽·본문이 원본과 같은가 — 기준 맞추기·태그 확인 시트 공용(추가 검토 2)."""
    return row["문서"] == doc and row["쪽"].strip() == str(page) and body_matches(row["본문"], text)


def _row_ok(row: dict[str, str], rows: dict[str, dict[str, Any]], texts: dict[str, str]) -> bool:
    src = rows.get(row["행"])
    if src is None or (src["typology"], src["chunk_id"]) != (row["유형"], row["chunk_id"]):
        return False
    return src["chunk_id"] in texts and source_matches(
        row, src["doc_id"], src["page"], texts[src["chunk_id"]]
    )


def check_calibration(
    csv_path: Path, round_no: int, texts: dict[str, str], out: Callable[[str], None] = print
) -> int:
    graded, problems = read_checked(csv_path, round_no, texts)
    if problems:
        out("\n".join(["시트를 반영 못 함:", *problems[:10]]))
        return 2
    reference = {(r["typology"], r["chunk_id"]): r["grade"] for r in calibration_population()}
    result = calibration_agrees({k: reference[k] for k in graded}, graded)
    out(f"round={round_no} rows={result['rows']} matches={result['matches']} same={result['same']}")
    return 0 if result["same"] else 1


def add_commands(sub: argparse._SubParsersAction) -> None:
    for name in COMMANDS:
        cmd = sub.add_parser(name)
        cmd.add_argument("--out" if name.startswith("export") else "--csv", type=Path, required=True)
        cmd.add_argument("--round", type=int, choices=(1, 2), default=1, help="2 는 1회차 미달 때만")


def run_command(args: argparse.Namespace, read_texts: Callable[[], dict[str, str]]) -> int:
    """리포 안 폴더면 DB 를 읽기 전에 거절. 본문은 호출 쪽이 DB 읽기 전용으로."""
    if args.cmd == "check-calibration":
        return check_calibration(args.csv, args.round, read_texts())  # 본문 대조 — DB 읽기 전용
    if "~" in Path(args.out).parts or inside_repo(Path(args.out).expanduser().resolve()):  # DB 읽기 전에
        print(INSIDE_REPO)
        return 2
    return export_calibration(args.out, args.round, read_texts())
