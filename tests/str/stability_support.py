"""SCRUM-131 (4/n) — 안정화 측정 순수 집계 (docs/str/07 "안정화 측정"). LLM·DB 0.

`stability_live`(손 실행)가 사건 × 회차마다 `RunRecord` 를 만들고, 여기서 일관성·통과율·비용·하루 처리
건수를 집계한다. **결과 파일에 본문·프롬프트 전문·금액을 남기지 않음** — 섹션 해시·글자 수·숫자 덩이 해시·
검사 이름·점수·토큰·시간만.

검색(RAG 켬) 확인: dry-run 은 `preflight_problems` 가 하나라도 내면 멈춤. 실측은 회차마다
`retrieval_status`(ok·empty·failed) — ok 아닌 회차는 `summarize` 에서 따로 표시(전체 + ok 만 두 벌 집계).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from tests.str.stability_metrics import aggregate
from tests.str.stability_render import render_group

RetrievalStatus = Literal["ok", "empty", "failed"]
CallKind = Literal["generate", "critique", "rewrite", "judge"]  # judge = verify 평가자(N=3 묶음 1회로 셈)
FinalStatus = Literal["PASSED", "LLM_FAILED", "CODE_FAILED", "VERIFY_UNAVAILABLE", "DRAFT_FAILED"]


@dataclass(frozen=True)
class Call:
    kind: CallKind
    tokens_in: int
    tokens_out: int
    latency_ms: int


@dataclass(frozen=True)
class RunRecord:
    case_id: str
    run_no: int  # 1부터
    retrieval_status: RetrievalStatus
    section_hashes: dict[str, str]  # 섹션 → 최종 본문 sha256 앞 16자
    section_chars: dict[str, int]  # 섹션 → 최종 본문 글자 수
    number_set_hash: (
        str  # 최종 본문 숫자 덩이(`\d` 덩이, 정렬·중복 유지) sha256 앞 16자 — 숫자 자체는 안 남김
    )
    code_failures_first: list[str]  # 첫 생성 본문 코드 검사 실패 "CHECK:REASON"
    code_failures_final: list[str]  # 최종(고쳐 쓰기 반영) 본문 코드 검사 실패
    rewrite_applied: bool
    rewrite_skipped_reason: str | None
    judge_scores: dict[str, int] | None  # verify 평가자 기준별 중앙값(코드 검사 실패면 None)
    final_status: FinalStatus
    calls: list[Call] = field(default_factory=list)
    error: str | None = None  # 초안·검증 실패의 예외 이름만(type(exc).__name__) — 메시지·본문 안 남김


def section_digest(texts: dict[str, str]) -> tuple[dict[str, str], dict[str, int], str]:
    """섹션 → 본문 → (섹션 해시, 섹션 글자 수, 숫자 덩이 해시). 본문은 돌려주지 않음."""
    hashes = {name: hashlib.sha256(text.encode()).hexdigest()[:16] for name, text in texts.items()}
    chars = {name: len(text) for name, text in texts.items()}
    numbers = sorted(re.findall(r"\d+", "".join(texts[name] for name in sorted(texts))))
    return hashes, chars, hashlib.sha256(",".join(numbers).encode()).hexdigest()[:16]


def preflight_problems(
    *, rag_enabled: bool, corpus_chunks: int, api_key_set: bool, embedding_model_set: bool
) -> list[str]:
    """RAG 켬이 실제로 켜졌는지 — 문제 목록(빈 목록이면 진행). 값은 안 받음(있음/없음만).

    `RAG_ENABLED` 꺼짐 · 코퍼스 청크 0 · LLM/임베딩 키 없음 · `EMBEDDING_MODEL` 빈 값 — 각각 한 줄.
    """
    checks = (
        (rag_enabled, "RAG_ENABLED 꺼짐"),
        (corpus_chunks > 0, "코퍼스 청크 없음 또는 DB 연결 실패"),
        (api_key_set, "LLM·임베딩 키 없음"),
        (embedding_model_set, "EMBEDDING_MODEL 없음"),
    )
    return [problem for valid, problem in checks if not valid]


def measure_problems(*, ai_llm_mock: bool) -> list[str]:
    """실측(--dry-run 아님) 전 추가 점검 — `AI_LLM_MOCK=true` 면 녹화 재생이라 실측이 아님 → 문제 한 줄."""
    return ["AI_LLM_MOCK=true — 녹화 재생이라 실측 아님"] if ai_llm_mock else []


def estimate_calls(*, cases: int, n: int, judge_votes: int) -> dict[str, int]:
    """dry-run 호출 수 추정 — {"generate", "critique", "rewrite_max", "judge_max", "embedding", "total_min", "total_max"}.

    회차마다: 생성 1 · 초안 안 평가자(critique) 1 · 고쳐 쓰기 0~1 · verify 평가자 0 또는 judge_votes · 임베딩 1.
    total_min = 생성 + critique + 임베딩(고쳐 쓰기·verify 0), total_max = 전부 최대.
    """
    runs = cases * n
    return {
        "generate": runs,
        "critique": runs,
        "rewrite_max": runs,
        "judge_max": runs * judge_votes,
        "embedding": runs,
        "total_min": runs * 3,
        "total_max": runs * (4 + judge_votes),
    }


def summarize(records: list[RunRecord], *, daily_token_budget: int) -> dict[str, Any]:
    """집계 — {"retrieval", "errors", "all", "retrieval_ok_only"}.

    retrieval = {"ok": int, "total": int, "not_ok": [{"case_id", "run_no", "retrieval_status"}]}
    errors = [{"case_id", "run_no", "error"}] — DRAFT_FAILED·VERIFY_UNAVAILABLE 회차, 예외 이름만.
    all / retrieval_ok_only = 같은 모양:
      "consistency": {case_id: {"distinct_per_section": {SECTION: int}, "numbers_same": bool, "status_same": bool}}
      "pass_rates": {"code_first": float, "code_final": float, "passed": float, "rewrite_applied": float}
      "judge_scores": {기준: {"min": int, "median": float, "max": int}}   (점수 있는 회차만)
      "cost": {kind: {"tokens_mean": float, "tokens_max": int}} (tokens = in + out),
              "draft_tokens_mean": float(생성+critique+고쳐 쓰기), "verify_tokens_mean": float(judge)
      "latency": {kind: {"p50": int, "p95": int, "max": int}}   (nearest-rank)
      "daily_capacity": int = daily_token_budget // (draft_tokens_mean + verify_tokens_mean), 분모 0 이면 0
    비율은 분모가 0 이면 0.0. 회차가 없으면(ok 0) 같은 모양에 빈 값.
    """
    ok = [r for r in records if r.retrieval_status == "ok"]
    return {
        "retrieval": {
            "ok": len(ok),
            "total": len(records),
            "not_ok": [
                {"case_id": r.case_id, "run_no": r.run_no, "retrieval_status": r.retrieval_status}
                for r in records
                if r.retrieval_status != "ok"
            ],
        },
        "errors": [
            {"case_id": r.case_id, "run_no": r.run_no, "error": r.error}
            for r in records
            if r.final_status in ("DRAFT_FAILED", "VERIFY_UNAVAILABLE")
        ],
        "all": aggregate(records, daily_token_budget),
        "retrieval_ok_only": aggregate(ok, daily_token_budget),
    }


def render_summary_md(summary: dict[str, Any]) -> str:
    """07용 한국어 표. 검색 ok n/N·검색 미성공 회차·초안/검증 실패 예외 이름을 표시한다. 본문·금액 없음."""
    retrieval = summary["retrieval"]
    lines = [
        "# 안정화 측정",
        "",
        f"검색 ok {retrieval['ok']}/{retrieval['total']}",
        "",
        "| 검색 ok 아닌 사건 | 회차 | 검색 상태 |",
        "|---|---:|---|",
    ]
    for r in retrieval["not_ok"]:
        lines.append(f"| {r['case_id']} | {r['run_no']} | {r['retrieval_status']} |")
    if not retrieval["not_ok"]:
        lines.append("| 없음 | — | — |")
    lines.extend(["", "| 초안·검증 실패 사건 | 회차 | 예외 이름 |", "|---|---:|---|"])
    for r in summary["errors"]:
        lines.append(f"| {r['case_id']} | {r['run_no']} | {r['error'] or '—'} |")
    if not summary["errors"]:
        lines.append("| 없음 | — | — |")
    lines.extend(render_group("전체", summary["all"]))
    lines.extend(render_group("검색 ok만", summary["retrieval_ok_only"]))
    return "\n".join(lines) + "\n"
