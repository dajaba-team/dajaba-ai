"""SCRUM-307 판정 순수 계산·거절 (docs/str/10 "하이브리드·다중 질의 판정")."""

from __future__ import annotations

import json

import pytest

from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.rag_eval_v3_hybrid_run import fuse

TYPES4 = hs.JUDGED_TYPES


def _metric(hit: float, recall: float) -> dict:
    return {
        "types": {t: {"n": 6, "hit3": hit, "recall10": recall} for t in TYPES4},
        "mean": {"recall10": recall},
    }


def test_conditions_are_six_off_plus_three_on() -> None:
    conds = hs.conditions()
    assert [c.name for c in conds] == [
        "off_a_kw0", "off_a_kw1", "off_ac_kw0", "off_ac_kw1", "off_abc_kw0", "off_abc_kw1",
        "on_a_kw0", "on_ac_kw0", "on_abc_kw0",
    ]  # fmt: skip
    assert not [c for c in conds if c.filtered and c.keyword]  # 필터 켬 + 키워드 = 해당 없음


def test_metrics_hand_example_and_no_answer_queries_skipped() -> None:
    answers = {"FAN_IN": {"x", "y"}, "CYCLE": {"z"}}
    records = [
        {"typology": "FAN_IN", "top10": ["q", "w", "x", "e", "y"]},  # hit · recall 2/2
        {"typology": "FAN_IN", "top10": ["q", "w", "e", "x"]},  # hit 0(4위) · recall 1/2
        {"typology": "CYCLE", "top10": ["a"] * 10 + ["z"]},  # 11위 — recall 0
        {"typology": "FX_RELAY", "top10": ["x"]},  # 정답 없는 유형 — 분모에서 뺌
        {"typology": None, "top10": ["x"]},
    ]
    out = hs.metrics(records, answers)
    assert out["types"]["FAN_IN"] == {"n": 2, "hit3": 0.5, "recall10": 0.75}
    assert out["types"]["CYCLE"] == {"n": 1, "hit3": 0.0, "recall10": 0.0}
    assert "FX_RELAY" not in out["types"]
    assert out["mean"] == {"hit3": 0.25, "recall10": 0.375}  # 정답 있는 4유형 중 있는 것만 평균


def test_sg_is_table_only() -> None:
    answers = {t: {"x"} for t in hs.TABLE_TYPES}
    records = [{"typology": t, "top10": ["x"] if t == "SCATTER_GATHER" else []} for t in hs.TABLE_TYPES]
    out = hs.metrics(records, answers)
    assert out["types"]["SCATTER_GATHER"]["recall10"] == 1.0
    assert out["mean"]["recall10"] == 0.0


def test_answer_sets_filtered_uses_db_tagged_only() -> None:
    cand = {"candidates": {"FAN_IN": [
        {"chunk_id": "t", "grade": 2, "db_tagged": True},
        {"chunk_id": "f", "grade": 1, "db_tagged": False},
        {"chunk_id": "z", "grade": 0, "db_tagged": True},
    ]}}  # fmt: skip
    assert hs.answer_sets(cand, filtered=False) == {"FAN_IN": {"t", "f"}}
    assert hs.answer_sets(cand, filtered=True) == {"FAN_IN": {"t"}}


def test_repo_v3_answers_are_confirmed_and_counted() -> None:
    cand = json.loads(hs.CANDIDATES_FILE.read_text(encoding="utf-8"))
    assert hs.unconfirmed(cand) is None
    assert sum(map(len, hs.answer_sets(cand, filtered=False).values())) == 58
    assert sum(map(len, hs.answer_sets(cand, filtered=True).values())) == 45


@pytest.mark.parametrize(
    ("patch", "word"),
    [({"consensus_pending": True}, "consensus_pending"), ({"fan_checked_by": ""}, "fan_checked_by")],
)
def test_unconfirmed_reasons(patch: dict, word: str) -> None:
    cand = {"consensus_pending": False, "fan_checked_by": "a", "fan_checked_at": "d",
            "consensus_checked_by": "a", "consensus_checked_at": "d", "candidates": {}, **patch}  # fmt: skip
    assert word in hs.unconfirmed(cand)
    cand.update(consensus_pending=False, fan_checked_by="a", candidates={"X": [{"grade": None}]})
    assert hs.unconfirmed(cand) == "등급 빈 칸 1"


def test_combo_gain_boundary_and_fallback() -> None:
    base = _metric(1.0, 0.300)
    assert hs.choose_combo(
        {("a",): base, ("a", "c"): _metric(1.0, 0.400), ("a", "b", "c"): _metric(1.0, 0.399)}
    )["kinds"] == ["a", "c"]  # 0.10 정확히 = 넘음
    none = hs.choose_combo(
        {("a",): base, ("a", "c"): _metric(1.0, 0.399), ("a", "b", "c"): _metric(1.0, 0.3)}
    )
    assert none == {"kinds": ["a"], "passed": []}


