"""SCRUM-306 표본 70 — 03 2·3절 재현 · 오프셋 해시 · 본문 칸 없음."""

from __future__ import annotations

import csv
import random
from collections import Counter

import pytest
from tools import rag2_sample as rs
from tools.corpus_chunks import compute_content_hash

EXPECTED_QUOTA = {
    ("fatf-pml-2018", True): 5, ("fatf-pml-2018", False): 12,
    ("fatf-tbml-2006", False): 10,
    ("fatf-tbml-2020", False): 14,
    ("ffiec-redflags", False): 2,
    ("fincen-money-mule-2020", False): 2,
    ("fincen-msb-ko-2007", True): 6, ("fincen-msb-ko-2007", False): 8,
    ("fincen-sar-narrative-2003", True): 5, ("fincen-sar-narrative-2003", False): 6,
}  # fmt: skip


def _sample_rows() -> list[dict[str, str]]:
    """05 앞 70행(기존 층) — 뒤 10행은 새 3문서 층(`test_rag2_sample_new.py`)."""
    with rs.SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))[: rs.SAMPLE_TARGET]


def test_allocate_matches_03_section_2() -> None:
    quota = rs.allocate(rs.load_review())
    assert quota == EXPECTED_QUOTA
    assert sum(quota.values()) == rs.SAMPLE_TARGET
    assert sum(n for (_, cand), n in quota.items() if cand) == 16


def test_allocate_rejects_candidate_layer_over_cap() -> None:
    rows = [rs.ReviewRow(f"{i:064x}", "doc-a", 1, i, True, True) for i in range(rs.CANDIDATE_CAP + 1)]
    with pytest.raises(ValueError, match="상한"):
        rs.allocate(rows)


def test_allocate_floor_never_exceeds_layer_size() -> None:
    rows = [rs.ReviewRow(f"a{i:063x}", rs.LARGEST_DOC, 1, i, False, False) for i in range(200)]
    rows.append(rs.ReviewRow("b" * 64, "doc-tiny", 1, 1, False, True))
    quota = rs.allocate(rows)
    assert quota[("doc-tiny", False)] == 1
    assert sum(quota.values()) == rs.SAMPLE_TARGET


def test_redraw_with_seed_281_equals_repo_file() -> None:
    rows = rs.load_review()
    picked = rs.draw(rows, rs.allocate(rows))
    repo = _sample_rows()
    assert [(r.chunk_id, r.doc_id, str(r.page), str(r.pos)) for r in picked] == [
        (r["chunk_id"], r["doc_id"], r["page"], r["쪽안_청크순번"]) for r in repo
    ]


def test_draw_depends_on_seed() -> None:
    rows = rs.load_review()
    quota = rs.allocate(rows)
    assert rs.draw(rows, quota, seed=2811) != rs.draw(rows, quota)


def test_sample_file_shape_and_no_text() -> None:
    with rs.SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)[: rs.SAMPLE_TARGET]
        assert reader.fieldnames == rs.SAMPLE_FIELDS
    assert len(rows) == rs.SAMPLE_TARGET
    assert len({r["chunk_id"] for r in rows}) == rs.SAMPLE_TARGET
    review = {r.chunk_id: r for r in rs.load_review()}
    assert all(r["chunk_id"] in review for r in rows)
    assert all(0 <= int(r["시작"]) < int(r["끝"]) for r in rows)
    assert rows == sorted(rows, key=lambda r: (r["doc_id"], int(r["page"]), int(r["쪽안_청크순번"])))


def test_sample_hides_layer_order_within_doc() -> None:
    """후보 있음 행이 문서 안에서 앞에 몰려 있지 않음 — 행 순서로 층을 짐작 못 하게."""
    review = {r.chunk_id: r.candidate for r in rs.load_review()}
    flags = [review[r["chunk_id"]] for r in _sample_rows() if r["doc_id"] == "fatf-pml-2018"]
    assert flags != sorted(flags, reverse=True)


def _pages() -> list[str]:
    words = " ".join(f"w{i}" for i in range(900))
    return [f"title\n\n{words}\n", "ｆｕｌｌ ｗｉｄｔｈ page two\n"]


def test_locate_spans_slice_hash_equals_chunk_id() -> None:
    pages = _pages()
    spans = rs.locate_spans("doc-x", pages)
    assert len(spans) >= 3
    for cid, span in spans.items():
        norm = rs.unicodedata.normalize("NFKC", pages[span.page - 1])
        assert compute_content_hash("doc-x", span.page, norm[span.start : span.end]) == cid
    assert sorted(Counter(s.page for s in spans.values())) == [1, 2]


def test_attach_spans_stops_on_mismatch() -> None:
    spans = rs.locate_spans("doc-x", _pages())
    cid, span = next(iter(spans.items()))
    good = rs.ReviewRow(cid, "doc-x", span.page, span.pos, False, True)
    assert rs.attach_spans([good], {"doc-x": spans})[0]["시작"] == span.start
    for bad in (
        rs.ReviewRow("f" * 64, "doc-x", span.page, span.pos, False, True),
        rs.ReviewRow(cid, "doc-x", span.page, span.pos + 1, False, True),
        rs.ReviewRow(cid, "doc-y", span.page, span.pos, False, True),
    ):
        with pytest.raises(ValueError, match="불일치"):
            rs.attach_spans([bad], {"doc-x": spans})


def test_read_pages_rejects_wrong_sha(tmp_path) -> None:
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "doc-x.pdf").write_bytes(b"not the file")
    with pytest.raises(ValueError, match="sha256"):
        rs.read_pages({"id": "doc-x", "sha256": "0" * 64, "pages": 1}, tmp_path)


@pytest.mark.skipif(not rs.sample_pdfs_present(), reason="corpus/pdf 없음(git 무시 폴더) — 로컬에서 돎")
def test_repo_sample_offsets_rehash_70_of_70() -> None:
    rebuilt = [{k: str(v) for k, v in r.items()} for r in rs.build_sample()]
    assert rebuilt == _sample_rows()


def test_random_sample_api_is_stable() -> None:
    """시드 재현은 random.Random.sample 의 알고리즘에 기댐 — 바뀌면 이 값이 먼저 깨짐."""
    assert random.Random(281).sample(range(100), 3) == [2, 39, 32]
