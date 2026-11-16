"""SCRUM-131 (4/n) — 안정화 측정 집계 (docs/str/07 "안정화 측정"). LLM·DB 0, 가짜 기록."""

from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from tests.str.stability_support import (
    Call,
    RunRecord,
    estimate_calls,
    preflight_problems,
    render_summary_md,
    section_digest,
    summarize,
)

TEXTS = {
    "SUBJECT": "보고 대상자는 개인사업자임.",
    "METHOD": "입금 합계는 42,750.50 미국 달러(USD)임. 입금은 3건임.",
}
SECRET_BITS = ("42,750.50", "42750.50", "개인사업자", "입금 합계")


def _rec(case: str = "fan_in", run: int = 1, **kw) -> RunRecord:  # type: ignore[no-untyped-def]
    hashes, chars, numbers = section_digest(TEXTS)
    base = dict(
        case_id=case, run_no=run, retrieval_status="ok", section_hashes=hashes, section_chars=chars,
        number_set_hash=numbers, code_failures_first=[], code_failures_final=[], rewrite_applied=False,
        rewrite_skipped_reason="not_triggered", judge_scores={"NO_SPECULATION": 5, "TYPOLOGY_CONSISTENT": 4},
        final_status="PASSED",
        calls=[Call("generate", 6000, 600, 7000), Call("critique", 3000, 300, 4000), Call("judge", 9000, 900, 8000)],
    )  # fmt: skip
    base.update(kw)
    return RunRecord(**base)


def test_digest_keeps_no_body_or_amount() -> None:
    hashes, chars, numbers = section_digest(TEXTS)
    assert set(hashes) == set(chars) == set(TEXTS)
    assert chars["SUBJECT"] == len(TEXTS["SUBJECT"])
    dumped = json.dumps([hashes, chars, numbers], ensure_ascii=False)
    assert not any(bit in dumped for bit in SECRET_BITS)
    assert section_digest(TEXTS) == (hashes, chars, numbers)  # 결정적


def test_number_hash_changes_only_when_numbers_change() -> None:
    _, _, same = section_digest({**TEXTS, "SUBJECT": "보고 대상자는 법인임."})
    _, _, changed = section_digest({**TEXTS, "METHOD": TEXTS["METHOD"].replace("3건", "4건")})
    base = section_digest(TEXTS)[2]
    assert same == base and changed != base


def test_preflight_stops_on_each_problem() -> None:
    ok = dict(rag_enabled=True, corpus_chunks=120, api_key_set=True, embedding_model_set=True)
    assert preflight_problems(**ok) == []
    for key, bad in (
        ("rag_enabled", False),
        ("corpus_chunks", 0),
        ("api_key_set", False),
        ("embedding_model_set", False),
    ):
        assert len(preflight_problems(**{**ok, key: bad})) == 1, key
    assert (
        len(
            preflight_problems(
                rag_enabled=False, corpus_chunks=0, api_key_set=False, embedding_model_set=False
            )
        )
        == 4
    )


def test_estimate_calls_for_five_by_five() -> None:
    est = estimate_calls(cases=5, n=5, judge_votes=3)
    assert est["generate"] == est["critique"] == est["embedding"] == 25
    assert est["rewrite_max"] == 25 and est["judge_max"] == 75
    assert est["total_min"] == 75 and est["total_max"] == 175


def test_retrieval_not_ok_runs_are_shown_and_split() -> None:
    recs = [_rec(run=1), _rec(run=2, retrieval_status="empty"), _rec(run=3, retrieval_status="failed")]
    s = summarize(recs, daily_token_budget=2_000_000)
    assert s["retrieval"]["ok"] == 1 and s["retrieval"]["total"] == 3
    assert [(r["run_no"], r["retrieval_status"]) for r in s["retrieval"]["not_ok"]] == [
        (2, "empty"),
        (3, "failed"),
    ]
    assert s["retrieval_ok_only"]["pass_rates"]["passed"] == 1.0
    assert "검색 ok 1/3" in render_summary_md(s)


def test_consistency_detects_body_number_and_status_changes() -> None:
    other_hashes = {**_rec().section_hashes, "SUBJECT": "ffffffffffffffff"}
    recs = [_rec(run=1), _rec(run=2, section_hashes=other_hashes), _rec(run=3)]
    c = summarize(recs, daily_token_budget=1)["all"]["consistency"]["fan_in"]
    assert c["distinct_per_section"] == {"SUBJECT": 2, "METHOD": 1}
    assert c["numbers_same"] and c["status_same"]
    recs2 = [_rec(run=1), _rec(run=2, number_set_hash="0000000000000000", final_status="LLM_FAILED")]
    c2 = summarize(recs2, daily_token_budget=1)["all"]["consistency"]["fan_in"]
    assert not c2["numbers_same"] and not c2["status_same"]


