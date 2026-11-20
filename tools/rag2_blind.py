"""SCRUM-306 블라인드 묶음 — 두 사람에게 주는 것만(03 3절): 표본 시트 · 00 기준 사본 · 문서별 PDF 쪽 안내.

01·02·AI 후보·다른 사람 시트는 넣지 않음. 원문 0 — 위치·문장 순번·공식 주소·sha256 만. 리포 안에는 만들지 않음.
PDF 는 7개 모두 진희가 파일로 보냄(03 3절) — 공식 주소는 출처 칸에만.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import unicodedata
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from tools.rag2_io import in_worktree
from tools.rag2_sample import MANIFEST, ROOT, SAMPLE_CSV, SAMPLE_FIELDS, read_pages
from tools.rag2_show_chunk import sentence_range, sentence_spans

CRITERIA_MD = ROOT / "docs/str/rag2/00_tagging_criteria.md"
VIEWER_SRC = Path(__file__).with_name("rag2_show_chunk.py")
SHEET_NAME = "sheet.csv"
GUIDE_NAME = "pdf_pages.md"
SUMS_NAME = "SHA256SUMS"
RANGE_FIELD = "문장범위"
TAG_FIELDS = ["태그", "근거위치", "메모"]
SHEET_FIELDS = SAMPLE_FIELDS + [RANGE_FIELD] + TAG_FIELDS
TAG_VALUES = ["FAN_IN", "FAN_OUT", "CYCLE", "SG", "GS", "없음"]
RECEIVE_NOTE = "진희가 보낸 파일(sha256 아래 값)"

PagesOf = Callable[[dict], list[str]]


def load_sample() -> list[dict[str, str]]:
    """시트 순서 — 05 80행(기존 70 + 새 3문서 10)을 doc_id·page·순번으로 섞음(03 3절, 새 문서 행이 뒤에 안 몰림)."""
    with SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda r: (r["doc_id"], int(r["page"]), int(r["쪽안_청크순번"])))


def load_metas() -> dict[str, dict]:
    return {m["id"]: m for m in json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]}


def sentence_ranges(rows: list[dict[str, str]], metas: dict[str, dict], pages_of: PagesOf) -> dict[str, str]:
    """chunk_id → `s3(중간)~s9` (03 3절 `문장범위`)."""
    out: dict[str, str] = {}
    for doc in sorted({r["doc_id"] for r in rows}):
        pages = [unicodedata.normalize("NFKC", p) for p in pages_of(metas[doc])]
        for r in (r for r in rows if r["doc_id"] == doc):
            spans = sentence_spans(pages[int(r["page"]) - 1])
            out[r["chunk_id"]] = sentence_range(spans, int(r["시작"]), int(r["끝"]))
    return out


def write_sheet(rows: list[dict[str, str]], ranges: dict[str, str], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {
                **{k: r[k] for k in SAMPLE_FIELDS},
                RANGE_FIELD: ranges[r["chunk_id"]],
                **dict.fromkeys(TAG_FIELDS, ""),
            }
            for r in rows
        )


def render_guide(rows: list[dict[str, str]], metas: dict[str, dict], viewer: bool) -> str:
    lines = [
        "# 문서별 PDF 쪽 안내 (SCRUM-306 표본 태깅)",
        "",
        f"- 태그는 `{SHEET_NAME}` 의 `태그` 칸에 {' · '.join(TAG_VALUES)} 중 해당하는 것 전부(여러 개는 `;`). "
        "기준은 `00_tagging_criteria.md` 만.",
        "- `근거위치` 는 태그마다 `p쪽 s문장`(00 의 문장 순번 규칙). 원문 문장은 옮기지 않음.",
        "- `시작`·`끝` = 그 쪽 추출 텍스트(NFKC)에서 그 청크의 문자 위치(0부터, 끝은 포함 안 함). "
        f"`{RANGE_FIELD}` = 그 범위가 걸친 첫·끝 문장 순번, 문장 중간에서 시작·끝나면 `(중간)`. "
        "그 범위 안 문장만 보고, 이웃 청크 문장은 근거로 쓰지 않음.",
        "- PDF 는 진희가 파일로 보냄. 받은 파일의 sha256 이 아래 값과 같아야 쪽 번호·위치가 맞음 — 다르면 태깅 전에 "
        "진희에게 알려 주세요. 출처 주소는 참고용(받는 곳 아님).",
        "- 끝날 때까지 다른 사람 시트·다른 자료를 보지 않음.",
    ]
    if viewer:
        ex = rows[0]
        lines += [
            "- 범위 보기(화면에만 띄움, 저장 0) — 1) `pip install pymupdf`",
            f"  2) `python rag2_show_chunk.py {ex['doc_id']}.pdf {ex['page']} {ex['시작']} {ex['끝']}` "
            "(PDF 경로 · page · 시작 · 끝 — 시트 그 행 값)",
            "  3) 출력 줄 앞의 `[s번호]` 를 `근거위치` 에 그대로 적기(예 `p3 s4`, 중간이면 `p3 s4(중간)`)",
        ]
    lines += [
        "",
        "| doc_id | 문서 | 발행 · 연도 | 출처(공식 주소) | 받는 곳 | sha256 | 쪽 수 | 표본 쪽 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for doc in sorted({r["doc_id"] for r in rows}):
        m = metas[doc]
        pages = ", ".join(str(p) for p in sorted({int(r["page"]) for r in rows if r["doc_id"] == doc}))
        lines.append(
            f"| {doc} | {m['title']} | {m.get('publisher') or '-'} · {m.get('year') or '-'} | {m['url']} | "
            f"{RECEIVE_NOTE} | `{m['sha256']}` | {m['pages']} | {pages} |"
        )
    return "\n".join(lines) + "\n"


def file_sums(folder: Path) -> dict[str, str]:
    return {
        p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.name != SUMS_NAME
    }


def build_bundle(out: Path, viewer: bool, pages_of: PagesOf = read_pages) -> dict[str, str]:
    if out.resolve().is_relative_to(ROOT) or in_worktree(out):
        raise ValueError("묶음은 리포 밖(Git 작업 트리 밖)에만 만듦")
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"빈 폴더가 아님: {out}")
    rows, metas = load_sample(), load_metas()
    ranges = sentence_ranges(rows, metas, pages_of)
    out.mkdir(parents=True, exist_ok=True)
    write_sheet(rows, ranges, out / SHEET_NAME)
    shutil.copyfile(CRITERIA_MD, out / CRITERIA_MD.name)
    (out / GUIDE_NAME).write_text(render_guide(rows, metas, viewer), encoding="utf-8")
    if viewer:
        shutil.copyfile(VIEWER_SRC, out / VIEWER_SRC.name)
    sums = file_sums(out)
    (out / SUMS_NAME).write_text("".join(f"{h}  {n}\n" for n, h in sums.items()), encoding="utf-8")
    return sums


def main() -> None:
    parser = argparse.ArgumentParser(description="SCRUM-306 블라인드 묶음 두 벌(A·B 내용 같음)")
    parser.add_argument("out", type=Path, help="묶음 상위 폴더(리포 밖) — 그 아래 blind_A·blind_B")
    parser.add_argument("--viewer", action="store_true", help="범위 보기 스크립트를 같이 넣음")
    args = parser.parse_args()
    sums = [build_bundle(args.out / name, args.viewer) for name in ("blind_A", "blind_B")]
    if sums[0] != sums[1]:
        raise SystemExit("두 벌 해시 다름")
    for name, digest in sums[0].items():
        print(f"{digest}  {name}")


if __name__ == "__main__":
    main()
