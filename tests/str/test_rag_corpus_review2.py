"""SCRUM-305 태그 도구 추가 검토 2 회귀 (docs/str/10 "305 실행 기록" 태그 도구 ⑦~⑫). DB·LLM 0."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools.corpus_chunks import resolve_typologies

from tests.str import rag_calibration_sheet as cal
from tests.str import rag_corpus_sheet as cs
from tests.str import rag_corpus_tags as tags
from tests.str.rag_corpus_check import tag_consistency_problems
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS
from tests.str.test_rag_corpus_sheet import DB, SCOPE, _export, _fill
from tests.str.test_rag_corpus_tags import NEW, REPO, _with_line

APG, FIN = "apg-typologies-2025", "fincen-cmln-2025"
OLD_CYCLE = list(tags.BASELINE_OLD_TAGGED["CYCLE"])


# ───────── ⑦ 확인등급 칸 = 행ID=등급 ─────────


K = "CY-a1a1a1a1"  # 추가 검토 3 — 칸 ID 는 (유형, chunk_id) 계산값


@pytest.mark.parametrize("cell", [f"{K}=2", f"{K}= 2", f" {K}=2 ", f"{K} = 2"])
def test_grade_cell_accepts_row_id_and_spaces(cell: str) -> None:
    assert cs.parse_grade(cell, K) == 2


@pytest.mark.parametrize(
    "cell", [f"{K}=", "2", "CY-a2a2a2a2=2", "CY-001=2", f"{K}=22", f"{K}=3", f"{K}=2x", "=2"]
)
def test_grade_cell_refuses_missing_or_moved(cell: str) -> None:
    assert cs.parse_grade(cell, K) is None


def test_grade_column_alone_sorted_is_refused(tmp_path: Path) -> None:
    path = _export(tmp_path)
    _fill(path, lambda r: 2 if r["행"] == "CY-001" else 0)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    cells = [r["확인등급"] for r in rows]
    for r, cell in zip(rows, cells[1:] + cells[:1], strict=True):  # 등급 열만 한 칸 밀림
        r["확인등급"] = cell
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cs.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError):
        cs.read_and_build(path, SCOPE, DB, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32)


# ───────── ⑧ 등급 → manifest 쪽 → DB 태그 청크 ─────────

LOC = {c: (d, p) for c, d, p in NEW} | {c: ("ffiec-redflags", 6) for c in OLD_CYCLE}
GRADES = {"checked_by": "김종민", "grades": {"CYCLE": [{"chunk_id": "a2" * 32, "grade": 2}, {"chunk_id": OLD_CYCLE[0], "grade": 1}],
          "SCATTER_GATHER": [], "GATHER_SCATTER": [{"chunk_id": "f1" * 32, "grade": 0}]}}  # fmt: skip
PAGES_OK = {APG: {"typology_pages": {"CYCLE": [5]}}}
TAGGED_OK = {"CYCLE": sorted(["a1" * 32, "a2" * 32, *OLD_CYCLE]), "SCATTER_GATHER": [], "GATHER_SCATTER": []}


def test_consistency_ok() -> None:
    assert tag_consistency_problems(GRADES, PAGES_OK, LOC, TAGGED_OK) == []


def test_manifest_not_updated_is_a_problem() -> None:
    """등급 게시 뒤 manifest 교체가 실패한 상태 — manifest 쪽이 비어 있음."""
    assert tag_consistency_problems(GRADES, {APG: {}}, LOC, TAGGED_OK) != []


def test_db_not_reloaded_is_a_problem() -> None:
    """manifest 는 반영됐지만 다시 적재를 안 함 — DB 태그는 기존 CYCLE 2 뿐."""
    stale = {"CYCLE": sorted(OLD_CYCLE), "SCATTER_GATHER": [], "GATHER_SCATTER": []}
    assert tag_consistency_problems(GRADES, PAGES_OK, LOC, stale) != []


# ───────── ⑨ 작업 트리 둘이 같은 코퍼스 ─────────


def test_second_worktree_with_different_grades_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.str import rag_corpus_sheet_live as live

    corpus = tmp_path / "corpus"
    (corpus / "pdf").mkdir(parents=True)
    (corpus / "manifest.json").write_text(
        (REPO / "corpus/manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(live, "get_settings", lambda: SimpleNamespace(corpus_dir=corpus))
    monkeypatch.setattr(live, "_scope_and_texts", lambda: (SCOPE, DB, "cd" * 32))
    codes = []
    for tree, grade in (("a", 2), ("b", 0)):
        monkeypatch.setattr(live, "GRADES_FILE", tmp_path / tree / "answers_corpus.json")
        (tmp_path / tree).mkdir()
        path = _export(tmp_path / tree)
        _fill(path, lambda r, g=grade: g if r["chunk_id"] == "a2" * 32 else 0)
        args = argparse.Namespace(cmd="apply-corpus", csv=path, checker="김종민", checked_at="2026-11-21")
        codes.append(live.run_command(args, lambda _m: None))
    assert codes == [0, 1]
    docs = {
        d["id"]: d for d in json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))["documents"]
    }
    assert docs[APG]["typology_pages"] == {"CYCLE": [5]}  # 첫 반영 그대로


# ───────── ⑩ 문서 단위 태그 ─────────


def test_new_doc_level_typologies_are_refused_and_pages_only_tagging_empties() -> None:
    text = (REPO / "corpus/manifest.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        tags.manifest_with_pages(_with_line(text, APG, typologies=["CYCLE"]), {d: {} for d in NEW_DOC_IDS})
    out = tags.manifest_with_pages(
        _with_line(text, APG, typology_pages={"CYCLE": [5]}), {d: {} for d in NEW_DOC_IDS}
    )
    apg = {d["id"]: d for d in json.loads(out)["documents"]}[APG]
    assert all(resolve_typologies(apg, page) == [] for page in range(1, apg["pages"] + 1))


# ───────── ⑪ 기준 맞추기 원본 대조 ─────────


def test_calibration_swapped_doc_page_text_is_refused(tmp_path: Path) -> None:
    rows1 = cal.round_rows(1)
    texts = {r["chunk_id"]: f"본문 {r['chunk_id'][:6]}" for r in rows1}
    out: list[str] = []
    assert cal.export_calibration(tmp_path / "c", 1, texts, out=out.append) == 0
    path = tmp_path / "c" / cal.SHEET_NAME
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    a, b = [i for i, r in enumerate(rows) if r["유형"] == "CYCLE"][:2]  # 같은 유형 두 행의 자료를 맞바꿈
    for key in ("문서", "쪽", "본문"):
        rows[a][key], rows[b][key] = rows[b][key], rows[a][key]
    for r in rows:
        r["확인등급"] = "0"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cal.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    assert cal.check_calibration(path, 1, texts, out=out.append) == 2


# ───────── ⑫ pymupdf 없이 CLI 가 뜸 ─────────


@pytest.mark.parametrize("module", ["tests.str.rag_answer_sheet_live", "tests.str.rag_corpus_draft_live"])
def test_cli_help_without_pymupdf(module: str) -> None:
    code = (
        "import sys, runpy; sys.modules['pymupdf'] = None; sys.modules['fitz'] = None; "
        f"sys.argv = ['{module}', '--help']; runpy.run_module('{module}', run_name='__main__')"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=False,
    )
    assert res.returncode == 0 and "usage" in res.stdout, res.stderr[-400:]
