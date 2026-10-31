"""계약 응답용 시스템 시각 — UTC, 초 단위."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
