"""채점 결과의 감사 기록. 커밋은 요청 전체를 처리하는 서비스가 맡는다."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from aml_ai.shared.logging import current_request_id
from aml_ai.shared.schemas.scores import ScoreItem

_SERVING_MODEL = text("""
    select 1 from ai.model_versions
     where model_version = :model and feature_version = :feature
       and threshold = :threshold and serving_package_version = :package_version and is_serving
""")
_INSERT = text("""
    insert into ai.predictions
      (prediction_id, alert_id, batch_run_id, model_version, feature_version, score, threshold,
       data_quality_status, failure_code, reasons, evidence_transaction_ids, context_transaction_ids, request_id)
    values
      (:prediction_id, :alert_id, :batch_run_id, :model, :feature, :score, :threshold,
       :data_quality_status, :failure_code, :reasons, :evidence_transaction_ids, :context_transaction_ids, :request_id)
""").bindparams(bindparam("reasons", type_=JSONB))


def is_registered(session: Session, model: str, feature: str, threshold: float, package_version: str) -> bool:
    return (
        session.execute(
            _SERVING_MODEL,
            {
                "model": model,
                "feature": feature,
                "threshold": Decimal(str(threshold)),
                "package_version": package_version,
            },
        ).scalar_one_or_none()
        is not None
    )


def save_predictions(
    session: Session, scores: list[ScoreItem], *, batch_run_id: int, model: str, feature: str
) -> None:
    request_id = current_request_id()
    session.execute(
        _INSERT,
        [
            {
                **item.model_dump(mode="json"),
                "score": Decimal(str(item.score)) if item.score is not None else None,
                "threshold": Decimal(str(item.threshold)),
                "prediction_id": item.prediction_id or str(uuid4()),
                "batch_run_id": batch_run_id,
                "model": model,
                "feature": feature,
                "request_id": request_id,
            }
            for item in scores
        ],
    )
