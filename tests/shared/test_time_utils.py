"""공용 시스템 시각의 UTC·초 단위 계약."""

from datetime import UTC, datetime

from aml_ai.shared.time_utils import utc_now


def test_utc_now_returns_current_utc_seconds() -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    result = utc_now()
    after = datetime.now(UTC).replace(microsecond=0)

    assert result.tzinfo is UTC
    assert result.microsecond == 0
    assert before <= result <= after
