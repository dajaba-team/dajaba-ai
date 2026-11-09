"""하네스 자체 테스트 (SCRUM-127) — mock LLM 으로 `injection_live_support` 가 끝까지 돈다.

★L 1·2 명령이 `masking.mask_for_llm().model_dump()` AttributeError 로 LLM 호출 전 실패한 걸
CI 에서 미리 잡음. `-m live` 아니라 평소 pytest 에서 돈다.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.infrastructure.llm_client import LlmResult
from tests.str import injection_live_support as support

_JUDGE_OK_TEXT = json.dumps(
    {
        "checks": [
            {"check": "FIVE_W_ONE_H_COMPLETE", "comment": "ok", "score": 5},
            {"check": "TYPOLOGY_CONSISTENT", "comment": "ok", "score": 5},
            {"check": "NO_UNSUPPORTED_CLAIM", "comment": "ok", "score": 5},
            {"check": "NO_SPECULATION", "comment": "ok", "score": 5},
            {"check": "NO_INSTRUCTION_TEXT", "comment": "ok", "score": 5},
        ],
        "sections": [
            {"section": s, "cites": []}
            for s in ("SUBJECT", "DATE", "PLACE", "INSTRUMENT", "METHOD", "GROUNDS", "OPINION")
        ],
    }
)


class _FakeClient:
    """`HttpLlmClient(settings)` 시그니처만 흉내. 호출마다 PASSED 응답."""

    def __init__(self, settings):  # noqa: ARG002 — 시그니처 호환
        pass

    def complete_json(self, *, system, user, model, max_tokens, tag, timeout_s=None):  # noqa: ARG002
        return LlmResult(
            text=_JUDGE_OK_TEXT,
            model="fake-model",
            tokens_in=100,
            tokens_out=50,
            latency_ms=10,
        )


@pytest.fixture
def patched(monkeypatch, tmp_path):
    monkeypatch.setattr(support, "HttpLlmClient", _FakeClient)
    monkeypatch.setattr(support, "TMP_DIR", tmp_path)
    return tmp_path


def test_run_judge_only_case_runs_end_to_end(patched) -> None:
    """mock LLM 으로 case 12(정상 회귀) 를 한 번 돌림 — masking·render·parse·save 통과."""
    results = support.run_judge_only_case(case=12, n=1, prompt_name="judge_v3")
    assert len(results) == 1
    r = results[0]
    assert r["status"] == "PASSED"
    assert r["scores"] == {
        "FIVE_W_ONE_H_COMPLETE": 5,
        "TYPOLOGY_CONSISTENT": 5,
        "NO_UNSUPPORTED_CLAIM": 5,
        "NO_SPECULATION": 5,
        "NO_INSTRUCTION_TEXT": 5,
    }
    assert r["ok"] is True  # case 12: all ≥4


@pytest.mark.parametrize("case", support.JUDGE_ONLY)
def test_all_injection_cases_structure(patched, case: int) -> None:
    """7·8·10·11·12 전부 narrative 주입 + judge 호출이 깨지지 않고 결과 dict 돌아옴."""
    results = support.run_judge_only_case(case=case, n=1, prompt_name="judge_v3")
    assert results and "scores" in results[0] and "status" in results[0]


def test_save_results_uses_m1_or_m2_slot(patched) -> None:
    path = support.save_results([{"case": 12, "run": 1}], "judge_v3_c12")
    assert path.exists()
    name = path.name
    assert ("_m1_" in name) or ("_m2_" in name), name
