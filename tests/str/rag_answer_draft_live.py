"""SCRUM-275 정답 초벌 (손 실행, pytest 수집 X — 진희 터미널, 호스트에서. docs/str/10 "평가 세트").

    PYTHONPATH=. uv run --frozen --extra dev --extra corpus python -m tests.str.rag_answer_draft_live --limit 5
    PYTHONPATH=. uv run --frozen --extra dev --extra corpus python -m tests.str.rag_answer_draft_live
    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_answer_draft_live --expand

(유형 × 청크) 한 번씩 LLM 에 등급(0·1·2)만 물음 — 프롬프트 `tools/prompts/rag_answer_v1.md`(버전 고정).
청크 본문을 외부 LLM 에 보냄(09 2026-11-19, 이용 조건 ⑤와 같은 처리). 결과 파일에는 chunk_id·doc_id·page·pos·grade 만.
`--expand` = 초벌 → `answers_dev.json`·`answers_holdout.json`(확인 칸 비움). 이미 있으면 덮어쓰지 않음.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import text

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.infrastructure.openai_responses import (
    build_body,
    extract_output_text,
    json_schema_for,
    parse_response,
)
from tests.str.rag_eval_v2_support import EVAL_DIR, expand_answers, load_queries

REPO = Path(__file__).resolve().parents[2]
PROMPT = REPO / "tools/prompts/rag_answer_v1.md"
PROMPT_VERSION = "rag_answer_v1"
DRAFT_FILE = EVAL_DIR / "answer_draft.json"
TYPOLOGIES = ("CYCLE", "FAN_IN", "FAN_OUT")  # 정답 있는 유형만(SG·GS·FX_RELAY 는 정답 없는 질의)
ANSWER_MAX_TOKENS = 2000  # 추론 모델 여유 포함 — 출력은 {"grade": n} 하나


class _Grade(BaseModel):
    grade: Literal[0, 1, 2]


def ask(http: httpx.Client, settings: Settings, system: str, typology: str, chunk: str) -> int:
    body = build_body(
        system,
        f"Typology: {typology}\n\nChunk:\n{chunk}",
        settings.llm_model_judge,
        ANSWER_MAX_TOKENS,
        json_schema_for(_Grade, name="rag_answer_grade"),
        temperature_supported=settings.llm_temperature_supported,
        reasoning_effort=settings.llm_reasoning_effort,
    )
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    raw = parse_response(
        http.post(f"{settings.llm_api_base.rstrip('/')}/responses", json=body, headers=headers)
    )
    return _Grade.model_validate_json(extract_output_text(raw)).grade


def draft(settings: Settings, typologies: tuple[str, ...], limit: int | None) -> dict:
    from tests.str.rag_baseline_live_db import readonly_session, restore_sequences

    with readonly_session() as session:
        rows = session.execute(
            text(
                "SELECT chunk_id, doc_id, page, text FROM ai.reference_chunks ORDER BY doc_id, page, chunk_id"
            )
        ).all()
    rows = rows[:limit] if limit else rows
    manifest = json.loads((settings.corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    seq, unavailable = restore_sequences(manifest, settings.corpus_dir)
    system = PROMPT.read_text(encoding="utf-8")
    by_typology: dict[str, list[dict]] = {t: [] for t in typologies}
    with httpx.Client(timeout=settings.llm_timeout_s) as http:
        for typology in typologies:
            for row in rows:
                grade = ask(http, settings, system, typology, row.text)
                if grade > 0:
                    by_typology[typology].append(
                        {"chunk_id": row.chunk_id, "doc_id": row.doc_id, "page": row.page,
                         "pos": seq.get(row.chunk_id), "grade": grade}
                    )  # fmt: skip
            print(f"{typology}: graded={len(rows)} positive={len(by_typology[typology])}")
    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256(PROMPT.read_bytes()).hexdigest(),
        "model": settings.llm_model_judge,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "chunks": len(rows),
        "limit": limit,
        "pos_unavailable_docs": unavailable,
        "by_typology": by_typology,
    }


def expand() -> int:
    source = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
    for split in ("dev", "holdout"):
        target = EVAL_DIR / f"answers_{split}.json"
        if target.exists():
            print(f"{target.name} 있음 — 덮어쓰지 않음(확인 내용 보호)")
            return 1
        doc = expand_answers(source, load_queries(split))
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{target.name}: queries={len(doc['queries'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--typologies", default=",".join(TYPOLOGIES))
    parser.add_argument("--limit", type=int, default=None, help="앞 N 청크만(시험 실행 — 파일 이름에 _limit)")
    parser.add_argument("--expand", action="store_true")
    args = parser.parse_args()
    if args.expand:
        return expand()
    result = draft(get_settings(), tuple(args.typologies.split(",")), args.limit)
    out = DRAFT_FILE if args.limit is None else EVAL_DIR / "answer_draft_limit.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
