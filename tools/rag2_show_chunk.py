"""표본 청크 범위 보기 — 자기 PDF 에서 그 쪽 추출 텍스트(NFKC)의 [시작, 끝) 를 문장마다 `[s번호]` 붙여 화면에 띄움.

블라인드 묶음에 같이 들어가는 단독 스크립트(리포 import 없음). 파일로 저장하지 않음.
문장 나누기(`docs/str/rag2/03_sampling.md` 3절)는 이 파일 한 곳 — 묶음 도구의 `문장범위` 도 여기서 계산.
사용: python rag2_show_chunk.py <PDF 경로> <page> <시작> <끝>
"""

from __future__ import annotations

import re
import sys
import unicodedata

SENTENCE_BREAK = re.compile(r"(?<=[.?!])\s+|\n\s*\n")
MID_MARK = "(중간)"


def sentence_spans(norm_text: str) -> list[tuple[int, int]]:
    """문장마다 [시작, 끝) — 1번 문장이 리스트 0번. 공백뿐인 조각은 안 셈, 앞뒤 공백은 뺌."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    breaks = [(m.start(), m.end()) for m in SENTENCE_BREAK.finditer(norm_text)]
    for piece_end, next_start in [*breaks, (len(norm_text), len(norm_text))]:
        piece = norm_text[cursor:piece_end]
        if piece.strip():
            lead = len(piece) - len(piece.lstrip())
            spans.append((cursor + lead, cursor + len(piece.rstrip())))
        cursor = next_start
    return spans


def labeled_sentences(spans: list[tuple[int, int]], start: int, end: int) -> list[tuple[str, int, int]]:
    """청크 [start, end) 가 걸친 문장마다 (`s3` 또는 `s3(중간)`, 범위 안 시작, 끝)."""
    hits = [(i, s, e) for i, (s, e) in enumerate(spans) if s < end and e > start]
    if not hits:
        raise ValueError("청크 범위에 문장이 없음")
    out = []
    for n, (i, s, e) in enumerate(hits):
        mid = (n == 0 and start > s) or (n == len(hits) - 1 and end < e)
        out.append((f"s{i + 1}{MID_MARK if mid else ''}", max(s, start), min(e, end)))
    return out


def sentence_range(spans: list[tuple[int, int]], start: int, end: int) -> str:
    """시트 `문장범위` — 첫·끝 문장 표시. 예 `s3(중간)~s9`."""
    hits = [i for i, (s, e) in enumerate(spans) if s < end and e > start]
    if not hits:
        raise ValueError("청크 범위에 문장이 없음")
    first, last = hits[0], hits[-1]
    head = MID_MARK if start > spans[first][0] else ""
    tail = MID_MARK if end < spans[last][1] else ""
    return f"s{first + 1}{head}~s{last + 1}{tail}"


def chunk_lines(page_text: str, start: int, end: int) -> list[str]:
    norm = unicodedata.normalize("NFKC", page_text)
    if not 0 <= start < end <= len(norm):
        raise ValueError("범위가 그 쪽 텍스트 밖 — PDF 가 다른 판일 수 있음(sha256 확인)")
    return [
        f"[{label}] {' '.join(norm[s:e].split())}"
        for label, s, e in labeled_sentences(sentence_spans(norm), start, end)
    ]


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    import pymupdf

    path, page, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    with pymupdf.open(path) as document:
        print("\n".join(chunk_lines(document[page - 1].get_text(), start, end)))


if __name__ == "__main__":
    main()
