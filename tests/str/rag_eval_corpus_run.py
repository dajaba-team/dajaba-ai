"""SCRUM-305 판정 묶음 — 원장 값으로만 `verdict` 를 부르고 판정 줄을 남김 (docs/str/10 "305 실행 기록").

`pre_sha256`·`prior`·`prior_sha256` 를 받는 인자가 없다(④). 원장 읽기부터 판정·판정 줄 기록까지 `judge_locked` 의
한 잠금 안. 등급표는 예약 전에 검증한 스냅샷(`grades_doc`) — 그 해시가 예약 줄과 다르면 판정 전에 거절. DB·검색 0.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests.str import rag_eval_corpus_gate as gate
from tests.str import rag_eval_corpus_ledger as cl
from tests.str.rag_eval_corpus_guard import FanCase, PreRun, Prior, Run, normalized_sha256
from tests.str.rag_eval_corpus_preflight import grade_table, grades_sha256
from tests.str.rag_eval_corpus_support import query_text, verdict


def judge(
    eval_dir: Path,
    runs: list[Run],
    pre: PreRun,
    grades_doc: Mapping[str, Any],
    fan: list[FanCase],
    queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """원장 값으로 판정 → 판정 줄. 예약 없음·전이 안 됨·해시 불일치·미달 해제는 ValueError(판정 줄 없음)."""
    snapshot = copy.deepcopy(dict(grades_doc))  # 호출 뒤 바뀌어도 판정은 이 값으로
    qs = (
        gate.queries_snapshot(eval_dir) if queries is None else list(queries)
    )  # 생략하면 eval_dir 에서 읽어 대조
    if (
        normalized_sha256(qs) != gate.QUERIES_SHA256 or cl.set_sha256(eval_dir) != gate.QUERIES_SHA256
    ):  # 추가 검토 4·5
        raise ValueError("holdout_v2 질의 목록(인자·eval_dir)이 304 고정값과 다름 — 판정 안 함")
    manifest = [(q["id"], q["typology"], query_text(q)) for q in qs]  # 질의 스냅샷

    def compute(
        pre_sha: str, grades_sha: str, prior: Prior | None, prior_sha: str | None
    ) -> tuple[dict, Prior]:
        if grades_sha256(snapshot) != grades_sha:
            raise ValueError("grades snapshot differs from the reserved one")
        out = verdict(runs, pre, grade_table(snapshot), fan, manifest=manifest, pre_sha256=pre_sha,
                      prior=prior, prior_sha256=prior_sha)  # fmt: skip
        return out, Prior.from_verdict(out)

    return cl.judge_locked(eval_dir, compute)
