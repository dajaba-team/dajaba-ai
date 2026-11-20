"""SCRUM-305 holdout_v2 원장 (docs/str/10 "305 실행 기록" 원장 표 ①~⑤ · 상태 전이). 덧붙이기만 · git 추적 파일.

275 원장 모듈(`rag_eval_v2_ledger`)은 안 고치고 같은 덧붙이기를 씀. 줄 종류:
- 예약(검색 전) `{set_sha256, status: reserved, pre_sha256, grades_sha256, at}` — 같은 세트 해시가 있으면 거절
- 판정 `{set_sha256, status: judged, prior, prior_sha256, from_prior_sha256, at}` — `judge_locked` 만 씀
- 끝 `{set_sha256, status: done | aborted, at, …}`
상태 전이는 `TRANSITIONS` 하나를 기록 함수와 형식 점검이 같이 씀. 판정은 원장 읽기부터 줄 기록까지 한 잠금 안이고,
앞 판정의 미달(fail)을 뒤 판정이 풀 수 없다(추가 검토 1).
"""

from __future__ import annotations

import fcntl
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from tests.str.rag_eval_corpus_guard import Prior, normalized_sha256
from tests.str.rag_eval_v2_ledger import _append, _now

LEDGER_NAME = "holdout_ledger.jsonl"
MISSING = "원장이 없음 — 원장 복구 필요(git 에서 tests/str/rag_eval_corpus/holdout_ledger.jsonl 되살림)"
USED = "이 holdout_v2 세트는 원장에 이미 있음 — 한 번만(중단·결과 파일 삭제·서식 변경과 무관)"
CLOSE_STATUSES = ("done", "aborted")  # record 가 쓰는 줄 — judged 는 judge_locked 만
HOLDOUT_QUERIES = "queries_holdout.json"
# 304 가 결과 보기 전에 고정한 질의 목록 정규화 해시 — 예약·판정 줄은 이 세트에만(추가 검토 5, test_rag_eval_corpus_set 과 같은 값)
QUERIES_SHA256 = "cd66f3b7c4e9c1f434aef9fa2456046621440facfdcae793ba3567971428139a"
NOT_FIXED = "eval_dir 질의 목록이 304 고정값과 다름(축소·재정렬·id) — 예약·판정 안 함"
# 마지막 상태 → 다음에 올 수 있는 상태. judged 는 바로 앞이 reserved 면 첫 판정, done 이면 재판정
TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"reserved"}),
    "reserved": frozenset({"judged", "aborted"}),
    "judged": frozenset({"done", "aborted"}),
    "done": frozenset({"judged"}),
    "aborted": frozenset(),
}
_SHA = re.compile(r"[0-9a-f]{64}")
Compute = Callable[[str, str, Prior | None, str | None], tuple[dict[str, Any], Prior]]


def set_sha256(eval_dir: Path) -> str:
    """세트 식별 = 질의 목록의 정규화 해시(304 가 고정한 값 — test_rag_eval_corpus_set 과 같은 함수). 서식과 무관."""
    return normalized_sha256(json.loads((eval_dir / HOLDOUT_QUERIES).read_text(encoding="utf-8"))["queries"])


@contextmanager
def _locked(eval_dir: Path) -> Iterator[tuple[IO[str], list[dict[str, Any]], list[str]]]:
    """잠금(flock) 안에서 잠근 파일을 한 번 읽어 (파일, 이 세트의 줄, 전체 줄 원문). 원장이 없으면 ValueError(MISSING)."""
    path = eval_dir / LEDGER_NAME
    if not path.is_file():
        raise ValueError(MISSING)
    digest = set_sha256(eval_dir)
    if digest != QUERIES_SHA256:  # 검증된 해시 하나로 예약 줄·prior·판정 줄(추가 검토 5)
        raise ValueError(NOT_FIXED)
    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        raw = fh.read().splitlines()
        mine = []
        for line in filter(str.strip, raw):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # 형식 점검(problems_of)이 잡음
            if e.get("set_sha256") == digest:
                mine.append(e)
        yield fh, mine, raw


def _last(mine: list[dict[str, Any]]) -> str | None:
    return mine[-1].get("status") if mine else None


def _check_next(mine: list[dict[str, Any]], status: str) -> None:
    if status not in TRANSITIONS.get(_last(mine), frozenset()):
        raise ValueError(f"상태 전이 안 됨: {_last(mine)} → {status}")


def reserve(eval_dir: Path, pre_sha256: str, grades_sha256: str) -> str | None:
    """검색 전. 통과하면 None(예약 줄 — 실행 전 고정값·등급표 해시), 아니면 거절 이유."""
    if not (_SHA.fullmatch(pre_sha256 or "") and _SHA.fullmatch(grades_sha256 or "")):
        raise ValueError("pre_sha256·grades_sha256 must be lowercase sha256 hex")
    try:
        with _locked(eval_dir) as (fh, mine, _):
            if mine:
                return USED
            _append(fh, {"set_sha256": set_sha256(eval_dir), "status": "reserved", "pre_sha256": pre_sha256,
                         "grades_sha256": grades_sha256, "at": _now()})  # fmt: skip
    except ValueError as exc:
        if str(exc) in (MISSING, NOT_FIXED):
            return str(exc)
        raise
    return None


