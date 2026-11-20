"""SCRUM-306 평가 세트 v3 — 질의 34 시드 재현·기존 질의와 겹침 0 · 정답 후보 출처·등급 (docs/str/10 SCRUM-306 줄)."""

from __future__ import annotations

import json
from collections import Counter

import pytest
from tools.rag2_sample import CORPUS_DIR

from aml_ai.str.domain.rag_queries import build_query
from tests.str import rag_eval_v3_candidates as cand
from tests.str import rag_eval_v3_draw as draw
from tests.str.rag_eval_v2_support import build_facts

_QUERIES = draw.load_queries()
_TAKEN = draw.existing_texts()
_CAND = json.loads(cand.CANDIDATES_FILE.read_text(encoding="utf-8"))
# 추출 규칙을 모듈과 따로 고정 — 모듈과 파일을 함께 바꿔도 여기서 걸림
EXPECTED_SEED = 306
EXPECTED_COUNTS = {"FAN_IN": 6, "FAN_OUT": 6, "CYCLE": 6, "SCATTER_GATHER": 6, "GATHER_SCATTER": 6,
                   "FX_RELAY": 2, None: 2}  # fmt: skip
EXPECTED_CANDIDATES = {
    "FAN_IN": 19,
    "FAN_OUT": 6,
    "CYCLE": 7,
    "SCATTER_GATHER": 2,
    "GATHER_SCATTER": 15,
}  # db_tagged
EXPECTED_ADDED = {"FAN_IN": 11, "FAN_OUT": 2}  # 합의 새 행 6 + 결정 행 7, 등급 ≥ 1 (②·③ 11/20)
NEW_SOURCES = ("합의_태그", "결정_태그")
QUERY_KEYS = {"id", "split", "typology", "base", "overrides", "uses"}
ROW_KEYS = {"chunk_id", "doc_id", "page", "pos", "source", "grade", "db_tagged"}


def test_file_is_the_seeded_draw() -> None:
    assert draw.QUERY_SEED == EXPECTED_SEED
    assert draw.draw_queries(_TAKEN) == _QUERIES


def test_counts_ids_and_uses() -> None:
    assert len(_QUERIES) == 34
    assert Counter(q["typology"] for q in _QUERIES) == EXPECTED_COUNTS
    assert len({q["id"] for q in _QUERIES}) == 34 and {q["split"] for q in _QUERIES} == {draw.SPLIT}
    for q in _QUERIES:
        want = (
            ["reference"] if q["typology"] is None else ["empty"] if q["typology"] == "FX_RELAY" else ["hit"]
        )
        assert q["uses"] == want and set(q) == QUERY_KEYS


def test_texts_distinct_and_not_in_any_existing_set() -> None:
    texts = [build_query(build_facts(q)) for q in _QUERIES]
    assert len(set(texts)) == len(texts)
    assert not set(texts) & _TAKEN
    assert len(_TAKEN) >= 50  # 275 dev 14 + 보류용 16 + holdout_v2 30 (같은 문자열은 하나로)


def test_existing_sets_are_unchanged_inputs() -> None:
    """건너뛸 목록이 비면 겹침 검사가 헛돎 — 세 파일 질의 수 고정."""
    from tests.str.rag_eval_corpus_support import load_queries as load_holdout_v2
    from tests.str.rag_eval_v2_support import load_queries as load_v2

    assert (len(load_v2("dev")), len(load_v2("holdout")), len(load_holdout_v2())) == (14, 16, 30)


def test_draw_skips_taken_text() -> None:
    first = _QUERIES[0]
    redrawn = draw.draw_queries(_TAKEN | {build_query(build_facts(first))})
    assert redrawn[0]["overrides"] != first["overrides"]


