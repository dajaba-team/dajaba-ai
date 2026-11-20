"""SCRUM-306 적용 제안 — 합의 태그가 붙은 표본 행만 `docs/str/rag2/06_apply_proposal.csv` (`03_sampling.md` 6절 4번).

제안일 뿐 manifest·DB·ES 는 안 바꿈. 칸 = 05 위치 + 제안태그 · 출처 · 이유분류(결정 행만) · 확인등급 · 이웃청크.
확인등급 = 후보 파일의 검증된 0·1·2 기록(`consensus_grades`, 0 도 남김) — 기록이 없는 제안 태그가 있으면 쓰지 않고 멈춤.
이웃청크 = 지금 manifest 처럼 쪽 단위로 적용하면 같이 태그가 붙는 같은 쪽 다른 청크. 본문·메모·근거위치 0.

    python -m tools.rag2_proposal A.csv B.csv decided.csv [--write]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from tools.corpus_chunks import resolve_typologies
from tools.rag2_agreement import TAG_SEP, TYPES, expected_rows, read_csv
from tools.rag2_consensus import consensus, disagreement_rows, load_decisions, load_pair
from tools.rag2_sample import ROOT, locate_spans, read_pages
from tools.rag2_sample_new import _metas

PROPOSAL_CSV = ROOT / "docs/str/rag2/06_apply_proposal.csv"
CANDIDATES = ROOT / "tests/str/rag_eval_v3/answer_candidates.json"
SHEET_TO_TYPE = {
    "FAN_IN": "FAN_IN",
    "FAN_OUT": "FAN_OUT",
    "CYCLE": "CYCLE",
    "SG": "SCATTER_GATHER",
    "GS": "GATHER_SCATTER",
}
POSITION_FIELDS = ["chunk_id", "doc_id", "page", "쪽안_청크순번"]
PROPOSAL_FIELDS = POSITION_FIELDS + ["제안태그", "출처", "이유분류", "확인등급", "이웃청크"]
AGREED, DECIDED = "두 사람 일치", "확인자 결정"
Pages = Mapping[tuple[str, int], list[tuple[int, str]]]  # (문서, 쪽) → [(쪽 안 순번, chunk_id)]


SOURCE_OF = {AGREED: "합의_태그", DECIDED: "결정_태그"}  # 후보 파일 `consensus_grades.source` 와 같은 이름


class Unchecked(ValueError):
    """확인 기록(0·1·2)이 없는 제안 태그 · 기록과 어긋난 제안 · 05 위치가 재분할과 다름 — 발행 전 멈춤."""


def position_problems(pages: Pages) -> list[str]:
    """05 의 (쪽안_청크순번, chunk_id) 가 재분할한 그 쪽에 정확히 한 번인가 — 아니면 이웃·쪽 단위 수를 믿을 수 없음."""
    bad = []
    for r in expected_rows():
        on_page = pages.get((r["doc_id"], int(r["page"])), [])
        if (
            on_page.count((int(r["쪽안_청크순번"]), r["chunk_id"])) != 1
            or [c for _, c in on_page].count(r["chunk_id"]) != 1
        ):
            bad.append(r["chunk_id"][:8])
    return bad


def record_mismatch(rows: list[dict[str, str]], doc: Mapping) -> tuple[set, set]:
    """(기록에만 있음, 제안에만 있음) — (유형, chunk_id, 출처). 원래 후보(db_tagged)에 있던 쌍은 ②③ 대상이 아니라 뺌."""
    old = {(t, r["chunk_id"]) for t, rs in doc["candidates"].items() for r in rs if r["db_tagged"]}
    got = {
        (SHEET_TO_TYPE[t], r["chunk_id"], SOURCE_OF[r["출처"]])
        for r in rows
        for t in r["제안태그"].split(TAG_SEP)
    }
    got = {g for g in got if g[:2] not in old}
    want = {(r["typology"], r["chunk_id"], r["source"]) for r in doc.get("consensus_grades", [])}
    return want - got, got - want


def grade_records(doc: Mapping) -> dict[tuple[str, str], int]:
    """(유형, chunk_id) → 등급 — 확인 ②③ 기록(0 포함) + 원래 후보의 확인 등급."""
    out = {
        (t, r["chunk_id"]): r["grade"]
        for t, rs in doc["candidates"].items()
        for r in rs
        if r["grade"] is not None
    }
    return out | {(r["typology"], r["chunk_id"]): r["grade"] for r in doc.get("consensus_grades", [])}


def corpus_pages(metas: Mapping[str, dict] | None = None) -> tuple[Pages, dict[str, dict]]:
    """코퍼스 재분할로 (문서, 쪽) → 청크 목록 — PDF 필요."""
    metas = dict(metas or _metas())
    pages: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for doc, meta in metas.items():
        for cid, s in locate_spans(doc, read_pages(meta)).items():
            pages.setdefault((doc, s.page), []).append((s.pos, cid))
    return {k: sorted(v) for k, v in pages.items()}, metas


def proposal_rows(sheets: tuple[Path, Path, Path], doc: Mapping, pages: Pages) -> list[dict[str, str]]:
    moved = position_problems(pages)
    if moved:
        raise Unchecked(f"05 위치가 재분할과 다른 청크 {moved[:10]} — 이웃·집계·쓰기 중단")
    a, b = load_pair(sheets[0], sheets[1])
    decided = load_decisions(sheets[2], disagreement_rows(a, b))
    reasons = {r["chunk_id"]: r["이유분류"].strip() for r in read_csv(sheets[2])[1]}
    agreed, grade = consensus(a, b, decided), grade_records(doc)
    out, missing = [], []
    for base in expected_rows():
        cid, tags = base["chunk_id"], [t for t in TYPES if t in agreed[base["chunk_id"]]]
        if not tags:
            continue
        missing += [f"{t}:{cid[:8]}" for t in tags if (SHEET_TO_TYPE[t], cid) not in grade]
        near = [f"{p}={c[:8]}" for p, c in pages[(base["doc_id"], int(base["page"]))] if c != cid]
        out.append({**{k: base[k] for k in POSITION_FIELDS}, "제안태그": TAG_SEP.join(tags),
                    "출처": DECIDED if cid in decided else AGREED, "이유분류": reasons.get(cid, ""),
                    "확인등급": TAG_SEP.join(f"{t}={grade.get((SHEET_TO_TYPE[t], cid), '')}" for t in tags),
                    "이웃청크": TAG_SEP.join(near)})  # fmt: skip
    if missing:
        raise Unchecked(f"확인 기록이 없는 제안 태그 {missing[:10]} — 확인 시트를 먼저")
    only_record, only_rows = record_mismatch(out, doc)
    if only_record or only_rows:
        raise Unchecked(
            f"확인 ②③ 기록과 제안이 다름 — 기록에만 {len(only_record)} · 제안에만 {len(only_rows)}(출처 포함), 06 그대로"
        )
    return out


def tag_counts(rows: list[dict[str, str]], pages: Pages, metas: Mapping[str, dict]) -> dict[str, Counter]:
    """지금 · 청크 단위 적용 · 쪽 단위 적용(지금 manifest 방식) — 유형별 청크 수 + 무태그."""
    by_chunk = {r["chunk_id"]: {SHEET_TO_TYPE[t] for t in r["제안태그"].split(TAG_SEP)} for r in rows}
    by_page: dict[tuple[str, int], set[str]] = {}
    for r in rows:
        by_page.setdefault((r["doc_id"], int(r["page"])), set()).update(by_chunk[r["chunk_id"]])
    out = {"지금": Counter(), "청크 단위": Counter(), "쪽 단위": Counter()}
    for (doc, page), chunks in pages.items():
        now = set(resolve_typologies(metas[doc], page))
        for _, cid in chunks:
            for name, tags in (("지금", now), ("청크 단위", now | by_chunk.get(cid, set())),
                               ("쪽 단위", now | by_page.get((doc, page), set()))):  # fmt: skip
                out[name].update(tags or {"무태그"})
    return out


def render(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=PROPOSAL_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="SCRUM-306 적용 제안 (03 6절 4번) — 적용 0")
    for name in ("a", "b", "decided"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--write", action="store_true", help="06_apply_proposal.csv 를 씀(없으면 대조만)")
    args = parser.parse_args()
    pages, metas = corpus_pages()
    doc = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    rows = proposal_rows((args.a, args.b, args.decided), doc, pages)
    for name, c in tag_counts(rows, pages, metas).items():
        print(name, dict(sorted(c.items())))
    if args.write:
        fd, tmp = tempfile.mkstemp(dir=PROPOSAL_CSV.parent, prefix=f".{PROPOSAL_CSV.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(render(rows))
        os.replace(tmp, PROPOSAL_CSV)  # 검사를 다 통과한 뒤에만, 원자 교체
        print(f"wrote {len(rows)} rows")
        return
    same = PROPOSAL_CSV.read_text(encoding="utf-8") == render(rows)
    print(f"rows {len(rows)} · 06 same={same}")
    raise SystemExit(0 if same else 1)


if __name__ == "__main__":
    main()
