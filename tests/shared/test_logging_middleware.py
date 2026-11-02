"""RequestIdMiddleware — X-Request-Id 길이 처리 (SCRUM-58).

verification_runs.request_id 는 VARCHAR(64). 65자+ 는 커밋 실패로 검증 결과 저장이 터지므로
미들웨어가 새 ID 발급 + 경고 로그로 받아 넘긴다 (docs/str/09 결정 2026-11-02).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.logging import REQUEST_ID_HEADER
from aml_ai.shared.logging import logger as mw_logger


@pytest.fixture
def captured_warnings() -> Iterator[list[logging.LogRecord]]:
    """미들웨어 전용 핸들러 — `setup_logging` 이 root 를 재설정해도 로거에 바로 붙은 건 유지."""
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture(level=logging.WARNING)
    mw_logger.addHandler(handler)
    try:
        yield captured
    finally:
        mw_logger.removeHandler(handler)


def test_request_id_64_chars_passthrough(captured_warnings: list[logging.LogRecord]) -> None:
    rid = "a" * 64
    with TestClient(app) as c:
        r = c.get("/v1/health", headers={REQUEST_ID_HEADER: rid})
    assert r.status_code == 200
    assert r.headers[REQUEST_ID_HEADER] == rid
    assert not [rec for rec in captured_warnings if rec.message == "request_id_replaced"]


def test_request_id_over_64_replaced(captured_warnings: list[logging.LogRecord]) -> None:
    raw = "x" * 65
    with TestClient(app) as c:
        r = c.get("/v1/health", headers={REQUEST_ID_HEADER: raw})
    assert r.status_code == 200
    new = r.headers[REQUEST_ID_HEADER]
    assert new != raw
    assert 1 <= len(new) <= 64
    replaced = [rec for rec in captured_warnings if rec.message == "request_id_replaced"]
    assert len(replaced) == 1
    assert replaced[0].received_len == 65
