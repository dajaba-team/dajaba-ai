"""SCRUM-306 합의 CLI — 출력은 chunk_id·숫자만 · --out 은 새 파일만(manifest·받은 시트·기존 결과 바이트 그대로)."""

from __future__ import annotations

import json
import sys

import pytest
from tools import rag2_consensus as rc
from tools.rag2_sample import ROOT

from tests.str.test_rag2_consensus import _decide, _pair


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    monkeypatch.setattr(rc, "compute_content_hash", lambda doc, page, text: text.removeprefix("body-"))


def _run_cli(monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["rag2_consensus", *argv])
    rc.main()


def test_cli_consensus_writes_ids_and_numbers_only(tmp_path, monkeypatch, capsys) -> None:
    a_path, b_path = _pair(tmp_path)
    listed = rc.disagreement_rows(*rc.load_pair(a_path, b_path))
    out = tmp_path / "result.json"
    argv = ["consensus", str(a_path), str(b_path), str(_decide(listed, tmp_path / "d.csv")), "--out", str(out),
            "--checker", "확인자", "--checked-at", "2026-11-20"]  # fmt: skip
    _run_cli(monkeypatch, argv)
    result = json.loads(out.read_text(encoding="utf-8"))
    assert set(result) == {"rows", "agreement", "disagree", "ai_vs_consensus", "new_vs_305", "consensus",
                           "checked_by", "checked_at", "reasons"}  # fmt: skip
    assert result["rows"] == 80 and result["disagree"] == 3
    assert (result["checked_by"], result["checked_at"]) == ("확인자", "2026-11-20")
    assert result["reasons"] == {"기준 모호": 0, "용어 오해": 0, "단순 실수": 3}
    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, [*argv[:-1], "11/20"])  # 날짜 형식
    assert "SECRET-MEMO" not in out.read_text(encoding="utf-8") + capsys.readouterr().out
    assert "근거" not in out.read_text(encoding="utf-8")  # 근거위치도 안 나감


@pytest.mark.parametrize("victim", ["manifest", "a", "result"])
def test_cli_out_never_overwrites(tmp_path, monkeypatch, victim) -> None:
    """--out 으로 manifest·받은 시트·이미 있는 결과를 줘도 원래 바이트 그대로(추가 검토 1회차)."""
    a_path, b_path = _pair(tmp_path)
    decided = _decide(rc.disagreement_rows(*rc.load_pair(a_path, b_path)), tmp_path / "d.csv")
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    target = {"manifest": ROOT / "corpus/manifest.json", "a": a_path, "result": tmp_path / "result.json"}[
        victim
    ]
    before = target.read_bytes()
    argv = ["consensus", str(a_path), str(b_path), str(decided), "--out", str(target),
            "--checker", "확인자", "--checked-at", "2026-11-20"]  # fmt: skip
    with pytest.raises(ValueError, match="작업 트리 안|덮지 않음"):
        _run_cli(monkeypatch, argv)
    assert target.read_bytes() == before
