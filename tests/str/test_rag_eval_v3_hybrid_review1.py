"""SCRUM-307 추가 검토 1 회귀 — 평균 산식 · RRF 앞 10 고정 · DB 태그 대조 · 위치표 칸 · ES 시간 · 실패 때 파일 0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import Reference
from aml_ai.str.domain.rag_queries import SearchQuery
from tests.str import rag_eval_v3_hybrid_es as es
from tests.str import rag_eval_v3_hybrid_guard as guard
from tests.str import rag_eval_v3_hybrid_live as live
from tests.str import rag_eval_v3_hybrid_run as run
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.rag_baseline_live_run import PreparedEmbedding

RUN1 = Path(__file__).parent / "fixtures/rag307_run1_answer_ranks.json"


def cand_file() -> dict:
    return json.loads(hs.CANDIDATES_FILE.read_text(encoding="utf-8"))


def _records(rows: list[dict], answers: dict[str, set[str]]) -> list[dict]:
    """정답 순위만 남긴 1회차 기록 → top10(정답 자리엔 정답 id, 나머지는 오답 자리표)."""
    out = []
    for row in rows:
        pool = sorted(answers.get(row["typology"] or "", set()))
        top = [f"x{i}" for i in range(1, 11)]
        for rank, cid in zip(row["answer_ranks"], pool, strict=False):
            top[rank - 1] = cid
        out.append({"typology": row["typology"], "top10": top})
    return out


def test_run1_means_use_unrounded_type_values() -> None:
    runs = json.loads(RUN1.read_text(encoding="utf-8"))["conditions"]
    cand = cand_file()
    mean = {}
    for name, rows in runs.items():
        answers = hs.answer_sets(cand, filtered=name.startswith("on"))
        mean[name] = hs.metrics(_records(rows, answers), answers)["mean"]["recall10"]
    assert (mean["off_a_kw1"], mean["off_ac_kw0"], mean["off_abc_kw1"]) == (0.063, 0.112, 0.132)
    gain = hs.choose_keyword(
        {"mean": {"recall10": mean["off_a_kw0"]}}, {"mean": {"recall10": mean["off_a_kw1"]}}
    )
    assert gain["gain"] == 0.010


class FakeRetriever:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    def _candidates(self, *_: object, **__: object) -> list[Reference]:
        return [ref(f"v{i}", 0.5 - i / 100) for i in range(1, 11)]

    def _cosines(self, _vec: list[float], ids: list[str]) -> list[Reference]:
        return [ref(c, float("nan") if c == "nan" else -0.01) for c in ids if c != "gone"]


def ref(cid: str, score: float) -> Reference:
    return Reference(chunk_id=cid, doc_id="d", doc_title="t", page=1, score=score, text="")


def prepared(keyword_lists: list[list[str]]) -> run.Prepared:
    emb = PreparedEmbedding([SearchQuery("a", "en", "s")], [[0.0]])
    query = {"id": "FI01", "typology": "FAN_IN", "uses": ["hit"]}
    return run.Prepared(query, emb, keyword_lists, keyword_ms=5.0)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "Retriever", FakeRetriever)


@pytest.mark.usefixtures("fake_db")
def test_rrf_top10_fixed_first_negative_cosine_kept() -> None:
    top, _ = run.search(prepared([["k1"]]), hs.Condition(False, ("a",), True), None)
    ids = [c for c, _ in top]
    assert len(ids) == 10 and "k1" in ids and "v10" not in ids  # 11위(v10)가 끌려 들어오지 않음
    assert dict(top)["k1"] == -0.01  # 유한한 음수 cosine 은 그 순위에


@pytest.mark.usefixtures("fake_db")
def test_keyword_chunk_without_db_score_stops() -> None:
    with pytest.raises(ValueError, match="DB 점수가 없음"):
        run.search(prepared([["gone"]]), hs.Condition(False, ("a",), True), None)


def test_db_tag_must_match_db_tagged() -> None:
    a, b = "a" * 64, "b" * 64
    cand = {
        "candidates": {"FAN_IN": [{"chunk_id": a, "db_tagged": True}, {"chunk_id": b, "db_tagged": False}]}
    }
    assert guard.tag_problem(cand, {a: {"FAN_IN"}, b: set()}) is None
    assert "2" in guard.tag_problem(cand, {a: set(), b: {"FAN_IN"}})  # 06 적용 뒤 같은 경우


def test_keyword_condition_adds_es_time_and_copies_position_fields_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live, "search", lambda p, c, s: ([("x", 0.5)], 2.0))
    positions = {"x": {"doc_id": "d", "page": 1, "pos": 1, "excerpt": "본문", "chunk_id": "z"}}
    cand = {"candidates": {"FAN_IN": [{"chunk_id": "x", "grade": 2, "db_tagged": True}]}}
    kw_on, kw_off = hs.Condition(False, ("a",), True), hs.Condition(False, ("a",), False)
    on = live.run_condition(kw_on, [prepared([])], positions, cand, None)["queries"][0]
    off = live.run_condition(kw_off, [prepared([])], positions, cand, None)["queries"][0]
    assert (on["search_ms"], on["pg_fuse_ms"], off["search_ms"]) == (7.0, 2.0, 2.0)
    assert on["top10"] == [{"rank": 1, "chunk_id": "x", "doc_id": "d", "page": 1, "pos": 1, "cosine": 0.5}]


def test_failure_mid_run_leaves_no_result_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "result_307.json"
    positions = tmp_path / "positions.json"
    positions.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(hs, "RESULT_FILE", out)
    monkeypatch.setattr(hs, "POSITIONS_FILE", positions)
    monkeypatch.setattr(live, "refuse", lambda *a: None)

    def boom(*_: object, **__: object) -> dict:
        raise es.PartialSearch("timed_out")

    monkeypatch.setattr(live, "evaluate", boom)
    with pytest.raises(es.PartialSearch):
        live.main([], settings=Settings())
    assert not out.exists()
