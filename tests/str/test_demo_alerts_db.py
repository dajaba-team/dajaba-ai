"""SCRUM-254 추가 검토 1차 — 내보내기 SQL 판정 ↔ build_facts → typology_support 같음 (-m db, 테스트 컨테이너만).

상대 계좌 법인이 NULL 이거나 계좌 행이 없으면 내부 아님(facts._is_internal 과 같게) — SQL 이 그 거래를 빠뜨리면
송금인 5 가 4 로 줄어 판정이 갈림. 경보·규칙·점수 테이블은 트랜잭션 안에서 만들고 끝에 되돌림.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from aml_ai.str.domain import masking
from aml_ai.str.domain.typology_support import Support, typology_support
from tests.str.demo_alerts import demo_facts, load_exports, sql_support

pytestmark = pytest.mark.db
SQL = (Path(__file__).resolve().parent / "demo_alerts.sql").read_text(encoding="utf-8")
SUBJ = "10_SUBJ00001"
_DDL = """
create table ops.rules (id bigint primary key, rule_id text, version int, typology_hint text);
create table ops.alerts (id bigint primary key, alert_no text, rule_ref_id bigint, account_key text, entity_id text,
  window_start timestamp, window_end timestamp, reference_ts timestamp, rule_facts jsonb, created_at timestamptz);
create table ops.alert_transactions (alert_id bigint, transaction_id bigint);
create table ops.alert_scores (alert_id bigint, payload jsonb, produced_at timestamptz);
create table ops.cases (id bigint primary key, alert_id bigint);
create table ops.str_draft_requests (case_id bigint, request_snapshot jsonb, created_at timestamptz);
"""


@pytest.fixture
def conn(_db_engine: Engine, _ops_seed: None) -> Iterator[Connection]:
    with _db_engine.connect() as c:
        trans = c.begin()
        try:
            for stmt in filter(str.strip, _DDL.split(";")):
                c.execute(text(stmt))
            yield c
        finally:
            trans.rollback()


def _seed(
    c: Connection,
    alert_id: int,
    senders: list[tuple[str, str | None, bool]],
    internal: int = 0,
    subject_entity: str | None = "E-SUBJ",
) -> None:
    """senders: (계좌 키, 법인 id 또는 None, 계좌 행 넣을지). internal: 같은 법인 계좌에서 들어온 거래 수.
    subject_entity: 대상 계좌 행의 법인 칸(None 이면 행은 있고 법인 NULL). 경보 entity_id 는 늘 E-SUBJ."""
    c.execute(
        text(
            "insert into ops.entities values ('E-SUBJ', 'Corporation #1', 'CORPORATION') on conflict do nothing"
        )
    )
    c.execute(text("insert into ops.accounts values (:k, 'Bank', :e), (:k2, 'Bank', 'E-SUBJ') on conflict do nothing"),
              {"k": SUBJ, "k2": "10_SUBJ00002", "e": subject_entity})  # fmt: skip
    rows = [(k, False) for k, _, _ in senders] + [("10_SUBJ00002", True)] * internal
    for key, entity, has_row in senders:
        if entity:
            c.execute(
                text("insert into ops.entities values (:e, 'X', 'INDIVIDUAL') on conflict do nothing"),
                {"e": entity},
            )
        if has_row:
            c.execute(text("insert into ops.accounts values (:k, 'Other', :e)"), {"k": key, "e": entity})
    c.execute(text("insert into ops.rules values (1, 'R02_FAN_IN', 1, 'FAN_IN') on conflict do nothing"))
    c.execute(text("""insert into ops.alerts values (:a, :no, 1, :s, 'E-SUBJ', '2022-08-29 00:00', '2022-09-02 00:00',
        '2022-09-02 00:00', '{}'::jsonb, '2026-11-10 00:00+00')"""), {"a": alert_id, "no": f"ALT-20220902-{alert_id:06d}", "s": SUBJ})  # fmt: skip
    for n, (frm, _) in enumerate(rows):
        tid = alert_id * 100 + n
        c.execute(text("""insert into ops.transactions (transaction_id, ts, from_account_key, to_account_key, amount_paid,
            currency_paid, amount_received, currency_received, payment_format, is_self_transfer)
            values (:t, '2022-09-01 10:00', :f, :s, 10, 'US Dollar', 10, 'US Dollar', 'ACH', false)"""),
                  {"t": tid, "f": frm, "s": SUBJ})  # fmt: skip
        c.execute(text("insert into ops.alert_transactions values (:a, :t)"), {"a": alert_id, "t": tid})


def _compare(c: Connection, alert_id: int, tmp_path: Path) -> tuple[Support | None, Support | None]:
    rows = c.execute(text(SQL.replace(":'ids'", f"'{alert_id}'"))).scalar_one()
    f = tmp_path / "x.json"
    f.write_text(json.dumps(rows if isinstance(rows, list) else json.loads(rows)), encoding="utf-8")
    e = load_exports(f, [alert_id])[alert_id]
    ai = typology_support(masking.mask_for_llm(demo_facts(Session(bind=c), e["request"])))
    return sql_support(e["sql_counts"], "FAN_IN"), ai


def test_null_entity_sender_counts_as_external(conn: Connection, tmp_path: Path) -> None:
    senders = [(f"020_SND0000{i}", f"E-SND{i}", True) for i in range(1, 5)] + [("020_SND00005", None, True)]
    _seed(conn, 901, senders)
    assert _compare(conn, 901, tmp_path) == (Support.SUPPORTED, Support.SUPPORTED)


def test_missing_account_row_counts_as_external_and_internal_still_internal(
    conn: Connection, tmp_path: Path
) -> None:
    senders = [(f"020_SND1000{i}", f"E-SNE{i}", True) for i in range(1, 5)] + [("020_NOROW0001", None, False)]
    _seed(conn, 902, senders, internal=1)
    sql, ai = _compare(conn, 902, tmp_path)
    assert sql == ai == Support.SUPPORTED


def test_subject_account_with_null_entity_keeps_null(conn: Connection, tmp_path: Path) -> None:
    """추가 검토 2차 — 대상 계좌 행은 있고 법인 NULL · 경보 법인 E-SUBJ · 송금인 하나가 E-SUBJ 법인.
    load_subject 는 계좌 칸(NULL)을 그대로 → 내부 거래 없음 → 상대 5 → SUPPORTED. SQL 도 같아야 함."""
    senders = [(f"020_SND2000{i}", f"E-SNF{i}", True) for i in range(1, 5)] + [
        ("020_SND20005", "E-SUBJ", True)
    ]
    _seed(conn, 903, senders, subject_entity=None)
    assert _compare(conn, 903, tmp_path) == (Support.SUPPORTED, Support.SUPPORTED)
