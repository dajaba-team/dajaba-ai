"""SCRUM-305 태그 도구 추가 검토 3 회귀 (docs/str/10 "305 실행 기록" 태그 도구 ⑬~⑰). DB·LLM·검색 0.

예약 회귀는 실제 `corpus_ready_problems` 로 — 합성 코퍼스(새 3문서 34·17·246 + 기존 CYCLE 2)에서 DB 읽기만 가짜.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

import pytest

from tests.str import rag_corpus_check as ck
from tests.str import rag_corpus_tags as tags
from tests.str import rag_eval_corpus_ledger as cl
from tests.str import rag_eval_corpus_live as live
from tests.str.rag_corpus_world import (
    APG,
    FIN,
    FTR,
    HIT,
    NEW,
    OLD,
    ids_of,
    problems,
    with_tags,
    without_doc,
    world,
)
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR

_world, _problems = world, problems


def test_ready_world_has_no_problems() -> None:
    assert _problems(_world()) == []


@pytest.mark.parametrize(
    "broken",
    [
        lambda w: w.update(grades={}),  # 등급 파일 없음
        lambda w: w.update(applied={}),  # 공용 표식만 없음
        lambda w: w.update(applied={"grades_sha256": "0" * 64}),  # 해시 다름(다른 작업 트리)
        lambda w: w.update(raw=w["raw"] + b" "),  # 초벌 파일이 등급 파일의 초벌과 다름
        lambda w: w.update(raw=None),  # 초벌 파일 없음
        lambda w: w.update(rows=without_doc(w["rows"], FTR)),  # 722→705, 후보 없던 문서
        lambda w: w.update(rows=with_tags(w["rows"], OLD[0], "FX_RELAY")),  # manifest 에 없는 FX_RELAY 잔여
        lambda w: w.update(
            rows={c: (d, p, ()) if d == APG else (d, p, ts) for c, (d, p, ts) in w["rows"].items()}
        ),  # 다시 적재 안 함
    ],
)
def test_broken_world_is_a_problem(broken) -> None:  # noqa: ANN001
    w = _world()
    broken(w)
    assert _problems(w) != []


# ───────── 실행 도구: 예약 호출 0회 ─────────


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict, list]:
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", tmp_path / "queries_holdout.json")
    (tmp_path / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    w, calls, snap = _world(), [], object()
    grades = tmp_path / "answers_corpus.json"
    grades.write_text(json.dumps(w["grades"], ensure_ascii=False), encoding="utf-8")
    (tmp_path / "draft.json").write_bytes(w["raw"])
    monkeypatch.setattr(live, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(live, "GRADES_FILE", grades)
    monkeypatch.setattr(live, "DRAFT_FILE", tmp_path / "draft.json")
    monkeypatch.setattr(live, "_applied_doc", lambda: w["applied"])
    monkeypatch.setattr(live, "_manifest", lambda: (w["manifest"], "x"))
    monkeypatch.setattr(live, "_snapshot_session", lambda: contextlib.nullcontext(snap))
    monkeypatch.setattr(
        live, "read_tags", lambda s: (ids_of(w["rows"]), 0, len(w["rows"])) if s is snap else pytest.fail()
    )
    monkeypatch.setattr(live, "read_corpus", lambda s: w["rows"] if s is snap else pytest.fail())
    monkeypatch.setattr(cl, "reserve", lambda *a: calls.append(a))
    return w, calls


def test_reserve_ready_world_reserves_once(env: tuple[dict, list]) -> None:
    w, calls = env
    assert live.reserve_cmd(lambda _m: None) == 0 and len(calls) == 1


@pytest.mark.parametrize("key", ["grades", "applied", "fintrac", "fx_relay"])
def test_reserve_refuses_without_calling_reserve(env: tuple[dict, list], key: str) -> None:
    w, calls = env
    if key == "grades":
        live.GRADES_FILE.unlink()
    elif key == "applied":
        w["applied"] = {}
    elif key == "fintrac":
        w["rows"] = without_doc(w["rows"], FTR)
    else:
        w["rows"] = with_tags(w["rows"], OLD[0], "FX_RELAY")
    assert live.reserve_cmd(lambda _m: None) == 2 and calls == []


def test_tags_and_locations_come_from_one_snapshot(
    monkeypatch: pytest.MonkeyPatch, env: tuple[dict, list]
) -> None:
    """⑮ 스냅샷 밖 읽기를 섞으면 통과하던 조합: 태그 = 정상, 위치 = 등급 0 청크 하나 빠짐 → 같은 스냅샷이면 거절."""
    w, calls = env
    gone = next(c for c, d, _ in NEW if d == FIN)
    state = {"ids": ids_of(w["rows"]), "rows": {c: v for c, v in w["rows"].items() if c != gone}}
    monkeypatch.setattr(live, "_snapshot_session", lambda: contextlib.nullcontext(state))
    monkeypatch.setattr(live, "read_tags", lambda s: (s["ids"], 0, len(s["rows"])))
    monkeypatch.setattr(live, "read_corpus", lambda s: s["rows"])
    assert live.reserve_cmd(lambda _m: None) == 2 and calls == []


# ───────── ⑯ 등급 칸 ID = (유형, chunk_id) ─────────


def test_grade_key_comes_from_typology_and_chunk() -> None:
    assert tags.grade_key("CYCLE", "ab12cd34" + "0" * 56) == "CY-ab12cd34"
    assert tags.grade_key("GATHER_SCATTER", HIT) == f"GS-{HIT[:8]}"


def test_grade_cells_copied_from_another_draft_sheet_are_refused(tmp_path: Path) -> None:
    """다른 초벌의 시트(같은 CY-001 이 다른 청크)에서 등급 칸을 복사 → 계산 ID 가 달라 거절."""
    from tests.str import rag_corpus_sheet as cs
    from tests.str.test_rag_corpus_sheet import DB, SCOPE, _export, _fill

    other = [r for r in SCOPE if r[1] != "a1" * 32]  # 첫 CYCLE 후보가 다른 초벌
    a = _export(tmp_path / "a")
    _fill(a, lambda r: 2 if r["행"] == "CY-001" else 0)
    cells = [r["확인등급"] for r in csv_rows(a)]
    b = tmp_path / "b" / "s" / cs.SHEET_NAME
    assert cs.export_corpus(b.parent, other, {c: v[2] for c, v in DB.items()}, out=lambda _m: None) == 0
    rows = csv_rows(b)
    for r, cell in zip(rows, cells, strict=False):
        r["확인등급"] = cell
    write_rows(b, rows, cs.COLUMNS)
    with pytest.raises(ValueError):
        cs.read_and_build(b, other, DB, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32)


def test_apply_retry_restores_missing_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """⑬ 등급 파일·manifest 는 반영됐지만 공용 표식이 없음 → 같은 입력 재시도가 표식을 복구하고 0, 그 뒤는 할 일 없음."""
    from tests.str.test_rag_corpus_sheet import _apply_env

    sheet_live, args, manifest = _apply_env(monkeypatch, tmp_path)
    assert sheet_live.run_command(args, lambda _m: None) == 0
    marker = manifest.parent / "pdf" / ck.APPLIED_NAME
    marker.unlink()
    assert sheet_live.run_command(args, lambda _m: None) == 0 and marker.exists()
    assert sheet_live.run_command(args, lambda _m: None) == 1


def csv_rows(path: Path) -> list[dict]:
    import csv

    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows: list[dict], columns: list[str]) -> None:
    import csv

    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
