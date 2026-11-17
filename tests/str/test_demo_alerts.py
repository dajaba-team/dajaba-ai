"""SCRUM-254 — 시연 후보 경보 입력(읽기 전용 내보내기 → 백엔드 요청 모양) (docs/str/08 "평가자 흔들림 — v4 초안"). LLM·DB 0.

내보내기 SQL 은 SELECT 만 · 경보 id 인자 · `--demo-alerts` 와 파일 id 집합이 다르면 거절 · 백엔드 스냅샷과 칸별 대조.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.str.demo_alerts import (
    DEFAULT_DEMO_ALERTS,
    load_exports,
    parse_alert_ids,
    request_from_rows,
    snapshot_diff,
)


def test_demo_alert_ids_argument() -> None:
    assert DEFAULT_DEMO_ALERTS == (7, 48)
    assert parse_alert_ids("7,48") == [7, 48] and parse_alert_ids(" 12 , 3 ") == [12, 3]
    for bad in ("", "7,,48", "a", "7,7", "-1"):
        with pytest.raises(ValueError):
            parse_alert_ids(bad)


def test_request_from_rows_matches_backend_snapshot_shape() -> None:
    """백엔드 초안 요청(str_draft_requests.request_snapshot)과 같은 칸 — reasons 는 점수 payload, evidence 는 경보 거래 전체."""
    alert = {"alert_no": "ALT-20220902-000007", "account_key": "10_S0000001", "entity_id": "E-S", "window_start": "2022-08-29T05:34:00",
             "window_end": "2022-09-02T05:34:00", "reference_ts": "2022-09-02T05:34:00", "rule_facts": {"distinct_senders": 5},
             "created_at": "2026-11-10T03:17:37Z"}  # fmt: skip
    rule = {"rule_id": "R02_FAN_IN", "version": 1, "typology_hint": "FAN_IN"}
    req = request_from_rows(alert, rule, [3, 1, 2], {"reasons": []}, prior_alert_count=2)
    assert req.alert.transaction_ids == [1, 2, 3] and req.evidence_transaction_ids == [1, 2, 3]
    assert (
        req.alert.rule_id == "R02_FAN_IN"
        and req.alert.typology_hint == "FAN_IN"
        and req.alert.rule_version == "1"
    )
    assert req.reasons == [] and req.prior_alert_count == 2 and req.investigator_notes is None
    assert request_from_rows(alert, rule, [1], None, prior_alert_count=0).reasons == []  # 점수 없음


SQL = Path(__file__).resolve().parent / "demo_alerts.sql"


def test_export_sql_is_select_only() -> None:
    body = "\n".join(line.split("--")[0] for line in SQL.read_text(encoding="utf-8").splitlines()).upper()
    for word in ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE", "GRANT"):
        assert not re.search(rf"\b{word}\b", body), word
    assert "SELECT" in body


def _export_row(alert_id: int, snapshot: dict | None = None) -> dict:
    return {"alert_id": alert_id, "alert": {"alert_no": f"ALT-20220902-{alert_id:06d}", "account_key": "10_S0000001",
            "entity_id": "E-S", "window_start": "2022-08-29T05:34:00", "window_end": "2022-09-02T05:34:00",
            "reference_ts": "2022-09-02T05:34:00", "rule_facts": {}, "created_at": "2026-11-10T03:17:37Z"},
            "rule": {"rule_id": "R02_FAN_IN", "version": 1, "typology_hint": "FAN_IN"}, "tx_ids": [2, 1],
            "score_payload": None, "prior_alert_count": 0, "snapshot": snapshot,
            "sql_counts": {"inbound": 2, "outbound": 0, "internal": 0, "counterparties": 2}}  # fmt: skip


def test_load_exports_rejects_different_id_set(tmp_path: Path) -> None:
    f = tmp_path / "demo.json"
    f.write_text(json.dumps([_export_row(7), _export_row(48)]), encoding="utf-8")
    loaded = load_exports(f, [7, 48])
    assert loaded[7]["request"].evidence_transaction_ids == [1, 2] and loaded[48]["snapshot"] is None
    for ids in ([7], [7, 48, 9], [7, 49]):
        with pytest.raises(ValueError):
            load_exports(f, ids)


def test_snapshot_diff_names_fields_only(tmp_path: Path) -> None:
    f = tmp_path / "demo.json"
    f.write_text(json.dumps([_export_row(7)]), encoding="utf-8")
    req = load_exports(f, [7])[7]["request"]
    same = req.model_dump(mode="json") | {"draft_id": "DRF-000002", "case_no": "CASE-2022-000004"}
    assert snapshot_diff(req, same) == [] and snapshot_diff(req, None) is None
    raw = json.loads(json.dumps(same))
    raw["alert"]["rule_facts"].pop("paths", None)  # 스냅샷 원문엔 기본값 칸이 없음 — 모델 검증 뒤 같음
    assert snapshot_diff(req, raw) == []
    other = json.loads(json.dumps(same))
    other["prior_alert_count"] = 3
    other["alert"]["rule_version"] = "2"
    assert snapshot_diff(req, other) == ["alert.rule_version", "prior_alert_count"]
