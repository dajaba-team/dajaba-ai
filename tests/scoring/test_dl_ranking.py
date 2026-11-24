from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.scoring.application import dl_ranking
from aml_ai.shared.config import Settings, get_settings
from tests.conftest import EXAMPLES, load_json

URL = "/v1/dl-rankings/2022-09-07"
HEADERS = {"X-Internal-Key": "test-key"}
PREFIX = "ALT-20220907-"
# 경보 번호 오름차순은 B < C < Z — 동점 규칙 테스트가 이 순서에 기댄다.
Z, B, C = PREFIX + "000009", PREFIX + "000002", PREFIX + "000003"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_snapshot(
    monkeypatch,
    tmp_path: Path,
    *,
    partial: bool = False,
    mutate: str = "",
    boundary: bool = False,
    c_number: str = "000003",
) -> Path:
    no_evidence = mutate == "no-evidence"
    alerts = "alert_no,alert_id,rule_id,reference_ts,transaction_ids\n"
    evidence = "alert_no,alert_id,rule_id,transaction_id,ts\n"
    ml = "alert_no,alert_id,rule_id,score,failure_code\n"
    for i, number, score in [(1, "000009", 0.9), (2, "000002", 0.8), (3, c_number, 0.7)]:
        ids = (2, 4) if i == 2 else () if i == 3 and no_evidence else (i,)
        rule = f"R0{i}"
        aid = PREFIX + number
        alerts += f"{aid},{i},{rule},2022-09-07 01:00:00,{' '.join(map(str, ids))}\n"
        evidence += "".join(f"{aid},{i},{rule},{j},2022-09-07T00:00:00\n" for j in ids)
        ml += f"{aid},{i},{rule},{score},\n"
    dl = "transaction_id,source_file,source_row_number,minute_since_2022_09_01,score\n"
    dl += "1,dataset.csv,10,8640,0.2\n2,dataset.csv,20,8640,0.4\n3,dataset.csv,30,8640,0.9\n"
    if not partial:
        dl += "4,dataset.csv,40,8640,0.4\n"
    if boundary:
        evidence = evidence.replace(",2,2022-09-07T00:00:00", ",2,2022-09-07T00:59:59")
        evidence = evidence.replace(",4,2022-09-07T00:00:00", ",4,2022-09-07T01:00:00")
        dl = dl.replace("2,dataset.csv,20,8640", "2,dataset.csv,20,8699")
        dl = dl.replace("4,dataset.csv,40,8640", "4,dataset.csv,40,8700")
    tx_ids = [i for i in range(1, 5) if not (no_evidence and i == 3)]
    if no_evidence:
        dl = dl.replace("3,dataset.csv,30,8640,0.9\n", "")
    mapping = "transaction_id,source_file,source_row_number\n"
    mapping += "".join(f"{i},dataset.csv,{i * 10}\n" for i in tx_ids)
    scan_hashes = {
        "alerts.csv": digest(alerts.encode()),
        "evidence_transactions.csv": digest(evidence.encode()),
        "history_24h.csv": "test-history",
        "history_coverage.csv": "test-coverage",
    }
    worker_input = {f"scan/{key}": value for key, value in scan_hashes.items()}
    worker_input["history/evidence_source_map.csv"] = digest(mapping.encode())
    if mutate == "different-scan":
        worker_input["scan/history_24h.csv"] = "other-history"
    if mutate == "wrong-source-id":
        dl = dl.replace("3,dataset.csv,30", "3,dataset.csv,31")
    if mutate == "duplicate":
        dl += "1,dataset.csv,10,8640,0.2\n"
    if mutate == "wrong-alert-id":
        ml = ml.replace(f"{Z},1", f"{Z},19")
    worker_raw = json.dumps(worker_input)
    payloads = {
        "alerts.csv": alerts,
        "evidence_transactions.csv": evidence,
        "evidence_source_map.csv": mapping,
        "ml.csv": ml,
        "dl.csv": dl,
        "worker-input.json": worker_raw,
        "ml-summary.json": json.dumps(
            {
                "status": "PASS",
                "package": "0.1.0rc3",
                "model": "xgb-hi-medium-r04-event-c2-31-v1",
                "feature_version": "hi-medium-evidence31-96h-r04-event-v1",
                "alerts": 3,
                "scored": 3,
                "input_sha256": scan_hashes,
            }
        ),
        "dl-summary.json": json.dumps(
            {
                "status": "PARTIAL" if partial else "PASS",
                "mode": "full",
                "dl_commit": "b75cf1e42d24a4a46ddff2f259dde5ac9a8c63c1",
                "model": "HI-Medium-B-GINe-counts-best-13",
                "snapshot_manifest_sha256": digest(worker_raw.encode()),
                "snapshot_alerts": 3,
                "snapshot_transactions": len(tx_ids),
                "transactions": len(tx_ids) - partial,
            }
        ),
    }
    for name, data in payloads.items():
        (tmp_path / name).write_bytes(data.encode())
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(
        json.dumps(
            {
                "scan_date": "2022-09-07",
                "files": {name: digest(data.encode()) for name, data in payloads.items()},
            }
        ).encode()
    )
    monkeypatch.setenv("AI_DL_SNAPSHOT_MANIFEST", str(manifest))
    monkeypatch.setenv("AI_DL_SNAPSHOT_SHA256", digest(manifest.read_bytes()))
    return tmp_path


