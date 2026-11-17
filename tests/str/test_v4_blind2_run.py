"""SCRUM-265 (1/2) — 재블라인드 실행 묶기·v2 첫 생성 체크포인트 (09 "SCRUM-265 1/2 추가 검토 3차"). LLM·DB 0.

다른 실행 키·진단·응답이 섞이면 거절(회귀쌍 매핑만 다른 키로 not_met→candidate 되던 것) ·
마지막 사건 실패 → 앞 사건 원본 저장됨 → 다시 실행해도 앞 사건 생성 0(사건 1 두 번 생성되던 것).
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import NarrativeSection, SectionV2
from tests.str.test_v4_blind2_reveal import _diag, _doc, _key, _responses
from tests.str.v4_blind2_build import blind2_cases
from tests.str.v4_blind2_cases import load_cases
from tests.str.v4_blind2_io import diag_hash
from tests.str.v4_blind2_live import originals
from tests.str.v4_blind2_reveal import reveal2
from tests.str.v4_blind_support import BlindCase


def test_other_run_key_rejected() -> None:
    """같은 쌍 번호·구조에 회귀쌍 10 매핑만 뒤집은 다른 실행 키 → 거절(전엔 실패 진단이 v2 쪽으로 가 candidate)."""
    assert reveal2(_responses(), _key(10), _diag(10), _doc()).verdict == "not_met"
    other = _key(10)
    other["pairs"][9].update(A="v2", B="v4")
    other["run_id"] = "20261118-000000"
    with pytest.raises(ValueError):
        reveal2(_responses(), other, _diag(10), _doc())
    other["run_id"] = _key()["run_id"]  # run_id 만 맞춰도 진단 해시가 다르면 거절
    other["diag_sha256"] = diag_hash(_diag())
    with pytest.raises(ValueError):
        reveal2(_responses(), other, _diag(10), _doc())


def test_other_run_diag_or_responses_rejected() -> None:
    diag = copy.deepcopy(_diag())
    diag["run_id"] = "20261118-000000"
    with pytest.raises(ValueError):
        reveal2(_responses(), _key(), diag, _doc())
    rs = _responses()
    rs[5] = replace(rs[5], run_id="20261118-000000")
    with pytest.raises(ValueError):
        reveal2(rs, _key(), _diag(), _doc())
    with pytest.raises(ValueError):
        reveal2([replace(r, run_id=None) for r in _responses()], _key(), _diag(), _doc())


def _sections(case: BlindCase) -> list[NarrativeSection]:
    return [NarrativeSection(section=s, text=f"{case.case_id} {s.value} 원본임.") for s in SectionV2]


def test_checkpoint_resumes_without_regenerating(tmp_path: Path) -> None:
    cases = blind2_cases(load_cases())
    calls: list[str] = []

    def failing_last(case: BlindCase) -> list[NarrativeSection]:
        calls.append(case.case_id)
        if case.case_id == cases[-1].case_id:
            raise TimeoutError("마지막 사건 실패 주입")
        return _sections(case)

    with pytest.raises(TimeoutError):
        originals(cases, failing_last, tmp_path)
    saved = sorted(p.stem for p in tmp_path.glob("*.json"))
    assert saved == sorted(c.case_id for c in cases[:-1])  # 앞 사건 원본은 성공 즉시 저장
    first = (tmp_path / f"{cases[0].case_id}.json").read_text(encoding="utf-8")
    calls.clear()

    def ok(case: BlindCase) -> list[NarrativeSection]:
        calls.append(case.case_id)
        return _sections(case)

    out = originals(cases, ok, tmp_path)
    assert calls == [cases[-1].case_id]  # 앞 사건 LLM 호출 0
    assert out[cases[0].case_id] == _sections(cases[0]) and len(out) == len(cases)
    assert (tmp_path / f"{cases[0].case_id}.json").read_text(encoding="utf-8") == first  # 원본 안 바뀜
