"""SCRUM-275 보류용 한 번만 (docs/str/10 "판정 순서"·"도구") — 실행 전 거절 규칙 · 원장 예약. 파일만, DB·임베딩·ES 0."""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import pytest

from tests.str import rag_eval_v2_ledger as ledger
from tests.str import rag_eval_v2_live as live
from tests.str.rag_eval_v2_support import EVAL_DIR


@pytest.fixture
def eval_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copy(EVAL_DIR / ledger.HOLDOUT_QUERIES, tmp_path / ledger.HOLDOUT_QUERIES)
    (tmp_path / ledger.LEDGER_NAME).write_text("", encoding="utf-8")
    monkeypatch.setattr(live, "EVAL_DIR", tmp_path)
    return tmp_path


def _ledger(eval_dir: Path) -> list[dict]:
    text = (eval_dir / ledger.LEDGER_NAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc), encoding="utf-8")


def _checked(path: Path) -> None:
    _write(
        path, {"queries": [{"query_id": "H01", "checked_by": "x", "checked_at": "2026-11-20", "answers": []}]}
    )


def test_dev_is_never_refused(eval_dir: Path) -> None:
    _write(eval_dir / "result_dev.json", {"status": "done", "keyword": True})
    assert live.refuse_reason("dev", True) is None


def test_holdout_needs_dev_result(eval_dir: Path) -> None:
    _checked(eval_dir / "answers_holdout.json")
    assert "개발용 결과" in (live.refuse_reason("holdout", True) or "")


def test_holdout_needs_checked_answers(eval_dir: Path) -> None:
    _write(eval_dir / "result_dev.json", {"status": "done", "keyword": True})
    assert "정답 확인" in (live.refuse_reason("holdout", True) or "")
    _write(
        eval_dir / "answers_holdout.json",
        {"queries": [{"query_id": "H01", "checked_by": None, "answers": []}]},
    )
    assert "정답 확인" in (live.refuse_reason("holdout", True) or "")


def test_holdout_needs_same_keyword_setting_as_dev(eval_dir: Path) -> None:
    _write(eval_dir / "result_dev.json", {"status": "done", "keyword": False})
    _checked(eval_dir / "answers_holdout.json")
    assert "키워드 설정" in (live.refuse_reason("holdout", True) or "")
    assert live.refuse_reason("holdout", False) is None


def test_holdout_only_once(eval_dir: Path) -> None:
    _write(eval_dir / "result_dev.json", {"status": "done", "keyword": True})
    _checked(eval_dir / "answers_holdout.json")
    assert live.refuse_reason("holdout", True) is None
    _write(eval_dir / "result_holdout.json", {})
    assert "한 번만" in (live.refuse_reason("holdout", True) or "")


def _ready(eval_dir: Path) -> None:
    _write(eval_dir / "result_dev.json", {"status": "done", "keyword": True, "runs": []})
    _checked(eval_dir / "answers_holdout.json")


def test_holdout_needs_finished_dev_result(eval_dir: Path) -> None:
    _write(eval_dir / "result_dev.json", {"status": "aborted", "keyword": True})
    _checked(eval_dir / "answers_holdout.json")
    assert "끝난 상태" in (live.refuse_reason("holdout", True) or "")


def test_repo_ledger_exists_and_is_empty() -> None:
    assert (EVAL_DIR / ledger.LEDGER_NAME).read_text(encoding="utf-8") == ""  # git 추적 빈 파일로 시작


def test_reserve_is_exclusive(eval_dir: Path) -> None:
    assert live.reserve_holdout() is None
    assert live.reserve_holdout() == ledger.USED
    entries = _ledger(eval_dir)
    assert len(entries) == 1 and entries[0]["status"] == "reserved"
    assert set(entries[0]) == {"set_sha256", "status", "at"}  # 정답·결과 없음