def test_internal_key_and_wrong_scan(monkeypatch, tmp_path) -> None:
    write_snapshot(monkeypatch, tmp_path)
    with TestClient(app) as client:
        denied = client.get(URL)
        assert denied.status_code == 401
        assert denied.json()["code"] == "UNAUTHENTICATED"
        good = client.get(URL, headers=HEADERS)
        assert good.status_code == 200
        assert good.headers["cache-control"] == "no-store"
        assert good.json()["linked_alerts"] == 3
        assert client.get("/v1/dl-rankings/2022-09-08", headers=HEADERS).status_code == 503


def test_partial_evidence_keeps_original_ml_slot(monkeypatch, tmp_path) -> None:
    write_snapshot(monkeypatch, tmp_path, partial=True)
    with TestClient(app) as client:
        response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert (body["scored_transactions"], body["linked_alerts"], body["ml_only_alerts"]) == (3, 2, 1)
    rows = body["alerts"]
    assert [(x["alert_id"], x["ml_rank"], x["fused_rank"], x["ml_score"]) for x in rows] == [
        (C, 3, 1, 0.7),
        (B, 2, 2, 0.8),
        (Z, 1, 3, 0.9),
    ]
    assert rows[1]["dl_score"] is None
    assert rows[1]["fallback_reason"] == "INCOMPLETE_DL_EVIDENCE"
    assert (rows[1]["dl_linked"], rows[1]["evidence_count"]) == (1, 2)


