"""SCRUM-306 두 사람 일치율 — 받은 시트 검사 · 유형별 Cohen's κ (`docs/str/rag2/03_sampling.md` 5절).

손 실행 도구. 받은 시트는 리포 밖에 둠. 출력은 chunk_id·숫자만(본문·메모 0).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tools.rag2_blind import RANGE_FIELD, SHEET_FIELDS, load_sample
from tools.rag2_io import SheetError, read_rows
from tools.rag2_sample import ROOT, SAMPLE_FIELDS

RANGES_FIXTURE = ROOT / "tests/str/fixtures/rag2_sentence_ranges.json"
TYPES = ("FAN_IN", "FAN_OUT", "CYCLE", "SG", "GS")
NONE_TAG = "없음"
TAG_SEP = ";"
ANY_KEY = "후보유무"
KAPPA_MIN_TAGGED = 5  # 두 사람 중 적은 쪽 붙임 수가 이보다 작으면 κ 칸을 비움(03 5절)
FIXED_FIELDS = SAMPLE_FIELDS + [RANGE_FIELD]
# 쪽과 문장 사이 = 공백 또는 가운데점(00 기준서 예시 `p쪽·s문장` · 묶음 안내 `p15 s19` 둘 다)
EVIDENCE_PART = re.compile(r"p(\d+)(?:\s*·\s*|\s+)s(\d+)(?:\(중간\))?(?:\s*~\s*s(\d+)(?:\(중간\))?)?")
RANGE_CELL = re.compile(r"s(\d+)(?:\(중간\))?(?:~s(\d+)(?:\(중간\))?)?")
__all__ = ["SheetError"]  # 예전 import 자리(tools.rag2_agreement.SheetError) 유지


@dataclass(frozen=True)
class Tagged:
    chunk_id: str
    tags: frozenset[str]
    evidence: str
    memo: str = ""


def evidence_key(cell: str) -> tuple[tuple[int, int, int] | str, ...]:
    """근거위치 정규형 — (쪽, 첫 문장, 끝 문장) 목록. 꼴이 아닌 조각은 공백만 지운 글자로."""
    out = []
    for part in (p.strip() for p in cell.split(TAG_SEP) if p.strip()):
        m = EVIDENCE_PART.fullmatch(part)
        out.append((int(m[1]), int(m[2]), int(m[3] or m[2])) if m else "".join(part.split()))
    return tuple(out)


def evidence_problem(cell: str, page: int, sentence_range: str) -> str | None:
    """근거위치 조각(`;`)마다 `p쪽 s번호[~s번호]` 꼴 · 쪽 = 그 행 page · 문장 번호가 그 행 문장범위 안."""
    span = RANGE_CELL.fullmatch(sentence_range)
    if span is None:
        return "문장범위 꼴이 아님"
    lo, hi = int(span[1]), int(span[2] or span[1])
    for part in (p.strip() for p in cell.split(TAG_SEP)):
        m = EVIDENCE_PART.fullmatch(part)
        if m is None:
            return "근거위치 꼴이 아님"
        first, last = int(m[2]), int(m[3] or m[2])
        if int(m[1]) != page:
            return "근거위치 쪽 ≠ 그 행 page"
        if not lo <= first <= last <= hi:
            return "근거위치 문장이 그 행 문장범위 밖"
    return None


def parse_tags(cell: str) -> frozenset[str]:
    parts = [p.strip() for p in cell.split(TAG_SEP)]
    if not cell.strip() or "" in parts:
        raise ValueError("태그 빈 칸")
    unknown = [p for p in parts if p not in TYPES and p != NONE_TAG]
    if unknown:
        raise ValueError(f"모르는 태그 {len(unknown)}개")  # 값은 안 냄(칸이 밀리면 본문이 들어 있음)
    if len(set(parts)) != len(parts):
        raise ValueError("같은 태그 두 번")
    if NONE_TAG in parts and len(parts) > 1:
        raise ValueError("없음 과 다른 태그를 같이")
    return frozenset() if parts == [NONE_TAG] else frozenset(parts)


def expected_rows() -> list[dict[str, str]]:
    """묶음 시트의 앞 칸(05 칸 + 문장범위) — 리포 파일로 다시 만듦(PDF 불필요)."""
    ranges = json.loads(RANGES_FIXTURE.read_text(encoding="utf-8"))["ranges"]
    return [{**r, RANGE_FIELD: ranges[r["chunk_id"]]} for r in load_sample()]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    return read_rows(path)


def _norm(cell: str) -> str:
    """셀 비교 — 셀 안 줄바꿈 CRLF → LF · 앞뒤 공백(엑셀 재저장으로만 바뀌는 차이)."""
    return cell.replace("\r\n", "\n").strip()


def check_rows(
    name: str, fields: list[str], want_fields: list[str], rows: list[dict], expected: list[dict]
) -> None:
    """칸 이름·순서 · 행 수 · 행마다 앞 칸 값이 기대와 같은지. 문제는 모아서 SheetError."""
    if fields != want_fields:
        at = next(
            (i for i, (x, y) in enumerate(zip(fields, want_fields, strict=False)) if x != y),
            min(len(fields), len(want_fields)),
        )
        raise SheetError(
            f"{name}: 칸이 다름 — 기대 {len(want_fields)}칸, 받은 {len(fields)}칸, {at + 1}번째 칸부터 다름"
        )
    problems = []
    if len(rows) != len(expected):
        problems.append(f"행 수 {len(rows)} ≠ {len(expected)}")
    ids = [r["chunk_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("chunk_id 중복")
    for i, (got, want) in enumerate(zip(rows, expected, strict=False), start=2):
        diff = [k for k in want if _norm(got.get(k) or "") != _norm(want[k])]
        if diff:
            problems.append(f"{i}행 {diff} 가 묶음과 다름(순서·값)")
    if problems:
        raise SheetError(f"{name}: " + " · ".join(problems[:10]))


def load_sheet(path: Path, expected: list[dict[str, str]] | None = None) -> list[Tagged]:
    expected = expected_rows() if expected is None else expected
    fields, rows = read_csv(path)
    check_rows(path.name, fields, SHEET_FIELDS, rows, expected)
    out, problems = [], []
    for i, r in enumerate(rows, start=2):
        try:
            tags = parse_tags(r["태그"] or "")
        except ValueError as exc:
            problems.append(f"{i}행 {exc}")
            continue
        evidence = (r["근거위치"] or "").strip()
        if tags and not evidence:
            problems.append(f"{i}행 근거위치 빈 칸")
        elif evidence and (bad := evidence_problem(evidence, int(r["page"]), r[RANGE_FIELD])):
            problems.append(f"{i}행 {bad}")
        out.append(Tagged(r["chunk_id"], tags, evidence, (r["메모"] or "").strip()))
    if problems:
        raise SheetError(f"{path.name}: " + " · ".join(problems[:10]))
    return out


def kappa(a: list[bool], b: list[bool]) -> tuple[float, float, float | None]:
    """(p_o, p_e, κ) — p_e = 1 이면 κ 정의 안 됨(None)."""
    if not a or len(a) != len(b):
        raise ValueError("길이가 다르거나 빈 목록")
    n = len(a)
    p_o = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    p_e = pa * pb + (1 - pa) * (1 - pb)
    return p_o, p_e, None if p_e == 1 else (p_o - p_e) / (1 - p_e)


def _flags(rows: list[Tagged], typ: str | None) -> list[bool]:
    return [bool(r.tags) if typ is None else typ in r.tags for r in rows]


def agreement(a: list[Tagged], b: list[Tagged]) -> dict[str, dict]:
    """유형별 + 후보 유무: 붙임 수 · p_o · κ(적은 쪽 붙임 < 5 이면 None, 원값은 kappa_raw)."""
    if [r.chunk_id for r in a] != [r.chunk_id for r in b]:
        raise SheetError("두 시트의 chunk_id 순서가 다름")
    out = {}
    for typ in (*TYPES, None):
        fa, fb = _flags(a, typ), _flags(b, typ)
        p_o, p_e, k = kappa(fa, fb)
        few = typ is not None and min(sum(fa), sum(fb)) < KAPPA_MIN_TAGGED
        out[typ or ANY_KEY] = {"tagged_a": sum(fa), "tagged_b": sum(fb), "p_o": p_o, "p_e": p_e,
                               "kappa": None if few else k, "kappa_raw": k}  # fmt: skip
    return out
