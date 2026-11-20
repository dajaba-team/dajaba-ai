"""SCRUM-305 태그 도구 순수 부분 (docs/str/10 "305 실행 기록" 태그 도구). DB·LLM 0 — 합성 청크."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from tests.str import rag_corpus_tags as tags
from tests.str.rag_corpus_world import _with_line, untagged_manifest
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

REPO = Path(__file__).parents[2]
APG, FIN = "apg-typologies-2025", "fincen-cmln-2025"
# (chunk_id, doc_id, page) — APG p5 두 청크, p6 한 청크, FinCEN p2 한 청크
NEW = [("a1" * 32, APG, 5), ("a2" * 32, APG, 5), ("a3" * 32, APG, 6), ("f1" * 32, FIN, 2)]
OLD_TAGGED = {"CYCLE": ["o1" * 32, "o2" * 32], "SCATTER_GATHER": [], "GATHER_SCATTER": []}
OLD_LOC = {"o1" * 32: ("ffiec-redflags", 6), "o2" * 32: ("ffiec-redflags", 6)}


def _grade(chunk: str, typology: str) -> int:
    return {("a1" * 32, "CYCLE"): 1, ("f1" * 32, "GATHER_SCATTER"): 2}.get((chunk, typology), 0)


def _draft() -> dict:
    """본문 자리에 chunk_id — 가짜 등급 함수가 청크를 알아보게."""
    return tags.draft_doc([(c, d, p, c) for c, d, p in NEW], _grade, prompt_sha256="ab" * 32, model="m")


def test_prompt_v2_adds_sg_gs_and_v1_is_unchanged() -> None:
    v2 = (REPO / "tools/prompts/rag_answer_v2.md").read_text(encoding="utf-8")
    assert "SCATTER_GATHER" in v2 and "GATHER_SCATTER" in v2 and "FAN_IN" not in v2.split("Grades:")[0]
    draft_275 = json.loads((REPO / "tests/str/rag_eval_v2/answer_draft.json").read_text(encoding="utf-8"))
    assert (
        sha256((REPO / "tools/prompts/rag_answer_v1.md").read_bytes()).hexdigest()
        == draft_275["prompt_sha256"]
    )


def test_draft_asks_three_typologies_and_keeps_no_text() -> None:
    asked: list[tuple[str, str]] = []

    def grade(chunk: str, typology: str) -> int:
        asked.append((chunk, typology))
        return 0

    doc = tags.draft_doc([(c, d, p, "본문") for c, d, p in NEW], grade, prompt_sha256="ab" * 32, model="m")
    assert {t for _, t in asked} == set(tags.CORPUS_TYPOLOGIES) and len(asked) == len(NEW) * 3
    assert "본문" not in json.dumps(doc, ensure_ascii=False)
    assert set(doc["graded"]) == set(tags.CORPUS_TYPOLOGIES)
    assert set(doc["graded"]["CYCLE"][0]) == {"chunk_id", "doc_id", "page", "grade"}


def test_draft_refuses_old_doc_rows() -> None:
    with pytest.raises(ValueError):
        tags.draft_doc([("o1" * 32, "ffiec-redflags", 6, "t")], _grade, prompt_sha256="ab" * 32, model="m")


def test_sheet_scope_is_candidate_pages_plus_old_tagged() -> None:
    scope = tags.sheet_scope(_draft(), NEW, OLD_TAGGED, OLD_LOC)
    by = {t: sorted(c for tt, c, _, _ in scope if tt == t) for t in tags.CORPUS_TYPOLOGIES}
    assert by["CYCLE"] == sorted(["a1" * 32, "a2" * 32, "o1" * 32, "o2" * 32])  # p5 전부 + 기존 태그
    assert by["GATHER_SCATTER"] == ["f1" * 32]
    assert by["SCATTER_GATHER"] == []
    assert all(t in tags.CORPUS_TYPOLOGIES for t, *_ in scope)  # FAN·FX_RELAY 없음


def test_numbered_rows_are_stable_and_unique() -> None:
    scope = tags.sheet_scope(_draft(), NEW, OLD_TAGGED, OLD_LOC)
    rows = tags.numbered(scope)
    assert rows == tags.numbered(list(reversed(scope)))  # 순서와 무관
    assert len({r[0] for r in rows}) == len(scope) and rows[0][0] == "CY-001"


def test_typology_pages_from_confirmed_grades_new_docs_only() -> None:
    loc = {c: (d, p) for c, d, p in NEW} | OLD_LOC
    grades = {
        ("CYCLE", "a2" * 32): 1,
        ("CYCLE", "a1" * 32): 0,
        ("CYCLE", "o1" * 32): 2,
        ("GATHER_SCATTER", "f1" * 32): 1,
    }
    pages = tags.typology_pages(grades, loc)
    assert pages == {
        APG: {"CYCLE": [5]},
        FIN: {"GATHER_SCATTER": [2]},
        NEW_DOC_IDS[1]: {},
    }  # 새 3문서 전부, 기존 문서 없음


def test_answers_doc_needs_checker_and_full_scope() -> None:
    scope = tags.sheet_scope(_draft(), NEW, OLD_TAGGED, OLD_LOC)
    graded = {(t, c): 0 for t, c, _, _ in scope}
    doc = tags.answers_doc(graded, scope, checker="김종민", checked_at="2026-11-21", draft_sha256="cd" * 32)
    assert doc["checked_by"] == "김종민" and set(doc["grades"]) == set(tags.CORPUS_TYPOLOGIES)
    with pytest.raises(ValueError):
        tags.answers_doc(graded, scope, checker=" ", checked_at="2026-11-21", draft_sha256="cd" * 32)
    with pytest.raises(ValueError):
        tags.answers_doc(
            dict(list(graded.items())[1:]), scope, checker="김종민", checked_at="x", draft_sha256="cd" * 32
        )


def test_manifest_update_touches_only_new_doc_lines() -> None:
    text = untagged_manifest()
    out = tags.manifest_with_pages(
        text, {APG: {"CYCLE": [5, 7]}, FIN: {"GATHER_SCATTER": [2]}, NEW_DOC_IDS[1]: {}}
    )
    before, after = text.splitlines(), out.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert len(changed) == 2
    assert all(any(f'"id": "{d}"' in after[i] for d in NEW_DOC_IDS) for i in changed)
    docs = {d["id"]: d for d in json.loads(out)["documents"]}
    assert (
        docs[APG]["typology_pages"] == {"CYCLE": [5, 7]}
        and "typology_pages" not in docs["fintrac-underground-banking-2023"]
    )


@pytest.mark.parametrize(
    "bad", [{APG: {"FAN_IN": [1]}}, {"ffiec-redflags": {"CYCLE": [1]}}, {APG: {"FX_RELAY": [1]}}]
)
def test_manifest_update_refuses_fan_old_docs_and_unknown_typologies(bad: dict) -> None:
    text = (REPO / "corpus/manifest.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        tags.manifest_with_pages(text, bad)


# ───────── 태그 도구 추가 검토 1 ─────────

ALL3 = {d: {} for d in NEW_DOC_IDS}
DB_NEW = list(NEW)
EXPECT = {d: sum(1 for _, dd, _ in NEW if dd == d) for d in NEW_DOC_IDS}
BASE_OLD = {"CYCLE": list(tags.BASELINE_OLD_TAGGED["CYCLE"]), "SCATTER_GATHER": [], "GATHER_SCATTER": []}


def test_scope_problems_ok_and_missing_chunk_on_same_page() -> None:
    assert tags.scope_problems(_draft(), DB_NEW, BASE_OLD, EXPECT) == []
    assert tags.scope_problems(_draft(), DB_NEW[1:], BASE_OLD, EXPECT) != []  # APG p5 청크 하나가 DB 에 없음


def test_scope_problems_empty_draft_and_old_tag_drift() -> None:
    empty = tags.draft_doc([], _grade, prompt_sha256="ab" * 32, model="m")
    assert tags.scope_problems(empty, DB_NEW, BASE_OLD, EXPECT) != []  # 적재 전에 만든 빈 초벌
    assert tags.scope_problems(_draft(), DB_NEW, {**BASE_OLD, "CYCLE": ["x" * 64]}, EXPECT) != []


def test_loaded_problems_needs_34_17_246() -> None:
    rows = [(f"{d[:2]}{i:062d}", d, 1, "t") for d, n in tags.NEW_DOC_CHUNKS.items() for i in range(n)]
    assert tags.loaded_problems(rows) == []
    assert tags.loaded_problems(rows[1:]) != [] and tags.loaded_problems([]) != []


def test_pages_are_recomputed_and_zeroed_pages_removed() -> None:
    text = _with_line(
        (REPO / "corpus/manifest.json").read_text(encoding="utf-8"), APG, typology_pages={"CYCLE": [5]}
    )
    out = tags.manifest_with_pages(text, ALL3)
    assert "typology_pages" not in {d["id"]: d for d in json.loads(out)["documents"]}[APG]


@pytest.mark.parametrize(
    "extra", [{"typology_pages": {"FX_RELAY": [3]}}, {"typologies": ["FAN_IN"]}], ids=["fx", "fan"]
)
def test_original_new_line_with_fan_or_fx_is_refused(extra: dict) -> None:
    text = _with_line((REPO / "corpus/manifest.json").read_text(encoding="utf-8"), APG, **extra)
    with pytest.raises(ValueError):
        tags.manifest_with_pages(text, ALL3)


def test_manifest_without_new_docs_or_reformatted_is_refused() -> None:
    current = (REPO / "corpus/manifest.json").read_text(encoding="utf-8")
    old8 = "\n".join(x for x in current.splitlines() if not any(f'"id": "{d}"' in x for d in NEW_DOC_IDS))
    old8 = old8.replace("},\n  ]", "}\n  ]")  # 마지막 기존 줄 쉼표 정리 — develop 참조 없이 8문서 manifest
    assert len(json.loads(old8)["documents"]) == 8
    compact = json.dumps(
        json.loads((REPO / "corpus/manifest.json").read_text(encoding="utf-8")), ensure_ascii=False
    )
    for text in (old8, compact):
        with pytest.raises(ValueError):
            tags.manifest_with_pages(text, ALL3)
