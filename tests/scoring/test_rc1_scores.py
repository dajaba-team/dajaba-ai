"""고정된 rc1 패키지로 성공·누락·입력 실패가 같은 묶음에서 분리되는지 확인한다."""

from datetime import datetime, timedelta
from decimal import Decimal

from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.scoring.infrastructure.aml_ml_adapter import AmlMlAdapter
from aml_ai.scoring.infrastructure.transaction_reader import HistoryCoverage
from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.scores import FailureCode
from tests.conftest import EXAMPLES, load_json


def test_rc1_respects_per_alert_outcomes() -> None:
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
        template.model_copy(update={"alert_id": "ALT-20300110-000002", "rule_id": "R05_SCATTER_GATHER"}),
        template.model_copy(update={"alert_id": "ALT-20300110-000003", "transaction_ids": [9]}),
        template.model_copy(update={"alert_id": "ALT-20300110-000004", "transaction_ids": [1]}),
        template.model_copy(update={"alert_id": "ALT-20300110-000005"}),
        template.model_copy(update={"alert_id": "ALT-20300110-000006", "window_start": history_start}),
    ]
    adapter = AmlMlAdapter.load()
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
