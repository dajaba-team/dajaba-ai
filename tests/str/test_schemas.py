"""규약 v0.2 스키마 규칙 — docs/shared/01, docs/str/04·05·06. 정상 · 경계 · 실패."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.scores import ScoreItem
from aml_ai.shared.schemas.str import CodeCheck, Facts, NarrativeOut, VerifyRequest, VerifyResponse
from tests.conftest import EXAMPLES, FIXTURES, load_json


def _facts() -> dict:
    return load_json(FIXTURES / "facts_fan_in.json")


def _llm_narrative() -> dict:
    """LLM 출력 모양 — cites 만, evidence_ids 없음."""
    d = load_json(FIXTURES / "narrative_ok.json")
    return {"narrative": [{k: v for k, v in s.items() if k != "evidence_ids"} for s in d["narrative"]]}


# ---------- facts ----------


def test_facts_fixture_valid() -> None:
    Facts.model_validate(_facts())


def test_facts_amount_must_be_two_decimal_string() -> None:
    d = _facts()
    d["inbound"]["by_currency"][0]["total"] = "42750.5"
    with pytest.raises(ValidationError):
        Facts.model_validate(d)


def test_facts_currency_must_be_code_not_name() -> None:
    d = _facts()
    d["inbound"]["by_currency"][0]["currency"] = "US Dollar"
    with pytest.raises(ValidationError):
        Facts.model_validate(d)


def test_facts_flow_count_must_match_ids() -> None:
    d = _facts()
    d["inbound"]["count"] = 4
    with pytest.raises(ValidationError):
        Facts.model_validate(d)


def test_facts_empty_flow_and_null_paths_ok() -> None:  # 경계: 출금 0건, 경로 없음
    f = Facts.model_validate(_facts())
    assert f.outbound.count == 0 and f.outbound.by_currency == []
    assert f.paths is None


def test_facts_unknown_key_rejected() -> None:
    d = _facts()
    d["top_reasons"] = []  # 10/27 에 없어진 필드
    with pytest.raises(ValidationError):
        Facts.model_validate(d)


# ---------- narrative ----------


def test_llm_narrative_requires_each_section_once() -> None:
    d = _llm_narrative()
    NarrativeOut.model_validate(d)
    d["narrative"][1]["section"] = "SUMMARY"
    with pytest.raises(ValidationError):
        NarrativeOut.model_validate(d)


def test_llm_narrative_must_not_carry_evidence_ids() -> None:
    """거래 ID 는 LLM 이 고르지 않는다 — 코드가 cites 에서 만든다 (docs/str/05)."""
    with pytest.raises(ValidationError):
        NarrativeOut.model_validate(load_json(FIXTURES / "narrative_ok.json"))


def test_verify_request_rejects_missing_section() -> None:
    d = load_json(EXAMPLES / "verify_request.json")
    d["narrative"] = d["narrative"][:5]
    with pytest.raises(ValidationError):
        VerifyRequest.model_validate(d)


# ---------- 경보·점수 ----------


def test_alert_id_must_be_string_format() -> None:
    d = load_json(EXAMPLES / "score_request.json")["alerts"][0]
    d["alert_id"] = 1001
    with pytest.raises(ValidationError):
        Alert.model_validate(d)


def test_alert_rule_facts_paths_and_free_keys() -> None:
    d = load_json(EXAMPLES / "score_request.json")["alerts"][0]
    d["rule_facts"] = {"paths": [[101, 102, 103]], "max_hops": 3}
    a = Alert.model_validate(d)
    assert a.rule_facts.paths == [[101, 102, 103]]


def test_score_failed_item_has_no_score() -> None:
    items = load_json(EXAMPLES / "score_response.json")["scores"]
    failed = next(i for i in items if i["data_quality_status"] == "FAILED")
    ScoreItem.model_validate(failed)
    with pytest.raises(ValidationError):
        ScoreItem.model_validate({**failed, "score": 0.1, "prediction_id": "p-1"})


def test_score_short_history_still_has_score() -> None:
    ok = load_json(EXAMPLES / "score_response.json")["scores"][0]
    ScoreItem.model_validate({**ok, "data_quality_status": "SHORT_HISTORY"})
    with pytest.raises(ValidationError):
        ScoreItem.model_validate({**ok, "data_quality_status": "SHORT_HISTORY", "score": None})


# ---------- 검증 ----------


def test_code_check_reason_only_when_failed() -> None:
    base = {"check": "AMOUNT_MATCH", "section": "SUMMARY", "draft_value": "x", "source_value": "y"}
    CodeCheck.model_validate({**base, "match": False, "reason": "UNPARSED"})
    with pytest.raises(ValidationError):
        CodeCheck.model_validate({**base, "match": False, "reason": None})
    with pytest.raises(ValidationError):
        CodeCheck.model_validate({**base, "match": True, "reason": "MISMATCH"})


def test_verify_response_passed_follows_status() -> None:
    d = load_json(EXAMPLES / "verify_response.json")
    with pytest.raises(ValidationError):
        VerifyResponse.model_validate({**d, "passed": True})  # status=CODE_FAILED
