"""SCRUM-275-3 리포 보류용 원장 모양 (docs/str/10 "보류용 한 번만"·"결과 (11/19)") — 빈 파일(실행 전) · 실행 뒤 짝 줄."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.str import rag_eval_v2_ledger as ledger
from tests.str import rag_eval_v2_live as live
from tests.str.rag_eval_v2_support import EVAL_DIR

REQUIRED = {"set_sha256", "status", "at"}
CLOSERS = {"done", "aborted"}
# 보류용을 새로 돌리면 그 세트 해시를 여기 추가(같은 PR)
CONSUMED_HOLDOUT_SETS = [("a7562b4532da01aa4eadd4f08b47d21614bddb4f7c9bfc0433ad3e57c3caae55", "done")]


Consumed = list[tuple[str, str]]


def ledger_problems(eval_dir: Path, consumed: Consumed = CONSUMED_HOLDOUT_SETS) -> list[str]:
    """같은 해시마다 reserved 1줄 → done|aborted 1줄(순서대로) · 해시 ∈ {지금 세트} ∪ 이미 쓴 세트. 문제 목록."""
    problems: list[str] = []
    allowed = {ledger.set_sha256(eval_dir)} | {d for d, _ in consumed}
    state: dict[str, str] = {}  # set_sha256 → reserved | closed
    for n, line in enumerate((eval_dir / ledger.LEDGER_NAME).read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"{n}: JSON 아님")
            continue
        if not isinstance(entry, dict) or not set(entry) >= REQUIRED:
            problems.append(f"{n}: 칸 빠짐")
            continue
        digest, status = entry["set_sha256"], entry["status"]
        if digest not in allowed:
            problems.append(f"{n}: 허용 집합에 없는 해시")
        if status == "reserved" and digest not in state:
            state[digest] = "reserved"
        elif status in CLOSERS and state.get(digest) == "reserved":
            state[digest] = "closed"
        else:
            problems.append(f"{n}: 순서·status 이상({status})")
    problems += [f"짝 없는 reserved {d[:8]}" for d, s in state.items() if s == "reserved"]
    return problems


def consumed_problems(eval_dir: Path, consumed: Consumed = CONSUMED_HOLDOUT_SETS) -> list[str]:
    """이미 쓴 세트마다 원장에 reserved 1줄 → 기대 상태 1줄이 남아 있는지 — 결과 파일·출력 경로와 무관."""
    path = eval_dir / ledger.LEDGER_NAME
    if not path.is_file():
        return ["원장 없음"]
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    problems = []
    for digest, closed in consumed:
        statuses = [e.get("status") for e in entries if e.get("set_sha256") == digest]
        if statuses != ["reserved", closed]:
            problems.append(f"쓴 세트 {digest[:8]} 기록 {statuses} ≠ ['reserved', '{closed}']")
    return problems


def current_set_recorded(eval_dir: Path, consumed: Consumed = CONSUMED_HOLDOUT_SETS) -> bool:
    """지금 보류용 세트가 이미 쓴 목록에 있으면 원장에도 그 해시가 있어야 함."""
    digest = ledger.set_sha256(eval_dir)
    if digest not in {d for d, _ in consumed}:
        return True
    return digest in (eval_dir / ledger.LEDGER_NAME).read_text(encoding="utf-8")


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    shutil.copy(EVAL_DIR / ledger.HOLDOUT_QUERIES, tmp_path / ledger.HOLDOUT_QUERIES)
    (tmp_path / ledger.LEDGER_NAME).write_text("", encoding="utf-8")
    return tmp_path


def _write(eval_dir: Path, *entries: dict | str) -> None:
    lines = (e if isinstance(e, str) else json.dumps(e) for e in entries)
    (eval_dir / ledger.LEDGER_NAME).write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")


def _e(eval_dir: Path, status: str, digest: str | None = None, **extra: object) -> dict:
    sha = digest or ledger.set_sha256(eval_dir)
    return {"set_sha256": sha, "status": status, "at": "2026-11-19T06:47:00+00:00", **extra}


def test_repo_ledger_is_well_formed() -> None:
    assert (EVAL_DIR / ledger.LEDGER_NAME).is_file()  # 없으면 실행 도구도 "원장 복구 필요"로 거절
    assert ledger_problems(EVAL_DIR) == []
    assert consumed_problems(EVAL_DIR) == []
    assert current_set_recorded(EVAL_DIR)


def test_empty_and_pairs_pass(eval_dir: Path) -> None:
    assert ledger_problems(eval_dir) == []  # 보류용을 아직 안 돌린 리포
    _write(eval_dir, _e(eval_dir, "reserved"), _e(eval_dir, "done"))
    assert ledger_problems(eval_dir) == []
    _write(eval_dir, _e(eval_dir, "reserved"), _e(eval_dir, "aborted", reason="X", queries_run=3))
    assert ledger_problems(eval_dir) == []


def test_unpaired_reserved_fails(eval_dir: Path) -> None:
    _write(eval_dir, _e(eval_dir, "reserved"))
    assert any("짝 없는 reserved" in p for p in ledger_problems(eval_dir))


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["reserved", "finished"], "순서·status 이상(finished)"),
        (["done", "reserved"], "순서·status 이상(done)"),
        (["reserved", "done", "reserved"], "순서·status 이상(reserved)"),
    ],
)
def test_unknown_status_or_order_fails(eval_dir: Path, statuses: list[str], expected: str) -> None:
    _write(eval_dir, *(_e(eval_dir, s) for s in statuses))
    assert any(expected in p for p in ledger_problems(eval_dir))


def test_other_set_hash_fails(eval_dir: Path) -> None:
    _write(eval_dir, _e(eval_dir, "reserved", "b" * 64), _e(eval_dir, "done", "b" * 64))
    assert any("허용 집합에 없는 해시" in p for p in ledger_problems(eval_dir))


def test_broken_line_fails(eval_dir: Path) -> None:
    _write(eval_dir, "not json", {"set_sha256": "x", "status": "reserved"})
    assert ledger_problems(eval_dir)[:2] == ["1: JSON 아님", "2: 칸 빠짐"]


@pytest.fixture
def used_dir(eval_dir: Path) -> Path:
    _write(eval_dir, _e(eval_dir, "reserved"), _e(eval_dir, "done"))
    assert consumed_problems(eval_dir) == []  # 이 복사본은 리포와 같은 세트 해시
    return eval_dir


def test_consumed_set_wiped_ledger_fails(used_dir: Path) -> None:
    _write(used_dir)  # ① 두 줄 전부 삭제 — 형식 검사는 빈 원장이라 통과
    assert ledger_problems(used_dir) == []
    assert consumed_problems(used_dir) and not current_set_recorded(used_dir)


def test_consumed_set_done_line_removed_fails(used_dir: Path) -> None:
    _write(used_dir, _e(used_dir, "reserved"))  # ② done 줄만 삭제
    assert consumed_problems(used_dir)


def test_consumed_set_hash_edited_fails(used_dir: Path) -> None:
    sha = ledger.set_sha256(used_dir)
    edited = ("b" if sha[0] != "b" else "c") + sha[1:]  # ③ 해시 한 글자
    _write(used_dir, _e(used_dir, "reserved", edited), _e(used_dir, "done", edited))
    assert consumed_problems(used_dir) and not current_set_recorded(used_dir)


def test_consumed_set_ledger_and_result_gone_fails(used_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (used_dir / ledger.LEDGER_NAME).unlink()  # ④ 원장 삭제 + 결과 삭제 + 출력 경로 변경
    (used_dir / "result_holdout.json").unlink(missing_ok=True)
    monkeypatch.setattr(live, "EVAL_DIR", used_dir)
    monkeypatch.setattr(live, "result_path", lambda split: used_dir / "elsewhere" / f"result_{split}.json")
    assert not live.result_path("holdout").exists()
    assert consumed_problems(used_dir) == ["원장 없음"]


def _as_holdout_v2(eval_dir: Path) -> tuple[dict, dict]:
    """과거 세트 두 줄을 남기고 지금 세트를 새 내용으로 바꿈(holdout_v2 흉내)."""
    old = (_e(eval_dir, "reserved"), _e(eval_dir, "done"))
    path = eval_dir / ledger.HOLDOUT_QUERIES
    path.write_bytes(path.read_bytes() + b"\n")
    return old


def test_new_set_keeps_old_lines_before_and_after_run(used_dir: Path) -> None:
    old = _as_holdout_v2(used_dir)
    _write(used_dir, *old)  # ① 새 세트 실행 전
    assert ledger_problems(used_dir) == [] and consumed_problems(used_dir) == []
    assert current_set_recorded(used_dir)
    _write(used_dir, *old, _e(used_dir, "reserved"), _e(used_dir, "done"))  # ② 실행 뒤 + 목록에 새 해시
    both = [*CONSUMED_HOLDOUT_SETS, (ledger.set_sha256(used_dir), "done")]
    assert ledger_problems(used_dir, both) == [] and consumed_problems(used_dir, both) == []
    assert current_set_recorded(used_dir, both)


def test_new_set_with_old_lines_removed_fails(used_dir: Path) -> None:
    _as_holdout_v2(used_dir)
    _write(used_dir)  # ③ 과거 두 줄 삭제
    assert consumed_problems(used_dir)
