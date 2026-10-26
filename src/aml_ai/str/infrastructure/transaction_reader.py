"""ops 읽기. app_ai 계정 SELECT. is_laundering·pattern_* 컬럼은 절대 SELECT 목록에 넣지 않는다."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.errors import InvalidRequest
from aml_ai.shared.schemas.alerts import Alert
from aml_ai.str.domain.models import Subject, Transaction

_TX_SQL = text(
    """
    select transaction_id, ts, from_account_key, to_account_key,
           amount_paid, currency_paid, amount_received, currency_received,
           payment_format, is_self_transfer
      from ops.transactions
     where transaction_id = any(:ids)
    """
)


class TransactionReader:
    def __init__(self, session: Session) -> None:
        self._s = session

    def load_transactions(self, ids: list[int]) -> list[Transaction]:
        rows = self._s.execute(_TX_SQL, {"ids": ids}).mappings().all()
        found = {r["transaction_id"] for r in rows}
        missing = sorted(set(ids) - found)
        if missing:
            raise InvalidRequest(f"unknown transaction_ids: {missing[:10]}", missing_count=len(missing))
        return [Transaction(**r) for r in rows]

    def load_subject(self, alert: Alert) -> Subject:
        """accounts → entities → customer_attributes. 없는 값은 None.

        TODO(W2): 실제 컬럼명은 백엔드 V002 (docs/shared/03 원천 4테이블) 확인 후.
        """
        raise NotImplementedError("W2 — accounts/entities/customer_attributes SELECT")