def test_combo_one_lost_hit_fails() -> None:
    lost = _metric(1.0, 0.9)
    lost["types"]["CYCLE"]["hit3"] = round(5 / 6, 3)  # 6개 중 하나 잃음 = 0.167 하락 > 0.05
    out = hs.choose_combo({("a",): _metric(1.0, 0.1), ("a", "c"): lost, ("a", "b", "c"): lost})
    assert out["kinds"] == ["a"]


def test_combo_tie_prefers_fewer_queries() -> None:
    base = _metric(1.0, 0.1)
    tie = hs.choose_combo({("a",): base, ("a", "c"): _metric(1.0, 0.30), ("a", "b", "c"): _metric(1.0, 0.32)})
    assert tie["kinds"] == ["a", "c"]  # 차이 0.02 = 안
    wide = hs.choose_combo(
        {("a",): base, ("a", "c"): _metric(1.0, 0.30), ("a", "b", "c"): _metric(1.0, 0.321)}
    )
    assert wide["kinds"] == ["a", "b", "c"]


def test_keyword_boundary() -> None:
    assert hs.choose_keyword(_metric(1, 0.30), _metric(1, 0.35)) == {"keyword": True, "gain": 0.05}
    assert hs.choose_keyword(_metric(1, 0.30), _metric(1, 0.349))["keyword"] is False


def test_filter_on_any_hit_drop_excludes() -> None:
    drop = _metric(1.0, 1.0)
    drop["types"]["FAN_OUT"]["hit3"] = 0.833
    assert hs.filter_on_usable(
        {("a",): _metric(1.0, 0.9), ("a", "c"): drop, ("a", "b", "c"): _metric(1.0, 0.5)}
    ) == [["a", "b", "c"]]


def test_verdict_keyword_only_on_chosen_combo() -> None:
    by = {}
    for c in hs.conditions():
        recall = {("a",): 0.1, ("a", "c"): 0.3, ("a", "b", "c"): 0.1}[c.kinds] + (
            0.2 if c.keyword and c.kinds == ("a", "c") else 0
        )
        by[c] = _metric(1.0, recall)  # fmt: skip
    out = hs.verdict(by)
    assert out["combo"]["kinds"] == ["a", "c"]
    assert out["keyword"] == {"keyword": True, "gain": 0.2}


def test_fuse_ties_are_deterministic() -> None:
    # 두 목록에서 같은 RRF — cosine 큰 순, 같으면 chunk_id 오름차순
    assert fuse([[("b", 0.5), ("a", 0.5)], [("a", 0.5), ("b", 0.5)]], []) == ["a", "b"]
    assert fuse([[("b", 0.6), ("a", 0.5)], [("a", 0.5), ("b", 0.6)]], []) == ["b", "a"]
    assert fuse([[("v", 0.4)]], [["k"]]) == ["v", "k"]  # 키워드 cosine 0.0 → 같은 순위면 벡터 쪽 먼저


def test_forbidden_keys_found() -> None:
    assert hs.forbidden_keys({"a": [{"chunk_id": "x", "text": "y"}], "query": "q"}) == [
        "/a[0]/text",
        "/query",
    ]
    assert hs.forbidden_keys({"queries": [{"top10": [{"chunk_id": "x", "cosine": 0.1}]}]}) == []


def test_repo_criteria_section_has_the_numbers() -> None:
    from tests.str.rag_eval_v3_hybrid_guard import DOC_09, DOC_10, REPO_ROOT

    section = hs.criteria_section((REPO_ROOT / DOC_10).read_text(encoding="utf-8"))
    assert section and hs.criteria_line((REPO_ROOT / DOC_09).read_text(encoding="utf-8"))
    for number in ("≥ 0.10", "> 0.05", "0.02 이하", "≥ 0.05", "4유형", "1/6(0.167)"):
        assert number in section


def test_repo_positions_cover_answers_with_same_place() -> None:
    positions = json.loads(hs.POSITIONS_FILE.read_text(encoding="utf-8"))
    assert len(positions["positions"]) == 722
    assert hs.forbidden_keys(positions) == []
    cand = json.loads(hs.CANDIDATES_FILE.read_text(encoding="utf-8"))
    for rows in cand["candidates"].values():
        for r in rows:
            where = positions["positions"][r["chunk_id"]]
            assert (where["doc_id"], where["page"], where["pos"]) == (r["doc_id"], r["page"], r["pos"])


def test_repo_result_has_no_body_and_is_real_run() -> None:
    if not hs.RESULT_FILE.exists():
        pytest.skip("result_307.json 없음 — 추가 검토 1 뒤 다시 돌리기 전")
    doc = json.loads(hs.RESULT_FILE.read_text(encoding="utf-8"))
    assert hs.forbidden_keys(doc) == []
    conf = doc["configuration"]
    assert doc["status"] == "done" and conf["dry"] is False
    assert conf["criteria_commit"] == conf["head"]
    assert [c["name"] for c in doc["conditions"]] == [c.name for c in hs.conditions()]
