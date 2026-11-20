"""SCRUM-306 블라인드 묶음 — 두 가지(+쪽 안내)만 · 01·02·AI 후보 0 · 두 벌 같음 · 리포 밖 · 문장범위 고정."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from tools import rag2_blind as rb
from tools import rag2_sample as rs

BASE_FILES = {rb.SHEET_NAME, rb.CRITERIA_MD.name, rb.GUIDE_NAME, rb.SUMS_NAME}
RANGES_FIXTURE = Path(__file__).parent / "fixtures" / "rag2_sentence_ranges.json"


def _fake_pages(meta: dict) -> list[str]:
    """PDF 없이 묶음 모양만 볼 때 — 짧은 문장이 이어진 쪽(오프셋이 늘 문장 안에 걸림)."""
    return ["Ab. " * 5000] * meta["pages"]


def _build(out: Path, viewer: bool = False) -> dict[str, str]:
    return rb.build_bundle(out, viewer, pages_of=_fake_pages)


def _read_sheet(folder: Path) -> tuple[list[str], list[dict[str, str]]]:
    with (folder / rb.SHEET_NAME).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def test_bundle_has_only_allowed_files(tmp_path) -> None:
    _build(tmp_path / "A")
    assert {p.name for p in (tmp_path / "A").iterdir()} == BASE_FILES
    _build(tmp_path / "V", viewer=True)
    assert {p.name for p in (tmp_path / "V").iterdir()} == BASE_FILES | {rb.VIEWER_SRC.name}


def test_sheet_is_sample_plus_range_and_empty_tag_columns(tmp_path) -> None:
    _build(tmp_path / "A")
    fields, rows = _read_sheet(tmp_path / "A")
    assert fields == rs.SAMPLE_FIELDS + [rb.RANGE_FIELD] + rb.TAG_FIELDS
    assert [{k: r[k] for k in rs.SAMPLE_FIELDS} for r in rows] == rb.load_sample()
    assert all(r[k] == "" for r in rows for k in rb.TAG_FIELDS)
    assert all(r[rb.RANGE_FIELD].startswith("s") and "~s" in r[rb.RANGE_FIELD] for r in rows)


def test_bundle_leaks_nothing_from_01_02(tmp_path) -> None:
    _build(tmp_path / "A", viewer=True)
    text = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "A").iterdir())
    assert rs.CANDIDATE_COL not in text and "검토상태" not in text  # 00 사본은 01·02 파일 이름만 적음(내용 0)
    with rs.REVIEW_CSV.open(encoding="utf-8", newline="") as f:
        review = list(csv.DictReader(f))
    judged = {r["메모"] for r in review if len(r["메모"]) > 8} | {
        r["근거위치"] for r in review if r["근거위치"]
    }
    assert not [m for m in judged if m in text]  # 근거용어(일반 낱말)는 00 에도 있어 대조 안 함


def test_two_bundles_identical(tmp_path) -> None:
    assert _build(tmp_path / "A") == _build(tmp_path / "B")
    sums = (tmp_path / "A" / rb.SUMS_NAME).read_text(encoding="utf-8")
    assert sums == (tmp_path / "B" / rb.SUMS_NAME).read_text(encoding="utf-8")
    assert len(sums.splitlines()) == len(BASE_FILES) - 1


def test_guide_source_url_and_receive_by_file_for_all_docs(tmp_path) -> None:
    _build(tmp_path / "A")
    guide = (tmp_path / "A" / rb.GUIDE_NAME).read_text(encoding="utf-8")
    metas = rb.load_metas()
    docs = sorted({r["doc_id"] for r in rb.load_sample()})
    lines = [line for line in guide.splitlines() if line.startswith("| ") and not line.startswith("| doc_id")]
    assert [line.split(" | ")[0][2:] for line in lines] == docs
    for doc, line in zip(docs, lines, strict=True):
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert cells[3] == metas[doc]["url"] and cells[4] == rb.RECEIVE_NOTE
        assert cells[5] == f"`{metas[doc]['sha256']}`"


def test_refuses_inside_repo_and_non_empty(tmp_path) -> None:
    with pytest.raises(ValueError, match="리포 밖"):
        _build(rs.ROOT / "tmp_blind_should_not_exist")
    assert not (rs.ROOT / "tmp_blind_should_not_exist").exists()
    (tmp_path / "A").mkdir()
    (tmp_path / "A" / "other_sheet.csv").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="빈 폴더"):
        _build(tmp_path / "A")


def test_guide_has_viewer_howto_3_lines(tmp_path) -> None:
    _build(tmp_path / "V", viewer=True)
    guide = (tmp_path / "V" / rb.GUIDE_NAME).read_text(encoding="utf-8")
    first = rb.load_sample()[0]
    assert "1) `pip install pymupdf`" in guide
    assert (
        f"2) `python rag2_show_chunk.py {first['doc_id']}.pdf {first['page']} {first['시작']} {first['끝']}`"
        in guide
    )
    assert "3) 출력 줄 앞의 `[s번호]` 를 `근거위치` 에 그대로" in guide
    _build(tmp_path / "N")
    assert "pip install" not in (tmp_path / "N" / rb.GUIDE_NAME).read_text(encoding="utf-8")


def test_viewer_has_no_repo_import() -> None:
    src = rb.VIEWER_SRC.read_text(encoding="utf-8")
    assert "from tools" not in src and "aml_ai" not in src and "open(" not in src.replace("pymupdf.open(", "")


@pytest.mark.skipif(not rs.sample_pdfs_present(), reason="corpus/pdf 없음(git 무시 폴더) — 로컬에서 돎")
def test_sentence_ranges_80_rows_fixed() -> None:
    fixed = json.loads(RANGES_FIXTURE.read_text(encoding="utf-8"))["ranges"]
    rows = rb.load_sample()
    assert len(fixed) == 80 and list(fixed) == [r["chunk_id"] for r in rows]
    assert rb.sentence_ranges(rows, rb.load_metas(), rs.read_pages) == fixed
