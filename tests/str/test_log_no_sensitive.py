"""SCRUM-272 — 초안·검증·점수 요청 동안 stdout 로그에 민감 값이 없다 (docs/shared/04 "남기지 않는 것").

★A-1: v4 초안(기본 경로, LLM 0, 조사역 메모 포함) + v2 초안 → 검증(judge_v3 녹화 재생, PASSED) + 점수(목업).
LLM 오류 경로는 v4 초안 검증(judge_v4 녹화가 리포에 없음 → VERIFY_UNAVAILABLE). DB·검증 오류는 `_errors.py`.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import DraftResponse, VerifyResponse, VerifyStatus
from tests.conftest import EXAMPLES, load_json
from tests.log_support import by_msg, parse_lines, stdout_json_logging
from tests.str.log_sensitive_support import fixed_values, leaked, narrative_values, with_notes
from tests.str.verify_integration_support import INTERNAL_KEY, create_draft, draft_body, verify_body

pytestmark = pytest.mark.db

HEADERS = {"X-Internal-Key": INTERNAL_KEY}


def _v4_draft(
    client: TestClient, sample: dict, draft_id: str, monkeypatch: pytest.MonkeyPatch
) -> DraftResponse:
    monkeypatch.delenv("NARRATIVE_PROMPT", raising=False)  # 기본값 경로 = narrative_v4
    get_settings.cache_clear()
    res = client.post("/v1/str/drafts", json=with_notes(draft_body(sample, draft_id)), headers=HEADERS)
    assert res.status_code == 200, res.text
    out = DraftResponse.model_validate(res.json())
    assert out.generation_meta.prompt_version == "narrative_v4"
    return out


def _probe() -> None:
    """캡처가 살아 있다는 증거 — 앱 로거가 꺼져 있으면 테스트가 헛돈다."""
    logging.getLogger("aml_ai.str.application.draft_service").warning("scrum272_probe")


# ───────── 정상 ─────────


def test_draft_verify_score_logs_have_no_sensitive_values(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with stdout_json_logging():
        _probe()
        v4 = _v4_draft(integration_client, draft_request_sample, "DRF-LOG272-V4", monkeypatch)
        monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v2")
        get_settings.cache_clear()
        v2 = create_draft(integration_client, draft_request_sample, "DRF-LOG272-V2")
        vres = integration_client.post("/v1/str/verify", json=verify_body(v2), headers=HEADERS)
        sres = integration_client.post(
            "/v1/scores", json=load_json(EXAMPLES / "score_request.json"), headers=HEADERS
        )
    out = capsys.readouterr().out
    lines = parse_lines(out)
    assert by_msg(lines, "scrum272_probe"), "앱 로거 캡처 실패 — 테스트가 헛돎"
    assert VerifyResponse.model_validate(vres.json()).status is VerifyStatus.PASSED
    assert sres.status_code == 200, sres.text
    assert leaked(out, fixed_values() + narrative_values(v4, v2)) == []


# ───────── 실패(LLM 오류) ─────────


def test_llm_failure_logs_have_no_sensitive_values(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """v4 초안 검증 — judge_v4 녹화 miss(LlmUnavailable) → VERIFY_UNAVAILABLE. 경고 로그는 남되 값은 없음."""
    v4 = _v4_draft(integration_client, draft_request_sample, "DRF-LOG272-LLM", monkeypatch)
    capsys.readouterr()
    with stdout_json_logging():
        res = integration_client.post("/v1/str/verify", json=verify_body(v4), headers=HEADERS)
    out = capsys.readouterr().out
    lines = parse_lines(out)
    assert res.status_code == 200, res.text
    assert VerifyResponse.model_validate(res.json()).status is VerifyStatus.VERIFY_UNAVAILABLE
    assert [line for line in lines if line["level"] == "WARNING"], "LLM 오류 경고 로그가 하나는 있어야 함"
    assert leaked(out, fixed_values() + narrative_values(v4)) == []
