"""SCRUM-306 ★B-4 새 3문서 층 — 앞 70행 그대로 · 10행 시드 306 재현 · 무태그·02 밖 (03 1·2·3절)."""

from __future__ import annotations

import csv
from hashlib import sha256

import pytest
from tools import rag2_sample as rs
from tools import rag2_sample_new as rn

OLD_05_SHA256 = "773ba999406a1537eb33536c8cbf860db7ab39a4b4ca0b1715ffe5e17a923d07"  # ★B 때 70행 파일


def _all_rows() -> list[dict[str, str]]:
    with rs.SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_first_70_rows_are_byte_identical_to_old_file() -> None:
    lines = rs.SAMPLE_CSV.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(lines) == 1 + rs.SAMPLE_TARGET + rn.NEW_TARGET
    assert sha256("".join(lines[: 1 + rs.SAMPLE_TARGET]).encode()).hexdigest() == OLD_05_SHA256


def test_new_rows_are_new_docs_outside_02_sorted() -> None:
    new = _all_rows()[rs.SAMPLE_TARGET :]
    review = {r.chunk_id for r in rs.load_review()}
    assert len(new) == rn.NEW_TARGET and not {r["chunk_id"] for r in new} & review
    assert {r["doc_id"] for r in new} == set(rn.NEW_DOCS)
    assert [r["doc_id"] for r in new].count("apg-typologies-2025") == 6
    assert new == sorted(new, key=lambda r: (r["doc_id"], int(r["page"]), int(r["쪽안_청크순번"])))
    assert len({r["chunk_id"] for r in _all_rows()}) == 80


def test_allocate_new_ratio_min_2_and_largest_absorbs() -> None:
    rows = [rs.ReviewRow(f"{d}{i:060x}", d, 1, i, False, False)
            for d, n in zip(rn.NEW_DOCS, (223, 32, 4), strict=True) for i in range(n)]  # fmt: skip
    assert rn.allocate_new(rows) == {
        "apg-typologies-2025": 6,
        "fincen-cmln-2025": 2,
        "fintrac-underground-banking-2023": 2,
    }
    tiny = [r for r in rows if r.doc_id != "fintrac-underground-banking-2023"] + rows[-1:]
    assert rn.allocate_new(tiny)["fintrac-underground-banking-2023"] == 1  # 최소 2 라도 있는 만큼만
    assert sum(rn.allocate_new(tiny).values()) == rn.NEW_TARGET


def test_draw_new_depends_on_seed() -> None:
    rows = [rs.ReviewRow(f"{d}{i:060x}", d, 1, i, False, False)
            for d, n in zip(rn.NEW_DOCS, (223, 32, 4), strict=True) for i in range(n)]  # fmt: skip
    quota = rn.allocate_new(rows)
    assert rn.draw_new(rows, quota) == rn.draw_new(rows, quota)
    assert rn.draw_new(rows, quota, seed=281) != rn.draw_new(rows, quota)


@pytest.mark.skipif(not rs.sample_pdfs_present(), reason="corpus/pdf 없음(git 무시 폴더) — 로컬에서 돎")
def test_population_259_and_redraw_equals_repo_rows() -> None:
    rows, _ = rn.new_population(rn._metas(), rs.read_pages)
    assert len(rows) == 259 and {d: sum(r.doc_id == d for r in rows) for d in rn.NEW_DOCS} == {
        "apg-typologies-2025": 223, "fincen-cmln-2025": 32, "fintrac-underground-banking-2023": 4}  # fmt: skip
    rebuilt = [{k: str(v) for k, v in r.items()} for r in rn.build_new()]
    assert rebuilt == _all_rows()[rs.SAMPLE_TARGET :]
