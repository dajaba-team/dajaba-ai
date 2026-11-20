"""SCRUM-305 태그 확인 시트 — export·반영 본체 (docs/str/10 "305 실행 기록" 태그 도구). DB·LLM 0.

export = 시트 범위(`rag_corpus_tags.sheet_scope`) + 본문(호출 쪽이 DB 읽기 전용으로) → 리포 밖 폴더에 CSV + 기준서 04·00
사본. 기준 맞추기 시트와 같은 칸(`확인등급` 빔, LLM·다른 사람 등급 칸 없음). 반영 = 확인된 CSV 를 같은 범위와 대조 →
`answers_corpus.json` 내용 + 새 3문서 `typology_pages`. 출력은 개수·행 번호만.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tests.str import rag_calibration_sheet as cal
from tests.str import rag_corpus_tags as tags
from tests.str.rag_answer_sheet_live import INSIDE_REPO, inside_repo

SHEET_NAME = "corpus_tag_sheet.csv"
COLUMNS = cal.COLUMNS  # 행·유형·chunk_id·문서·쪽·본문·확인등급·메모
# 확인등급 칸 = "ID=등급" — ID 는 (유형, chunk_id) 계산값 `tags.grade_key`(추가 검토 2·3). 내보낼 때 "ID=" 로 채워 둠 —
# 등급 열만 정렬·다른 초벌 시트 복사는 ID 가 어긋나 거절. 칸 앞뒤 공백과 "=" 앞뒤 공백은 허용, 그 밖은 거절
_GRADE_CELL = re.compile(r"\s*([A-Z]{2}-[0-9A-Za-z]{8})\s*=\s*([012])\s*")


def export_corpus(
    out_dir: Path, scope: tags.Scope, texts: dict[str, str], out: Callable[[str], None] = print
) -> int:
    if "~" in Path(out_dir).parts:
        out("--out 에 풀리지 않은 ~ 가 있음 — 절대 경로로")
        return 2
    out_dir = Path(out_dir).expanduser().resolve()
    if inside_repo(out_dir):
        out(INSIDE_REPO)
        return 2
    rows = tags.numbered(scope)
    missing = [rid for rid, _, c, _, _ in rows if c not in texts]
    if missing:
        out(f"DB 에 본문이 없는 행: {missing[:10]}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (out_dir / SHEET_NAME).open("x", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            for rid, t, c, d, p in rows:
                w.writerow(
                    dict(
                        zip(COLUMNS, (rid, t, c, d, p, texts[c], f"{tags.grade_key(t, c)}=", ""), strict=True)
                    )
                )
    except FileExistsError:
        out(f"{SHEET_NAME} 이 이미 있음 — 확인 중인 시트를 덮지 않음")
        return 1
    for name, source in ((cal.GUIDE_NAME, cal.GUIDE_SOURCE), (cal.CRITERIA_NAME, cal.CRITERIA_SOURCE)):
        (out_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    counts = {t: sum(1 for r in rows if r[1] == t) for t in tags.CORPUS_TYPOLOGIES}
    out(f"rows={len(rows)} " + " ".join(f"{t}={n}" for t, n in counts.items()) + f" → {SHEET_NAME}")
    return 0


def read_and_build(
    csv_path: Path,
    scope: tags.Scope,
    db: Mapping[str, tuple[str, int, str]],
    *,
    checker: str,
    checked_at: str,
    draft_sha256: str,
) -> tuple[dict[str, Any], dict[str, dict[str, list[int]]]]:
    """확인된 CSV → (answers_corpus 내용, 새 3문서 typology_pages). db = {chunk_id: (문서, 쪽, 본문)} — DB 원본.

    행·유형·chunk_id 가 범위와 다르거나, 행의 문서·쪽·본문이 그 chunk_id 의 원본과 다르거나(열만 정렬된 시트),
    등급 칸이 `행ID=0·1·2` 가 아니면(등급 열만 정렬) ValueError — 결과 파일을 쓰기 전.
    """
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise ValueError("머리글이 다름")
        got = list(reader)
    want = {rid: (t, c) for rid, t, c, _, _ in tags.numbered(scope)}
    wrong = [
        r["행"] for r in got if want.get(r["행"]) != (r["유형"], r["chunk_id"]) or not _same_source(r, db)
    ]
    bad = [r["행"] for r in got if parse_grade(r["확인등급"], _key(r)) is None]
    if wrong or bad or sorted(r["행"] for r in got) != sorted(want):
        raise ValueError(
            f"시트가 범위·원본과 다름 — 행·유형·chunk_id·문서·쪽·본문 {wrong[:5]} · 등급 {bad[:5]}"
        )
    graded = {(r["유형"], r["chunk_id"]): parse_grade(r["확인등급"], _key(r)) for r in got}
    answers = tags.answers_doc(
        graded, scope, checker=checker, checked_at=checked_at, draft_sha256=draft_sha256
    )
    loc = {c: (d, p) for _, c, d, p in scope}
    return answers, tags.typology_pages(graded, loc)


def parse_grade(cell: str, key: str) -> int | None:
    """`ID=등급` 칸 → 등급. ID 가 그 행의 계산값과 다르거나 등급이 0·1·2 가 아니면 None."""
    m = _GRADE_CELL.fullmatch(cell or "")
    return int(m.group(2)) if m and m.group(1) == key else None


def _key(row: Mapping[str, str]) -> str:
    return tags.grade_key(row["유형"], row["chunk_id"]) if row["유형"] in tags.ROW_PREFIX else ""


def _same_source(row: Mapping[str, str], db: Mapping[str, tuple[str, int, str]]) -> bool:
    if row["chunk_id"] not in db:
        return False
    return cal.source_matches(row, *db[row["chunk_id"]])  # 기준 맞추기와 같은 원본 대조
