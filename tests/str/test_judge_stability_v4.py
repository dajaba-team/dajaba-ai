"""SCRUM-254 ★L-1 — v4 초안 검증 평가자 측정 하네스 (docs/str/08 "평가자 흔들림 — v4 초안"). LLM·DB 0.

사건 19(v4 18 · v2 1) · v4 초안 → verify 요청 모양 · 코드 검사 0 · dry-run 호출 0·sha256 결정적 ·
집계(사전 기준 = v4 전부 n회 PASSED, v2 대조는 판정 밖) · 시연 후보 경보 id 인자 · 백엔드 요청 모양 조립 ·
재블라인드 키·진단·응답 경로 접근 없음.
"""

from __future__ import annotations

import builtins
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.str import RevisedNarrativeSection
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import verification
from aml_ai.str.domain.fact_keys import fact_keys
from tests.str.judge_stability_v4 import V2_CASE, build_cases, dry_run
from tests.str.judge_stability_v4_tally import meets_criterion, render_table, tally
from tests.str.v4_blind2_cases import case_facts, load_cases

BLIND2 = case_facts(load_cases())
DEMO = [("demo_7", BLIND2["sup_fan_in"]), ("demo_48", BLIND2["uns_fan_in"])]  # DB 대신 가짜 facts
BLIND_PRIVATE = ("v4_blind_key_", "v4_blind_diag_", "v4_blind_responses_")


@pytest.fixture(scope="module")
def cases() -> list[Any]:
    return build_cases(DEMO)


def test_nineteen_cases_by_source(cases: list[Any]) -> None:
    assert len(cases) == 19 and len({c.case_id for c in cases}) == 19
    assert Counter(c.kind for c in cases) == {"v4": 18, "v2": 1}
    assert Counter(c.source for c in cases) == {"228": 8, "blind2": 8, "demo": 2, "injection": 1}
    assert {c.case_id for c in cases if c.source == "demo"} == {"demo_7", "demo_48"}
    blind2 = {c.case_id for c in cases if c.source == "blind2"}
    assert not any(cid.startswith("blind2:reg_") for cid in blind2)  # 회귀 3 은 228 과 같은 사건이라 뺌
    assert next(c for c in cases if c.kind == "v2").case_id == f"injection:{V2_CASE}"


def test_v4_narrative_matches_verify_request_shape(cases: list[Any]) -> None:
    for c in cases:
        assert [s.section for s in c.narrative] == list(SectionV2), c.case_id
        assert all(isinstance(s, RevisedNarrativeSection) for s in c.narrative)
        keys = set(fact_keys(c.facts))
        assert {k for s in c.narrative for k in s.cites} <= keys, c.case_id


def test_v4_cases_pass_code_checks_like_verify(cases: list[Any]) -> None:
    """실제 verify 처럼 코드 검사 5종부터 — v4 는 실패 0 이어야 평가자까지 감."""
    for c in cases:
        if c.kind != "v4":
            continue
        scope = sorted({i for ids in fact_keys(c.facts).values() for i in ids})
        failed = [k for k in verification.run_code_checks(c.facts, c.narrative, scope) if not k.match]
        assert failed == [], c.case_id


def test_dry_run_makes_no_llm_call_and_is_deterministic(
    cases: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise AssertionError("dry-run 이 LLM 을 부름")

    monkeypatch.setattr(HttpLlmClient, "complete_json", boom)
    first, second = dry_run(cases, "judge_v3"), dry_run(cases, "judge_v3")
    assert first == second and len(first) == 19
    assert all(
        len(r["user_sha256"]) == 64 and r["code_check_failures"] == 0 for r in first if r["kind"] == "v4"
    )
    sha = {r["case_id"]: r["user_sha256"] for r in first}
    assert (
        sha["demo_7"] == sha["blind2:sup_fan_in"] and sha["demo_48"] == sha["blind2:uns_fan_in"]
    )  # 같은 facts → 같은 입력
    assert sha["228:fan_in"] == sha["228:fan_in_b"]  # 마스킹 뒤 두 픽스처 입력이 같음(기록)
    assert len(set(sha.values())) == 16


def test_blind_private_files_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open, real_read = builtins.open, Path.read_text

    def spy_open(file: Any, *a: Any, **kw: Any) -> Any:
        opened.append(str(file))
        return real_open(file, *a, **kw)

    def spy_read(self: Path, *a: Any, **kw: Any) -> str:
        opened.append(str(self))
        return real_read(self, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", spy_read)
    dry_run(build_cases(DEMO), "judge_v3")
    assert opened and not [p for p in opened if any(m in p for m in BLIND_PRIVATE)]


def _rec(
    case_id: str, kind: str, run: int, scores: dict[str, int], comments: dict[str, str] | None = None
) -> dict:
    status = "PASSED" if min(scores.values()) >= 4 else "LLM_FAILED"
    return {"case_id": case_id, "kind": kind, "run": run, "status": status, "scores": scores,
            "comments": comments or {}, "tokens_in": 100, "tokens_out": 10, "wall_clock_ms": 5}  # fmt: skip


OK = {"FIVE_W_ONE_H_COMPLETE": 5, "TYPOLOGY_CONSISTENT": 5, "NO_UNSUPPORTED_CLAIM": 4, "NO_SPECULATION": 5,
      "NO_INSTRUCTION_TEXT": 5}  # fmt: skip


def test_tally_counts_and_failed_items_with_comments() -> None:
    bad = OK | {"TYPOLOGY_CONSISTENT": 3}
    records = [_rec("a", "v4", r, OK) for r in (1, 2, 3)]
    records += [_rec("b", "v4", 1, OK), _rec("b", "v4", 2, bad, {"TYPOLOGY_CONSISTENT": "경로 근거 부족"}),
                _rec("b", "v4", 3, OK)]  # fmt: skip
    s = tally(records)
    assert (s["a"]["passed"], s["a"]["failed"]) == (3, 0) and (s["b"]["passed"], s["b"]["failed"]) == (2, 1)
    assert s["b"]["checks"]["TYPOLOGY_CONSISTENT"] == {"median": 5, "min": 3}
    assert s["b"]["failed_items"] == [
        {"run": 2, "check": "TYPOLOGY_CONSISTENT", "score": 3, "comment": "경로 근거 부족"}
    ]
    assert meets_criterion(s, n=3) is False
    table = render_table(s)
    assert "b" in table and "2/3" in table


def test_criterion_needs_every_v4_all_runs_and_ignores_v2() -> None:
    bad = OK | {"NO_SPECULATION": 2}
    records = [_rec(c, "v4", r, OK) for c in ("a", "b") for r in (1, 2, 3)]
    records += [_rec("injection:23", "v2", r, bad) for r in (1, 2, 3)]
    assert meets_criterion(tally(records), n=3) is True  # v2 대조는 판정 밖
    assert meets_criterion(tally(records[:-4]), n=3) is False  # b 가 2회뿐 — n 회 모두가 아님
