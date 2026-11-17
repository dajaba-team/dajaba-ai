"""SCRUM-265 (1/2) — 재블라인드 집계 전 쌍 완전성·결과 경로 (09 "SCRUM-265 1/2 추가 검토 2차"). LLM·DB 0.

쌍이 빠지면 판정이 뒤집힘(대조쌍 directional→candidate · 실패 회귀쌍 not_met→candidate) → 거절.
결과 파일은 별도 이름 — 입력 이름이 무엇이든 입력을 덮지 않음.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.str.test_v4_blind2_reveal import _diag, _doc, _key, _responses
from tests.str.v4_blind2_cases import load_cases
from tests.str.v4_blind2_io import diag_hash, result_paths
from tests.str.v4_blind2_reveal import main, reveal2


def _without(pair_no: int, **kw: Any) -> tuple[list, dict, dict]:
    failing = kw.pop("failing_pair", None)
    key, diag = _key(failing), _diag(failing)
    key["pairs"] = [p for p in key["pairs"] if p["pair_no"] != pair_no]
    diag["pairs"] = [p for p in diag["pairs"] if p["pair_no"] != pair_no]
    key["diag_sha256"] = diag_hash(diag)  # 같은 실행에서 빠진 것처럼 — 완전성 검사가 거절해야 함
    return [r for r in _responses(**kw) if r.pair_no != pair_no], key, diag


def test_dropping_control_pair_is_rejected() -> None:
    assert reveal2(_responses(control=("A", "B", "same")), _key(), _diag(), _doc()).verdict == "directional"
    rs, key, diag = _without(12, control=("A", "B", "same"))
    with pytest.raises(ValueError):
        reveal2(rs, key, diag, _doc())  # 전엔 candidate


def test_dropping_failing_regression_pair_is_rejected() -> None:
    assert reveal2(_responses(), _key(failing_pair=10), _diag(failing_pair=10), _doc()).verdict == "not_met"
    rs, key, diag = _without(10, failing_pair=10)
    with pytest.raises(ValueError):
        reveal2(rs, key, diag, _doc())  # 전엔 candidate


def test_duplicate_pair_number_is_rejected() -> None:
    key = _key()
    key["pairs"][10]["pair_no"] = 10  # 쌍 11 → 10 중복
    with pytest.raises(ValueError):
        reveal2(_responses(), key, _diag(), _doc())


@pytest.mark.parametrize(
    ("index", "sides"),
    [(0, ("v4", "v4")), (9, ("v2", "v2")), (11, ("v2", "v4")), (11, ("v4", "v2"))],
)
def test_version_mapping_errors_rejected(index: int, sides: tuple[str, str]) -> None:
    """새·회귀는 v4/v2 한 쪽씩, 대조(쌍 12)는 v4/v4."""
    key = _key()
    key["pairs"][index].update(A=sides[0], B=sides[1])
    with pytest.raises(ValueError):
        reveal2(_responses(), key, _diag(), _doc())


def test_wrong_control_case_or_missing_case_rejected() -> None:
    key = _key()
    key["pairs"][11]["case_id"] = "c2"  # 사건 파일 대조는 c1
    with pytest.raises(ValueError):
        reveal2(_responses(), key, _diag(), _doc())
    key = _key()
    key["pairs"][7]["case_id"] = "c1"  # c8 빠지고 c1 두 번
    with pytest.raises(ValueError):
        reveal2(_responses(), key, _diag(), _doc())


def test_result_paths_never_equal_inputs(tmp_path: Path) -> None:
    key = tmp_path / "key.json"
    out_json, out_md = result_paths(key, [tmp_path / "diag.json", key, tmp_path / "responses.json"])
    assert out_json.name == "v4_blind2_revealed_key.json" and out_md.suffix == ".md"
    tagged = tmp_path / "v4_blind_key_v4blind2_x.json"
    assert result_paths(tagged, [tagged])[0].name == "v4_blind2_revealed_v4blind2_x.json"
    with pytest.raises(ValueError):
        result_paths(key, [key, tmp_path / "v4_blind2_revealed_key.json"])


def test_main_with_arbitrary_input_names_keeps_inputs(tmp_path: Path) -> None:
    doc = load_cases()
    ids = [c["case_id"] for c in doc["cases"]]
    pairs = [
        {"pair_no": n, "case_id": c, "control": False, "A": "v4", "B": "v2"} for n, c in enumerate(ids, 1)
    ]
    pairs.append(
        {"pair_no": len(ids) + 1, "case_id": doc["control_case_id"], "control": True, "A": "v4", "B": "v4"}
    )
    side = {"chars": 1, "sentences": {}, "code_check_failures": 0}
    rows = [
        {"rater": r, "pair_no": p["pair_no"], "choice": "same" if p["control"] else "A", "fix_a": 0, "fix_b": 1,
         "wrong_a": [], "wrong_b": [], "reason": "", "support_a": "yes", "support_b": "yes", "run_id": "r"}
        for r in ("r1", "r2", "r3") for p in pairs
    ]  # fmt: skip
    diag = {"run_id": "r", "pairs": [{"pair_no": p["pair_no"], "A": side, "B": side} for p in pairs]}
    files = {
        "diag.json": diag,
        "key.json": {"run_id": "r", "seed": 1, "pairs": pairs, "diag_sha256": diag_hash(diag)},
        "responses.json": rows,
    }
    for name, body in files.items():
        (tmp_path / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    before = {name: (tmp_path / name).read_text(encoding="utf-8") for name in files}
    assert main([str(tmp_path / name) for name in files]) == 0
    assert {name: (tmp_path / name).read_text(encoding="utf-8") for name in files} == before
    assert (tmp_path / "v4_blind2_revealed_key.json").exists() and (
        tmp_path / "v4_blind2_revealed_key.md"
    ).exists()