def _pre(mine: list[dict[str, Any]]) -> tuple[str, str]:
    reserved = [e for e in mine if e.get("status") == "reserved"]
    if len(reserved) != 1:
        raise ValueError("예약 줄이 없음 — 판정은 예약(검색 전) 뒤에만")
    return reserved[0]["pre_sha256"], reserved[0]["grades_sha256"]


def _prior(mine: list[dict[str, Any]]) -> tuple[Prior | None, str | None]:
    judged = [e for e in mine if e.get("status") == "judged"]
    if not judged:
        return None, None
    prior = Prior(judged[-1]["prior"])
    if prior.sha256() != judged[-1]["prior_sha256"]:
        raise ValueError("ledger prior differs from its recorded sha256")
    return prior, judged[-1]["prior_sha256"]


def read_pre(eval_dir: Path) -> tuple[str, str]:
    with _locked(eval_dir) as (_, mine, _raw):
        return _pre(mine)


def read_prior(eval_dir: Path) -> tuple[Prior | None, str | None]:
    with _locked(eval_dir) as (_, mine, _raw):
        return _prior(mine)


def _releases(old: Prior | None, new: Prior) -> list[str]:
    return (
        []
        if old is None
        else [t for t, s in old.statuses.items() if s == "fail" and new.statuses[t] != "fail"]
    )


def judge_locked(eval_dir: Path, compute: Compute) -> dict[str, Any]:
    """한 잠금 안: 원장 값(예약 줄·마지막 판정) 읽기 → compute → 전이·미달 해제 검사 → 판정 줄. 거절은 ValueError."""
    with _locked(eval_dir) as (fh, mine, raw):
        broken = problems_of(raw)  # 잠근 파일 내용으로 원장 전체 — 경로를 다시 열지 않음(추가 검토 2·3)
        if broken:
            raise ValueError(f"원장이 깨짐 — 판정 안 함: {broken[:3]}")
        _check_next(mine, "judged")
        pre_sha256, grades_sha256 = _pre(mine)
        prior, prior_sha256 = _prior(mine)
        out, new = compute(pre_sha256, grades_sha256, prior, prior_sha256)
        released = _releases(prior, new)
        if released:
            raise ValueError(f"앞 판정의 미달을 풀 수 없음: {released}")
        _append(fh, {"set_sha256": set_sha256(eval_dir), "status": "judged", "prior": dict(new.statuses),
                     "prior_sha256": new.sha256(), "from_prior_sha256": prior_sha256, "at": _now()})  # fmt: skip
    return out


def record(eval_dir: Path, status: str, **extra: object) -> None:
    """끝(done)·중단(aborted)만 — judged 는 judge_locked 만 씀. 전이 표에 없으면 ValueError. 원장이 없으면 안 만듦."""
    if status not in CLOSE_STATUSES:
        raise ValueError(f"record 는 {CLOSE_STATUSES} 만 — 판정 줄은 judge_locked")
    if not (eval_dir / LEDGER_NAME).is_file():
        return
    with _locked(eval_dir) as (fh, mine, _):
        _check_next(mine, status)
        _append(fh, {"set_sha256": set_sha256(eval_dir), "status": status, "at": _now(), **extra})


def problems(eval_dir: Path) -> list[str]:
    """형식 점검 — 빈 파일 통과. 같은 `TRANSITIONS` · 예약 줄 해시 · 판정 줄 해시·최신 prior·미달 해제."""
    return problems_of((eval_dir / LEDGER_NAME).read_text(encoding="utf-8").splitlines())


def problems_of(lines: list[str]) -> list[str]:
    out: list[str] = []
    by_set: dict[str, list[dict[str, Any]]] = {}
    for n, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            out.append(f"{n}: JSON 아님")
            continue
        mine = by_set.setdefault(str(e.get("set_sha256")), [])
        out += [f"{n}: {p}" for p in _line_problems(e, mine)]
        mine.append(e)
    return out


def _line_problems(e: dict[str, Any], mine: list[dict[str, Any]]) -> list[str]:
    status = e.get("status")
    if status not in TRANSITIONS.get(_last(mine), frozenset()):
        return [f"상태 전이 안 됨: {_last(mine)} → {status}"]
    if status == "reserved":
        ok = all(_SHA.fullmatch(str(e.get(k))) for k in ("pre_sha256", "grades_sha256"))
        return [] if ok else ["예약 줄 해시 없음"]
    if status != "judged":
        return []
    try:
        new = Prior(e["prior"])
        prior, prior_sha256 = _prior(mine)
    except (KeyError, TypeError, ValueError):
        return ["판정 줄 prior 를 못 읽음"]
    out = [] if new.sha256() == e.get("prior_sha256") else ["판정 줄 해시가 prior 와 다름"]
    out += [] if e.get("from_prior_sha256") == prior_sha256 else ["계산에 쓴 prior 가 최신이 아님"]
    released = _releases(prior, new)
    return out + ([f"앞 판정의 미달을 풂: {released}"] if released else [])