def test_pass_rates_and_judge_distribution() -> None:
    recs = [
        _rec(run=1),
        _rec(run=2, code_failures_first=["COUNT_MATCH:MISMATCH"], rewrite_applied=True, rewrite_skipped_reason=None),
        _rec(run=3, code_failures_first=["DATE_MATCH:UNPARSED"], code_failures_final=["DATE_MATCH:UNPARSED"],
             judge_scores=None, final_status="CODE_FAILED"),
        _rec(run=4, judge_scores={"NO_SPECULATION": 3, "TYPOLOGY_CONSISTENT": 5}, final_status="LLM_FAILED"),
    ]  # fmt: skip
    a = summarize(recs, daily_token_budget=1)["all"]
    assert a["pass_rates"] == {"code_first": 0.5, "code_final": 0.75, "passed": 0.5, "rewrite_applied": 0.25}
    assert a["judge_scores"]["NO_SPECULATION"] == {"min": 3, "median": 5.0, "max": 5}
    assert a["judge_scores"]["TYPOLOGY_CONSISTENT"] == {"min": 4, "median": 4.0, "max": 5}


def test_cost_latency_and_daily_capacity() -> None:
    rewrite = [*_rec().calls, Call("rewrite", 7000, 700, 9000)]
    recs = [_rec(run=1), _rec(run=2, calls=rewrite)]
    a = summarize(recs, daily_token_budget=2_000_000)["all"]
    assert a["cost"]["generate"] == {"tokens_mean": 6600.0, "tokens_max": 6600}
    assert a["cost"]["rewrite"] == {"tokens_mean": 7700.0, "tokens_max": 7700}
    assert a["cost"]["draft_tokens_mean"] == pytest.approx((6600 + 3300) + 7700 / 2)
    assert a["cost"]["verify_tokens_mean"] == 9900.0
    assert a["daily_capacity"] == 2_000_000 // int(a["cost"]["draft_tokens_mean"] + 9900)
    assert a["latency"]["judge"] == {"p50": 8000, "p95": 8000, "max": 8000}


def test_empty_ok_only_has_same_shape_and_zero_rates() -> None:
    s = summarize([_rec(retrieval_status="failed")], daily_token_budget=1)
    assert set(s["retrieval_ok_only"]) == set(s["all"])
    assert (
        s["retrieval_ok_only"]["pass_rates"]["passed"] == 0.0
        and s["retrieval_ok_only"]["daily_capacity"] == 0
    )


def test_summary_and_md_carry_no_body() -> None:
    s = summarize([_rec(run=1), _rec(run=2)], daily_token_budget=2_000_000)
    blob = (
        json.dumps(s, ensure_ascii=False)
        + render_summary_md(s)
        + json.dumps(asdict(_rec()), ensure_ascii=False)
    )
    assert not any(bit in blob for bit in SECRET_BITS)


def test_record_is_frozen() -> None:
    with pytest.raises(AttributeError):
        _rec().run_no = 2  # type: ignore[misc]
    assert replace(_rec(), run_no=2).run_no == 2


def test_rewrite_call_counted_when_attempted_even_if_not_applied() -> None:
    """고쳐 쓰기 호출을 보냈으면(attempted) 적용 안 됐어도 토큰을 셈 — draft_rewrite 도 합산함."""
    from types import SimpleNamespace

    from tests.str.stability_phases import rewrite_calls

    first = SimpleNamespace(tokens_in=6000, tokens_out=600, latency_ms=7000)
    merged = SimpleNamespace(tokens_in=13000, tokens_out=1300, latency_ms=16000)
    meta = SimpleNamespace(
        attempted=True,
        applied=False,
        critique_tokens_in=3000,
        critique_tokens_out=300,
        critique_latency_ms=4000,
    )
    calls = rewrite_calls(meta, merged, first)
    assert [c.kind for c in calls] == ["critique", "rewrite"]
    assert (calls[1].tokens_in, calls[1].tokens_out, calls[1].latency_ms) == (7000, 700, 9000)
    skipped = SimpleNamespace(**{**vars(meta), "attempted": False})
    assert [c.kind for c in rewrite_calls(skipped, first, first)] == ["critique"]


def test_measure_stops_when_llm_is_mocked() -> None:
    from tests.str.stability_support import measure_problems

    assert measure_problems(ai_llm_mock=False) == []
    assert len(measure_problems(ai_llm_mock=True)) == 1


def test_draft_failure_keeps_only_exception_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from tests.str import stability_live

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("본문 42,750.50 비밀")

    monkeypatch.setattr(stability_live, "retrieve", boom)
    rec = stability_live.run_once(
        "fan_in", 1, settings=SimpleNamespace(draft_budget_s=1.0), llm=None, embedder=None, session=None
    )
    assert rec.final_status == "DRAFT_FAILED" and rec.error == "RuntimeError"
    assert "42,750.50" not in json.dumps(asdict(rec), ensure_ascii=False)
