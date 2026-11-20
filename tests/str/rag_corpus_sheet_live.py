"""SCRUM-305 태그 확인 시트 하위 명령 (`rag_answer_sheet_live.py` 에 붙음 — docs/str/10 "305 실행 기록" 태그 도구).

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_answer_sheet_live export-corpus --out <리포 밖 폴더>
    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_answer_sheet_live apply-corpus --csv <CSV> --checker <이름>

범위 = 초벌(`answer_draft_corpus.json`) + DB(읽기 전용: 새 3문서 청크·기존 태그 청크·본문) — 초벌과 DB 청크 집합·기존 태그가
기준선과 다르면 시트·반영 안 함. apply-corpus 는 manifest 잠금 하나 안에서 `answers_corpus.json`(덮지 않게 게시)·manifest
(새 3줄만, 원자적 교체)를 씀. 같은 입력으로 다시 돌리면 남은 반영만, 다른 입력은 거절, 다 됐으면 1.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy import text

from aml_ai.shared.config import get_settings
from tests.str import rag_corpus_sheet as cs
from tests.str import rag_corpus_tags as tags
from tests.str.rag_baseline_live_db import readonly_session
from tests.str.rag_corpus_check import APPLIED_NAME, LOCK_NAME, SAME_KEYS, grades_digest
from tests.str.rag_corpus_draft_live import DRAFT_FILE
from tests.str.rag_eval_corpus_live import GRADES_FILE
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

COMMANDS = ("export-corpus", "apply-corpus")


def add_commands(sub: argparse._SubParsersAction) -> None:
    ex = sub.add_parser("export-corpus")
    ex.add_argument("--out", type=Path, required=True)
    ap = sub.add_parser("apply-corpus")
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--checker", required=True)
    ap.add_argument("--checked-at", default=datetime.now(UTC).date().isoformat())


def _scope_and_texts() -> tuple[tags.Scope, dict[str, tuple[str, int, str]], str]:
    """(범위, {chunk_id: (문서, 쪽, 본문)}, 초벌 sha256). 초벌·DB 청크 집합이나 기존 태그가 기준선과 다르면 ValueError."""
    raw = DRAFT_FILE.read_bytes()
    draft = json.loads(raw)
    with readonly_session() as session:
        rows = session.execute(
            text("SELECT chunk_id, doc_id, page, typologies, text FROM ai.reference_chunks")
        ).all()
    new = [(r.chunk_id, r.doc_id, r.page) for r in rows if r.doc_id in NEW_DOC_IDS]
    old_tagged = {t: [r.chunk_id for r in rows if r.doc_id not in NEW_DOC_IDS and t in (r.typologies or [])]
                  for t in tags.CORPUS_TYPOLOGIES}  # fmt: skip
    problems = tags.scope_problems(draft, new, old_tagged)
    if problems:
        raise ValueError("시트 범위를 못 만듦: " + " · ".join(problems[:3]))
    old_loc = {r.chunk_id: (r.doc_id, r.page) for r in rows if r.doc_id not in NEW_DOC_IDS}
    scope = tags.sheet_scope(draft, new, old_tagged, old_loc)
    keep = {c for _, c, _, _ in scope}
    return (
        scope,
        {r.chunk_id: (r.doc_id, r.page, r.text) for r in rows if r.chunk_id in keep},
        sha256(raw).hexdigest(),
    )


def run_command(args: argparse.Namespace, out: Callable[[str], None] = print) -> int:
    if args.cmd == "export-corpus":
        if "~" in Path(args.out).parts or cs.inside_repo(
            Path(args.out).expanduser().resolve()
        ):  # DB 읽기 전에
            out(cs.INSIDE_REPO)
            return 2
        scope, db, _ = _scope_and_texts()
        return cs.export_corpus(args.out, scope, {c: v[2] for c, v in db.items()}, out=out)
    corpus = get_settings().corpus_dir
    (corpus / "pdf").mkdir(exist_ok=True)
    with (corpus / "pdf" / LOCK_NAME).open(
        "a", encoding="utf-8"
    ) as lock:  # 교체하지 않는 공용 잠금(작업 트리 공유)
        fcntl.flock(lock, fcntl.LOCK_EX)  # 동시 apply 는 줄 서서 — 뒤엣것은 "할 일 없음"
        return _apply(args, corpus, out)


def _apply(args: argparse.Namespace, corpus: Path, out: Callable[[str], None]) -> int:
    manifest, applied = corpus / "manifest.json", corpus / "pdf" / APPLIED_NAME
    scope, db, draft_sha = _scope_and_texts()
    answers, pages = cs.read_and_build(args.csv, scope, db, checker=args.checker, checked_at=args.checked_at,
                                       draft_sha256=draft_sha)  # fmt: skip
    current = manifest.read_text(encoding="utf-8")
    new_manifest = tags.manifest_with_pages(current, pages)
    digest = grades_digest(answers)
    if applied.exists() and json.loads(applied.read_text(encoding="utf-8")).get("grades_sha256") != digest:
        out("이 코퍼스에 다른 확인 등급이 이미 반영됨(다른 작업 트리) — 거절")
        return 1
    if GRADES_FILE.exists():
        kept = json.loads(GRADES_FILE.read_text(encoding="utf-8"))
        if any(kept.get(k) != answers[k] for k in SAME_KEYS):
            out(f"{GRADES_FILE.name} 이 다른 입력으로 이미 있음 — 덮지 않음")
            return 1
        if current == new_manifest and applied.exists():  # 공용 표식까지 있어야 반영 완료(추가 검토 3)
            out("이미 다 반영됨 — 할 일 없음")
            return 1
    else:
        _publish_new(GRADES_FILE, json.dumps(answers, ensure_ascii=False, indent=2) + "\n")
    if not applied.exists():
        _publish_new(applied, json.dumps({"grades_sha256": digest}) + "\n")
    if current != new_manifest:
        _replace(manifest, new_manifest)
    out(f"answers rows={sum(len(v) for v in answers['grades'].values())} typology_pages={json.dumps(pages)}")
    return 0


def _tmp(target: Path, body: str) -> str:
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    return tmp


def _publish_new(target: Path, body: str) -> None:
    """임시 파일을 다 쓴 뒤 hard link 로 게시 — 이미 있으면 FileExistsError(덮지 않음)."""
    tmp = _tmp(target, body)
    try:
        os.link(tmp, target)
    finally:
        os.unlink(tmp)


def _replace(target: Path, body: str) -> None:
    """임시 파일을 다 쓴 뒤 원자적 교체 — 중간에 끊겨도 기존 manifest 는 통째로 남음."""
    tmp = _tmp(target, body)
    try:
        os.replace(tmp, target)
    except BaseException:
        os.unlink(tmp)
        raise
