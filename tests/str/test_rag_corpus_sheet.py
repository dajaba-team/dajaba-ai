"""SCRUM-305 태그 확인 시트 export·apply (docs/str/10 "305 실행 기록" 태그 도구). DB·LLM 0 — 합성 범위·본문."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tests.str import rag_corpus_sheet as cs
from tests.str import rag_corpus_tags as tags
from tests.str.test_rag_corpus_tags import NEW, OLD_LOC, OLD_TAGGED, _draft, untagged_manifest

REPO = Path(__file__).parents[2]
SCOPE = tags.sheet_scope(_draft(), NEW, OLD_TAGGED, OLD_LOC)
TEXTS = {c: f"본문 {c[:6]}" for _, c, _, _ in SCOPE}
DB = {c: (d, p, TEXTS[c]) for _, c, d, p in SCOPE}


def _export(tmp_path: Path) -> Path:
    out: list[str] = []
    assert cs.export_corpus(tmp_path / "s", SCOPE, TEXTS, out=out.append) == 0
    return tmp_path / "s" / cs.SHEET_NAME


def _fill(path: Path, grade_of) -> None:  # noqa: ANN001
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    for r in rows:
        r["확인등급"] = f"{tags.grade_key(r['유형'], r['chunk_id'])}={grade_of(r)}"  # 미리 채운 칸 뒤에 등급
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cs.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_export_is_blind_and_out_of_repo(tmp_path: Path) -> None:
    path = _export(tmp_path)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert len(rows) == len(SCOPE) and all(
        r["확인등급"] == f"{tags.grade_key(r['유형'], r['chunk_id'])}=" for r in rows
    )
    assert "llm" not in path.read_text(encoding="utf-8-sig").lower()
    for name in ("checker_guide.md", "00_tagging_criteria.md"):
        assert (tmp_path / "s" / name).is_file()
    out: list[str] = []
    assert cs.export_corpus(REPO / "tmp_sheet", SCOPE, TEXTS, out=out.append) == 2
    assert cs.export_corpus(Path("~/x"), SCOPE, TEXTS, out=out.append) == 2
    assert not (REPO / "tmp_sheet").exists()


def test_apply_writes_answers_and_pages(tmp_path: Path) -> None:
    path = _export(tmp_path)
    _fill(path, lambda r: 1 if r["chunk_id"] in ("a2" * 32, "f1" * 32) else 0)
    answers, pages = cs.read_and_build(
        path, SCOPE, DB, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32
    )
    assert answers["checked_by"] == "김종민"
    loc = {c: (d, p) for _, c, d, p in SCOPE}
    assert pages == tags.typology_pages({(t, c): g for t, rows in answers["grades"].items() for c, g in
                                         ((x["chunk_id"], x["grade"]) for x in rows)}, loc)  # fmt: skip
    assert pages == {"apg-typologies-2025": {"CYCLE": [5]}, "fincen-cmln-2025": {"GATHER_SCATTER": [2]},
                     "fintrac-underground-banking-2023": {}}  # fmt: skip
    assert "본문" not in json.dumps(answers, ensure_ascii=False)


@pytest.mark.parametrize("bad", ["", "3"])
def test_apply_refuses_blank_or_bad_grade(tmp_path: Path, bad: str) -> None:
    path = _export(tmp_path)
    _fill(path, lambda r: bad if r["행"] == "CY-001" else 0)
    with pytest.raises(ValueError):
        cs.read_and_build(path, SCOPE, DB, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32)


def test_apply_refuses_changed_rows_or_no_checker(tmp_path: Path) -> None:
    path = _export(tmp_path)
    _fill(path, lambda r: 0)
    with pytest.raises(ValueError):
        cs.read_and_build(
            path, SCOPE[1:], DB, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32
        )
    with pytest.raises(ValueError):
        cs.read_and_build(path, SCOPE, DB, checker="", checked_at="2026-11-21", draft_sha256="cd" * 32)


def _apply_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # noqa: ANN202
    import argparse
    from types import SimpleNamespace

    from tests.str import rag_corpus_sheet_live as live

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text(untagged_manifest(), encoding="utf-8")  # 태그 반영 전 모양
    monkeypatch.setattr(live, "GRADES_FILE", tmp_path / "answers_corpus.json")
    monkeypatch.setattr(live, "get_settings", lambda: SimpleNamespace(corpus_dir=corpus))
    monkeypatch.setattr(live, "_scope_and_texts", lambda: (SCOPE, DB, "cd" * 32))
    path = _export(tmp_path)
    _fill(path, lambda r: 1 if r["chunk_id"] == "a2" * 32 else 0)
    args = argparse.Namespace(cmd="apply-corpus", csv=path, checker="김종민", checked_at="2026-11-21")
    return live, args, corpus / "manifest.json"


def test_apply_corpus_writes_answers_and_only_new_manifest_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live, args, manifest = _apply_env(monkeypatch, tmp_path)
    before = manifest.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    assert live.run_command(args, out.append) == 0
    after = manifest.read_text(encoding="utf-8").splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert len(changed) == 1 and '"apg-typologies-2025"' in after[changed[0]]
    assert json.loads(live.GRADES_FILE.read_text(encoding="utf-8"))["checked_by"] == "김종민"
    assert live.run_command(args, out.append) == 1  # 다 반영됨 — 할 일 없음(덮지 않음)


def test_apply_refuses_rows_whose_doc_page_text_were_resorted(tmp_path: Path) -> None:
    """추가 검토 1 high — 문서·쪽·본문 열만 정렬된 CSV(등급이 다른 청크 본문에 붙음) → 거절."""
    path = _export(tmp_path)
    _fill(path, lambda r: 0)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    moved = [(r["문서"], r["쪽"], r["본문"]) for r in rows]
    moved = moved[1:] + moved[:1]
    for r, (d, p, t) in zip(rows, moved, strict=True):
        r["문서"], r["쪽"], r["본문"] = d, p, t
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cs.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError):
        cs.read_and_build(path, SCOPE, DB, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32)


def test_apply_retry_after_manifest_write_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """두 번째 쓰기(manifest 교체) 실패 → 등급 파일만 남음 → 같은 입력 재시도로 마저 반영, 기존 8줄 그대로."""
    import os

    live, args, manifest = _apply_env(monkeypatch, tmp_path)
    before = manifest.read_text(encoding="utf-8").splitlines()
    real, calls = os.replace, []

    def flaky(src, dst):  # noqa: ANN001
        calls.append(dst)
        if len(calls) == 1:
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(live.os, "replace", flaky)
    out: list[str] = []
    with pytest.raises(OSError):
        live.run_command(args, out.append)
    assert live.GRADES_FILE.exists() and manifest.read_text(encoding="utf-8").splitlines() == before
    assert live.run_command(args, out.append) == 0
    after = manifest.read_text(encoding="utf-8").splitlines()
    assert [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b] == [
        i for i, line in enumerate(after) if '"apg-typologies-2025"' in line
    ]


def test_apply_retry_with_different_grades_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live, args, _ = _apply_env(monkeypatch, tmp_path)
    live.GRADES_FILE.write_text(
        json.dumps({"checked_by": "다른 사람", "grades": {}, "draft_sha256": "x"}), encoding="utf-8"
    )
    out: list[str] = []
    assert live.run_command(args, out.append) == 1


def test_concurrent_apply_only_one_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import threading
    import time

    live, args, _ = _apply_env(monkeypatch, tmp_path)
    real = live.cs.read_and_build

    def slow(*a, **k):  # noqa: ANN002, ANN003, ANN202
        time.sleep(0.2)
        return real(*a, **k)

    monkeypatch.setattr(live.cs, "read_and_build", slow)
    codes: list[int] = []
    threads = [
        threading.Thread(target=lambda: codes.append(live.run_command(args, lambda _m: None)))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [0, 1]
