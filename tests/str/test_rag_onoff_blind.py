"""SCRUM-126 추가 검토 1차 — 블라인드 분리·검색 실패·사후 집계 왕복 회귀.

지침 (findings 3 + recommendations):
- 생성 결과 JSON 레코드에는 `rag` 키가 없어야 하고 `side` ∈ {A,B} 만.
- `retrieval_status`: `ok`(ref>0) · `empty`(정상 빈 결과, SG) · `failed`(예외) · `disabled`(rag=False).
- `rag_onoff_reveal.reveal()` 가 `failed` 를 `excluded_failed` 로 분리.
- `rag_onoff_unsupported_post._parse_blind` 가 새 형식(생성기 `_blind_md`)·예전 06:35 형식 둘 다 읽음.

개별 호출은 전부 mock — LLM·DB·임베딩 호출 **0**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import Facts, NarrativeSection, SectionV2
from tests.str.rag_onoff_live import _record_blind
from tests.str.rag_onoff_live_support import FIXTURE_FILES, _get_references
from tests.str.rag_onoff_reveal import reveal
from tests.str.rag_onoff_unsupported_post import _parse_blind

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO / "tests" / "str" / "fixtures"


def _sample_result(retrieval_status: str, refs: int = 0) -> dict:
    return {
        "references_count": refs,
        "references": [],
        "retrieval_status": retrieval_status,
        "code_checks_all_match": True,
        "code_checks_failed": [],
        "judge_scores_median": {"TYPOLOGY_CONSISTENT": 2, "NO_UNSUPPORTED_CLAIM": 2},
        "typology_consistent": 2,
        "no_unsupported_claim": 2,
        "grounds_signal_mentions": 1,
        "unsupported_candidate_count": 0,
        "fact_coverage": {"covered": 0, "required": 0, "missing": []},  # SCRUM-225
        "status": "PASSED",
        "few_shot_ids": ["ex_1"],
        "prompt_version": "narrative_v2",
        "judge_prompt_version": "judge_v3",
        "llm_model_generate": "mock-gen",
        "llm_model_judge": "mock-judge",
    }


def test_record_blind_has_no_rag_key():
    rec = _record_blind("case_1_fan_in", "FAN_IN", "A", _sample_result("ok"))
    assert "rag" not in rec
    assert rec["side"] == "A"
    assert "retrieval_status" not in rec  # SCRUM-225 — 진단 파일로 분리


def test_record_blind_side_b_also_no_rag():
    rec = _record_blind("case_3_fan_out", "FAN_OUT", "B", _sample_result("disabled"))
    assert "rag" not in rec
    assert rec["side"] == "B"


class _StubFailEmbedder:
    def embed_text(self, _text: str) -> list[float]:
        raise RuntimeError("embedding service unreachable")

    def embed_texts(self, _texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service unreachable")


def test_get_references_failed_on_exception():
    """임베딩 예외 → `failed`. recommendation: 비교 집계에서 제외."""
    facts = Facts.model_validate(json.loads((FIXTURES_DIR / "facts_fan_in.json").read_text()))
    refs, status = _get_references(facts, _StubFailEmbedder(), session=None, rag=True)
    assert refs == []
    assert status == "failed"


def test_get_references_disabled_when_rag_off():
    facts = Facts.model_validate(json.loads((FIXTURES_DIR / "facts_fan_in.json").read_text()))
    refs, status = _get_references(facts, _StubFailEmbedder(), session=None, rag=False)
    assert refs == []
    assert status == "disabled"


def test_reveal_separates_failed_from_ok():
    result = {
        "runs": [
            {"case_id": "case_1", "side": "A", **_sample_result("ok")},
            {"case_id": "case_1", "side": "B", **_sample_result("failed")},
            {"case_id": "case_2", "side": "A", **_sample_result("empty")},
            {"case_id": "case_2", "side": "B", **_sample_result("ok")},
        ]
    }
    key = {
        "case_1": {"A_rag": True, "B_rag": False},
        "case_2": {"A_rag": False, "B_rag": True},
    }
    out = reveal(result, key)
    assert len(out["runs_revealed"]) == 3  # ok·empty·ok
    assert len(out["excluded_failed"]) == 1
    assert out["excluded_failed"][0]["retrieval_status"] == "failed"
    rags = {r["case_id"] + ":" + str(r["rag"]) for r in out["runs_revealed"]}
    assert "case_1:True" in rags  # A=ON
    assert "case_2:True" in rags  # B=ON (키 매핑)
    assert all("side" not in r for r in out["runs_revealed"])  # side 키 제거


def _mk_section(name: str, text: str) -> NarrativeSection:
    return NarrativeSection(section=SectionV2(name), text=text, cites=[])


def _blind_md_new(pairs: list[dict]) -> str:
    """현재 생성기(`### case_... (TYPE)` + `**A**`·`**B**`)와 똑같은 모양."""
    lines = ["# header", "", "## 본문", ""]
    for p in pairs:
        lines.append(f"### {p['case_id']} ({p['typology']})")
        lines.append("")
        for side in ("A", "B"):
            lines.append(f"**{side}**")
            lines.append("")
            for s in p[f"narrative_{side}"]:
                lines.append(f"- **{s.section.value}**: {s.text}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _blind_md_old(pairs: list[dict]) -> str:
    """예전 06:35 저장본 모양(`## case_... (TYPE)` + `### A`·`### B`) — 재현용."""
    lines = ["# header", ""]
    for p in pairs:
        lines.append(f"## {p['case_id']} ({p['typology']})")
        lines.append("")
        for side in ("A", "B"):
            lines.append(f"### {side}")
            for s in p[f"narrative_{side}"]:
                lines.append(f"- **{s.section.value}**: {s.text}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


@pytest.fixture()
def _pairs() -> list[dict]:
    """5 사건 × A/B 샘플 (내용은 테스트용 더미)."""
    out: list[dict] = []
    for case_id, _ in FIXTURE_FILES:
        out.append(
            {
                "case_id": case_id,
                "typology": case_id.split("_", 2)[-1].upper(),
                "narrative_A": [_mk_section("SUBJECT", "A 본문"), _mk_section("GROUNDS", "A 근거")],
                "narrative_B": [_mk_section("SUBJECT", "B 본문"), _mk_section("GROUNDS", "B 근거")],
            }
        )
    return out


def test_parse_blind_roundtrip_new_format(_pairs):
    """새 형식 → 파싱 → 5×A/B 전부 복원."""
    md = _blind_md_new(_pairs)
    parsed = _parse_blind(md)
    assert len(parsed) == 5
    for p in _pairs:
        assert "A" in parsed[p["case_id"]]
        assert "B" in parsed[p["case_id"]]
        assert len(parsed[p["case_id"]]["A"]) == 2
        assert len(parsed[p["case_id"]]["B"]) == 2


def test_parse_blind_roundtrip_old_format(_pairs):
    """예전 06:35 형식 → 파싱 — 이번 결과 재현용 fallback."""
    md = _blind_md_old(_pairs)
    parsed = _parse_blind(md)
    assert len(parsed) == 5
    for p in _pairs:
        assert "A" in parsed[p["case_id"]] and "B" in parsed[p["case_id"]]
