"""ops 읽기 — app_ai 계정 SELECT 만. is_laundering·pattern_* 컬럼은 절대 SELECT 목록에 넣지 않는다 (docs/str/04 "입력").

컬럼 이름은 백엔드 V002(ops.transactions·accounts·entities·customer_attributes)와 같다.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.errors import InvalidRequest, UnknownCurrency
from aml_ai.shared.schemas.alerts import Alert
from aml_ai.str.domain.facts import currency_code
from aml_ai.str.domain.models import Customer, Subject, Transaction

MISSING_IDS_SHOWN = 10

_TX_SQL = text(
    """
    select transaction_id, ts, from_account_key, to_account_key,
           amount_paid, currency_paid, amount_received, currency_received,
           payment_format, is_self_transfer
      from ops.transactions
     where transaction_id = any(:ids)
    """
)
_ACCOUNTS_SQL = text(
    """
    select account_key, bank_name, entity_id
      from ops.accounts
     where account_key = any(:keys)
    """
)
_ENTITY_SQL = text("select entity_name from ops.entities where entity_id = :eid")
_CUSTOMER_SQL = text(
    """
    select industry, risk_level, account_purpose, onboarded_at, country_code
      from ops.customer_attributes
     where entity_id = :eid
    """
)


class TransactionReader:
    def __init__(self, session: Session) -> None:
        self._s = session

    def load_transactions(self, ids: list[int]) -> list[Transaction]:
        rows = self._s.execute(_TX_SQL, {"ids": ids}).mappings().all()
        missing = sorted(set(ids) - {r["transaction_id"] for r in rows})
        if missing:
            raise InvalidRequest(
                f"unknown transaction_ids: {missing[:MISSING_IDS_SHOWN]}", missing_count=len(missing)
            )
        return sorted((self._to_tx(dict(r)) for r in rows), key=lambda t: t.transaction_id)

    def load_subject(self, alert: Alert, txs: list[Transaction]) -> Subject:
        """대상 계좌 S + 경보 거래에 나오는 계좌들의 entity_id(internal 판정) + S 법인의 이름·고객 속성."""
        keys = sorted({alert.account_key} | {k for t in txs for k in (t.from_account_key, t.to_account_key)})
        accounts = {r["account_key"]: r for r in self._s.execute(_ACCOUNTS_SQL, {"keys": keys}).mappings()}
        own = accounts.get(alert.account_key)
        entity_id = own["entity_id"] if own else alert.entity_id
        entity_name = customer = None
        if entity_id is not None:
            entity_name = self._s.execute(_ENTITY_SQL, {"eid": entity_id}).scalar_one_or_none()
            row = self._s.execute(_CUSTOMER_SQL, {"eid": entity_id}).mappings().one_or_none()
            customer = Customer(**row) if row else None
        return Subject(
            account_key=alert.account_key,
            entity_id=entity_id,
            entity_name=entity_name,
            bank_name=own["bank_name"] if own else None,
            customer=customer,
            account_entities={k: r["entity_id"] for k, r in accounts.items()},
        )

    @staticmethod
    def _to_tx(row: dict[str, object]) -> Transaction:
        for col in ("currency_paid", "currency_received"):
            code = currency_code(str(row[col]))
            if code is None:
                raise UnknownCurrency(f"unknown currency name in {col}")  # 원문 값은 메시지에 안 넣는다
            row[col] = code
        return Transaction(**row)  # type: ignore[arg-type]
