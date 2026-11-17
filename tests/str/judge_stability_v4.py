"""SCRUM-254 ★L-1 — v4 초안 검증 평가자 측정 입력 (docs/str/08 "평가자 흔들림 — v4 초안"). LLM 0.

사건 19 = 228 사건 8(real_names → v4) + 재블라인드 새 8(사전 등록 파일 facts 만 → v4) + 시연 후보 경보 2(v4, facts 는
호출하는 쪽이 줌 — `demo_alerts`) + 오류 주입 23(v2 녹화 초안, 대조·참고). 재블라인드 키·진단·응답은 읽지 않음.
본문은 실제 verify 요청처럼 `RevisedNarrativeSection` 으로 왕복. dry-run 은 judge user 문자열 sha256 과
코드 검사 실패 수만(호출 0).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from aml_ai.shared.schemas.str import Facts, NarrativeSection, RevisedNarrativeSection
from aml_ai.str.domain import masking, verification
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.judge import render_judge_user
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.judge_input_support import facts_for_case, original_narrative_for_case
from tests.str.v4_blind2_cases import case_facts, load_cases
from tests.str.v4_blind_support import blind_cases
from tests.str.v4_real_names import real_names

V2_CASE = 23  # 오류 주입 23 — SCRUM-254 본문 원래 사례(v2 녹화 초안, facts_cycle_nopaths)


@dataclass(frozen=True)
class V4Case:
    case_id: str
    kind: str  # "v4" | "v2"
    source: str  # "228" | "blind2" | "demo" | "injection"
    facts: Facts
    narrative: list[RevisedNarrativeSection]


def _as_verify_request(sections: list[NarrativeSection]) -> list[RevisedNarrativeSection]:
    """백엔드가 받은 초안을 그대로 검증 요청에 싣는 왕복(JSON)."""
    return [RevisedNarrativeSection.model_validate(s.model_dump(mode="json")) for s in sections]


def v4_narrative(facts: Facts) -> list[RevisedNarrativeSection]:
    """실제 생성 경로와 같게 — 마스킹본으로 조립(LLM 0) → 근거 붙임."""
    return _as_verify_request(
        attach_evidence(build_v4(masking.mask_for_llm(facts), load_display_labels()), facts)
    )


def build_cases(demo: list[tuple[str, Facts]]) -> list[V4Case]:
    """사건 19(시연 후보 수만큼) — 순서 고정."""
    out = [
        V4Case(f"228:{c.case_id}", "v4", "228", f, v4_narrative(f))
        for c in blind_cases()
        for f in [real_names(c.facts)]
    ]
    doc = load_cases()
    facts = case_facts(doc)
    for c in doc["cases"]:
        if c["role"] == "judged":  # 회귀 3 은 228 과 같은 사건이라 뺌
            f = facts[c["case_id"]]
            out.append(V4Case(f"blind2:{c['case_id']}", "v4", "blind2", f, v4_narrative(f)))
    out += [V4Case(name, "v4", "demo", f, v4_narrative(f)) for name, f in demo]
    v2 = _as_verify_request(original_narrative_for_case(V2_CASE))
    out.append(V4Case(f"injection:{V2_CASE}", "v2", "injection", facts_for_case(V2_CASE), v2))
    return out


def verify_inputs(case: V4Case) -> tuple[dict[str, Any], list[RevisedNarrativeSection], list[str]]:
    """verify_service._decide 와 같은 judge 입력 — 마스킹 facts · 본문 · fact_keys."""
    return masking.mask_for_llm(case.facts), case.narrative, list(fact_keys(case.facts).keys())


def code_check_failures(case: V4Case) -> int:
    scope = sorted({i for ids in fact_keys(case.facts).values() for i in ids})
    return sum(not c.match for c in verification.run_code_checks(case.facts, case.narrative, scope))


def dry_run(cases: list[V4Case], prompt_name: str) -> list[dict[str, Any]]:
    """호출 0 — 사건마다 judge user 문자열 sha256 · 코드 검사 실패 수(같은 입력 → 같은 값)."""
    _, template = load_prompt(prompt_name)
    out = []
    for c in cases:
        facts_masked, narrative, keys = verify_inputs(c)
        user = render_judge_user(template, facts_masked=facts_masked, narrative=narrative, fact_keys=keys,
                                 request_sections=[s.section.value for s in narrative])  # fmt: skip
        out.append({"case_id": c.case_id, "kind": c.kind, "source": c.source,
                    "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
                    "code_check_failures": code_check_failures(c)})  # fmt: skip
    return out