@pytest.mark.parametrize("mutate", ["different-scan", "wrong-source-id", "duplicate", "wrong-alert-id"])
def test_rejects_inconsistent_artifacts_even_with_valid_hashes(monkeypatch, tmp_path, mutate, caplog) -> None:
    write_snapshot(monkeypatch, tmp_path, mutate=mutate)
    with TestClient(app) as client:
        response = client.get(URL, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "DL_RANKING_UNAVAILABLE"
    reason = "PROVENANCE_MISMATCH" if mutate == "different-scan" else "ID_MISMATCH"
    _assert_safe_warning(caplog, reason, "SnapshotInvalid", str(tmp_path), PREFIX, "dataset.csv")


@pytest.mark.parametrize("change", ["delete", "tamper", "manifest", "manifest-delete"])
def test_unavailable_dl_does_not_change_scores_contract(monkeypatch, tmp_path, change, caplog) -> None:
    snapshot = write_snapshot(monkeypatch, tmp_path)
    with TestClient(app) as client:
        request = load_json(EXAMPLES / "score_request.json")
        before = client.post("/v1/scores", headers=HEADERS, json=request)
        assert client.get(URL, headers=HEADERS).status_code == 200
        target = snapshot / ("manifest.json" if change.startswith("manifest") else "dl.csv")
        original = target.read_bytes()
        if "delete" in change:
            target.unlink()
        elif change == "tamper":
            before_stat = target.stat()
            target.write_bytes(original.replace(b"dataset.csv", b"private.csv", 1))
            os.utime(target, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
        else:
            target.write_bytes(original + b"\n")
        unavailable = client.get(URL, headers=HEADERS)
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "DL_RANKING_UNAVAILABLE"
        if "delete" in change:
            _assert_safe_warning(caplog, "FILE_MISSING", "FileNotFoundError", str(target))
        else:
            _assert_safe_warning(caplog, "HASH_MISMATCH", "SnapshotInvalid", str(target), "private.csv")
        rank = Mock(wraps=dl_ranking._rank)
        monkeypatch.setattr(dl_ranking, "_rank", rank)
        target.write_bytes(original)
        assert client.get(URL, headers=HEADERS).status_code == 200
        rank.assert_called_once()
        after = client.post("/v1/scores", headers=HEADERS, json=request)
    assert before.status_code == after.status_code == 200
    assert {k: v for k, v in before.json().items() if k != "produced_at"} == {
        k: v for k, v in after.json().items() if k != "produced_at"
    }


def test_fusion_tie_uses_ascending_alert_number(monkeypatch, tmp_path) -> None:
    write_snapshot(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    rows = response.json()["alerts"]
    # Z는 ML 1위, C는 DL 1위라 둘의 결합값이 같다.
    assert [(row["alert_id"], row["ml_rank"], row["fused_rank"]) for row in rows[:2]] == [
        (C, 3, 1),
        (Z, 1, 2),
    ]


def test_previous_minute_counts_and_reference_minute_keeps_ml_slot(monkeypatch, tmp_path) -> None:
    write_snapshot(monkeypatch, tmp_path, boundary=True)
    with TestClient(app) as client:
        response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    rows = {row["alert_id"]: row for row in body["alerts"]}
    assert body["scored_transactions"] == 4
    assert body["linked_alerts"] == 2
    b = rows[B]
    assert (b["dl_linked"], b["evidence_count"], b["dl_score"]) == (1, 2, None)
    assert b["fallback_reason"] == "INCOMPLETE_DL_EVIDENCE"
    assert (b["ml_rank"], b["fused_rank"]) == (2, 2)
    assert (rows[C]["fused_rank"], rows[Z]["fused_rank"]) == (1, 3)


def test_valid_repeated_request_reuses_parsed_result(monkeypatch, tmp_path) -> None:
    write_snapshot(monkeypatch, tmp_path)
    rank = Mock(wraps=dl_ranking._rank)
    monkeypatch.setattr(dl_ranking, "_rank", rank)
    with TestClient(app) as client:
        first = client.get(URL, headers=HEADERS)
        again = client.get(URL, headers=HEADERS)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    rank.assert_called_once()


def test_missing_settings_warns_without_request_secrets(monkeypatch, caplog) -> None:
    monkeypatch.delenv("AI_DL_SNAPSHOT_MANIFEST", raising=False)
    monkeypatch.delenv("AI_DL_SNAPSHOT_SHA256", raising=False)
    # 작업 트리의 .env 에 스냅샷 경로가 있어도 읽지 않게 설정 객체를 직접 만든다.
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: Settings(_env_file=None))
    with TestClient(app) as client:
        response = client.get(URL, headers=HEADERS)
        schema = client.get("/openapi.json").json()
    assert response.status_code == 503
    assert response.json()["code"] == "DL_RANKING_UNAVAILABLE"
    assert schema["paths"]["/v1/dl-rankings/{scan_date}"]["get"]["summary"] == "ML+DL 조사 순위 (스냅샷)"
    _assert_safe_warning(caplog, "SETTINGS_MISSING", "SnapshotInvalid")


def _assert_safe_warning(caplog, reason, kind, *private_values) -> None:
    record = next(
        r for r in reversed(caplog.records) if getattr(r, "error_code", None) == "DL_RANKING_UNAVAILABLE"
    )
    assert (record.reason_code, record.error_type) == (reason, kind)
    assert record.msg == "ai_error"
    assert record.args == ()
    assert not record.exc_info
    for value in (HEADERS["X-Internal-Key"], *private_values):
        assert value not in repr(vars(record))
