"""고정된 rc2 패키지의 성공·누락·입력 실패와 묶음 복구를 검증한다."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.scoring.infrastructure.aml_ml_adapter import AmlMlAdapter
from aml_ai.scoring.infrastructure.transaction_reader import HistoryCoverage
from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.scores import FailureCode
from tests.conftest import EXAMPLES, load_json


def test_rc2_respects_per_alert_outcomes() -> None:
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
    assert adapter.version.package_version == "0.1.0rc2"
    scores = ScoreService._score_batch(adapter, alerts, rows, [complete] * 4 + [partial, complete])

    assert [item.alert_id for item in scores] == [a.alert_id for a in alerts]
    assert scores[0].score == 0.006362054497003555
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
