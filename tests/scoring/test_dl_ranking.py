from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from tests.conftest import EXAMPLES, load_json

URL = "/v1/dl-rankings/2022-09-07"
HEADERS = {"X-Internal-Key": "test-key"}
PREFIX = "ALT-20220907-"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_snapshot(monkeypatch, tmp_path: Path, *, partial: bool = False, mutate: str = "") -> Path:
    alerts = "alert_no,alert_id,rule_id,reference_ts,transaction_ids\n"
    evidence = "alert_no,alert_id,rule_id,transaction_id,ts\n"
    ml = "alert_no,alert_id,rule_id,score,failure_code\n"
    for i, suffix, score in [(1, "Z", 0.9), (2, "B", 0.8), (3, "C", 0.7)]:
        ids = (2, 4) if i == 2 else (i,)
        rule = f"R0{i}"
        aid = PREFIX + suffix
        alerts += f"{aid},{i},{rule},2022-09-07T01:00:00,{' '.join(map(str, ids))}\n"
        evidence += "".join(f"{aid},{i},{rule},{j},2022-09-07T00:00:00\n" for j in ids)
        ml += f"{aid},{i},{rule},{score},\n"
    dl = "transaction_id,source_file,source_row_number,minute_since_2022_09_01,score\n"
    dl += "1,dataset.csv,10,8640,0.2\n2,dataset.csv,20,8640,0.4\n3,dataset.csv,30,8640,0.9\n"
    if not partial:
        dl += "4,dataset.csv,40,8640,0.4\n"
    mapping = "transaction_id,source_file,source_row_number\n"
    mapping += "".join(f"{i},dataset.csv,{i * 10}\n" for i in range(1, 5))
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
        ml = ml.replace(f"{PREFIX}Z,1", f"{PREFIX}Z,19")
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
                "snapshot_transactions": 4,
                "transactions": 3 if partial else 4,
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
        (PREFIX + "C", 3, 1, 0.7),
        (PREFIX + "B", 2, 2, 0.8),
        (PREFIX + "Z", 1, 3, 0.9),
    ]
    assert rows[1]["dl_score"] is None
    assert rows[1]["fallback_reason"] == "INCOMPLETE_DL_EVIDENCE"
    assert (rows[1]["dl_linked"], rows[1]["evidence_count"]) == (1, 2)


@pytest.mark.parametrize("mutate", ["different-scan", "wrong-source-id", "duplicate", "wrong-alert-id"])
def test_rejects_inconsistent_artifacts_even_with_valid_hashes(monkeypatch, tmp_path, mutate) -> None:
    write_snapshot(monkeypatch, tmp_path, mutate=mutate)
    with TestClient(app) as client:
        response = client.get(URL, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "DL_RANKING_UNAVAILABLE"


@pytest.mark.parametrize("change", ["delete", "tamper", "manifest"])
def test_unavailable_dl_does_not_change_scores_contract(monkeypatch, tmp_path, change) -> None:
    snapshot = write_snapshot(monkeypatch, tmp_path)
    with TestClient(app) as client:
        request = load_json(EXAMPLES / "score_request.json")
        before = client.post("/v1/scores", headers=HEADERS, json=request)
        if change == "delete":
            (snapshot / "dl.csv").unlink()
        elif change == "tamper":
            with (snapshot / "dl.csv").open("ab") as f:
                f.write(b"\n")
        else:
            with (snapshot / "manifest.json").open("ab") as f:
                f.write(b"\n")
        unavailable = client.get(URL, headers=HEADERS)
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "DL_RANKING_UNAVAILABLE"
        after = client.post("/v1/scores", headers=HEADERS, json=request)
    assert before.status_code == after.status_code == 200
    assert {k: v for k, v in before.json().items() if k != "produced_at"} == {
        k: v for k, v in after.json().items() if k != "produced_at"
    }
