"""SCRUM-225 — 켬/끔 하네스 고침 2건 (docs/str/10 「RAG 켬/끔 2차」).

1. 공개용 결과 JSON 에 ON/OFF 를 맞힐 수 있는 칸이 없음 — 검색 진단은 진단 파일로, reveal 때 같이 엶.
2. 사후 파서가 여러 줄 본문을 이어 붙임 — `_blind_md` 로 쓴 md 를 다시 읽어 글자·반입 후보 수가 같음.
LLM·DB·임베딩 호출 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import Facts, NarrativeSection, SectionV2
from tests.str.rag_onoff_live import _blind_md, _record_blind, _record_diag
from tests.str.rag_onoff_reveal import reveal
from tests.str.rag_onoff_unsupported import unsupported_candidate_count
from tests.str.rag_onoff_unsupported_post import _parse_blind

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "facts_fan_in.json"
DIAG_KEYS = {"retrieval_status", "references", "references_count"}


def _result(status: str, refs: int) -> dict:
    return {
        "references_count": refs,
        "references": [{"chunk_id": "c", "doc_id": "d", "page": 1}] * refs,
        "retrieval_status": status,
        "code_checks_all_match": True,
        "code_checks_failed": [],
        "judge_scores_median": {"TYPOLOGY_CONSISTENT": 5},
        "typology_consistent": 5,
        "no_unsupported_claim": 5,
        "grounds_signal_mentions": 0,
        "unsupported_candidate_count": 0,
        "fact_coverage": {"covered": 14, "required": 14, "missing": []},
        "status": "PASSED",
        "few_shot_ids": [2, 3, 4],
        "prompt_version": "narrative_v3",
        "judge_prompt_version": "judge_v3",
        "llm_model_generate": "m",
        "llm_model_judge": "j",
    }


def test_public_record_has_no_retrieval_hint() -> None:
    on = _record_blind("case_1_fan_in", "FAN_IN", "A", _result("ok", 2))
    off = _record_blind("case_1_fan_in", "FAN_IN", "B", _result("disabled", 0))
    for rec in (on, off):
        assert not DIAG_KEYS & set(rec)
        assert "rag" not in rec
        assert rec["fact_coverage"]["required"] == 14
    strip = {k: v for k, v in on.items() if k != "side"}
    assert strip == {k: v for k, v in off.items() if k != "side"}  # 같은 지표면 구분 불가


def test_diag_record_keeps_retrieval_fields() -> None:
    diag = _record_diag("case_1_fan_in", "A", _result("ok", 2))
    assert diag == {
        "case_id": "case_1_fan_in", "side": "A", "retrieval_status": "ok", "references_count": 2,
        "references": [{"chunk_id": "c", "doc_id": "d", "page": 1}] * 2,
    }  # fmt: skip


def test_reveal_merges_diag_and_excludes_failed() -> None:
    result = {"runs": [_record_blind("c1", "FAN_IN", s, _result("ok", 0)) for s in ("A", "B")]}
    diag = {
        "runs": [
            _record_diag("c1", "A", _result("failed", 0)),
            _record_diag("c1", "B", _result("disabled", 0)),
        ]
    }
    out = reveal(result, {"c1": {"A_rag": True, "B_rag": False}}, diag)
    assert [r["rag"] for r in out["runs_revealed"]] == [False]
    assert out["runs_revealed"][0]["retrieval_status"] == "disabled"
    assert out["excluded_failed"][0]["rag"] is True


def _sec(name: str, text: str) -> NarrativeSection:
    return NarrativeSection(section=SectionV2(name), text=text, cites=[])


def test_parser_joins_multiline_body_roundtrip() -> None:
    facts = Facts.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    a = [_sec("SUBJECT", "첫 줄임.\n둘째 줄 Acme Holdings 언급.\n셋째 줄."), _sec("GROUNDS", "근거 한 줄.")]
    b = [_sec("SUBJECT", "B 본문."), _sec("GROUNDS", "B 근거\n둘째 줄 Zeta Trading.")]
    md = _blind_md([{"case_id": "case_1_fan_in", "typology": "FAN_IN", "narrative_A": a, "narrative_B": b}])
    parsed = _parse_blind(md)["case_1_fan_in"]
    for side, orig in (("A", a), ("B", b)):
        assert [s.text for s in parsed[side]] == [s.text for s in orig]
        assert unsupported_candidate_count(parsed[side], facts) == unsupported_candidate_count(orig, facts)
    assert unsupported_candidate_count(parsed["A"], facts) > 0


def _new_result() -> dict:
    return {"runs": [_record_blind("c1", "FAN_IN", s, _result("ok", 0)) for s in ("A", "B")]}


KEY = {"c1": {"A_rag": True, "B_rag": False}}


def test_reveal_new_format_without_diag_stops() -> None:
    with pytest.raises(ValueError, match="needs diag"):
        reveal(_new_result(), KEY)


def test_reveal_new_format_with_one_diag_missing_stops() -> None:
    diag = {"runs": [_record_diag("c1", "B", _result("disabled", 0))]}
    with pytest.raises(ValueError, match="diag missing"):
        reveal(_new_result(), KEY, diag)


def test_reveal_failed_diag_goes_to_excluded() -> None:
    diag = {
        "runs": [
            _record_diag("c1", "A", _result("failed", 0)),
            _record_diag("c1", "B", _result("disabled", 0)),
        ]
    }
    out = reveal(_new_result(), KEY, diag)
    assert [r["rag"] for r in out["excluded_failed"]] == [True]
    assert [r["rag"] for r in out["runs_revealed"]] == [False]


def test_reveal_old_format_two_args_still_works() -> None:
    """126 옛 형식 — 결과 레코드에 retrieval_status 가 있으면 진단 없이 그대로."""
    old = {
        "runs": [
            {**_record_blind("c1", "FAN_IN", s, _result("ok", 0)), "retrieval_status": st}
            for s, st in (("A", "failed"), ("B", "disabled"))
        ]
    }
    out = reveal(old, KEY)
    assert len(out["excluded_failed"]) == 1 and len(out["runs_revealed"]) == 1
