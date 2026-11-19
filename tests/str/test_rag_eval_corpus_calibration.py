"""SCRUM-304 기준 맞추기 표본 (docs/str/10 "확인자 기준서·기준 맞추기"). 275 정답 파일 읽기만 — DB·LLM 0."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from tests.str import rag_eval_corpus_draw as draw
from tests.str.rag_eval_corpus_draw import CALIBRATION_QUOTAS, calibration_population, draw_calibration
from tests.str.rag_eval_corpus_guard import normalized_sha256
from tests.str.rag_eval_corpus_support import (
    CALIBRATION_MATCH_MIN,
    CALIBRATION_ROWS,
    CORPUS_EVAL_DIR,
    calibration_agrees,
)

_FILE = json.loads((CORPUS_EVAL_DIR / "calibration_rows.json").read_text(encoding="utf-8"))
_POP = calibration_population()
_GRADE = {(r["typology"], r["chunk_id"]): r["grade"] for r in _POP}
ROW_KEYS = {"row_id", "chunk_id", "typology", "doc_id", "page", "pos"}
# 추가 검토 1 의 질의 쪽 지적과 같은 구멍 — 시드·층 배분을 모듈과 따로 고정
EXPECTED_SEEDS = (304, 3042)
EXPECTED_QUOTAS = {
    ("CYCLE", 1): 3, ("CYCLE", 0): 7,
    ("FAN_IN", 2): 4, ("FAN_IN", 1): 4, ("FAN_IN", 0): 2,
    ("FAN_OUT", 2): 2, ("FAN_OUT", 1): 2, ("FAN_OUT", 0): 1,
}  # fmt: skip
CALIBRATION_SHA256 = "53b9242845cd31f1b1d936aefc90aec616cdb5e54991071c858b9b2798b2b54c"


def _strata(rows: list[dict]) -> Counter:
    return Counter((r["typology"], _GRADE[(r["typology"], r["chunk_id"])]) for r in rows)


def test_population_is_the_rows_junhyuk_checked() -> None:
    assert len(_POP) == 487
    assert _strata(_POP) == {
        ("CYCLE", 1): 3, ("CYCLE", 0): 422,
        ("FAN_IN", 2): 13, ("FAN_IN", 1): 25, ("FAN_IN", 0): 5,
        ("FAN_OUT", 2): 4, ("FAN_OUT", 1): 13, ("FAN_OUT", 0): 2,
    }  # fmt: skip


def test_draw_rule_and_file_are_pinned() -> None:
    assert draw.CALIBRATION_SEEDS == EXPECTED_SEEDS
    assert list(draw.CALIBRATION_QUOTAS.items()) == list(EXPECTED_QUOTAS.items())  # 순서 포함
    assert normalized_sha256(_FILE) == CALIBRATION_SHA256


def test_changed_seed_breaks_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(draw, "CALIBRATION_SEEDS", (305, 3042))
    assert normalized_sha256(draw_calibration(_POP)) != CALIBRATION_SHA256


def test_file_is_the_seeded_draw() -> None:
    assert draw_calibration(_POP) == _FILE
    assert [r["seed"] for r in _FILE["rounds"]] == [304, 3042]


@pytest.mark.parametrize("n", [0, 1])
def test_each_round_follows_quotas(n: int) -> None:
    rows = _FILE["rounds"][n]["rows"]
    assert len(rows) == CALIBRATION_ROWS == sum(CALIBRATION_QUOTAS.values())
    assert _strata(rows) == CALIBRATION_QUOTAS
    assert sum(k for (_, g), k in CALIBRATION_QUOTAS.items() if g >= 1) == 15


def test_second_round_records_reused_rows() -> None:
    first, second = ({(r["typology"], r["chunk_id"]) for r in rd["rows"]} for rd in _FILE["rounds"])
    assert _FILE["rounds"][1]["reused_from_round1"] == len(first & second) == 3  # CYCLE 1등급 3행뿐


def test_handoff_rows_carry_no_grade_and_no_stratum_order() -> None:
    for rd in _FILE["rounds"]:
        assert all(set(r) == ROW_KEYS for r in rd["rows"])
        assert [r["chunk_id"] for r in rd["rows"]] == sorted(r["chunk_id"] for r in rd["rows"])
    raw = json.dumps(_FILE)
    assert "grade" not in raw and "llm" not in raw.lower()


def _reference(rows: list[dict]) -> dict[tuple[str, str], int]:
    return {(r["typology"], r["chunk_id"]): _GRADE[(r["typology"], r["chunk_id"])] for r in rows}


@pytest.mark.parametrize(("flips", "same"), [(0, True), (5, True), (6, False)])
def test_agreement_threshold(flips: int, same: bool) -> None:
    ref = _reference(_FILE["rounds"][0]["rows"])
    checker = {k: (0 if g >= 1 else 1) if i < flips else g for i, (k, g) in enumerate(ref.items())}
    out = calibration_agrees(ref, checker)
    assert out == {"rows": 25, "matches": 25 - flips, "same": same, "match_min": CALIBRATION_MATCH_MIN}


def test_one_vs_two_is_still_agreement() -> None:
    ref = _reference(_FILE["rounds"][0]["rows"])
    checker = {k: (2 if g == 1 else 1 if g == 2 else 0) for k, g in ref.items()}
    assert calibration_agrees(ref, checker)["matches"] == 25


def test_agreement_rejects_missing_rows() -> None:
    ref = _reference(_FILE["rounds"][0]["rows"])
    with pytest.raises(ValueError):
        calibration_agrees(ref, dict(list(ref.items())[:24]))
