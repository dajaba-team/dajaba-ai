"""SCRUM-305 holdout_v2 원장 — 추가 검토 2·3·5 회귀 (docs/str/10 "305 실행 기록"). 임시 폴더만.

공용 값·픽스처는 `test_rag_eval_corpus_ledger` 에서 가져옴(파일 200줄 관문으로 나눔).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.str import rag_eval_corpus_ledger as cl
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR
from tests.str.test_rag_eval_corpus_ledger import (
    ALL_PASS,
    FIRST,
    GRADES_SHA,
    PRE,
    _lines,
    _returns,
)


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", tmp_path / "queries_holdout.json")
    (tmp_path / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    return tmp_path


# ───────── 추가 검토 2 ─────────


def test_set_id_is_the_fixed_normalized_hash(eval_dir: Path) -> None:
    """① 세트 식별 = 304 가 고정한 질의 정규화 해시(test_rag_eval_corpus_set 과 같은 함수·같은 값)."""
    from tests.str.test_rag_eval_corpus_set import QUERIES_SHA256

    assert cl.set_sha256(eval_dir) == QUERIES_SHA256


@pytest.mark.parametrize("closing", ["aborted", "grades_changed"])
def test_reformatted_queries_cannot_reserve_again(eval_dir: Path, closing: str) -> None:
    """① 중단(aborted·종료 코드 3) 뒤 질의 파일 서식만 바꿔도 같은 세트 — 재예약 거절."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.record(eval_dir, "aborted", reason=closing)
    path = eval_dir / "queries_holdout.json"
    path.write_text(
        json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=4, sort_keys=True), encoding="utf-8"
    )
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) == cl.USED


def test_record_cannot_write_judged(eval_dir: Path) -> None:
    """② 판정 줄은 judge_locked 만 — record 로 judged 를 직접 쓰면 거절."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    cl.record(eval_dir, "done")
    with pytest.raises(ValueError):
        cl.record(eval_dir, "judged", prior=dict(ALL_PASS.statuses), prior_sha256=ALL_PASS.sha256())
    assert [e["status"] for e in _lines(eval_dir)] == ["reserved", "judged", "done"]


def test_judge_refuses_a_broken_ledger(eval_dir: Path) -> None:
    """② 손으로 미달을 푼 판정 줄이 끼어든 원장 — judge_locked 가 판정 전에 원장 전체를 점검해 거절."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    cl.record(eval_dir, "done")
    line = {"set_sha256": cl.set_sha256(eval_dir), "status": "judged", "prior": dict(ALL_PASS.statuses),
            "prior_sha256": ALL_PASS.sha256(), "from_prior_sha256": FIRST.sha256(), "at": "t"}  # fmt: skip
    done = {"set_sha256": cl.set_sha256(eval_dir), "status": "done", "at": "t"}
    with (eval_dir / cl.LEDGER_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n" + json.dumps(done) + "\n")
    seen: list = []
    with pytest.raises(ValueError):
        cl.judge_locked(eval_dir, _returns(ALL_PASS, seen))
    assert seen == []  # 판정(compute)까지 가지 않음


def test_judge_reads_the_locked_ledger_once(eval_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """추가 검토 3 ③ — 잠금 중 경로의 원장이 깨끗한 파일로 바뀌어도(경로로 다시 읽으면 통과) 잠근 내용 기준으로 거절."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    cl.record(eval_dir, "done")
    clean = (eval_dir / cl.LEDGER_NAME).read_text(encoding="utf-8")
    line = {"set_sha256": cl.set_sha256(eval_dir), "status": "judged", "prior": dict(ALL_PASS.statuses),
            "prior_sha256": ALL_PASS.sha256(), "from_prior_sha256": FIRST.sha256(), "at": "t"}  # fmt: skip
    done = {"set_sha256": cl.set_sha256(eval_dir), "status": "done", "at": "t"}
    with (eval_dir / cl.LEDGER_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n" + json.dumps(done) + "\n")
    real = Path.read_text

    def swapped(self: Path, *a, **k) -> str:  # noqa: ANN002, ANN003
        return clean if self.name == cl.LEDGER_NAME else real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", swapped)
    seen: list = []
    with pytest.raises(ValueError):
        cl.judge_locked(eval_dir, _returns(ALL_PASS, seen))
    assert seen == []


# ───────── 추가 검토 5 — 세트 해시 하나(304 고정값) ─────────


def _reduce_cycle(eval_dir: Path, n: int = 2) -> None:
    path = eval_dir / "queries_holdout.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    cycle = [q["id"] for q in doc["queries"] if q["typology"] == "CYCLE"][:n]
    doc["queries"] = [q for q in doc["queries"] if q["id"] not in cycle]
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_reserve_refuses_a_set_other_than_the_fixed_one(eval_dir: Path) -> None:
    """(1) CYCLE 행 2개가 빠진 eval_dir 로 예약 → 거절, 원장 0줄."""
    _reduce_cycle(eval_dir)
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) == cl.NOT_FIXED
    assert _lines(eval_dir) == []


def test_judge_locked_refuses_a_set_other_than_the_fixed_one(eval_dir: Path) -> None:
    """예약 줄이 이미 있는 축소 세트(손으로 쓴 줄)에서도 판정 줄 0."""
    _reduce_cycle(eval_dir)
    line = {"set_sha256": cl.set_sha256(eval_dir), "status": "reserved", "pre_sha256": PRE.sha256(),
            "grades_sha256": GRADES_SHA, "at": "t"}  # fmt: skip
    (eval_dir / cl.LEDGER_NAME).write_text(json.dumps(line) + "\n", encoding="utf-8")
    seen: list = []
    with pytest.raises(ValueError):
        cl.judge_locked(eval_dir, _returns(FIRST, seen))
    assert seen == [] and len(_lines(eval_dir)) == 1
