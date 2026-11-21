"""SCRUM-308 ② 리랭커 판정 실행 전·중 거절 (308-1 `rag_eval_v3_cutoff_guard` 의 기준 커밋 검사 재사용).

① 고정 기준 커밋 `87aef09` 이 HEAD 조상 · 308 기준 절 = HEAD = 작업 트리 ② v3 정답 후보·질의·위치표 + 질의가 쓰는
base 픽스처가 기준 커밋 안 파일과 바이트가 같을 때만(한 번 읽은 바이트로 계산) · 정답 확인 끝남 ③ 실측 모드는 첫 외부 호출
전에 녹화 재생(`AI_LLM_MOCK`)·빈 모델명·`reasoning_effort` ≠ low·타임아웃 ≠ 8초 거절(추가 검토 1·2) · DB
`embedding_model` 이 질의 모델 하나와 같아야(사전·스냅샷) ④ 후보 고정 직후 정답 없는 질의에
결과가 하나라도 있으면 판정 중단 ⑤ DB(307 `db_problem`) · 결과 파일·잠금은 실행 모듈. 검색·LLM 0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import Reference
from aml_ai.str.infrastructure.retriever_rerank import rerank_model
from tests.str import rag_eval_v3_cutoff_guard as cg
from tests.str.rag_eval_v3_hybrid_support import unconfirmed

POSITIONS = "tests/str/rag_eval_v3/positions_722.json"
INPUTS = (cg.CANDIDATES, cg.QUERIES, POSITIONS)
FIXTURES_DIR = "tests/str/fixtures"
REASONING_EFFORT = "low"  # 308 기준 ② — 온도를 못 걸 때 고정
TIMEOUT_S = 8.0  # 308 기준 ② `RAG_RERANK_TIMEOUT_S=8` — 다르면 p95·실패율이 기준과 달라짐(추가 검토 2)


def fixture_paths(queries: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({f"{FIXTURES_DIR}/{q['base']}" for q in queries["queries"]}))


def refuse_before(repo: Path, out: Path | None) -> tuple[dict[str, Any] | None, dict[str, str], str | None]:
    """외부 호출·DB 전 거절 — (입력, sha256, 이유). `out` 이 None 이면(dry) 결과 파일 검사만 건너뜀."""
    if reason := cg.criteria_problem(repo):
        return None, {}, reason
    if out is not None and out.exists():
        return None, {}, f"결과 파일이 이미 있음({out.name})"
    loaded, digests, reason = cg.read_committed(repo, INPUTS)
    if reason or loaded is None:
        return None, {}, reason
    fixtures, fixture_digests, reason = cg.read_committed(repo, fixture_paths(loaded[cg.QUERIES]))
    if reason or fixtures is None:
        return None, {}, reason
    if reason := unconfirmed(loaded[cg.CANDIDATES]):
        return None, {}, f"v3 정답 확인 안 끝남: {reason}"
    return (
        {**loaded, **fixtures},
        {**digests, **fixture_digests},
        None,
    )  # 픽스처 객체도 — 질의는 이것만으로 만듦


def real_mode_problem(settings: Settings) -> str | None:
    """실측 모드 — 녹화 재생이면 실측이 아님 · 모델 빈 값 · 추론 설정이 기준과 다름."""
    if settings.ai_llm_mock:
        return "AI_LLM_MOCK=true — 녹화 재생은 실측이 아님"
    if not rerank_model(settings):
        return "리랭커 모델이 비어 있음(RAG_RERANK_MODEL · LLM_MODEL_JUDGE, 공백 제외)"
    if settings.llm_reasoning_effort != REASONING_EFFORT:
        return f"LLM_REASONING_EFFORT 가 {REASONING_EFFORT} 가 아님"
    if float(settings.rag_rerank_timeout_s) != TIMEOUT_S:
        return f"RAG_RERANK_TIMEOUT_S 가 기준값 {TIMEOUT_S:g} 가 아님"
    if not settings.embedding_model.strip():
        return "EMBEDDING_MODEL 이 비어 있음"
    return None


def embedding_model_problem(session: Session, expected: str) -> str | None:
    """DB 청크의 `embedding_model` 이 정확히 하나이고 질의 임베딩 모델과 같아야(추가 검토 2 — 사전·스냅샷 둘 다)."""
    models = set(session.execute(text("SELECT DISTINCT embedding_model FROM ai.reference_chunks")).scalars())
    if models != {expected.strip()}:
        return f"DB embedding_model {len(models)}종 — 질의 모델과 하나로 같아야 함"
    return None


def no_answer_problem(
    queries: list[dict[str, Any]], cands: dict[str, list[Reference]], answers: dict[str, set[str]]
) -> str | None:
    """정답 없는 질의(유형 없음·그 유형 정답 0)에 초안 경로 결과가 있으면 판정 중단(②의 0건 유지)."""
    leaks = [q["id"] for q in queries if not answers.get(q["typology"] or "") and cands[q["id"]]]
    return f"정답 없는 질의에 결과가 있음: {leaks}" if leaks else None
