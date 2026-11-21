"""SCRUM-308 ① 유사도 컷오프 판정 (손 실행, pytest 수집 X — docs/str/10 "청크 맥락·리랭커·컷오프 판정" ①).

외부 호출 0 — 307 `result_307.json` 에 저장된 cosine 과 v3 정답 후보만 읽는다. 규칙(결과 보기 전 커밋):
초안 경로(`on_a_kw0`) top-3 에서 정답 칸을 하나도 잃지 않는 가장 큰 값 t 가 정답 없는 질의의 결과
(초안 경로 + 필터 끔 6조건 top-3)를 하나 이상 없앨 때만 `MIN_SIMILARITY = t`, 아니면 0.0.
없앰 = 실제 cosine < t(검색은 `score >= MIN_SIMILARITY` 를 남김). 추가 검토 1: 저장값은 6자리 반올림(±5e-7) —
t = 정답 칸 최소 − 오차(실제 정답도 남게), 없앰은 저장값이 정답 칸 최소보다 2 단위(백만분의 1) 이상 낮을 때만 셈
(확실히 t 아래), 1 단위 낮으면 판별 못 하는 경계 칸 → 경계면 채택 보류.
실행 전 거절은 `rag_eval_v3_cutoff_guard`(고정 기준 커밋 · 입력 바이트 = 기준 커밋 · 구조) + 결과 파일 덮어쓰기 금지.
결과 `result_308_cutoff.json` — 값·개수·입력 해시만, 원문 0.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from tests.str import rag_eval_v3_cutoff_guard as guard
from tests.str.rag_eval_v3_hybrid_support import GRADE_MIN, V3_DIR, forbidden_keys

REPO = Path(__file__).resolve().parents[2]
CUTOFF_FILE = V3_DIR / "result_308_cutoff.json"
TOP_K = 3  # RAG_TOP_K — 화면에 나가는 칸 수
KEEP = 0.0  # 지금 MIN_SIMILARITY
STORED_EPS = 5e-7  # 307 저장 cosine 은 round(·, 6) — 실제 값은 저장값 ± 이만큼 안


def draft_answers(candidates: dict[str, Any]) -> dict[str, set[str]]:
    """초안 경로 정답 = 등급 ≥ 1 이고 `db_tagged=true`."""
    return {
        typ: {r["chunk_id"] for r in rows if (r["grade"] or 0) >= GRADE_MIN and r["db_tagged"]}
        for typ, rows in candidates["candidates"].items()
    }


def _micro(cos: float) -> int:
    """저장 cosine(소수 6자리) → 백만분의 1 정수. 실제 값은 이 정수 ± 0.5 안 — 비교를 정수로 해 부동소수 오차를 뺌."""
    return round(cos * 1_000_000)


def _cells(query: dict[str, Any]) -> list[dict[str, Any]]:
    return query["top10"][:TOP_K]


def _split_draft(draft: dict[str, Any], answers: dict[str, set[str]]) -> tuple[list[float], list[float]]:
    right, wrong = [], []
    for q in draft["queries"]:
        expected = answers.get(q["typology"] or "", set())
        if expected:
            for cell in _cells(q):
                (right if cell["chunk_id"] in expected else wrong).append(cell["cosine"])
    return right, wrong


def cutoff_verdict(result: dict[str, Any], candidates: dict[str, Any]) -> dict[str, Any]:
    """규칙 ① — 적용값·확실히 없어지는 정답 없는 칸 수·경계 칸 수. 정답 칸이 없으면 판정 안 함."""
    conds = {c["name"]: c for c in result["conditions"]}
    right, wrong = _split_draft(conds[guard.DRAFT_CONDITION], draft_answers(candidates))
    if not right:
        return {"judged": False, "reason": "초안 경로 정답 칸 0", "min_similarity": KEEP}
    stored_min = min(right)
    t = stored_min - STORED_EPS  # 실제 정답 값이 저장값보다 최대 5e-7 작아도 남음
    no_answer = [
        cell["cosine"]
        for c in result["conditions"]
        if c["name"] == guard.DRAFT_CONDITION or not c["filtered"]
        for q in c["queries"]
        if "hit" not in q["uses"]
        for cell in _cells(q)
    ]
    m = _micro(stored_min)
    removed = sum(_micro(cos) <= m - 2 for cos in no_answer)  # 실제 값이 최대여도 t 아래
    boundary = sum(_micro(cos) == m - 1 for cos in no_answer)  # 실제 값이 t 위아래 어느 쪽인지 판별 못 함
    return {
        "judged": True,
        "candidate_t": stored_min,
        "applied_t": t,
        "stored_eps": STORED_EPS,
        "answer_cells": len(right),
        "answer_cells_lost": sum(_micro(cos) < m for cos in right),  # 정의상 0 — 최악(−5e-7)에도 남음
        "draft_wrong_cells": len(wrong),
        "draft_wrong_cells_removed": sum(_micro(cos) <= m - 2 for cos in wrong),
        "no_answer_cells": len(no_answer),
        "no_answer_cells_removed": removed,
        "no_answer_boundary_cells": boundary,
        "no_answer_min_cosine": min(no_answer) if no_answer else None,
        "min_similarity": t if removed else KEEP,
        "adopt": bool(removed),
    }


def main(repo: Path = REPO, out: Path = CUTOFF_FILE) -> int:
    if reason := guard.criteria_problem(repo):
        print(reason)
        return 2
    if out.exists():
        print(f"결과 파일이 이미 있음({out.name})")
        return 2
    loaded, digests, reason = guard.read_inputs(repo)
    if reason or loaded is None:
        print(reason)
        return 2
    md = (repo / guard.DOC_10).read_text(encoding="utf-8")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout
    doc = {
        "_doc": "SCRUM-308 ① 유사도 컷오프 — 307 저장 cosine 으로만(외부 호출 0), 원문 0 (docs/str/10 308 절 ①).",
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "head": head.strip(),
        "criteria_commit": guard.CRITERIA_COMMIT,
        "criteria_section_sha256": sha256(guard.criteria_section(md).encode()).hexdigest(),
        **{f"{Path(p).stem}_sha256": digest for p, digest in digests.items()},
        "verdict": cutoff_verdict(loaded[guard.RESULT_307], loaded[guard.CANDIDATES]),
    }
    if leaks := forbidden_keys(doc):
        raise ValueError(f"결과에 본문 키: {leaks[:3]}")
    with out.open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(doc["verdict"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
