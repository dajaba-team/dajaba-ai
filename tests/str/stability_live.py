"""SCRUM-131 (4/n) — 안정화 측정 (손 실행, pytest 수집 X). docs/str/07 "안정화 측정".

설정은 시연 설정 그대로(09 2026-11-17 SCRUM-131 4/n ★A): narrative_v2 · RAG 켬 · 고쳐 쓰기 켬 ·
verify 평가자 judge_v3 N=3 중앙값. 검사기 버전은 결과 파일에 기록(측정 도중 안 바꿈).

사건마다 N회: draft_service 와 같은 흐름(검색 → 생성 → 고쳐 쓰기 → 최종 본문, DB 저장 없이 조립)
→ 최종 본문을 verify_service 와 같은 흐름(코드 검사 → 통과면 평가자 N=3 중앙값)으로 검증.

사용 (진희 터미널):
    RAG_ENABLED=true uv run --frozen --extra dev python -m tests.str.stability_live --dry-run
    AI_LLM_MOCK=false RAG_ENABLED=true uv run --frozen --extra dev python -m tests.str.stability_live --n 5

- `--dry-run`: LLM·임베딩 호출 0. 설정(프롬프트·RAG·평가자 N·검사기 버전) · 코퍼스 청크 수 · 키/임베딩 모델
  있음·없음(값 출력 금지) · 호출 수 추정 출력. `preflight_problems` 가 하나라도 있으면 종료 코드 1로 멈춤.
- 실측도 시작 전에 같은 preflight — 문제가 있으면 호출 없이 멈춤.
결과: `tests/str/recorded/_tmp/stability_<stamp>.json` = {"settings", "verifier_version", "records", "summary"}
(+ 같은 이름 `.md` = `render_summary_md`). 본문·프롬프트 전문은 저장하지 않음.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from aml_ai.shared.db import get_engine
from aml_ai.str.domain.fact_keys import attach_evidence
from tests.str.stability_phases import (
    draft_inputs,
    generate,
    generation_call,
    inspect_body,
    retrieve,
    rewrite,
    rewrite_calls,
    verify,
)
from tests.str.stability_support import RunRecord
from tests.str.v4_slot_support import load_fixture

CASES = ("fan_in", "fan_in_b", "fan_out", "cycle_nopaths", "scatter_gather")


def corpus_chunk_count(settings: Any) -> int:
    """`ai.reference_chunks` 행 수(DB 읽기 1회). DB 연결 실패면 0."""
    try:
        factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
        with factory() as session:
            return int(session.execute(text("SELECT count(*) FROM ai.reference_chunks")).scalar_one())
    except Exception:
        return 0


def run_once(case_id: str, run_no: int, *, settings: Any, llm: Any, embedder: Any, session: Any) -> RunRecord:
    """한 회차: 검색(retrieval_status) → 생성 → try_rewrite → 최종 본문 → 코드 검사 → 평가자(N=3) → RunRecord.

    호출마다 Call(kind, tokens_in, tokens_out, latency_ms) — 생성·critique(RewriteMeta.critique_*)·
    고쳐 쓰기(시도됐고 토큰 차액이 양수면 미적용도 포함)·judge(JudgeMeta 합계).
    예외로 초안을 못 만들면 final_status DRAFT_FAILED, error에는 예외 이름만 남긴다.
    """
    record = RunRecord(case_id, run_no, "failed", {}, {}, "", [], [], False, None, None, "DRAFT_FAILED")
    try:
        deadline = time.monotonic() + settings.draft_budget_s
        facts = load_fixture(f"facts_{case_id}.json")
        refs, status = retrieve(facts, settings, embedder, session)
        record = replace(record, retrieval_status=status)
        inputs = draft_inputs(facts, refs, deadline, settings)
        gen = generate(inputs, llm, settings)
        record.calls.append(generation_call(gen))
        narrative = attach_evidence(gen.narrative, facts)
        record = inspect_body(record, facts, narrative, inputs["evidence_scope"], first=True)
        rewritten = rewrite(inputs, gen, narrative, llm, settings)
        if rewritten is not None:
            meta, narrative, final_gen = rewritten
            record.calls.extend(rewrite_calls(meta, final_gen, gen))
            record = replace(record, rewrite_applied=meta.applied, rewrite_skipped_reason=meta.skipped_reason)
        record = inspect_body(record, facts, narrative, inputs["evidence_scope"], first=False)
    except Exception as exc:
        return replace(record, error=type(exc).__name__)
    return verify(record, inputs, narrative, llm, settings)


def main(argv: list[str] | None = None) -> int:
    from tests.str.stability_cli import run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
