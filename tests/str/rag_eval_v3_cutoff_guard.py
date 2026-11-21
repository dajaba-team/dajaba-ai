"""SCRUM-308 ① 컷오프 실행 전 거절 (추가 검토 1) — git·파일만, 계산 0.

기준: 고정한 기준 커밋(`CRITERIA_COMMIT`)이 커밋이고 HEAD 조상이며, 그 커밋의 308 기준 절 = HEAD = 작업 트리.
입력: 307 결과·v3 정답 후보·v3 질의를 **한 번만** 바이트로 읽고, 기준 커밋 안 같은 경로 파일과 바이트가 같을 때만
그 바이트로 계산(질의 표식·조건을 고친 입력 거절). 구조: 초안 조건 1 + 필터 끔 6조건, 조건마다 질의 id·`uses` = v3 질의.
"""

from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

CRITERIA_COMMIT = "87aef099a91be90440d79b65f0daff462aa73216"  # 결과 보기 전 기준 커밋(11/21) — 바꾸지 않음
DOC_10 = "docs/str/10_rag.md"
CRITERIA_HEADING = "## 청크 맥락·리랭커·컷오프 판정 (SCRUM-308"
RESULT_307 = "tests/str/rag_eval_v3/result_307.json"
CANDIDATES = "tests/str/rag_eval_v3/answer_candidates.json"
QUERIES = "tests/str/rag_eval_v3/queries_dev.json"
INPUTS = (RESULT_307, CANDIDATES, QUERIES)
DRAFT_CONDITION = "on_a_kw0"
FILTER_OFF_CONDITIONS = 6


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(repo), *args], capture_output=True, check=False
    )


def _show(repo: Path, rev: str, path: str) -> bytes | None:
    done = _git(repo, "show", f"{rev}:{path}")
    return done.stdout if done.returncode == 0 else None


def criteria_section(md: str) -> str | None:
    start = md.find(CRITERIA_HEADING)
    if start < 0:
        return None
    end = md.find("\n## ", start + 1)
    return md[start : end if end >= 0 else len(md)]


def criteria_problem(repo: Path) -> str | None:
    """기준 — 통과면 None."""
    fixed = CRITERIA_COMMIT
    if _git(repo, "cat-file", "-t", fixed).stdout.strip() != b"commit":
        return "고정한 기준 커밋이 리포에 없음"
    if _git(repo, "merge-base", "--is-ancestor", fixed, "HEAD").returncode != 0:
        return "판정 기준 커밋이 HEAD 조상에 없음"
    at_commit = criteria_section((_show(repo, fixed, DOC_10) or b"").decode())
    if at_commit is None:
        return "기준 커밋에 308 기준 절이 없음"
    if criteria_section((_show(repo, "HEAD", DOC_10) or b"").decode()) != at_commit:
        return "기준 커밋 뒤 308 기준 절이 바뀌어 커밋됨(HEAD)"
    if criteria_section((repo / DOC_10).read_text(encoding="utf-8")) != at_commit:
        return "기준 커밋 뒤 308 기준 절이 바뀜(작업 트리)"
    return None


def read_inputs(repo: Path) -> tuple[dict[str, Any] | None, dict[str, str], str | None]:
    """입력 셋을 한 번 읽어 기준 커밋 바이트와 대조 → (경로 → 파싱 값, 경로 → 바이트 sha256, 이유)."""
    loaded: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for path in INPUTS:
        now = (repo / path).read_bytes()
        if now != _show(repo, CRITERIA_COMMIT, path):
            return None, {}, f"입력이 기준 커밋과 다름({Path(path).name})"
        loaded[path], digests[path] = json.loads(now), sha256(now).hexdigest()
    if reason := structure_problem(loaded[RESULT_307], loaded[QUERIES]):
        return None, {}, reason
    return loaded, digests, None


def structure_problem(result: dict[str, Any], queries: dict[str, Any]) -> str | None:
    """초안 조건 1 + 필터 끔 6조건, 조건마다 질의 id·`uses` 가 v3 질의와 같아야."""
    names = [c["name"] for c in result["conditions"]]
    if names.count(DRAFT_CONDITION) != 1:
        return "초안 경로 조건이 하나가 아님"
    off = [c for c in result["conditions"] if not c["filtered"]]
    if len(off) != FILTER_OFF_CONDITIONS:
        return f"필터 끔 조건 수 {len(off)} ≠ {FILTER_OFF_CONDITIONS}"
    expected = [(q["id"], q["uses"]) for q in queries["queries"]]
    for cond in result["conditions"]:
        if [(q["id"], q["uses"]) for q in cond["queries"]] != expected:
            return f"질의 id·uses 가 v3 질의와 다름({cond['name']})"
    return None
