"""SCRUM-268 — judge_v4 사전 기준 1·2 사례 (docs/str/08 "judge_v4 사전 기준 측정", 09 SCRUM-268). LLM 0.

기준 1: 평가자마다 자기 기준 본문(judge_v3 = v2 `facts_fan_in` 녹화 초안, judge_v4 = v4 demo_7)에 주입 7·8·10·11,
11 은 평가자 단독 호출. 참고(판정 밖) judge_v3 23 · judge_v4 12·23. 기준 2: 254 v4 18건 판정 문장 text 만 블록과
반대로 — 반대 문장은 반대 판정이 나오는 facts 로 `support_sentence` 를 다시 불러 만듦(문장을 새로 쓰지 않음).
대조(추가 검토 2차): 같은 18건을 뒤집지 않고 그대로 — 원래 초안이 이미 NO_UNSUPPORTED 를 낮게 받는지 가림.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any

from aml_ai.shared.schemas.str import Facts, RevisedNarrativeSection
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import JUDGE_PROMPT, JUDGE_PROMPT_V4
from aml_ai.str.domain.constants_v4 import MIN_DISTINCT_RECEIVERS, MIN_DISTINCT_SENDERS, MIN_INTERMEDIATES
from aml_ai.str.domain.typology_support import Support, typology_support
from aml_ai.str.domain.typology_support_text import support_sentence
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.judge import render_judge_user
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from tests.str.injection_live_support import EXPECTS, INJECTIONS, base_facts, base_narrative
from tests.str.judge_stability_v4 import V2_CASE, V4Case, build_cases, code_check_failures, verify_inputs

C1_INJECTIONS = (7, 8, 10, 11)  # 09 SCRUM-268 기준 1 — 평가자 오류 주입(23 은 오류 사례 아님)
JUDGE_ONLY = frozenset({11})  # verify 경로면 OPINION_PRESENT 로 CODE_FAILED — 평가자 단독 호출
BASE_V4_CASE = "demo_7"  # v4 기준 본문(시연 후보 — 뒷받침됨)
FLIP_PREFIX, CONTROL_PREFIX = "c2:", "c2ctl:"  # 기준 2 뒤집기 · 대조(같은 254 사건 id 로 짝)
# FAN 유형 → 판정을 바꿀 반대 방향 칸·임계값
_FLOW = {"FAN_IN": ("outbound", MIN_DISTINCT_SENDERS), "FAN_OUT": ("inbound", MIN_DISTINCT_RECEIVERS)}


@dataclass(frozen=True)
class CriteriaCase:
    case_id: str  # c1:<평가자>:<base|inject_k|ref_k> · c2:<254 v4 사건>
    criterion: int
    prompt: str
    role: str  # base | inject | reference | flip
    facts: Facts
    narrative: list[RevisedNarrativeSection] = field(compare=False)
    target: str | None = None  # 기준 1 주입의 목표 항목(EXPECTS)
    judge_only: bool = False

    @property
    def kind(self) -> str:  # 254 run_iteration 기록 칸
        return f"c{self.criterion}"


def _c1(prompt: str, name: str, role: str, facts: Facts, narrative: list[RevisedNarrativeSection],
        k: int | None = None) -> CriteriaCase:  # fmt: skip
    target = EXPECTS[k]["target"] if role == "inject" and k is not None else None
    return CriteriaCase(f"c1:{prompt}:{name}", 1, prompt, role, facts, narrative, target, k in JUDGE_ONLY)


def c1_cases(v4_base: V4Case, ref_23: V4Case) -> list[CriteriaCase]:
    v2_facts, v2_narr = base_facts(), base_narrative()
    out: list[CriteriaCase] = []
    for prompt, facts, narr in (
        (JUDGE_PROMPT, v2_facts, v2_narr),
        (JUDGE_PROMPT_V4, v4_base.facts, v4_base.narrative),
    ):
        out.append(_c1(prompt, "base", "base", facts, narr))
        out += [
            _c1(prompt, f"inject_{k}", "inject", facts, INJECTIONS[k](list(narr)), k) for k in C1_INJECTIONS
        ]
        if prompt == JUDGE_PROMPT_V4:
            out.append(
                _c1(prompt, "ref_12", "reference", v2_facts, v2_narr)
            )  # judge_v3 쪽은 base 와 같은 본문
        out.append(_c1(prompt, f"ref_{V2_CASE}", "reference", ref_23.facts, ref_23.narrative))
    return out


def _opposite_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """판정이 반대로 나오는 마스킹본 — 문장의 대상("위 입금"·"위 거래")은 그대로 두도록 셀 칸만 바꿈."""
    f = copy.deepcopy(facts)
    typology, supported = f["typology"], typology_support(facts) is Support.SUPPORTED
    if typology in _FLOW:
        other, threshold = _FLOW[typology]
        f["internal"]["count"] = 0
        f["counterparties"]["count"] = 0 if supported else threshold + f[other]["count"]
    elif supported:
        f.pop("paths", None)
    else:
        f["paths"] = {"kind": typology, "count": MIN_INTERMEDIATES, "max_hops": 2, "max_accounts": 3}
    assert (typology_support(f) is Support.SUPPORTED) is not supported
    return f


def flip_narrative(case: V4Case) -> list[RevisedNarrativeSection]:
    """GROUNDS 판정 문장 text 만 반대로 — cites·evidence_ids·다른 문장 그대로."""
    labels = load_display_labels()
    fm = masking.mask_for_llm(case.facts)
    original, flipped = support_sentence(fm, labels), support_sentence(_opposite_facts(fm), labels)
    assert original is not None and flipped is not None, case.case_id
    out = []
    for s in case.narrative:
        if s.section.value == "GROUNDS":
            assert s.text.count(original.text) == 1, case.case_id
            s = s.model_copy(update={"text": s.text.replace(original.text, flipped.text)})
        out.append(s)
    return out


def c2_cases(v4_cases: list[V4Case]) -> list[CriteriaCase]:
    """사건마다 뒤집기 + 대조(뒤집지 않은 원래 초안, 추가 검토 2차) — 같은 실행에서 짝으로."""
    out: list[CriteriaCase] = []
    for c in v4_cases:
        if c.kind != "v4":
            continue
        out.append(
            CriteriaCase(f"{FLIP_PREFIX}{c.case_id}", 2, JUDGE_PROMPT_V4, "flip", c.facts, flip_narrative(c))
        )
        out.append(
            CriteriaCase(f"{CONTROL_PREFIX}{c.case_id}", 2, JUDGE_PROMPT_V4, "control", c.facts, c.narrative)
        )
    return out


def build_criteria_cases(demo: list[tuple[str, Facts]]) -> list[CriteriaCase]:
    """기준 1(judge_v3 6 · judge_v4 7) + 기준 2(뒤집기 18 · 대조 18) — 순서 고정."""
    v4 = build_cases(demo)
    by_id = {c.case_id: c for c in v4}
    return c1_cases(by_id[BASE_V4_CASE], by_id[f"injection:{V2_CASE}"]) + c2_cases(v4)


def dry_run(cases: list[CriteriaCase]) -> list[dict[str, Any]]:
    """호출 0 — 사례마다 평가자 user sha256 · 코드 검사 실패 수(같은 입력 → 같은 값)."""
    out = []
    for c in cases:
        _, template = load_prompt(c.prompt)
        facts_masked, narrative, keys = verify_inputs(c)  # type: ignore[arg-type]
        user = render_judge_user(template, facts_masked=facts_masked, narrative=narrative, fact_keys=keys,
                                 request_sections=[s.section.value for s in narrative])  # fmt: skip
        out.append({"case_id": c.case_id, "criterion": c.criterion, "prompt": c.prompt, "role": c.role,
                    "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
                    "code_check_failures": code_check_failures(c)})  # type: ignore[arg-type]  # fmt: skip
    return out
