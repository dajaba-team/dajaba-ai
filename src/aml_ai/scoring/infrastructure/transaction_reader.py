"""채점용 거래 조회. DB의 시각, Decimal 금액, 통화 값을 보존한다."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.schemas.alerts import Alert

HISTORY_WINDOW = timedelta(hours=24)
MAX_TRANSACTION_ID = 2**63 - 1
TX_COLUMNS = (
    "transaction_id",
    "ts",
    "from_account_key",
    "to_account_key",
    "amount_paid",
    "currency_paid",
    "amount_received",
    "currency_received",
    "payment_format",
    "is_self_transfer",
)

_EXTENT = text("select min(ts), max(ts) from ops.transactions")
_TRANSACTIONS = text(f"""
    with windows as (
        select distinct account_key, starts_at, ends_at
          from unnest(cast(:accounts as text[]), cast(:starts as timestamp[]),
                      cast(:ends as timestamp[])) as w(account_key, starts_at, ends_at)
    ), ids as (
        select unnest(cast(:ids as bigint[])) as transaction_id
        union
        select t.transaction_id from windows w join ops.transactions t
          on t.from_account_key = w.account_key and t.ts >= w.starts_at and t.ts < w.ends_at
        union
        select t.transaction_id from windows w join ops.transactions t
          on t.to_account_key = w.account_key and t.ts >= w.starts_at and t.ts < w.ends_at
    )
    select {", ".join(TX_COLUMNS)}
      from ops.transactions join ids using (transaction_id)
""")


@dataclass(frozen=True)
class HistoryCoverage:
    requested_start: datetime
    requested_end: datetime
    db_min_ts: datetime | None
    db_max_ts: datetime | None
    status: str


def history_start(reference: datetime) -> datetime | None:
    if reference.tzinfo is not None or reference < datetime.min + HISTORY_WINDOW:
        return None
    return reference - HISTORY_WINDOW


def read_transactions(
    session: Session, alerts: list[Alert], *, history_bounds: tuple[datetime, datetime]
) -> tuple[list[dict[str, object]], list[HistoryCoverage | None]]:
    """근거 ID와 계좌별 [시작, 기준) 이력의 합집합을 한 번에 조회한다."""
    starts = [history_start(a.reference_ts) if "\x00" not in a.account_key else None for a in alerts]
    windows = [
        (a.account_key, start, a.reference_ts)
        for a, start in zip(alerts, starts, strict=True)
        if start is not None
    ]
    rows = session.execute(
        _TRANSACTIONS,
        {
            "ids": sorted({i for a in alerts for i in a.transaction_ids if i <= MAX_TRANSACTION_ID}),
            "accounts": [account for account, _, _ in windows],
            "starts": [start for _, start, _ in windows],
            "ends": [end for _, _, end in windows],
        },
    ).mappings()
    transactions = [dict(row) for row in rows]
    low, high = session.execute(_EXTENT).one()
    verified_start, verified_end = history_bounds

    def coverage(start: datetime | None, end: datetime) -> HistoryCoverage | None:
        if start is None:
            return None
        status = "UNKNOWN"
        if low is not None and high is not None:
            # 마지막 거래 이후에도 적재가 검증된 구간에는 거래가 없을 수 있다.
            status = "COMPLETE" if max(low, verified_start) <= start and end <= verified_end else "PARTIAL"
        return HistoryCoverage(start, end, low, high, status)

    return transactions, [coverage(start, a.reference_ts) for a, start in zip(alerts, starts, strict=True)]
