"""SCRUM-307 실행 전 거절 (docs/str/10 "하이브리드·다중 질의 판정" 실행 절). 검색 0 — git·파일·ES `_count` 만.

① 고정한 기준 커밋(`CRITERIA_COMMIT`)이 HEAD 조상이고, 그 커밋과 HEAD 의 307 절·09 줄이 같음 — 인자로 다른 커밋을
   주면 거절(추가 검토 1: 기준을 고친 커밋 자체를 넘기는 길) ② v3 정답 미확인 · 정답 후보 `db_tagged` ≠ DB 태그
③ ES 문서 수 ≠ DB 행 수(`_count` 는 `rag_eval_v3_hybrid_es`) ④ `ELASTIC_INDEX` ≠ v2 ⑤ 결과 파일이 이미 있음 ⑥ 위치표 ≠ DB(형식 포함).
컨테이너 안에선 `.git` 을 읽기 전용으로 붙여 부름(소유자가 달라 `safe.directory` 를 이 호출에만).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.str.rag_eval_v3_hybrid_support import ES_INDEX, criteria_line, criteria_section

REPO_ROOT = Path(__file__).resolve().parents[2]
CRITERIA_COMMIT = "48b76ad0609728d87ded41a82b6133ab660eda2c"  # 결과 보기 전 기준 커밋(11/21) — 바꾸지 않음
POSITION_KEYS = {"doc_id": str, "page": int, "pos": int}
DOC_10 = "docs/str/10_rag.md"
DOC_09 = "docs/str/09_decisions.md"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def _show(repo: Path, rev: str, path: str) -> str | None:
    done = _git(repo, "show", f"{rev}:{path}")
    return done.stdout if done.returncode == 0 else None


def criteria_problem(repo: Path, given: str | None) -> str | None:
    """① — 통과면 None. `CRITERIA_COMMIT` 이 커밋이고 HEAD 조상이며, 307 절·09 줄이 그 뒤로 그대로인지.

    `given`(실행 인자)은 확인용만. 고정값은 인자로 못 바꿈(추가 검토 2) — 테스트만 모듈 상수를 바꿔 끼움.
    """
    fixed = CRITERIA_COMMIT
    if given is not None and given != fixed:
        return "--criteria-commit 이 고정한 기준 커밋과 다름"
    if _git(repo, "cat-file", "-t", fixed).stdout.strip() != "commit":
        return "고정한 기준 커밋이 리포에 없음"
    if _git(repo, "merge-base", "--is-ancestor", fixed, "HEAD").returncode != 0:
        return "판정 기준 커밋이 HEAD 조상에 없음"
    for path, pick in ((DOC_10, criteria_section), (DOC_09, criteria_line)):
        at_commit, at_head = _show(repo, fixed, path), _show(repo, "HEAD", path)
        before = pick(at_commit) if at_commit is not None else None
        if before is None:
            return f"판정 기준 커밋에 307 기준이 없음({path})"
        if at_head is None or pick(at_head) != before:
            return f"판정 기준 커밋 뒤 307 기준이 바뀜({path})"
    return None


def head_commit(repo: Path) -> str | None:
    done = _git(repo, "rev-parse", "HEAD")
    return done.stdout.strip() if done.returncode == 0 else None


def es_problem(index: str, es_docs: int | None, db_rows: int) -> str | None:
    """③④ — 색인 이름·문서 수."""
    if index != ES_INDEX:
        return f"ELASTIC_INDEX 가 {ES_INDEX} 가 아님"
    if es_docs != db_rows:
        return f"ES 문서 수 {es_docs} ≠ DB 행 수 {db_rows}"
    return None


def positions_problem(positions: dict[str, dict], db_ids: set[str]) -> str | None:
    """⑥ — 위치표 chunk_id 집합 = DB chunk_id 집합, 행은 doc_id(str)·page(int)·pos(int) 셋만(추가 검토 1)."""
    missing, extra = len(db_ids - positions.keys()), len(positions.keys() - db_ids)
    if missing or extra:
        return f"위치표 ≠ DB(빠짐 {missing} · 더 있음 {extra})"
    bad = [c for c, row in positions.items() if not _position_ok(row)]
    return f"위치표 행 형식이 다름 {len(bad)}" if bad else None


def _position_ok(row: object) -> bool:
    return (
        isinstance(row, dict)
        and set(row) == set(POSITION_KEYS)
        and all(type(row[k]) is t for k, t in POSITION_KEYS.items())  # bool 이 int 로 지나가지 않게
    )


def tag_problem(candidates: dict, db_tags: dict[str, set[str]]) -> str | None:
    """② — 정답 후보 chunk_id 가 DB 에 다 있는지 먼저(추가 검토 2), 그다음 (chunk_id, 유형) DB 태그 포함 = `db_tagged`."""
    rows = [r for group in candidates["candidates"].values() for r in group]
    if absent := sorted({r["chunk_id"][:8] for r in rows if r["chunk_id"] not in db_tags}):
        return f"정답 후보 chunk_id 가 DB 에 없음 {len(absent)}: {absent[:3]}"
    bad = [
        (typ, r["chunk_id"][:8])
        for typ, rows in candidates["candidates"].items()
        for r in rows
        if (typ in db_tags[r["chunk_id"]]) != bool(r["db_tagged"])
    ]
    return f"정답 후보 db_tagged ≠ DB 태그 {len(bad)}: {bad[:3]}" if bad else None


def db_problem(session: Session, candidates: dict, positions: dict) -> tuple[str | None, int]:
    """⑥·② DB 쪽 — 같은 세션(스냅샷)에서 위치표 = DB · 정답 후보 = DB 태그. (이유, DB 행 수)."""
    rows = session.execute(text("SELECT chunk_id, typologies FROM ai.reference_chunks")).all()
    db_tags = {r.chunk_id: set(r.typologies or ()) for r in rows}
    reason = positions_problem(positions["positions"], set(db_tags)) or tag_problem(candidates, db_tags)
    return reason, len(db_tags)


def result_problem(path: Path) -> str | None:
    """⑤ — 덮어쓰기 금지. 다시 돌릴 땐 사람이 지우고 사유를 기록."""
    return f"결과 파일이 이미 있음({path.name}) — 지우고 사유를 기록한 뒤 다시" if path.exists() else None
