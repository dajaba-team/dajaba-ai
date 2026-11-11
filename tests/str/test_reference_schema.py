"""SCRUM-125 — Reference.chunk_id 선택 칸 라운드트립 (docs/str/10 "프롬프트에서", INTENT ★A 3).

- `chunk_id: str | None = None` 추가, 값은 content_hash (재적재해도 같은 id — 126 평가 단위)
- 옛 저장 응답 (chunk_id 없는 JSON) 그대로 통과 — 백엔드 AiDtos.java 는 references 안 읽어 안 깨짐
- contracts/examples/draft_response.json 왕복 — references=[] 그대로 통과

develop 에서 실패: `Reference` 가 `StrictModel(extra="forbid")` 라 `chunk_id` 칸 없으면 거부.
"""

from __future__ import annotations

import json
from pathlib import Path

from aml_ai.shared.schemas.str import DraftResponse, Reference

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_chunk_id_optional_roundtrip() -> None:
    """chunk_id 선택 칸 — 있을 때·없을 때 둘 다 라운드트립."""
    with_chunk = {
        "chunk_id": "a" * 64,  # sha256 16진 64자
        "doc_id": "fincen-funnel-2014",
        "doc_title": "Funnel Accounts",
        "page": 1,
        "score": 0.82,
        "text": "Funnel Account: An individual or business account ...",
    }
    ref = Reference.model_validate(with_chunk)
    assert ref.chunk_id == "a" * 64
    assert ref.model_dump()["chunk_id"] == "a" * 64

    without_chunk = {k: v for k, v in with_chunk.items() if k != "chunk_id"}
    ref_old = Reference.model_validate(without_chunk)
    assert ref_old.chunk_id is None  # 기본 None — 하위 호환


def test_chunk_id_default_none_when_omitted() -> None:
    """Reference(doc_id, ...) 생성 — chunk_id 기본값 None."""
    ref = Reference(
        doc_id="ffiec-redflags",
        doc_title="BSA/AML Appendix F",
        page=5,
        score=0.71,
    )
    assert ref.chunk_id is None


def test_draft_response_example_roundtrip_preserves_references() -> None:
    """contracts/examples/draft_response.json 왕복 — references=[] 그대로 통과 (StrictModel extra forbid)."""
    sample_path = REPO_ROOT / "contracts" / "examples" / "draft_response.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    resp = DraftResponse.model_validate(sample)
    assert resp.generation_meta.references == []
    # 왕복 — 모양 유지
    dumped = resp.model_dump(mode="json")
    DraftResponse.model_validate(dumped)


def test_legacy_references_without_chunk_id_pass() -> None:
    """옛 generation_meta.references JSON (chunk_id 없음) — 저장된 응답 재사용 경로."""
    legacy_meta = {
        "llm_model": "gpt-x",
        "prompt_version": "narrative_v2",
        "few_shot_ids": [1, 2, 3],
        "references": [
            {
                "doc_id": "fincen-funnel-2014",
                "doc_title": "Funnel Accounts",
                "page": 1,
                "score": 0.9,
            },
            {
                "doc_id": "ffiec-redflags",
                "doc_title": "BSA/AML Appendix F",
                "page": 5,
                "score": 0.75,
                "text": "Unusually large number and variety of beneficiaries ...",
            },
        ],
        "retrieval_version": None,
        "server_version": "dev",
        "tokens_in": 100,
        "tokens_out": 50,
        "latency_ms": 1234,
    }
    from aml_ai.shared.schemas.str.draft import GenerationMeta

    meta = GenerationMeta.model_validate(legacy_meta)
    assert len(meta.references) == 2
    assert all(r.chunk_id is None for r in meta.references)
