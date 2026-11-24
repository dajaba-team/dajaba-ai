"""고정된 rc3 패키지의 성공·누락·입력 실패와 묶음 복구를 검증한다."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.scoring.application import score_service
from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.scoring.infrastructure.aml_ml_adapter import AmlMlAdapter
from aml_ai.scoring.infrastructure.transaction_reader import HistoryCoverage
from aml_ai.shared.errors import ModelUnavailable
from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.scores import FailureCode
from tests.conftest import EXAMPLES, load_json


@pytest.mark.parametrize("wrong_hash", [False, True])
def test_bad_rc3_checkpoint_is_request_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, wrong_hash: bool
) -> None:
    monkeypatch.delenv("AML_ML_MODEL_PATH", raising=False)
    if wrong_hash:
        checkpoint = tmp_path / "checkpoint.ubj"
        checkpoint.write_bytes(b"synthetic incorrect checkpoint")
        monkeypatch.setenv("AML_ML_MODEL_PATH", str(checkpoint))
    with pytest.raises(ModelUnavailable, match="scoring checkpoint could not be loaded"):
        AmlMlAdapter.load().ensure_model_ready()


@pytest.mark.parametrize("split", [False, True], ids=["initial-batch", "second-sub-batch"])
def test_checkpoint_error_after_readiness_returns_whole_request_503(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, split: bool
) -> None:
    import aml_ml

    request = load_json(EXAMPLES / "score_request.json")
    alert = Alert.model_validate(request["alerts"][0])
    request["alerts"].extend(
        {**request["alerts"][0], "alert_id": f"ALT-20220903-{suffix:06d}"}
        for suffix in range(143, 146 if split else 144)
    )
    alert_ids = [item["alert_id"] for item in request["alerts"]]
    history = HistoryCoverage(
        alert.reference_ts - timedelta(hours=24), alert.reference_ts, None, None, "COMPLETE"
    )
    load = MagicMock()
    checkpoint_error = aml_ml.CheckpointUnavailableError("checkpoint lost after readiness")
    score = MagicMock(
        side_effect=[
            RuntimeError("initial batch compute error"),
            [
                aml_ml.ScoreResult(alert_id, 0.625, "OK", None, [], alert.transaction_ids, [])
                for alert_id in alert_ids[:2]
            ],
            checkpoint_error,
        ]
        if split
        else checkpoint_error
    )
    save = MagicMock()
    monkeypatch.setenv("AI_SCORING_MOCK", "false")
    monkeypatch.setenv("AI_SCORING_HISTORY_START", "2022-09-01T00:00:00")
    monkeypatch.setenv("AI_SCORING_HISTORY_END", "2022-09-19T00:00:00")
    monkeypatch.setattr("aml_ai.main.db_ping", lambda _: "ok")
    monkeypatch.setattr(aml_ml, "load_candidate", load)
    monkeypatch.setattr(aml_ml, "score", score)
    monkeypatch.setattr(score_service, "get_engine", MagicMock())
    monkeypatch.setattr(score_service, "Session", MagicMock())
    monkeypatch.setattr(score_service, "is_registered", lambda *args: True)
    monkeypatch.setattr(
        score_service,
        "read_transactions",
        lambda *args, **kwargs: (
            [{"transaction_id": i} for i in alert.transaction_ids],
            [history] * len(alert_ids),
        ),
    )
    monkeypatch.setattr(score_service, "save_predictions", save)

    with TestClient(app) as client:
        response = client.post("/v1/scores", headers={"X-Internal-Key": "test-key"}, json=request)
    assert response.status_code == 503
    assert response.json()["code"] == "MODEL_UNAVAILABLE"
    assert "scores" not in response.json()
    load.assert_called_once_with()
    expected_calls = [alert_ids, alert_ids[:2], alert_ids[2:]] if split else [alert_ids]
    assert [[item.alert_id for item in call.args[0]] for call in score.call_args_list] == expected_calls
    if split:
        assert "scoring_batch_recovery_started" in caplog.messages
    save.assert_not_called()


def test_rc3_respects_per_alert_outcomes(synthetic_rc3_booster: None) -> None:
    reference = datetime(2030, 1, 10, 12)
    start = reference - timedelta(hours=96)
    history_start = reference - timedelta(hours=24)
    complete = HistoryCoverage(history_start, reference, start, reference, "COMPLETE")
    partial = HistoryCoverage(history_start, reference, start, reference, "PARTIAL")
    template = Alert.model_validate(
        {
            **load_json(EXAMPLES / "score_request.json")["alerts"][0],
            "reference_ts": reference,
            "window_start": start,
            "window_end": reference,
            "transaction_ids": [1, 2, 3, 4, 5],
        }
    )
    rows = [
        {
            "transaction_id": i + 1,
            "ts": reference - timedelta(minutes=5 - i),
            "from_account_key": f"300_TEST_{i}",
            "to_account_key": template.account_key,
            "amount_paid": Decimal(20 + i),
            "currency_paid": "US Dollar",
            "amount_received": Decimal(20 + i),
            "currency_received": "US Dollar",
            "payment_format": "Wire",
            "is_self_transfer": False,
        }
        for i in range(5)
    ]
    alerts = [
        template,
        template.model_copy(update={"alert_id": "ALT-20300110-000002", "rule_id": "R99_UNKNOWN"}),
        template.model_copy(update={"alert_id": "ALT-20300110-000003", "transaction_ids": [9]}),
        template.model_copy(update={"alert_id": "ALT-20300110-000004", "transaction_ids": [1]}),
        template.model_copy(update={"alert_id": "ALT-20300110-000005"}),
        template.model_copy(update={"alert_id": "ALT-20300110-000006", "window_start": history_start}),
    ]
    adapter = AmlMlAdapter.load()
    assert adapter.version.package_version == "0.1.0rc3"
    assert adapter.version.model_version == "xgb-hi-medium-r04-event-c2-31-v1"
    assert adapter.version.feature_version == "hi-medium-evidence31-96h-r04-event-v1"
    scores = ScoreService._score_batch(adapter, alerts, rows, [complete] * 4 + [partial, complete])

    assert [item.alert_id for item in scores] == [a.alert_id for a in alerts]
    assert scores[0].score == 0.625
    assert scores[0].prediction_id and scores[0].evidence_transaction_ids == template.transaction_ids
    assert [item.failure_code for item in scores] == [
        None,
        FailureCode.RULE_NOT_SUPPORTED,
        FailureCode.TRANSACTION_NOT_FOUND,
        FailureCode.REQUIRED_INPUT_MISSING,
        FailureCode.HISTORY_NOT_SUPPORTED,
        FailureCode.HISTORY_NOT_SUPPORTED,
    ]
    assert all(item.score is item.prediction_id is None for item in scores[1:])


def test_rc3_scores_all_six_rules_in_one_batch(synthetic_rc3_booster: None) -> None:
    reference = datetime(2030, 1, 10, 12)
    window_start = reference - timedelta(hours=96)
    history = HistoryCoverage(reference - timedelta(hours=24), reference, window_start, reference, "COMPLETE")
    template = load_json(EXAMPLES / "score_request.json")["alerts"][0]
    cases = [
        ("R01_FAN_OUT", "R01_SUBJECT", [("R01_SUBJECT", f"R01_DST_{i}") for i in range(10)], {}),
        ("R02_FAN_IN", "R02_SUBJECT", [(f"R02_SRC_{i}", "R02_SUBJECT") for i in range(5)], {}),
        ("R03_FX_RELAY", "R03_SUBJECT", [("R03_SRC", "R03_SUBJECT"), ("R03_SUBJECT", "R03_DST")], {}),
        ("R04_CYCLE", "R04_SUBJECT", [("R04_SUBJECT", "R04_MID"), ("R04_MID", "R04_SUBJECT")], {}),
        (
            "R05_SCATTER_GATHER",
            "R05_SUBJECT",
            [leg for i in range(3) for leg in (("R05_SRC", f"R05_MID_{i}"), (f"R05_MID_{i}", "R05_SUBJECT"))],
            {"source_account_key": "R05_SRC", "intermediates": 3},
        ),
        (
            "R06_GATHER_SCATTER",
            "R06_SUBJECT",
            [(f"R06_SRC_{i}", "R06_SUBJECT") for i in range(5)]
            + [("R06_SUBJECT", f"R06_DST_{i}") for i in range(5)],
            {"distinct_senders": 5, "distinct_receivers": 5},
        ),
    ]
    alerts, transactions = [], []
    for index, (rule, account, legs, facts) in enumerate(cases, 1):
        ids = list(range(len(transactions) + 1, len(transactions) + len(legs) + 1))
        if rule in {"R03_FX_RELAY", "R04_CYCLE", "R05_SCATTER_GATHER"}:
            facts = {**facts, "paths": [ids[i : i + 2] for i in range(0, len(ids), 2)]}
        if rule == "R04_CYCLE":
            facts["hops_by_path"] = [2]
        for offset, (uid, (sender, receiver)) in enumerate(zip(ids, legs, strict=True)):
            transactions.append(
                {
                    "transaction_id": uid,
                    "ts": reference - timedelta(minutes=len(legs) - offset),
                    "from_account_key": sender,
                    "to_account_key": receiver,
                    "amount_paid": Decimal(100),
                    "amount_received": Decimal(100),
                    "currency_paid": "Euro" if rule == "R03_FX_RELAY" and offset == 1 else "US Dollar",
                    "currency_received": "US Dollar",
                    "payment_format": "Wire",
                    "is_self_transfer": False,
                }
            )
        alerts.append(
            Alert.model_validate(
                {
                    **template,
                    "alert_id": f"ALT-20300110-{index:06d}",
                    "rule_id": rule,
                    "account_key": account,
                    "reference_ts": reference,
                    "window_start": window_start,
                    "window_end": reference,
                    "transaction_ids": ids,
                    "rule_facts": facts,
                }
            )
        )

    scores = ScoreService._score_batch(AmlMlAdapter.load(), alerts, transactions, [history] * len(alerts))

    for alert, result in zip(alerts, scores, strict=True):
        assert result.alert_id == alert.alert_id
        assert result.failure_code is None, alert.rule_id
        assert result.score is not None and 0 <= result.score <= 1, alert.rule_id
        assert result.prediction_id and result.evidence_transaction_ids == alert.transaction_ids


@pytest.fixture
def batch_alerts() -> tuple[list[Alert], list[HistoryCoverage]]:
    template = Alert.model_validate(load_json(EXAMPLES / "score_request.json")["alerts"][0])
    alerts = [
        template.model_copy(update={"alert_id": f"ALT-20220903-{number:06d}"}) for number in range(1, 501)
    ]
    coverage = [
        HistoryCoverage(alert.reference_ts - timedelta(hours=24), alert.reference_ts, None, None, "COMPLETE")
        for alert in alerts
    ]
    return alerts, coverage


def test_batch_exception_recovers_other_499_alerts(
    batch_alerts: tuple[list[Alert], list[HistoryCoverage]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aml_ml import AlertInput, ScoreResult

    alerts, coverage = batch_alerts
    broken_id = alerts[377].alert_id
    expected = {alert.alert_id: (i + 1) / 500 for i, alert in enumerate(alerts)}
    calls: list[int] = []

    def score(inputs: list[AlertInput], _frame: object, *, coverage: list[object]) -> list[ScoreResult]:
        assert len(inputs) == len(coverage)
        calls.append(len(inputs))
        if any(alert.alert_id == broken_id for alert in inputs):
            raise RuntimeError("synthetic batch exception")
        return [
            ScoreResult(a.alert_id, expected[a.alert_id], "OK", None, [], list(a.transaction_ids), [])
            for a in inputs
        ]

    monkeypatch.setattr("aml_ml.score", score)
    scores = AmlMlAdapter.load().score(alerts, [], coverage)

    assert [item.alert_id for item in scores] == [a.alert_id for a in alerts]
    assert len(calls) <= 19
    assert calls[0] == 500
    assert [item.alert_id for item in scores if item.failure_code == FailureCode.COMPUTE_ERROR] == [broken_id]
    assert scores[377].score is scores[377].prediction_id is None
    assert {item.alert_id: item.score for item in scores if item.prediction_id} == {
        alert_id: value for alert_id, value in expected.items() if alert_id != broken_id
    }
    assert "scoring_alert_compute_error" in caplog.messages
    assert "scoring_batch_recovery_exhausted" not in caplog.messages


def test_common_batch_exception_stops_with_unconfirmed_alerts(
    batch_alerts: tuple[list[Alert], list[HistoryCoverage]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aml_ml import AlertInput

    alerts, coverage = batch_alerts
    calls: list[int] = []

    def score(inputs: list[AlertInput], _frame: object, *, coverage: list[object]) -> None:
        calls.append(len(inputs))
        raise RuntimeError("synthetic common failure")

    monkeypatch.setattr("aml_ml.score", score)
    scores = AmlMlAdapter.load().score(alerts, [], coverage)

    assert [item.alert_id for item in scores] == [a.alert_id for a in alerts]
    assert 1 < len(calls) <= 32
    assert min(calls) > 1
    assert all(item.failure_code == FailureCode.COMPUTE_ERROR for item in scores)
    assert all(item.score is item.prediction_id is None for item in scores)
    assert "scoring_alert_compute_error" not in caplog.messages
    assert "scoring_batch_recovery_exhausted" in caplog.messages


@pytest.mark.parametrize("wrong_count", [True, False])
def test_malformed_batch_results_are_not_assigned(
    batch_alerts: tuple[list[Alert], list[HistoryCoverage]],
    monkeypatch: pytest.MonkeyPatch,
    wrong_count: bool,
) -> None:
    from aml_ml import AlertInput, ScoreResult

    alerts, coverage = batch_alerts

    def score(inputs: list[AlertInput], _frame: object, *, coverage: list[object]) -> list[ScoreResult]:
        results = [ScoreResult(a.alert_id, 0.7, "OK", None, [], [], []) for a in inputs]
        return results[:1] if wrong_count else results[::-1]

    monkeypatch.setattr("aml_ml.score", score)
    scores = AmlMlAdapter.load().score(alerts[:2], [], coverage[:2])

    assert [item.alert_id for item in scores] == [a.alert_id for a in alerts[:2]]
    assert all(item.failure_code == FailureCode.COMPUTE_ERROR for item in scores)
    assert all(item.score is item.prediction_id is None for item in scores)
