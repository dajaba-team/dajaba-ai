"""SCRUM-272 2차 — 처리 안 된 예외(500) 로그 (docs/shared/04 "로그").

- `RequestIdMiddleware` 안에서 잡아 `unhandled` 를 **한 번**, 그 줄에 `request_id`. 500 응답은 develop 과 같은
  `INTERNAL` 모양이고 `request_id` 만 "-" → 실제 값(★A-4) + `X-Request-Id` 헤더.
- Pydantic `ValidationError` 면 메시지·스택 대신 `loc`·`type` 만(입력값의 본문 조각이 안 남게). 다른 예외는 스택.
TestClient 기본(`raise_server_exceptions=True`) — 예외가 미들웨어를 빠져나가면 테스트가 바로 터진다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.shared.logging import REQUEST_ID_HEADER
from aml_ai.shared.schemas.str.narrative import NarrativeSection
from tests.conftest import EXAMPLES, load_json
from tests.log_support import REQUIRED_FIELDS, by_msg, parse_lines, stdout_json_logging

# develop 04bd9da 실측 — 본문 request_id 는 "-", X-Request-Id 헤더 없음
DEVELOP_500_BODY = {"code": "INTERNAL", "message": "internal error", "request_id": "-"}
LEAK_TEXT = "입금 직후 두 계좌로 분산되어 매출 규모 대비 비정상적인 흐름 10_****BD30 12,500"


def _runtime_error(self: ScoreService, req: object) -> None:
    raise RuntimeError("scrum272 boom")


def _validation_error(self: ScoreService, req: object) -> None:
    NarrativeSection.model_validate({"text": LEAK_TEXT})  # section 빠짐 → missing, input_value 에 본문


def _post_scores(headers: dict[str, str]) -> object:
    with TestClient(app) as c:
        return c.post(
            "/v1/scores",
            json=load_json(EXAMPLES / "score_request.json"),
            headers={"X-Internal-Key": "test-key", **headers},
        )


def _expected_body(rid: str) -> dict[str, str]:
    return {**DEVELOP_500_BODY, "request_id": rid}


# ───────── 정상: 헤더 있는 500 ─────────


def test_unhandled_logged_once_with_request_id(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ScoreService, "score", _runtime_error)
    with stdout_json_logging():
        r = _post_scores({REQUEST_ID_HEADER: "req-272-500"})
    assert r.status_code == 500
    assert r.json() == _expected_body("req-272-500")
    assert set(r.json()) == set(DEVELOP_500_BODY)
    assert r.headers[REQUEST_ID_HEADER] == "req-272-500"
    (line,) = by_msg(parse_lines(capsys.readouterr().out), "unhandled")  # 두 번 안 찍힘
    assert line["request_id"] == "req-272-500" and line["level"] == "ERROR"
    assert set(REQUIRED_FIELDS) <= set(line)
    assert "RuntimeError" in line["exc_info"]  # 다른 예외는 스택 그대로


# ───────── 경계: 헤더 없음 → 생성값이 본문·헤더·로그에 같게 ─────────


def test_unhandled_generated_request_id_matches(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ScoreService, "score", _runtime_error)
    with stdout_json_logging():
        r = _post_scores({})
    rid = r.headers[REQUEST_ID_HEADER]
    assert rid not in ("", "-")
    assert r.json() == _expected_body(rid)
    (line,) = by_msg(parse_lines(capsys.readouterr().out), "unhandled")
    assert line["request_id"] == rid


# ───────── 실패: ValidationError → loc·type 만 ─────────


def test_unhandled_validation_error_keeps_only_loc_and_type(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ScoreService, "score", _validation_error)
    with stdout_json_logging():
        r = _post_scores({REQUEST_ID_HEADER: "req-272-val"})
    assert r.status_code == 500 and r.json() == _expected_body("req-272-val")
    out = capsys.readouterr().out
    (line,) = by_msg(parse_lines(out), "unhandled")
    assert line["request_id"] == "req-272-val"
    assert line["error_type"] == "ValidationError"
    assert line["errors"] == [{"loc": ["section"], "type": "missing"}]
    assert "exc_info" not in line and "exc_text" not in line  # 스택·메시지 없음
    joined = repr(parse_lines(out))  # JSON 을 푼 값 — 한글 이스케이프 우회
    assert "입금" not in joined and "10_****BD30" not in joined and "12,500" not in joined


def _bad_response(self: ScoreService, req: object) -> dict:
    """라우터 response_model 검증 실패 → FastAPI ResponseValidationError(pydantic ValidationError 아님)."""
    return {"scores": [{"alert_id": "10_8000EBD30", "score": LEAK_TEXT}]}


def test_unhandled_response_validation_error_keeps_only_loc_and_type(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ResponseValidationError.__str__` 은 오류 dict 를 input 째 찍음 — 이 경로도 loc·type 만."""
    monkeypatch.setattr(ScoreService, "score", _bad_response)
    with stdout_json_logging():
        r = _post_scores({REQUEST_ID_HEADER: "req-272-resp"})
    assert r.status_code == 500 and r.json() == _expected_body("req-272-resp")
    out = capsys.readouterr().out
    (line,) = by_msg(parse_lines(out), "unhandled")
    assert line["error_type"] == "ResponseValidationError"
    assert line["errors"] and all(set(e) == {"loc", "type"} for e in line["errors"])
    assert "exc_info" not in line and "exc_text" not in line
    joined = repr(parse_lines(out))
    assert "입금" not in joined and "10_8000EBD30" not in joined and "12,500" not in joined


def test_ai_error_is_not_unhandled(capsys: pytest.CaptureFixture[str]) -> None:
    """4xx(AiError)는 지금처럼 `ai_error` 한 줄 — 미들웨어가 가로채지 않음."""
    with stdout_json_logging(), TestClient(app) as c:
        r = c.post("/v1/scores", json={}, headers={REQUEST_ID_HEADER: "req-272-401"})
    lines = parse_lines(capsys.readouterr().out)
    assert r.status_code == 401
    assert by_msg(lines, "unhandled") == []
    assert len(by_msg(lines, "ai_error")) == 1
