"""채점 API와 0006을 격리 PostgreSQL에서 검증한다."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from aml_ai.main import app
from aml_ai.scoring.application import score_service
from aml_ai.shared import versioning
from aml_ai.shared.config import get_settings
from tests.conftest import EXAMPLES, ROOT, load_json
from tests.str.conftest import _pg_container  # noqa: F401

pytestmark = pytest.mark.db

REFERENCE = datetime(2030, 1, 10, 12)
HEAD = "0006_serving_package_version"
PREVIOUS = "0005_scoring_tables"
PACKAGE = "0.1.0rc2"
HEADERS = {"X-Internal-Key": "test-key"}


def migrate(engine: Engine, revision: str, *, downgrade: bool = False) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    with pytest.MonkeyPatch.context() as env:
        env.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            (command.downgrade if downgrade else command.upgrade)(cfg, revision)
        finally:
            get_settings.cache_clear()


@pytest.fixture(scope="module")
def scoring_db(_pg_container) -> Iterator[Engine]:  # noqa: F811
    engine = create_engine(_pg_container.get_connection_url())
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION vector; CREATE SCHEMA ai; CREATE SCHEMA ops"))
            conn.execute(
                text("""
                CREATE TABLE ops.transactions (
                    transaction_id bigint PRIMARY KEY, ts timestamp NOT NULL,
                    from_account_key text NOT NULL, to_account_key text NOT NULL,
                    amount_paid numeric(20,6) NOT NULL, currency_paid text NOT NULL,
                    amount_received numeric(20,6) NOT NULL, currency_received text NOT NULL,
                    payment_format text NOT NULL, is_self_transfer boolean NOT NULL
                )
            """)
            )
        migrate(engine, HEAD)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def scoring_client(scoring_db: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with scoring_db.begin() as conn:
        conn.execute(text("TRUNCATE ops.transactions, ai.predictions"))
    monkeypatch.setattr(score_service, "get_engine", lambda: scoring_db)
    monkeypatch.setattr("aml_ai.main.db_ping", lambda _: "ok")
    monkeypatch.setattr(versioning, "_served_model", None)
    monkeypatch.setenv("AI_SCORING_MOCK", "false")
    monkeypatch.setenv("AI_SCORING_HISTORY_START", "2030-01-01T00:00:00")
    monkeypatch.setenv("AI_SCORING_HISTORY_END", "2030-02-01T00:00:00")
    with TestClient(app) as client:
        yield client


def alert(index: int, rule: str, account: str, ids: list[int], facts: dict) -> dict:
    template = load_json(EXAMPLES / "score_request.json")["alerts"][0]
    return {
        **template,
        "alert_id": f"ALT-20300110-{index:06d}",
        "rule_id": rule,
        "account_key": account,
        "reference_ts": REFERENCE.isoformat(),
        "window_start": (REFERENCE - timedelta(hours=96)).isoformat(),
        "window_end": REFERENCE.isoformat(),
        "transaction_ids": ids,
        "rule_facts": facts,
    }


def seed(engine: Engine, rows: list[tuple[int, timedelta, str, str]]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO ops.transactions VALUES (
                    :id, :ts, :sender, :receiver, 1234567.123456, 'US Dollar',
                    3456789.654321, 'Mexican Peso', 'Wire', false
                )
            """),
            [
                {"id": i, "ts": REFERENCE - ago, "sender": sender, "receiver": receiver}
                for i, ago, sender, receiver in rows
            ],
        )


def post(client: TestClient, alerts: list[dict]):
    return client.post("/v1/scores", json={"batch_run_id": 42, "alerts": alerts}, headers=HEADERS)


