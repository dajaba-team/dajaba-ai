"""공개 rc1 호출과 결과 검증. 모듈을 불러올 때는 모델을 읽지 않는다."""

import json
import logging
from collections import deque
from dataclasses import asdict, dataclass
from importlib import import_module
from importlib.metadata import version as distribution_version
from types import ModuleType
from uuid import uuid4

from aml_ai.scoring.infrastructure.transaction_reader import TX_COLUMNS, HistoryCoverage
from aml_ai.shared.errors import ModelUnavailable
from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.scores import DataQualityStatus, FailureCode, Reason, ScoreItem

MAX_REASONS = 3
# 500건을 반씩 나누면 깊이 9에서 한 건까지 좁힐 수 있다.
MAX_SCORE_SPLIT_DEPTH = 9
MAX_SCORE_CALLS = 32
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelVersion:
    model_version: str
    feature_version: str
    threshold: float
    package_version: str


def failed_score(alert: Alert, version: ModelVersion, code: FailureCode) -> ScoreItem:
    return ScoreItem(
        alert_id=alert.alert_id,
        prediction_id=None,
        score=None,
        threshold=version.threshold,
        data_quality_status=DataQualityStatus.FAILED,
        failure_code=code,
        reasons=[],
        evidence_transaction_ids=[],
        context_transaction_ids=[],
    )


class AmlMlAdapter:
    def __init__(self, package: ModuleType, pandas: ModuleType, version: ModelVersion) -> None:
        self._package = package
        self._pandas = pandas
        self.version = version

    @classmethod
    def load(cls) -> "AmlMlAdapter":
        try:
            package = import_module("aml_ml")
            pandas = import_module("pandas")
            version = ModelVersion(
                package.MODEL_VERSION,
                package.FEATURE_VERSION,
                package.THRESHOLD,
                distribution_version("aml-ml"),
            )
            if (
                package.__version__ != version.package_version
                or not callable(package.score)
                or not 0 <= version.threshold <= 1
            ):
                raise ValueError("invalid model contract")
        except Exception as exc:
            raise ModelUnavailable(error_type=type(exc).__name__) from exc
        return cls(package, pandas, version)

    def score(
        self,
        alerts: list[Alert],
        transactions: list[dict[str, object]],
        coverage: list[HistoryCoverage],
    ) -> list[ScoreItem]:
        try:
            inputs = [
                self._package.AlertInput(
                    alert_id=a.alert_id,
                    rule_id=a.rule_id,
                    account_key=a.account_key,
                    reference_ts=a.reference_ts,
                    window_start=a.window_start,
                    window_end=a.window_end,
                    transaction_ids=tuple(a.transaction_ids),
                    rule_facts=a.rule_facts.model_dump(exclude_unset=True),
                )
                for a in alerts
            ]
            if len(coverage) != len(alerts):
                raise ValueError("invalid coverage count")
            frame = self._pandas.DataFrame.from_records(transactions, columns=TX_COLUMNS)
            package_coverage = [self._package.Coverage(**asdict(c)) for c in coverage]
        except Exception as exc:
            log.warning("scoring_batch_prepare_error", extra={"error_type": type(exc).__name__})
            return [failed_score(a, self.version, FailureCode.COMPUTE_ERROR) for a in alerts]

        scores: list[ScoreItem | None] = [None] * len(alerts)
        pending = deque([(0, len(alerts), 0)])
        calls = 0
        unconfirmed = 0
        while pending and calls < MAX_SCORE_CALLS:
            start, end, depth = pending.popleft()
            size = end - start
            calls += 1
            try:
                results = self._package.score(inputs[start:end], frame, coverage=package_coverage[start:end])
            except Exception as exc:
                details = {"error_type": type(exc).__name__, "batch_size": size}
                if size == 1:
                    log.warning("scoring_alert_compute_error", extra=details)
                    scores[start] = failed_score(alerts[start], self.version, FailureCode.COMPUTE_ERROR)
                elif depth < MAX_SCORE_SPLIT_DEPTH:
                    if depth == 0:
                        log.warning("scoring_batch_recovery_started", extra=details)
                    middle = start + size // 2
                    pending.extend([(start, middle, depth + 1), (middle, end, depth + 1)])
                else:
                    unconfirmed += size
                continue

            if not isinstance(results, list) or len(results) != size:
                log.warning("scoring_batch_invalid_result_count", extra={"batch_size": size})
                continue
            scores[start:end] = [
                self._validate(a, result) for a, result in zip(alerts[start:end], results, strict=True)
            ]

        unconfirmed += sum(end - start for start, end, _ in pending)
        if unconfirmed:
            log.warning(
                "scoring_batch_recovery_exhausted", extra={"unconfirmed_alerts": unconfirmed, "calls": calls}
            )
        return [
            score if score is not None else failed_score(alert, self.version, FailureCode.COMPUTE_ERROR)
            for alert, score in zip(alerts, scores, strict=True)
        ]

    def _validate(self, alert: Alert, result: object) -> ScoreItem:
        try:
            item = asdict(result)  # rc1 ScoreResult
            if item["alert_id"] != alert.alert_id or not set(item["evidence_transaction_ids"]).issubset(
                alert.transaction_ids
            ):
                raise ValueError("result does not match alert")
            prediction_id = None if item["data_quality_status"] == "FAILED" else str(uuid4())
            if prediction_id is not None:
                item["reasons"] = self._validate_reasons(item["reasons"])
            return ScoreItem.model_validate(
                {
                    **item,
                    "prediction_id": prediction_id,
                    "threshold": self.version.threshold,
                }
            )
        except (TypeError, ValueError, KeyError) as exc:
            log.warning("scoring_invalid_result", extra={"error_type": type(exc).__name__})
            return failed_score(alert, self.version, FailureCode.COMPUTE_ERROR)

    @staticmethod
    def _validate_reasons(raw: list[object]) -> list[Reason]:
        try:
            reasons = [Reason.model_validate(reason) for reason in raw[:MAX_REASONS]]
            json.dumps([reason.model_dump(mode="json") for reason in reasons], allow_nan=False)
            return reasons
        except (TypeError, ValueError) as exc:
            log.warning("scoring_invalid_reasons", extra={"error_type": type(exc).__name__})
            return []
