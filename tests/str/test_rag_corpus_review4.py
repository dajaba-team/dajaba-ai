"""SCRUM-305 태그 도구 추가 검토 4 회귀 (docs/str/10 "305 실행 기록" 태그 도구 ⑱). DB·LLM·검색 0.

기대 코퍼스 전체(기존 425 + 새 297, 위치·태그) = DB 스냅샷 전체여야 reserve — 실제 `corpus_ready_problems`.
"""

from __future__ import annotations

import pytest

from tests.str import rag_corpus_check as ck
from tests.str import rag_eval_corpus_live as live
from tests.str.rag_corpus_world import FTR, old_rows, problems, without_doc, world
from tests.str.test_rag_corpus_review3 import env  # noqa: F401 — 예약 회귀 환경(실제 대조 함수)


def _drop_line(w: dict, doc_id: str) -> None:
    w["manifest"] = {
        **w["manifest"],
        "documents": [d for d in w["manifest"]["documents"] if d["id"] != doc_id],
    }


def _doc_level_cycle(w: dict, doc_id: str) -> None:
    docs = [{**d, "typologies": ["CYCLE"]} if d["id"] == doc_id else d for d in w["manifest"]["documents"]]
    w["manifest"] = {**w["manifest"], "documents": docs}


def _dup_line(w: dict, doc_id: str) -> None:
    docs = w["manifest"]["documents"]
    w["manifest"] = {**w["manifest"], "documents": [*docs, next(d for d in docs if d["id"] == doc_id)]}


def _extra_line(w: dict) -> None:
    w["manifest"] = {
        **w["manifest"],
        "documents": [*w["manifest"]["documents"], {"id": "unknown-doc", "pages": 1}],
    }


BROKEN = {
    "old_doc_missing_712": lambda w: w.update(rows=without_doc(w["rows"], "fincen-funnel-2014")),
    "manifest_line_missing": lambda w: _drop_line(w, FTR),
    "doc_level_typologies": lambda w: _doc_level_cycle(w, FTR),
    "manifest_line_twice": lambda w: _dup_line(w, FTR),
    "untagged_old_line_missing": lambda w: _drop_line(w, "fatf-tbml-2020"),  # 추가 검토 5
    "unknown_line_added": _extra_line,
    "old_tag_dropped": lambda w: w["rows"].update({c: (d, p, ()) for c, (d, p, ts) in w["rows"].items() if "FAN_IN" in ts}),
}  # fmt: skip


def test_old_baseline_is_275_positions_with_manifest_tags() -> None:
    """기존 425 = 275 초벌 위치 + manifest 기존 줄 태그 — FAN_IN 19·FAN_OUT 6·CYCLE 2, 해시 고정값."""
    w = world()
    old = {c: w["rows"][c] for c, _, _ in old_rows()}
    assert len(old) == 425
    assert {t: sum(t in ts for _, _, ts in old.values()) for t in ("FAN_IN", "FAN_OUT", "CYCLE")} == {
        "FAN_IN": 19, "FAN_OUT": 6, "CYCLE": 2}  # fmt: skip
    assert ck.corpus_sha256(old) == ck.OLD_CORPUS_SHA256


@pytest.mark.parametrize("name", sorted(BROKEN))
def test_broken_corpus_is_a_problem(name: str) -> None:
    w = world()
    BROKEN[name](w)
    assert problems(w) != []


def test_problem_names_the_doc_and_counts() -> None:
    w = world()
    w["rows"] = without_doc(w["rows"], "fincen-funnel-2014")
    assert any("fincen-funnel-2014" in x and "빠짐 10" in x for x in problems(w))


@pytest.mark.parametrize(
    "name",
    ["old_doc_missing_712", "manifest_line_missing", "doc_level_typologies",
     "untagged_old_line_missing", "unknown_line_added"],
)  # fmt: skip
def test_reserve_is_not_called(env: tuple[dict, list], name: str) -> None:  # noqa: F811
    w, calls = env
    BROKEN[name](w)
    assert live.reserve_cmd(lambda _m: None) == 2 and calls == []


def test_problem_names_missing_and_extra_ids() -> None:
    w = world()
    _drop_line(w, "fatf-tbml-2020")
    _extra_line(w)
    got = " ".join(problems(w))
    assert "fatf-tbml-2020" in got and "unknown-doc" in got