def test_concurrent_reserve_only_one_wins(eval_dir: Path) -> None:
    barrier, results = threading.Barrier(8), []

    def attempt() -> None:
        barrier.wait()
        results.append(live.reserve_holdout())

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(None) == 1 and len(_ledger(eval_dir)) == 1


def _boom(calls: list[str]):
    def boom(split: str, use_keyword: bool, settings: object, done: list[str]) -> dict:
        calls.append(split)
        done.append("H01")  # H01 은 봤고 H02 에서 끊김
        raise RuntimeError("embedding down")

    return boom


def test_aborted_holdout_keeps_record_and_refuses_rerun(
    eval_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ready(eval_dir)
    calls: list[str] = []
    monkeypatch.setattr(live, "evaluate", _boom(calls))
    with pytest.raises(RuntimeError):
        live.main(["--split", "holdout"], settings=object())
    record = json.loads((eval_dir / "result_holdout.json").read_text(encoding="utf-8"))
    assert record["status"] == "aborted" and record["queries_run"] == ["H01"]
    assert [e["status"] for e in _ledger(eval_dir)] == ["reserved", "aborted"]
    assert live.main(["--split", "holdout"], settings=object()) == 2  # 다시 못 돌림
    assert calls == ["holdout"] and "한 번만" in capsys.readouterr().out


def test_deleting_result_file_does_not_reopen_holdout(
    eval_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(eval_dir)
    calls: list[str] = []
    monkeypatch.setattr(live, "evaluate", _boom(calls))
    with pytest.raises(RuntimeError):
        live.main(["--split", "holdout"], settings=object())
    (eval_dir / "result_holdout.json").unlink()  # 결과 파일 정리
    assert live.main(["--split", "holdout"], settings=object()) == 2
    assert calls == ["holdout"]


def test_other_output_path_does_not_reopen_holdout(
    eval_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(eval_dir)
    calls: list[str] = []
    monkeypatch.setattr(live, "evaluate", _boom(calls))
    with pytest.raises(RuntimeError):
        live.main(["--split", "holdout"], settings=object())
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    real_result_path = live.result_path
    monkeypatch.setattr(
        live,
        "result_path",
        lambda split: elsewhere / f"result_{split}.json" if split == "holdout" else real_result_path(split),
    )
    assert live.main(["--split", "holdout"], settings=object()) == 2
    assert calls == ["holdout"]


def test_missing_ledger_refuses_with_restore_message(
    eval_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ready(eval_dir)
    (eval_dir / ledger.LEDGER_NAME).unlink()
    calls: list[str] = []
    monkeypatch.setattr(live, "evaluate", _boom(calls))
    assert live.main(["--split", "holdout"], settings=object()) == 2
    assert calls == [] and "원장 복구 필요" in capsys.readouterr().out
    assert not (eval_dir / ledger.LEDGER_NAME).exists()  # 거절만 — 새로 만들지 않음


def test_finished_holdout_is_recorded_done(eval_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(eval_dir)
    monkeypatch.setattr(
        live, "evaluate", lambda split, use_keyword, settings, done: {"runs": [], "verdict": {}}
    )
    assert live.main(["--split", "holdout"], settings=object()) == 0
    assert [e["status"] for e in _ledger(eval_dir)] == ["reserved", "done"]


def test_aborted_dev_keeps_previous_dev_result(eval_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(eval_dir / "result_dev.json", {"status": "done", "keyword": True, "runs": ["previous"]})

    def boom(split: str, use_keyword: bool, settings: object, done: list[str]) -> dict:
        raise RuntimeError("es down")

    monkeypatch.setattr(live, "evaluate", boom)
    with pytest.raises(RuntimeError):
        live.main(["--split", "dev"], settings=object())
    assert json.loads((eval_dir / "result_dev.json").read_text(encoding="utf-8"))["runs"] == ["previous"]
    assert _ledger(eval_dir) == []  # 개발용은 원장에 안 씀
