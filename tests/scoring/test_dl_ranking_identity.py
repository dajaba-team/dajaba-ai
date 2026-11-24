"""순위 응답의 근거 신원 칸과 스냅샷 검증 조건 (scoring/01 "근거 신원 칸"·"스냅샷 검증 조건")."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from tests.scoring.test_dl_ranking import (
    HEADERS,
    PREFIX,
    URL,
    B,
    C,
    Z,
    _assert_safe_warning,
    write_snapshot,
)

FIELDS = [
    "alert_id",
    "rule_id",
    "ml_score",
    "ml_failure_code",
    "dl_score",
    "evidence_count",
    "dl_linked",
    "fallback_reason",
    "ml_rank",
    "fused_rank",
    "reference_ts",
    "evidence_digest",
]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get(monkeypatch, tmp_path, **kwargs):
    write_snapshot(monkeypatch, tmp_path, **kwargs)
    with TestClient(app) as client:
        return client.get(URL, headers=HEADERS)


def test_every_alert_carries_reference_and_evidence_identity(monkeypatch, tmp_path) -> None:
    response = _get(monkeypatch, tmp_path)
    assert response.status_code == 200
    rows = {row["alert_id"]: row for row in response.json()["alerts"]}
    assert all(list(row) == FIELDS for row in rows.values())
    # 스냅샷 원본은 공백 구분이지만 응답은 T 모양이다.
    assert {row["reference_ts"] for row in rows.values()} == {"2022-09-07T01:00:00"}
    assert rows[Z]["evidence_digest"] == sha("dataset.csv:10")
    assert rows[B]["evidence_digest"] == sha("dataset.csv:20\ndataset.csv:40")
    assert rows[C]["evidence_digest"] == sha("dataset.csv:30")


def test_identity_fields_do_not_change_ranks(monkeypatch, tmp_path) -> None:
    response = _get(monkeypatch, tmp_path, partial=True)
    assert response.status_code == 200
    rows = response.json()["alerts"]
    assert [(r["alert_id"], r["ml_rank"], r["fused_rank"]) for r in rows] == [(C, 3, 1), (B, 2, 2), (Z, 1, 3)]
    # DL 점수가 빠진 근거도 digest 에는 들어간다.
    assert rows[1]["evidence_digest"] == sha("dataset.csv:20\ndataset.csv:40")


def test_alert_without_evidence_is_id_mismatch(monkeypatch, tmp_path, caplog) -> None:
    response = _get(monkeypatch, tmp_path, mutate="no-evidence")
    assert response.status_code == 503
    assert response.json()["code"] == "DL_RANKING_UNAVAILABLE"
    _assert_safe_warning(caplog, "ID_MISMATCH", "SnapshotInvalid", str(tmp_path), PREFIX)


@pytest.mark.parametrize(
    "number",
    ["00000A", "12345", "1" * 19, "０００００３", "00000-3", " 000003"],
    ids=["letter", "5-digits", "19-digits", "fullwidth-digits", "dash", "space"],
)
def test_alert_number_tail_must_be_6_to_18_digits(monkeypatch, tmp_path, caplog, number) -> None:
    response = _get(monkeypatch, tmp_path, c_number=number)
    assert response.status_code == 503
    assert response.json()["code"] == "DL_RANKING_UNAVAILABLE"
    _assert_safe_warning(caplog, "ID_MISMATCH", "SnapshotInvalid", str(tmp_path))


@pytest.mark.parametrize("number", ["000001", "1" * 18])
def test_alert_number_tail_boundaries_pass(monkeypatch, tmp_path, number) -> None:
    response = _get(monkeypatch, tmp_path, c_number=number)
    assert response.status_code == 200
    assert PREFIX + number in {row["alert_id"] for row in response.json()["alerts"]}
