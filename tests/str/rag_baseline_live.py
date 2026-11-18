"""SCRUM-146 기준선 (손 실행, pytest 수집 X).

--dry: 실제 임베딩 0, 가짜 벡터로 읽기 전용 DB 경로만 확인.
--kinds a|a,c|a,b,c: 여러 번 찾기의 검색어 조합. a/b 진단 호출은 따로 센다.
결과에는 청크 위치와 cosine만 남기고 청크 원문·앞부분 지문을 넣지 않는다.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from aml_ai.shared.config import Settings, get_settings
from aml_ai.str.domain import constants
from aml_ai.str.infrastructure import retriever as retriever_mod
from tests.str.rag_baseline_live_db import (
    corpus_rows,
    language_chars,
    readonly_session,
    restore_sequences,
)
from tests.str.rag_baseline_live_overlap import overlap_diagnostics
from tests.str.rag_baseline_live_run import run_condition
from tests.str.rag_baseline_support import chunk_ref, parse_kinds
from tests.str.rag_eval_live_support import retrieval_version, verify_expected

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "tests/str/retrieval_eval.json"
DEFAULT_OUT = REPO / "tests/str/rag_baseline_20261118.json"
MEASUREMENT_MIN_SIMILARITY = 0.0


def display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO)
    except ValueError:
        return path


def configuration(settings: Settings, manifest_bytes: bytes, kinds: tuple[str, ...], dry: bool) -> dict:
    names = (
        "RAG_CANDIDATES",
        "RAG_TOP_K",
        "MIN_SIMILARITY",
        "REFERENCE_TEXT_MAX_CHARS",
        "RAG_RRF_K",
        "RAG_MAX_QUERIES",
    )
    return {
        "constants": {name: getattr(constants, name) for name in names},
        "measurement_min_similarity": MEASUREMENT_MIN_SIMILARITY,
        "retrieval_version": retrieval_version(settings),
        "embedding_model": settings.embedding_model,
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "kinds": list(kinds),
        "dry": dry,
        "interpretation": "만점 세트라 개선 판정 못 함 · 방향만",
    }


def collect(settings: Settings, kinds: tuple[str, ...], dry: bool) -> dict:
    data = json.loads(EVAL.read_text(encoding="utf-8"))
    manifest_bytes = (settings.corpus_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    seq, unavailable = restore_sequences(manifest, settings.corpus_dir)
    with readonly_session() as session:
        verify_expected(session, data["expected_sets"])
        rows = corpus_rows(session)
        characters = language_chars(session)
    plans: dict[str, list[str]] = {}
    conditions = {
        f"{'multi' if multi else 'single'}_filter_{'on' if filtered else 'off'}": run_condition(
            data,
            settings,
            dry=dry,
            multi=multi,
            filtered=filtered,
            kinds=kinds,
            rows=rows,
            seq=seq,
            plans=plans,
        )
        for multi in (False, True)
        for filtered in (True, False)
    }
    expected_ids = {cid for group in data["expected_sets"].values() for ids in group.values() for cid in ids}
    return {
        **configuration(settings, manifest_bytes, kinds, dry),
        "corpus_chunks": len(rows),
        "characters_by_lang": characters,
        "page_seq_unavailable": unavailable,
        "page_seq_unmatched": [chunk_ref(row, seq) for cid, row in rows.items() if cid not in seq],
        "expected_chunks": [chunk_ref(rows[cid], seq) for cid in sorted(expected_ids)],
        "conditions": conditions,
        "explain": plans,
        "ab_overlap": overlap_diagnostics(data, settings, dry=dry, rows=rows, seq=seq),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kinds", type=parse_kinds, default=parse_kinds("a,b,c"))
    parser.add_argument("--dry", action="store_true")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help=f"출력 경로 (기본값: {display_path(DEFAULT_OUT)})"
    )
    args = parser.parse_args()
    saved = retriever_mod.MIN_SIMILARITY
    retriever_mod.MIN_SIMILARITY = MEASUREMENT_MIN_SIMILARITY
    try:
        result = collect(get_settings(), args.kinds, args.dry)
    finally:
        retriever_mod.MIN_SIMILARITY = saved
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    calls = sum(c["embedding_calls"] for c in result["conditions"].values())
    calls += result["ab_overlap"]["embedding_calls"]
    print(f"[rag_baseline] saved → {display_path(args.out)}; embedding_calls={calls}; dry={args.dry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
