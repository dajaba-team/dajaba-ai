"""SCRUM-305 실행 도구가 멈추는 경우 (docs/str/10 "305 실행 기록"). DB·검색·리포 원장 0 — 집계·검색을 가짜로."""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

import pytest

from tests.str import rag_eval_corpus_ledger as cl
from tests.str import rag_eval_corpus_live as live
from tests.str.rag_eval_corpus_guard import FAN_CASE_IDS
from tests.str.rag_eval_corpus_preflight import BASELINE_MANIFEST_SHA256, BASELINE_TAGGED
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR

COUNTS = {"CYCLE": ["c"] * 12, "SCATTER_GATHER": [], "GATHER_SCATTER": ["g"] * 11, "FX_RELAY": []}
GRADES = {"checked_by": "확인자", "checked_at": "2026-11-22", "grades": {"CYCLE": [{"chunk_id": "c", "grade": 1}],
          "GATHER_SCATTER": [{"chunk_id": "g", "grade": 0}]}}  # fmt: skip


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", tmp_path / "queries_holdout.json")
    (tmp_path / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    grades = tmp_path / "answers_corpus.json"
    grades.write_text(json.dumps(GRADES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(live, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(live, "GRADES_FILE", grades)
    monkeypatch.setattr(live, "RESULT_FILE", tmp_path / "result.json")
    monkeypatch.setattr(live, "_manifest", lambda: ({"documents": []}, BASELINE_MANIFEST_SHA256))
    monkeypatch.setattr(live, "read_tags", lambda *_a: (COUNTS, 0, 722))
    monkeypatch.setattr(live, "_search", lambda *_a: (_ for _ in ()).throw(AssertionError("검색하면 안 됨")))
    monkeypatch.setattr(live, "read_corpus", lambda *_a: {})
    monkeypatch.setattr(
        live.ck, "corpus_ready_problems", lambda **_k: []
    )  # 대조 자체는 test_rag_corpus_review3
    monkeypatch.setattr(live, "_snapshot_session", contextlib.nullcontext)  # DB 0 — 스냅샷은 -m db 테스트


def _statuses(tmp_path: Path) -> list[str]:  # 원장 상태 순서
    return [
        json.loads(x)["status"] for x in (tmp_path / cl.LEDGER_NAME).read_text(encoding="utf-8").splitlines()
    ]


def test_fan_tag_on_new_doc_stops_before_reserve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(live, "read_tags", lambda *_a: (COUNTS, 1, 722))
    out: list[str] = []
    assert live.run(out.append) == 2
    assert "FAN 태그 1개" in out[0] and _statuses(tmp_path) == []


def test_fan_tag_in_manifest_stops_before_reserve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = {"id": "apg-typologies-2025", "typologies": [], "typology_pages": {"FAN_IN": [3]}}
    monkeypatch.setattr(live, "_manifest", lambda: ({"documents": [doc]}, "0" * 64))
    out: list[str] = []
    assert live.run(out.append) == 2 and _statuses(tmp_path) == []


def test_existing_result_file_stops_before_reserve(tmp_path: Path) -> None:
    live.RESULT_FILE.write_text("{}", encoding="utf-8")
    out: list[str] = []
    assert live.run(out.append) == 2 and _statuses(tmp_path) == []


def test_id_only_change_stops_reserve_and_run(tmp_path: Path) -> None:
    """추가 검토 3 ② — 질의 id 만 바꿔도 304 고정 해시와 달라 예약·검색 0회."""
    path = tmp_path / "queries_holdout.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["queries"][0]["id"] = "XX99"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    out: list[str] = []
    assert live.reserve_cmd(out.append) == 2 and live.run(out.append) == 2
    assert _statuses(tmp_path) == []


def test_run_without_committed_reservation_searches_nothing(tmp_path: Path) -> None:
    """추가 검토 3 ① — 예약만 하고 커밋 안 함(또는 예약 없음) → 검색 0회."""
    out: list[str] = []
    assert live.run(out.append) == 2
    assert live.reserve_cmd(out.append) == 0 and _statuses(tmp_path) == ["reserved"]
    assert live.run(out.append) == 2  # 임시 폴더는 git 리포가 아님 — 커밋된 예약 줄 없음
    assert _statuses(tmp_path) == ["reserved"]


@pytest.mark.parametrize("change", ["delete", "edit"])
def test_grades_file_changed_during_search_stops_without_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str
) -> None:
    """추가 검토 1 ② — 검색 중 등급 파일이 사라지거나 바뀌면 판정 안 함, 원장 aborted, 0 아닌 종료 코드."""
    out0: list[str] = []
    assert live.reserve_cmd(out0.append) == 0
    monkeypatch.setattr(
        live.gate, "open_search_in", lambda *_a: None
    )  # 커밋·표식은 test_rag_eval_corpus_gate

    def search(facts_list: list, *_a) -> list[list[str]]:
        if change == "delete":
            live.GRADES_FILE.unlink()
        else:
            live.GRADES_FILE.write_text(json.dumps({**GRADES, "checked_by": "다른 사람"}), encoding="utf-8")
        return [[] for _ in facts_list]

    monkeypatch.setattr(live, "_search", search)
    out: list[str] = []
    assert live.run(out.append) == 3
    assert _statuses(tmp_path) == ["reserved", "aborted"] and not live.RESULT_FILE.exists()


def _fan_search(hits: int):  # noqa: ANN202
    """D07~D10 중 앞 `hits` 개만 준혁 등급 ≥1 청크를 돌려줌."""
    grades = live._dev_fan_grades()

    def search(facts_list: list, *_a) -> list[list[str]]:
        assert len(facts_list) == len(FAN_CASE_IDS)
        good = [next(c for c, g in grades[i].items() if g >= 1) for i in FAN_CASE_IDS]
        return [[good[n]] if n < hits else ["0" * 64] for n in range(len(FAN_CASE_IDS))]

    return search


def _restored(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = {t: ["x"] * BASELINE_TAGGED[t] for t in ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER", "FX_RELAY")}
    monkeypatch.setattr(live, "read_tags", lambda *_a: (ids, 0, 425))
    monkeypatch.setattr(live, "_fan_counts", lambda: {"FAN_IN": 19, "FAN_OUT": 6})


def test_check_restore_needs_fan_baseline_search(monkeypatch: pytest.MonkeyPatch) -> None:
    _restored(monkeypatch)
    monkeypatch.setattr(live, "_search", _fan_search(4))
    out: list[str] = []
    assert live.check_restore(out.append) == 0


@pytest.mark.parametrize("search", ["drop", "error"])
def test_check_restore_fails_on_fan_drop_or_search_error(
    monkeypatch: pytest.MonkeyPatch, search: str
) -> None:
    """추가 검토 1 ④ — 집계가 같아도 D07~D10 hit@3 0.75·검색 실패면 0 아닌 종료 코드."""
    _restored(monkeypatch)
    if search == "drop":
        monkeypatch.setattr(live, "_search", _fan_search(3))
    out: list[str] = []
    assert live.check_restore(out.append) == 1
    assert ("0.75" in out[-1]) if search == "drop" else ("검색" in out[-1])


def test_check_restore_reports_expanded_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "_fan_counts", lambda: {"FAN_IN": 19, "FAN_OUT": 6})
    monkeypatch.setattr(live, "_search", _fan_search(4))
    out: list[str] = []
    assert live.check_restore(out.append) == 1 and "722" in out[-1]


def test_tag_inconsistency_stops_before_reserve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """태그 도구 추가 검토 2 ⑧ — 등급 게시 뒤 manifest 교체 실패·다시 적재 안 함 → 예약·검색 0."""
    monkeypatch.setattr(
        live.ck, "corpus_ready_problems", lambda **_k: ["CYCLE: DB 태그 청크가 확인 등급·manifest 와 다름"]
    )
    out: list[str] = []
    assert live.reserve_cmd(out.append) == 2 and live.run(out.append) == 2
    assert _statuses(tmp_path) == []
