"""SCRUM-61 — verify_service 의 narrative_refs 재계산. docs/str/06 "수정본의 cites".

- 평가자 sections 의 cites 중 `fact_keys` **밖** 키는 cites 에서 빠짐
- `customer.*`·`subject` 처럼 거래 ID 가 없는 키는 cites 에 남고 evidence_ids 는 빔
- narrative_refs 섹션 순서 = 요청 섹션 순서
- 빈 cites → 빈 evidence_ids
- CODE_FAILED·VERIFY_UNAVAILABLE → narrative_refs=None
- LLM_FAILED → 값 있음
- 버린 키는 `log.warning("judge_cites_dropped", extra={section, count})`

구현 전에 쓴 테스트 — develop 에서는 narrative_refs=None 하드코드라 전부 실패.
"""

from __future__ import annotations

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import (
    JudgeMeta,
    LlmCheck,
    LlmCheckName,
    NarrativeRefLlm,
    SectionV1,
    VerifyStatus,
)
from aml_ai.str.infrastructure.judge import JudgeResult
from tests.str.verify_service_support import (
    FakeJudge,
    LogCall,
    build_service,
    facts_fan_in,
    judge_pass_checks,
    narrative_ok,
    stored_draft,
    verify_request,
)


def _pass_checks() -> list[LlmCheck]:
    return [LlmCheck(check=n, comment="ok", score=5) for n in LlmCheckName]


def _sections_from_v1(cites_map: dict[SectionV1, list[str]] | None = None) -> list[NarrativeRefLlm]:
    cites_map = cites_map or {}
    return [NarrativeRefLlm(section=s, cites=cites_map.get(s, [])) for s in SectionV1]


def _judge_result(sections: list[NarrativeRefLlm], *, all_pass: bool = True) -> JudgeResult:
    scores = [5, 5, 5, 5, 5] if all_pass else [5, 5, 3, 5, 5]  # NO_UNSUPPORTED_CLAIM 3점
    checks = [LlmCheck(check=n, comment="ok", score=sc) for n, sc in zip(LlmCheckName, scores, strict=True)]
    meta = JudgeMeta(
        llm_model="stub-judge",
        prompt_version="judge_v2",
        tokens_in=1800,
        tokens_out=600,
        latency_ms=8000,
        attempts=1,
    )
    return JudgeResult(checks=checks, meta=meta, sections=sections)


def test_narrative_refs_passed_in_request_order() -> None:
    """★ PASSED — narrative_refs 섹션 순서 = 요청 섹션 순서."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1({SectionV1.SUMMARY: ["period", "inbound.count"]})
    judge = FakeJudge(result=_judge_result(sections, all_pass=True))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.PASSED
    assert resp.narrative_refs is not None
    assert [r.section for r in resp.narrative_refs] == [s.section for s in narrative]


def test_narrative_refs_filters_keys_outside_fact_keys() -> None:
    """★ 목록 밖 cites 는 narrative_refs 에서 빠짐. 안쪽 cites 는 남음."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1({SectionV1.SUMMARY: ["period", "no_such_fact_key", "inbound.count"]})
    judge = FakeJudge(result=_judge_result(sections))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    summary_ref = next(r for r in resp.narrative_refs if r.section is SectionV1.SUMMARY)
    assert "period" in summary_ref.cites
    assert "inbound.count" in summary_ref.cites
    assert "no_such_fact_key" not in summary_ref.cites


def test_narrative_refs_subject_customer_no_evidence_ids() -> None:
    """`subject`·`customer.*` 같은 거래 ID 없는 키는 cites 에 남고 evidence_ids 는 빔."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1({SectionV1.WHO: ["subject", "customer.industry", "customer.onboarded_at"]})
    judge = FakeJudge(result=_judge_result(sections))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    who_ref = next(r for r in resp.narrative_refs if r.section is SectionV1.WHO)
    assert set(who_ref.cites) >= {"subject", "customer.industry", "customer.onboarded_at"}
    assert who_ref.evidence_ids == []


def test_narrative_refs_empty_cites_empty_evidence_ids() -> None:
    """빈 cites → 빈 evidence_ids (섹션은 존재)."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1()  # 전부 빈 cites
    judge = FakeJudge(result=_judge_result(sections))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert len(resp.narrative_refs) == len(narrative)
    for r in resp.narrative_refs:
        assert r.cites == []
        assert r.evidence_ids == []


def test_narrative_refs_llm_failed_has_value() -> None:
    """★ LLM_FAILED 도 narrative_refs 값 있음(평가자는 돌았음)."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1({SectionV1.SUMMARY: ["period"]})
    judge = FakeJudge(result=_judge_result(sections, all_pass=False))  # 점수 3점 섞임
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.LLM_FAILED
    assert resp.narrative_refs is not None
    assert len(resp.narrative_refs) == len(narrative)


def test_narrative_refs_code_failed_is_null() -> None:
    """CODE_FAILED → narrative_refs=None (judge 안 부름)."""
    narrative = narrative_ok()
    narrative[0] = narrative[0].model_copy(update={"evidence_ids": [999]})  # OUT_OF_SCOPE 유발
    draft = stored_draft(facts_fan_in(), narrative_ok())
    judge = FakeJudge(checks=judge_pass_checks())
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.CODE_FAILED
    assert resp.narrative_refs is None
    assert judge.calls == 0


def test_narrative_refs_verify_unavailable_is_null() -> None:
    """VERIFY_UNAVAILABLE → narrative_refs=None."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(exc=LlmUnavailable("llm unavailable"))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.narrative_refs is None


def test_narrative_refs_dropped_cites_logged(judge_log: list[LogCall]) -> None:
    """★ 목록 밖 cites 가 있으면 `judge_cites_dropped` 로그 한 줄(섹션·개수만)."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1({SectionV1.SUMMARY: ["period", "bad_key_1", "bad_key_2"]})
    judge = FakeJudge(result=_judge_result(sections))
    svc, _ = build_service(judge=judge, draft=draft)

    svc.verify(verify_request(narrative))

    dropped = [c for c in judge_log if c.msg == "judge_cites_dropped"]
    assert dropped, f"로그에 judge_cites_dropped 없음: {[c.msg for c in judge_log]}"
    entry = dropped[0]
    assert entry.extra.get("count") == 2
    # 본문·키 이름 안 찍힘
    assert all("bad_key" not in str(v) for v in entry.extra.values())


def test_narrative_refs_fact_keys_passed_to_judge() -> None:
    """Judge.run 에 `fact_keys` 리스트가 넘어감 — 생성기와 같은 모양으로 user 조립."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    sections = _sections_from_v1({SectionV1.SUMMARY: ["period"]})
    judge = FakeJudge(result=_judge_result(sections))
    svc, _ = build_service(judge=judge, draft=draft)

    svc.verify(verify_request(narrative))

    assert judge.received_fact_keys is not None
    assert isinstance(judge.received_fact_keys, list)
    assert "period" in judge.received_fact_keys  # period 는 늘 포함
