"""응답에 붙는 버전들. 어떤 코드·모델·프롬프트·코퍼스에서 나온 응답인지 재구성할 수 있어야 한다 (docs/shared/04)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aml_ai.shared.config import Settings
from aml_ai.str.domain.constants_rag_query import QUERY_KINDS

_served_model: tuple[str, str] | None = None


def set_served_model(versions: tuple[str, str] | None) -> None:
    global _served_model
    _served_model = versions


def scoring_mode(settings: Settings) -> str:
    """이 프로세스에서 실제 모델 점수 저장을 확인한 뒤 model을 알린다."""
    if settings.ai_scoring_mock:
        return "mock"
    return "model" if _served_model is not None else "unavailable"


def retrieval_version(settings: Settings) -> str | None:
    """{embedding_model}@{manifest_sha256[:8]} — RAG 꺼져 있으면 None.

    SCRUM-275: 빈칸 채우기가 켜져 있으면(v4 만) 꼬리 `+fill:{검색어 종류}+kw:{ELASTIC_INDEX}` (str/10 "버전").
    """
    manifest = settings.corpus_dir / "manifest.json"
    if not settings.rag_enabled or not manifest.exists():
        return None
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()[:8]
    version = f"{settings.embedding_model}@{digest}"
    if settings.rag_gap_fill_active:
        version += f"+fill:{''.join(QUERY_KINDS)}+kw:{settings.elastic_index}"
    return version


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def health_versions(settings: Settings) -> dict[str, str | None]:
    mv, fv = (None if settings.ai_scoring_mock else _served_model) or (None, None)
    return {
        "server_version": settings.server_version,
        "model_version": mv,
        "feature_version": fv,
        "retrieval_version": retrieval_version(settings),
    }


def generation_meta(
    settings: Settings,
    *,
    llm_model: str,
    prompt_version: str,
    few_shot_ids: list[int],
    references: list[dict[str, object]],
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    rewrite: dict[str, object] | None = None,
) -> dict[str, object]:
    """STR 응답 generation_meta (규약 5절). 필드 이름이 바뀌면 schemas/str.py 와 같이.

    `rewrite` 는 SCRUM-147 — 초안 생성 안 작성자–비평가 고쳐 쓰기 결과. 생략하면 응답에서 제외됨.
    """
    out: dict[str, object] = {
        "llm_model": llm_model,
        "prompt_version": prompt_version,
        "few_shot_ids": few_shot_ids,
        "references": references,
        "retrieval_version": retrieval_version(settings),
        "server_version": settings.server_version,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
    }
    if rewrite is not None:
        out["rewrite"] = rewrite
    return out


def stable_json(obj: object) -> str:
    """녹화 파일 이름·해시용. 키 정렬, 공백 없음."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
