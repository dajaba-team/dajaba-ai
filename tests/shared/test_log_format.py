"""SCRUM-272 — 공통 로그 형식(docs/shared/04 "로그" 표)과 request_id 가 로그 칸에 들어가는지.

DB 없이 돈다. 인증 실패(401 `ai_error`)를 요청 안 로그 한 줄로 쓴다. 민감 값은 `tests/str/test_log_no_sensitive.py`.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.logging import REQUEST_ID_HEADER
from tests.log_support import OLD_FIELDS, REQUIRED_FIELDS, by_msg, parse_lines, stdout_json_logging

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
TS_SKEW_S = 5  # 로그 시각과 테스트 시계 차이 허용 — 지역 시각에 Z 만 붙이면 9시간 어긋남
probe_log = logging.getLogger("aml_ai.tests.log_format")


def _unauthenticated(client: TestClient, headers: dict[str, str]) -> object:
    return client.post("/v1/scores", json={}, headers=headers)  # X-Internal-Key 없음 → 401 ai_error


# ───────── 형식(정상) ─────────


def test_line_is_json_with_required_fields(capsys: pytest.CaptureFixture[str]) -> None:
    with stdout_json_logging():
        probe_log.warning("probe_event", extra={"probe_count": 2, "target": "DRF-000312"})
    lines = parse_lines(capsys.readouterr().out)
    assert len(lines) == 1
    line = lines[0]
    assert set(REQUIRED_FIELDS) <= set(line)
    assert line["service"] == "ai"
    assert line["level"] == "WARNING"
    assert line["logger"] == "aml_ai.tests.log_format"
    assert line["msg"] == "probe_event"
    assert line["request_id"] == "-"  # 요청 밖
    assert line["probe_count"] == 2 and line["target"] == "DRF-000312"  # extra 는 최상위
    assert not set(OLD_FIELDS) & set(line)


def test_ts_is_utc_iso_millis(capsys: pytest.CaptureFixture[str]) -> None:
    with stdout_json_logging():
        probe_log.info("probe_ts")
    (line,) = parse_lines(capsys.readouterr().out)
    assert TS_PATTERN.match(line["ts"]), line["ts"]
    logged = datetime.fromisoformat(line["ts"].replace("Z", "+00:00"))
    assert abs((datetime.now(UTC) - logged).total_seconds()) < TS_SKEW_S


# ───────── 경계 ─────────


def test_exception_stays_one_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    """스택이 여러 줄이어도 로그는 JSON 한 줄(Loki `| json`)."""
    with stdout_json_logging():
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            probe_log.exception("probe_exception")
    (line,) = parse_lines(capsys.readouterr().out)
    assert line["msg"] == "probe_exception" and line["level"] == "ERROR"
    assert set(REQUIRED_FIELDS) <= set(line)


def test_info_below_warning_level_is_dropped(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """레벨 정책은 그대로 — LOG_LEVEL 아래는 안 찍힘."""
    from aml_ai.shared.config import get_settings

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    with stdout_json_logging():
        probe_log.info("probe_dropped")
    assert parse_lines(capsys.readouterr().out) == []


# ───────── request_id ─────────


@pytest.mark.parametrize("rid", ["req-272-abc", "a" * 64])
def test_header_request_id_is_logged(capsys: pytest.CaptureFixture[str], rid: str) -> None:
    with stdout_json_logging(), TestClient(app) as c:
        r = _unauthenticated(c, {REQUEST_ID_HEADER: rid})
    assert r.status_code == 401
    (line,) = by_msg(parse_lines(capsys.readouterr().out), "ai_error")
    assert line["request_id"] == rid == r.headers[REQUEST_ID_HEADER]
    assert line["error_code"] == "UNAUTHENTICATED"


def test_generated_request_id_matches_response_header(capsys: pytest.CaptureFixture[str]) -> None:
    with stdout_json_logging(), TestClient(app) as c:
        r = _unauthenticated(c, {})
    (line,) = by_msg(parse_lines(capsys.readouterr().out), "ai_error")
    assert line["request_id"] not in ("", "-")
    assert line["request_id"] == r.headers[REQUEST_ID_HEADER]


# ───────── 실패(길이 초과 — 기존 동작 그대로) ─────────


def test_over_64_replaced_and_warned(capsys: pytest.CaptureFixture[str]) -> None:
    raw = "x" * 65
    with stdout_json_logging(), TestClient(app) as c:
        r = _unauthenticated(c, {REQUEST_ID_HEADER: raw})
    out = capsys.readouterr().out
    lines = parse_lines(out)
    (replaced,) = by_msg(lines, "request_id_replaced")
    assert replaced["received_len"] == 65 and replaced["level"] == "WARNING"
    (err,) = by_msg(lines, "ai_error")
    new = r.headers[REQUEST_ID_HEADER]
    assert new != raw and 1 <= len(new) <= 64
    assert err["request_id"] == new
    assert raw not in out  # 받은 값은 길이만 남김
