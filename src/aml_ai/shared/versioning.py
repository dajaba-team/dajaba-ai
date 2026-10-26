"""응답에 붙는 버전들. 어떤 코드·모델·프롬프트·코퍼스에서 나온 응답인지 재구성할 수 있어야 한다 (docs/shared/04)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aml_ai.shared.config import Settings


def model_versions() -> tuple[str | None, str | None]:
    """aml_ml 이 설치돼 있으면 (MODEL_VERSION, FEATURE_VERSION), 아니면 (None, None)."""
    try:
        import aml_ml  # type: ignore[import-not-found]

        return aml_ml.MODEL_VERSION, aml_ml.FEATURE_VERSION
    except ImportError:
        return None, None


def retrieval_version(settings: Settings) -> str | None:
    """{embedding_model}@{manifest_sha256[:8]} — RAG 꺼져 있으면 None."""
    manifest = settings.corpus_dir / "manifest.json"
    if not settings.rag_enabled or not manifest.exists():
        return None
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()[:8]
    return f"{settings.embedding_model}@{digest}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def health_versions(settings: Settings) -> dict[str, str | None]:
    mv, fv = model_versions()
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
) -> dict[str, object]:
    """STR 응답 generation_meta (규약 5절). 필드 이름이 바뀌면 schemas/str.py 와 같이."""
    return {
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


def stable_json(obj: object) -> str:
    """녹화 파일 이름·해시용. 키 정렬, 공백 없음."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