def test_candidates_shape_sources_and_grades() -> None:
    rows = {t: [r for r in rs if r["db_tagged"]] for t, rs in _CAND["candidates"].items()}
    assert {t: len(r) for t, r in rows.items()} == EXPECTED_CANDIDATES
    assert _CAND["consensus_pending"] is False
    assert (_CAND["consensus_checked_by"], _CAND["consensus_checked_at"]) == ("김종민", "2026-11-20")
    assert _CAND["grades_305"] == {"checked_by": "김종민", "checked_at": "2026-11-20"}
    assert (_CAND["fan_checked_by"], _CAND["fan_checked_at"]) == ("김종민", "2026-11-20")
    fan = [r["grade"] for t in cand.FAN_TYPES for r in rows[t]]
    assert sum(g >= 1 for g in fan) == 21  # FAN_IN 16 + FAN_OUT 5 (① 11/20)
    for typ, items in rows.items():
        assert all(set(r) == ROW_KEYS for r in items)
        if typ in cand.FAN_TYPES:
            assert all(r["source"] == cand.SOURCE_FAN and r["grade"] in (0, 1, 2) for r in items)  # ① 반영 뒤
        else:
            assert all(r["source"] == cand.SOURCE_305 and r["grade"] >= 1 for r in items)


def test_db_tagged_splits_old_sources_from_consensus_rows() -> None:
    """필터 켠 경로는 db_tagged=true 정답만으로도 계산 — FAN 태그·305 는 true, 합의·결정 새 행은 false·등급 ≥ 1."""
    rows = _CAND["candidates"]
    for items in rows.values():
        assert all(r["db_tagged"] is (r["source"] not in NEW_SOURCES) for r in items)
    added = {t: [r for r in items if not r["db_tagged"]] for t, items in rows.items()}
    assert {t: len(r) for t, r in added.items() if r} == EXPECTED_ADDED
    assert all(r["grade"] >= 1 for items in added.values() for r in items)
    records = _CAND["consensus_grades"]  # 확인 ②③ 0·1·2 기록 전부(적용 제안 입력)
    assert len(records) == 13 and {(r["typology"], r["chunk_id"]) for r in records} == {
        (t, r["chunk_id"]) for t, items in added.items() for r in items}  # fmt: skip
    old = {(t, r["chunk_id"]) for t, items in rows.items() for r in items if r["db_tagged"]}
    assert not old & {(t, r["chunk_id"]) for t, items in added.items() for r in items}


def test_305_candidates_equal_graded_rows() -> None:
    graded = json.loads(cand.GRADES_305.read_text(encoding="utf-8"))["grades"]
    for typ in cand.GRADED_TYPES:
        want = {(r["chunk_id"], r["grade"]) for r in graded[typ] if r["grade"] >= 1}
        assert {(r["chunk_id"], r["grade"]) for r in _CAND["candidates"][typ] if r["db_tagged"]} == want


def test_candidates_carry_no_text() -> None:
    raw = cand.CANDIDATES_FILE.read_text(encoding="utf-8")
    assert '"text"' not in raw and '"body"' not in raw


def _all_pdfs_present() -> bool:
    return all((CORPUS_DIR / "pdf" / f"{m['id']}.pdf").exists() for m in cand._metas())


@pytest.mark.skipif(not _all_pdfs_present(), reason="corpus/pdf 없음(git 무시 폴더) — 로컬에서 돎")
def test_candidates_rebuild_from_pdfs() -> None:
    graded = json.loads(cand.GRADES_305.read_text(encoding="utf-8"))["grades"]
    unapplied = {t: [{**r, "grade": None} if t in cand.FAN_TYPES else r for r in rows if r["db_tagged"]]
                 for t, rows in _CAND["candidates"].items()}  # fmt: skip
    assert cand.build_candidates(cand._metas(), graded) == unapplied  # FAN 등급·합의 행은 반영으로만 바뀜


def test_generator_refuses_existing_file(tmp_path, monkeypatch) -> None:
    """초안 생성은 파일이 없을 때만 — 확인 반영을 지우지 않음(재현 검사는 위 테스트가 메모리에서)."""
    target = tmp_path / "answer_candidates.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cand, "CANDIDATES_FILE", target)
    with pytest.raises(SystemExit, match="이미 있음"):
        cand.main()
    assert target.read_text(encoding="utf-8") == "{}"