def test_history_edges_and_full_evidence_are_passed_as_db_values(
    scoring_db: Engine, scoring_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aml_ml

    cycle = alert(1, "R04_CYCLE", "CYCLE", [1, 2], {"paths": [[1, 2]], "hops_by_path": [2]})
    scatter = alert(
        2,
        "R05_SCATTER_GATHER",
        "TARGET",
        [10, 11, 12, 13, 14, 15, 16, 17],
        {"paths": [[10, 11], [12, 13], [14, 15]], "source_account_key": "SRC", "intermediates": 3},
    )
    seed(
        scoring_db,
        [
            (1, timedelta(hours=50), "CYCLE", "MID"),
            (2, timedelta(minutes=1), "MID", "CYCLE"),
            (3, timedelta(hours=24), "CYCLE", "LOWER"),
            (4, timedelta(hours=24, seconds=1), "CYCLE", "BEFORE"),
            (5, timedelta(0), "AT_REF", "CYCLE"),
            (10, timedelta(hours=60), "SRC", "MID1"),
            (11, timedelta(hours=51), "MID1", "TARGET"),
            (12, timedelta(hours=59), "SRC", "MID2"),
            (13, timedelta(hours=49), "MID2", "TARGET"),
            (14, timedelta(hours=58), "SRC", "MID3"),
            (15, timedelta(hours=48), "MID3", "TARGET"),
            (16, timedelta(hours=57), "SRC", "MID1"),
            (17, timedelta(hours=47), "MID1", "TARGET"),
        ],
    )
    actual_score = aml_ml.score
    captured = []

    def observe(alerts, transactions, *, coverage):
        captured.append((alerts, transactions, coverage))
        return actual_score(alerts, transactions, coverage=coverage)

    monkeypatch.setattr(aml_ml, "score", observe)
    response = post(scoring_client, [cycle, scatter])
    assert response.status_code == 200, response.json()
    scores = response.json()["scores"]
    assert all(item["score"] is not None and item["failure_code"] is None for item in scores)
    assert [item["evidence_transaction_ids"] for item in scores] == [
        cycle["transaction_ids"],
        scatter["transaction_ids"],
    ]
    [(inputs, tx, coverage)] = captured
    assert [list(a.transaction_ids) for a in inputs] == [cycle["transaction_ids"], scatter["transaction_ids"]]
    assert set(tx["transaction_id"]) == {1, 2, 3, *scatter["transaction_ids"]}
    assert all(c.status == "COMPLETE" for c in coverage)
    assert all(
        c.requested_start == REFERENCE - timedelta(hours=24) and c.requested_end == REFERENCE
        for c in coverage
    )
    for row in tx.itertuples():
        assert isinstance(row.amount_paid, Decimal) and row.amount_paid == Decimal("1234567.123456")
        assert isinstance(row.amount_received, Decimal) and row.amount_received == Decimal("3456789.654321")
        assert (row.currency_paid, row.currency_received) == ("US Dollar", "Mexican Peso")
    with scoring_db.connect() as conn:
        persisted = dict(conn.execute(text("SELECT prediction_id, score FROM ai.predictions")).all())
    assert persisted == {item["prediction_id"]: Decimal(str(item["score"])) for item in scores}


@pytest.mark.parametrize(
    "change",
    [
        "serving_package_version = '0.1.0rc1'",
        "serving_package_version = NULL",
        "threshold = 0.4",
        "is_serving = false",
    ],
)
def test_model_registry_mismatch_rejects_request(
    scoring_db: Engine, scoring_client: TestClient, change: str
) -> None:
    with scoring_db.begin() as conn:
        conn.execute(text(f"UPDATE ai.model_versions SET {change}"))
    try:
        request = alert(1, "R02_FAN_IN", "TARGET", [1], {})
        response = post(scoring_client, [request])
        assert response.status_code == 503 and response.json()["code"] == "MODEL_UNAVAILABLE"
        assert scoring_client.get("/v1/health").json()["scoring_mode"] == "unavailable"
        with scoring_db.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM ai.predictions")) == 0
    finally:
        with scoring_db.begin() as conn:
            conn.execute(
                text("""
                UPDATE ai.model_versions
                   SET serving_package_version = :package, threshold = 0.5, is_serving = true
            """),
                {"package": PACKAGE},
            )


def test_second_write_failure_rolls_back_batch(
    scoring_db: Engine,
    scoring_client: TestClient,
) -> None:
    seed(
        scoring_db,
        [
            (1, timedelta(hours=30), "CYCLE", "MID"),
            (2, timedelta(minutes=1), "MID", "CYCLE"),
        ],
    )
    first, second = [
        alert(i, "R04_CYCLE", "CYCLE", [1, 2], {"paths": [[1, 2]], "hops_by_path": [2]}) for i in (1, 2)
    ]
    with scoring_db.begin() as conn:
        conn.execute(
            text("""
            CREATE SEQUENCE ai.test_prediction_attempts;
            CREATE FUNCTION ai.test_fail_second_prediction() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF nextval('ai.test_prediction_attempts') = 2 THEN
                    RAISE EXCEPTION 'synthetic second prediction failure';
                END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER test_fail_second_prediction BEFORE INSERT ON ai.predictions
              FOR EACH ROW EXECUTE FUNCTION ai.test_fail_second_prediction();
        """)
        )
    try:
        response = post(scoring_client, [first, second])
        assert response.status_code == 503 and response.json()["code"] == "DB_UNAVAILABLE"
        with scoring_db.connect() as conn:
            assert conn.scalar(text("SELECT last_value FROM ai.test_prediction_attempts")) == 2
            assert conn.scalar(text("SELECT count(*) FROM ai.predictions")) == 0
        assert scoring_client.get("/v1/health").json()["scoring_mode"] == "unavailable"
    finally:
        with scoring_db.begin() as conn:
            conn.execute(
                text("""
                DROP TRIGGER test_fail_second_prediction ON ai.predictions;
                DROP FUNCTION ai.test_fail_second_prediction();
                DROP SEQUENCE ai.test_prediction_attempts;
            """)
            )


def test_0006_round_trip_preserves_model_prediction_and_fk(scoring_db: Engine) -> None:
    insert_legacy = text("""
        INSERT INTO ai.predictions (
            prediction_id, alert_id, batch_run_id, model_version, feature_version,
            score, threshold, data_quality_status, reasons, evidence_transaction_ids,
            context_transaction_ids, request_id
        )
        SELECT :id, 'ALT-20300110-000001', 17, :model, feature_version,
               0.25, threshold, 'OK', '[]', ARRAY[1]::bigint[], ARRAY[]::bigint[], 'legacy'
          FROM ai.model_versions WHERE is_serving
    """)
    try:
        migrate(scoring_db, PREVIOUS, downgrade=True)
        with scoring_db.begin() as conn:
            model = dict(conn.execute(text("SELECT * FROM ai.model_versions")).mappings().one())
            assert "serving_package_version" not in model
            conn.execute(insert_legacy, {"id": "legacy", "model": model["model_version"]})
            prediction = conn.execute(text("SELECT * FROM ai.predictions WHERE prediction_id='legacy'")).one()
        migrate(scoring_db, HEAD)
        with scoring_db.connect() as conn:
            upgraded = dict(conn.execute(text("SELECT * FROM ai.model_versions")).mappings().one())
            assert upgraded.pop("serving_package_version") == PACKAGE
            assert upgraded == model
            assert conn.execute(text("SELECT * FROM ai.predictions WHERE prediction_id='legacy'")).one() == (
                prediction
            )
        migrate(scoring_db, PREVIOUS, downgrade=True)
        with scoring_db.connect() as conn:
            assert dict(conn.execute(text("SELECT * FROM ai.model_versions")).mappings().one()) == model
            assert conn.execute(text("SELECT * FROM ai.predictions WHERE prediction_id='legacy'")).one() == (
                prediction
            )
        with pytest.raises(IntegrityError), scoring_db.begin() as conn:
            conn.execute(insert_legacy, {"id": "invalid", "model": "unknown-model"})
    finally:
        migrate(scoring_db, HEAD)
        with scoring_db.begin() as conn:
            conn.execute(text("DELETE FROM ai.predictions WHERE prediction_id = 'legacy'"))
