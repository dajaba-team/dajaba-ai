"""응답에 붙는 버전들. 어떤 코드·모델·프롬프트·코퍼스에서 나온 응답인지 재구성할 수 있어야 한다 (docs/shared/04)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aml_ai.shared.config import Settings


def scoring_mode(settings: Settings) -> str:
    """목업이면 mock, score_service 가 aml_ml 을 실제로 부르기 전에는 패키지 유무와 무관하게 unavailable.

    model 판단은 연결 PR(SCRUM-130 나머지)에서 넣는다.
    """
    return "mock" if settings.ai_scoring_mock else "unavailable"


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
