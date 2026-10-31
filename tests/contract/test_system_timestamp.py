"""시스템 시각 정규화와 데이터 시각 불변 계약."""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from aml_ai.shared.schemas.alerts import ScoreRequest
from aml_ai.shared.schemas.common import SystemTimestamp, Timestamp
from aml_ai.shared.schemas.scores import ScoreResponse
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse, VerifyResponse
from tests.conftest import EXAMPLES, load_json

SYSTEM = TypeAdapter(SystemTimestamp)
EXPECTED = "2026-10-30T05:12:00Z"
RESPONSES = [
    ("score_response.json", ScoreResponse),
    ("draft_response.json", DraftResponse),
    ("verify_response.json", VerifyResponse),
]


@pytest.mark.parametrize(
    "value", [EXPECTED, "2026-10-30T05:12:00.999999Z", "2026-10-30T14:12:00.999999+09:00"]
)
def test_system_timestamp_utc_seconds(value: str) -> None:
    result = SYSTEM.validate_python(value)
    assert result.tzinfo == UTC
    assert result.microsecond == 0
    assert SYSTEM.dump_python(result, mode="json") == EXPECTED


@pytest.mark.parametrize("value", ["2026-10-30T05:12:00", datetime(2026, 10, 30, 5, 12)])
def test_naive_system_timestamp_rejected(value: str | datetime) -> None:
    with pytest.raises(ValidationError) as exc:
        SYSTEM.validate_python(value)
    assert exc.value.errors()[0]["type"] == "timezone_aware"


@pytest.mark.parametrize(("name", "model"), RESPONSES)
def test_response_system_timestamp_roundtrip(name: str, model: type) -> None:
    payload = load_json(EXAMPLES / name)
    result = model.model_validate(payload).model_dump(mode="json")
    assert result["produced_at"] == payload["produced_at"]
    payload["produced_at"] = "2026-10-30T14:12:00.999999+09:00"
    assert model.model_validate(payload).model_dump(mode="json")["produced_at"] == EXPECTED
    payload["produced_at"] = EXPECTED.removesuffix("Z")
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("score_request.json", ScoreRequest),
        ("draft_request.json", DraftRequest),
    ],
)
def test_alert_system_and_data_timestamps(name: str, model: type) -> None:
    payload = load_json(EXAMPLES / name)
    result = model.model_validate(payload).model_dump(mode="json")
    original = payload["alerts"][0] if "alerts" in payload else payload["alert"]
    alert = result["alerts"][0] if "alerts" in result else result["alert"]
    assert alert["created_at"] == original["created_at"]
    for field in ("window_start", "window_end", "reference_ts"):
        assert alert[field] == original[field]
        assert not alert[field].endswith("Z")
    original["created_at"] = original["created_at"].removesuffix("Z")
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_period_and_observation_timestamps_unchanged() -> None:
    payload = load_json(EXAMPLES / "draft_response.json")
    result = DraftResponse.model_validate(payload).model_dump(mode="json")
    assert result["facts"]["period"] == payload["facts"]["period"]
    for original, observation in zip(
        payload["facts"]["observations"], result["facts"]["observations"], strict=True
    ):
        for field in ("window_start", "window_end"):
            assert observation[field] == original[field]
    payload = load_json(EXAMPLES / "score_response.json")
    result = ScoreResponse.model_validate(payload).model_dump(mode="json")
    for original, score in zip(payload["scores"], result["scores"], strict=True):
        assert [r["observation"] for r in score["reasons"]] == [r["observation"] for r in original["reasons"]]


@pytest.mark.parametrize("value", ["2026-10-30T14:12:00", "2026-10-30T14:12:00.123456+09:00"])
def test_data_timestamp_retains_existing_behavior(value: str) -> None:
    adapter = TypeAdapter(Timestamp)
    assert adapter.dump_python(adapter.validate_python(value), mode="json") == value
