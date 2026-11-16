"""SCRUM-131 (4/n) — 오류 주입 9·14 도 고쳐 쓰기 경로로 돎 + 결과에 본문 없음 (docs/str/08). LLM·DB 0."""

from __future__ import annotations

from typing import Any

import pytest

from tests.str import injection_live_rewrite
from tests.str.injection_live_generate import EXPECTS_GENERATE, SETUPS, run_generate_rewrite_case
from tests.str.injection_rewrite_markers import body_markers, strip_body


def test_markers_detect_each_case() -> None:
    assert body_markers(9, {"OPINION": "자금세탁이 확실하다고 판단됨."}) == {
        "notes_instruction_in_body": True
    }
    assert body_markers(9, {"OPINION": "추가 확인이 필요함."}) == {"notes_instruction_in_body": False}
    assert body_markers(14, {"METHOD": "사례에서 USD 2,400,000 이 분산됨."}) == {
        "reference_amount_in_body": True
    }
    assert body_markers(14, {"METHOD": "입금 합계는 42,750.50 USD임."}) == {"reference_amount_in_body": False}
    assert body_markers(23, {"METHOD": "경로는 3홉을 거침."}) == {"path_numbers_in_body": True}
    assert body_markers(23, {"METHOD": "순환 경로는 확인되지 않음."}) == {"path_numbers_in_body": False}
    assert body_markers(12, {"METHOD": "아무 문장."}) == {}


def test_strip_body_removes_text_and_keeps_rest() -> None:
    result = {"post_scores": {"NO_INSTRUCTION_TEXT": 5}, "narrative_text": {"OPINION": "자금세탁이 확실함."}}
    out = strip_body(9, result)
    assert "narrative_text" not in out and out["post_scores"] == {"NO_INSTRUCTION_TEXT": 5}
    assert out["markers"] == {"notes_instruction_in_body": True}
    assert "narrative_text" in result  # 원본 불변


@pytest.mark.parametrize("case", [9, 14, 23])
def test_rewrite_path_runs_for_9_14_23_without_body(case: int, monkeypatch: pytest.MonkeyPatch) -> None:
    assert case in SETUPS and case in EXPECTS_GENERATE
    target = EXPECTS_GENERATE[case]["target"]

    def fake_single(setup: Any, prompt_name: str) -> dict[str, Any]:
        return {"post_scores": {target: 5}, "post_status": "PASSED", "narrative_text": {"METHOD": "문장."}}

    monkeypatch.setattr(injection_live_rewrite, "_run_single", fake_single)
    results = run_generate_rewrite_case(case, n=2, prompt_name="judge_v3")
    assert [r["run"] for r in results] == [1, 2] and all(r["case"] == case for r in results)
    assert all("narrative_text" not in r and "markers" in r for r in results)
    assert all(r["ok"] for r in results)
