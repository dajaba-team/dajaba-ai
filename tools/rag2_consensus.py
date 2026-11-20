"""SCRUM-306 불일치 목록 · 확인자 결정 반영 · 합의 태그 · AI 보조 후보(02) 대 합의 (`03_sampling.md` 5·6절).

손 실행:
  python -m tools.rag2_consensus check A.csv B.csv
  (불일치 목록은 DB 본문이 들어가 `tests/str/rag_eval_v3_round2.py export` 가 씀)
  python -m tools.rag2_consensus consensus A.csv B.csv decided.csv --out <결과.json> --checker 이름 --checked-at YYYY-MM-DD
이름은 A·B 로만. 출력은 chunk_id·숫자만(본문·메모 0) — 불일치 목록·받은 시트는 리포 밖.
불일치 목록 `본문` 칸은 확인자 읽기용 — 결정 반영 때 보지 않음.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import date
from pathlib import Path

from tools.corpus_chunks import compute_content_hash
from tools.rag2_agreement import (
    FIXED_FIELDS,
    TAG_SEP,
    TYPES,
    SheetError,
    Tagged,
    agreement,
    check_rows,
    evidence_key,
    expected_rows,
    load_sheet,
    parse_tags,
    read_csv,
)
from tools.rag2_ai_compare import ai_candidates, ai_vs_consensus
from tools.rag2_io import write_new
from tools.rag2_new_vs_305 import compare, load_305
from tools.rag2_sample_new import NEW_DOCS

TEXT_FIELD = "본문"
PAIR_FIELDS = ["A_태그", "B_태그", "A_근거위치", "B_근거위치"]
DECISION_FIELDS = ["결정태그", "근거줄", "이유분류"]
DISAGREE_FIELDS = FIXED_FIELDS + [TEXT_FIELD] + PAIR_FIELDS + DECISION_FIELDS
REASONS = ("기준 모호", "용어 오해", "단순 실수")


def _cell(tags: frozenset[str]) -> str:
    return TAG_SEP.join(t for t in TYPES if t in tags) or "없음"


def _same_key(t: Tagged) -> tuple:
    """같은 내용 비교용 정규형 — 셀 안 줄바꿈 CRLF→LF · 앞뒤 공백 · 근거위치는 (쪽, 문장) 목록."""
    return t.chunk_id, t.tags, evidence_key(t.evidence), t.memo.replace("\r\n", "\n").strip()


def load_pair(path_a: Path, path_b: Path) -> tuple[list[Tagged], list[Tagged]]:
    """두 시트 — 행마다 태그·근거위치·메모까지 전부 같으면 같은 사람 시트의 사본으로 보고 거절(BOM·줄바꿈만 달라도)."""
    a, b = load_sheet(path_a), load_sheet(path_b)
    if [_same_key(x) for x in a] == [_same_key(y) for y in b]:
        raise SheetError(
            "두 시트가 행마다 태그·근거위치·메모까지 같음 — 같은 사람 시트를 두 번 넣었는지 확인"
        )
    return a, b


def disagreement_rows(
    a: list[Tagged], b: list[Tagged], texts: dict[str, str] | None = None
) -> list[dict[str, str]]:
    """두 사람 태그 묶음이 다른 행만 — 결정 칸은 빈 채로. texts = 해시 대조를 마친 DB 본문(없으면 빈 칸)."""
    fixed = expected_rows()
    return [
        {**{k: base[k] for k in FIXED_FIELDS}, TEXT_FIELD: (texts or {}).get(x.chunk_id, ""),
         "A_태그": _cell(x.tags), "B_태그": _cell(y.tags),
         "A_근거위치": x.evidence, "B_근거위치": y.evidence, **dict.fromkeys(DECISION_FIELDS, "")}
        for base, x, y in zip(fixed, a, b, strict=True) if x.tags != y.tags
    ]  # fmt: skip


def write_disagreement(rows: list[dict[str, str]], out: Path) -> None:
    """Git 작업 트리 밖 · 새 파일로만(rag2_io.write_new)."""
    if any(not r[TEXT_FIELD] for r in rows):
        raise ValueError("본문 빈 행 — DB 본문 해시 대조를 마친 뒤에만 씀")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=DISAGREE_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    write_new(out, buf.getvalue(), encoding="utf-8-sig")


def body_matches_id(row: dict[str, str]) -> bool:
    """결정 시트 `본문` 해시 = chunk_id — 줄바꿈 CRLF·엑셀 앞 작은따옴표는 풀고 봄."""
    body = (row.get(TEXT_FIELD) or "").replace("\r\n", "\n")
    doc, page = row["doc_id"], int(row["page"])
    return any(compute_content_hash(doc, page, t) == row["chunk_id"] for t in {body, body.removeprefix("'")})


def reason_counts(path: Path) -> dict[str, int]:
    """결정 시트 `이유분류` 개수(load_decisions 를 통과한 시트에만 씀)."""
    rows = read_csv(path)[1]
    return {k: sum(r["이유분류"].strip() == k for r in rows) for k in REASONS}


def load_decisions(path: Path, listed: list[dict[str, str]]) -> dict[str, frozenset[str]]:
    """확인자 결정 — 행·순서·앞 칸이 불일치 목록과 같고, 본문 해시 = chunk_id, 결정 칸 셋이 다 차 있어야 함."""
    fields, rows = read_csv(path)
    fixed = [{k: r[k] for k in FIXED_FIELDS + PAIR_FIELDS} for r in listed]
    check_rows(path.name, fields, DISAGREE_FIELDS, rows, fixed)
    out, problems = {}, []
    for i, r in enumerate(rows, start=2):
        if not body_matches_id(r):
            problems.append(f"{i}행 본문 해시 ≠ chunk_id(다른 청크 본문)")
        try:
            out[r["chunk_id"]] = parse_tags(r["결정태그"] or "")
        except ValueError as exc:
            problems.append(f"{i}행 결정태그 {exc}")
        if not (r["근거줄"] or "").strip():
            problems.append(f"{i}행 근거줄 빈 칸")
        if (r["이유분류"] or "").strip() not in REASONS:
            problems.append(f"{i}행 이유분류는 {REASONS} 중 하나")
    if problems:
        raise SheetError(f"{path.name}: " + " · ".join(problems[:10]))
    return out


def consensus(
    a: list[Tagged], b: list[Tagged], decided: dict[str, frozenset[str]]
) -> dict[str, frozenset[str]]:
    """일치 행은 두 사람 태그, 불일치 행은 확인자 결정. 결정이 빠지거나 남으면 거절."""
    split = {x.chunk_id for x, y in zip(a, b, strict=True) if x.tags != y.tags}
    if set(decided) != split:
        raise SheetError("결정한 행이 불일치 행과 다름")
    return {x.chunk_id: decided.get(x.chunk_id, x.tags) for x in a}


def new_doc_ids() -> set[str]:
    return {r["chunk_id"] for r in expected_rows() if r["doc_id"] in NEW_DOCS}


def agreement_groups(a: list[Tagged], b: list[Tagged]) -> dict[str, dict]:
    """두 사람 κ — 전체 · 기존 8문서 · 새 3문서 따로(03 5절 ★B-4)."""
    new = new_doc_ids()
    pick = {"전체": lambda c: True, "기존": lambda c: c not in new, "새3문서": lambda c: c in new}
    return {name: agreement([x for x in a if keep(x.chunk_id)], [y for y in b if keep(y.chunk_id)])
            for name, keep in pick.items()}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description="SCRUM-306 일치율·불일치·합의 (03 5·6절)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "consensus"):
        p = sub.add_parser(name)
        p.add_argument("a", type=Path)
        p.add_argument("b", type=Path)
        if name == "consensus":
            p.add_argument("decided", type=Path)
            p.add_argument("--checker", required=True)
            p.add_argument("--checked-at", type=date.fromisoformat, required=True)
        if name != "check":
            p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    a, b = load_pair(args.a, args.b)
    result: dict = {"rows": len(a), "agreement": agreement_groups(a, b)}
    listed = disagreement_rows(a, b)
    result["disagree"] = len(listed)
    if args.cmd == "consensus":
        agreed = consensus(a, b, load_decisions(args.decided, listed))
        result |= {
            "checked_by": args.checker,
            "checked_at": str(args.checked_at),
            "reasons": reason_counts(args.decided),
        }
        result["ai_vs_consensus"] = ai_vs_consensus(agreed, ai_candidates())
        new = new_doc_ids()
        result["new_vs_305"] = compare({c: t for c, t in agreed.items() if c in new}, *load_305())
        result["consensus"] = {c: sorted(t) for c, t in agreed.items()}
        write_new(args.out, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "consensus"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
