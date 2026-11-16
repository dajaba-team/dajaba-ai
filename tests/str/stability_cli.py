"""안정화 측정의 인자·사전 점검·결과 저장. 실측은 명시적 실행 때만 한다."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.str.domain.constants import JUDGE_VOTES, VERIFIER_VERSION
from tests.str.stability_phases import JUDGE_PROMPT
from tests.str.stability_support import (
    estimate_calls,
    measure_problems,
    preflight_problems,
    render_summary_md,
    summarize,
)


def _settings_summary(settings: Any, cases: tuple[str, ...], n: int) -> dict[str, Any]:
    """자격 증명·접속 주소를 제외한 이름·숫자만 기록한다."""
    return {
        "narrative_prompt": settings.narrative_prompt,
        "rag_enabled": settings.rag_enabled,
        "judge_prompt": JUDGE_PROMPT,
        "judge_votes": JUDGE_VOTES,
        "llm_daily_token_budget": settings.llm_daily_token_budget,
        "llm_model_generate": settings.llm_model_generate,
        "llm_model_judge": settings.llm_model_judge,
        "cases": list(cases),
        "n": n,
    }


def _preflight(settings: Any, n: int, cases: tuple[str, ...]) -> list[str]:
    """값 대신 있음·없음만 출력하고, 검색 전제와 시연 프롬프트를 확인한다."""
    from tests.str.stability_live import corpus_chunk_count

    chunks = corpus_chunk_count(settings)
    api_key_set = bool(settings.llm_api_key)
    embedding_model_set = bool(settings.embedding_model)
    print(f"검사기: {VERIFIER_VERSION}")
    print(f"코퍼스 청크 수: {chunks}")
    print(f"LLM·임베딩 키: {'있음' if api_key_set else '없음'}")
    print(f"임베딩 모델: {'있음' if embedding_model_set else '없음'}")
    print("호출 수 추정: " + json.dumps(estimate_calls(cases=len(cases), n=n, judge_votes=JUDGE_VOTES)))
    problems = preflight_problems(
        rag_enabled=settings.rag_enabled,
        corpus_chunks=chunks,
        api_key_set=api_key_set,
        embedding_model_set=embedding_model_set,
    )
    if settings.narrative_prompt != "narrative_v2":
        problems.append("NARRATIVE_PROMPT가 시연 설정 narrative_v2와 다름")
    return problems


def _measure(settings: Any, cases: tuple[str, ...], n: int) -> list:
    """사건·회차·두 상태와 예외 이름만 진행 표시한다."""
    from tests.str.stability_live import run_once

    llm = make_llm_client(settings)
    embedder = make_embedding_client(settings)
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    records = []
    with factory() as session:
        for case in cases:
            for run_no in range(1, n + 1):
                record = run_once(
                    case, run_no, settings=settings, llm=llm, embedder=embedder, session=session
                )
                records.append(record)
                error = f" {record.error}" if record.error else ""
                print(f"{case} {run_no} {record.final_status} {record.retrieval_status}{error}")
    return records


def _save(records: list, settings_summary: dict[str, Any], budget: int) -> None:
    """본문이 없는 기록·집계만 새 결과 파일 두 개에 저장한다."""
    summary = summarize(records, daily_token_budget=budget)
    payload = {
        "settings": settings_summary,
        "verifier_version": VERIFIER_VERSION,
        "records": [asdict(r) for r in records],
        "summary": summary,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    directory = Path(__file__).resolve().parent / "recorded" / "_tmp"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"stability_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(render_summary_md(summary), encoding="utf-8")
    print(path)
    print(path.with_suffix(".md"))


def run(argv: list[str] | None = None) -> int:
    """사전 점검 뒤에만 클라이언트를 만들고 측정한다."""
    from tests.str.stability_live import CASES

    parser = argparse.ArgumentParser(description="시연 설정 안정화 측정")
    parser.add_argument("--n", type=int, default=5, help="사건당 회차 수 (기본 5)")
    parser.add_argument("--dry-run", action="store_true", help="사전 점검만 수행")
    args = parser.parse_args(argv)
    if args.n < 1:
        parser.error("--n은 1 이상이어야 함")
    settings = get_settings()
    snapshot = _settings_summary(settings, CASES, args.n)
    print("설정: " + json.dumps(snapshot, ensure_ascii=False))
    print(f"LLM 녹화 재생(AI_LLM_MOCK): {'켜짐' if settings.ai_llm_mock else '꺼짐'}")
    problems = _preflight(settings, args.n, CASES)
    if not args.dry_run:
        problems.extend(measure_problems(ai_llm_mock=settings.ai_llm_mock))
    if problems:
        for problem in problems:
            print(f"문제: {problem}")
        return 1
    if args.dry_run:
        return 0
    records = _measure(settings, CASES, args.n)
    _save(records, snapshot, settings.llm_daily_token_budget)
    return 0
