"""SCRUM-272 — 오류 경로에서도 로그에 민감 값이 없다 (docs/shared/04 "남기지 않는 것").

- DB 저장 실패(★A-2): `generations` SUCCEEDED UPDATE 를 트리거로 막아 파라미터 있는 문장 오류를 낸다.
  앱 엔진(`shared/db.get_engine`)을 그대로 써야 `hide_parameters` 를 확인한다 — 테스트 엔진 아님.
- 요청 검증 오류(INVALID_REQUEST) · 응답 스키마 검증 실패(★A-3 → 2차에서 고침: `loc`·`type` 만).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import DraftResponse
from aml_ai.str.application import draft_service
from tests.log_support import by_msg, parse_lines, stdout_json_logging
from tests.str.log_sensitive_support import fixed_values, leaked, narrative_values, with_notes
from tests.str.verify_integration_support import INTERNAL_KEY, draft_body

pytestmark = pytest.mark.db

HEADERS = {"X-Internal-Key": INTERNAL_KEY}
HIDDEN_MARK = "hide_parameters=True"  # SQLAlchemy 가 파라미터 대신 남기는 문구
BLOCK_SUCCESS_SQL = """
CREATE OR REPLACE FUNCTION ai.scrum272_block_success() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'scrum272 injected save failure'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER scrum272_block_success BEFORE UPDATE ON ai.generations
FOR EACH ROW WHEN (NEW.status = 'SUCCEEDED') EXECUTE FUNCTION ai.scrum272_block_success();
"""
UNBLOCK_SQL = """
DROP TRIGGER IF EXISTS scrum272_block_success ON ai.generations;
DROP FUNCTION IF EXISTS ai.scrum272_block_success();
"""


@pytest.fixture
def app_engine_client(_ai_mock_env, _ops_seed, db_session: Session, monkeypatch) -> Iterator[TestClient]:
    """앱 엔진 세션 + 500 을 응답으로 받는 클라이언트. 기본값 경로(narrative_v4)."""
    from aml_ai.main import app
    from aml_ai.shared.db import get_engine, get_session

    monkeypatch.delenv("NARRATIVE_PROMPT", raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()  # DATABASE_URL = 테스트 컨테이너(_db_engine 이 넣음)
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)
    get_engine().dispose()
    get_engine.cache_clear()


def _reference_v4(client: TestClient, sample: dict) -> DraftResponse:
    """같은 입력의 v4 본문(코드 조립이라 결정적) — 실패 요청 로그에서 찾을 본문."""
    res = client.post(
        "/v1/str/drafts", json=with_notes(draft_body(sample, "DRF-LOG272-REF")), headers=HEADERS
    )
    assert res.status_code == 200, res.text
    return DraftResponse.model_validate(res.json())


def test_db_save_failure_hides_sql_parameters(
    app_engine_client: TestClient,
    _db_engine: Engine,
    draft_request_sample: dict,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ref = _reference_v4(app_engine_client, draft_request_sample)
    body = with_notes(draft_body(draft_request_sample, "DRF-LOG272-DBFAIL"))
    with _db_engine.begin() as conn:
        conn.execute(text(BLOCK_SUCCESS_SQL))
    capsys.readouterr()
    try:
        with stdout_json_logging():
            res = app_engine_client.post("/v1/str/drafts", json=body, headers=HEADERS)
    finally:
        with _db_engine.begin() as conn:
            conn.execute(text(UNBLOCK_SQL))
    out = capsys.readouterr().out
    assert res.status_code == 500 and res.json()["code"] == "INTERNAL"
    assert by_msg(parse_lines(out), "unhandled"), "저장 실패가 스택과 함께 찍혀야 함"
    assert HIDDEN_MARK in out, "SQL 파라미터가 숨겨지지 않음(shared/db.py hide_parameters)"
    assert leaked(out, fixed_values() + narrative_values(ref)) == []


def test_request_validation_error_logs_have_no_sensitive_values(
    app_engine_client: TestClient,
    draft_request_sample: dict,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = with_notes(draft_body(draft_request_sample, "DRF-LOG272-BADREQ"))
    body["alert"] = {**body["alert"], "window_start": "not-a-date"}  # 계좌·금액·메모는 그대로 실림
    capsys.readouterr()
    with stdout_json_logging():
        res = app_engine_client.post("/v1/str/drafts", json=body, headers=HEADERS)
    out = capsys.readouterr().out
    parse_lines(out)
    assert res.status_code == 400 and res.json()["code"] == "INVALID_REQUEST"
    assert leaked(out, fixed_values()) == []


def test_response_schema_failure_logs_have_no_sensitive_values(
    app_engine_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """응답 조립 중 Pydantic 오류(섹션 이름 빠짐 → missing 오류의 input_value 가 섹션 통째)."""
    ref = _reference_v4(app_engine_client, draft_request_sample)
    real_attach = draft_service.fact_keys_domain.attach_evidence

    def _broken(narrative, facts):  # noqa: ANN001, ANN202 — 원 함수 시그니처 그대로 감쌈
        return [
            {k: v for k, v in s.model_dump(mode="json").items() if k != "section"}
            for s in real_attach(narrative, facts)
        ]

    monkeypatch.setattr(draft_service.fact_keys_domain, "attach_evidence", _broken)
    capsys.readouterr()
    with stdout_json_logging():
        res = app_engine_client.post(
            "/v1/str/drafts",
            json=with_notes(draft_body(draft_request_sample, "DRF-LOG272-BADRES")),
            headers=HEADERS,
        )
    out = capsys.readouterr().out
    assert res.status_code == 500 and res.json()["code"] == "INTERNAL"
    assert by_msg(parse_lines(out), "unhandled")
    assert leaked(out, fixed_values() + narrative_values(ref)) == []
