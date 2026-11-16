"""SCRUM-131 (3/n) — v2 자유 문장 반례 측정 도우미 (docs/str/08 "v2 반례 측정"). LLM·DB 0.

SCRUM-228 추가 검토 반례 문장을 v2 녹화 1건(`recorded/narrative_v2/a976ae216c7fb1bb.json`, fan_in 본문)의
섹션 끝에 하나씩 끼워 06 검사기(`run_code_checks`)에 돌린다. 검사기는 고치지 않는다 — 현재 동작 기록.
분류는 **끼우기 전 같은 facts 결과와 비교한 새 실패**로만:
- `caught`: 새 MISMATCH·UNPARSED 가 생김
- `silent`: 숫자가 있는 반례(`has_number`)인데 새 실패 없음 — 06 한계, v4 는 문장 모양으로 막음
- `not_target`: 숫자 없는 반례 — 코드 검사가 볼 게 없음, v2 는 평가자 기준(`judge`)이 맡음(미측정)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from aml_ai.shared.schemas.str import Facts, NarrativeSection, SectionV2

Category = Literal["caught", "silent", "not_target"]
Guard = Literal["lint", "closed", "requires", "claims"]
# v4 에서 막는 장치: 카탈로그 린트(문장 자체가 걸림) · closed(자유 문장 경로 없음 — 카탈로그에 이 문장 없음, 린트는 못 잡음)
# · requires 전제 · 주장 표
FactsSpec = Literal[
    "fixture:fan_in",  # 상대 3·입금 3건 USD 42,750.50·출금 0·하루(00:14~22:51)
    "fixture:multi_currency",  # 상대 4(자행 1)·EUR+USD·9/2~9/4
    "fixture:cycle_nopaths",  # 유형 CYCLE·경로 없음
    "build:internal_only",  # facts_for(0, 0, 1, "none", None) — 내부 거래만
    "build:first_only",  # facts_for(1, 1, 0, "none", "FAN_IN", obs="first_only") — baseline 일부 null
    "build:internal_small",  # facts_for(1, 1, 1, "none", "FAN_IN", internal="small") — 내부 거래가 외부보다 작은 금액
]


@dataclass(frozen=True)
class Counterexample:
    cid: str
    group: str  # 숫자 우회 · 플래그 변형 · 추측 · 전제 위반 · 부재·범위 과장
    section: SectionV2  # 끼울 섹션(끝에 덧붙임)
    sentence: str
    facts: FactsSpec  # 이 문장이 거짓이 되는 facts
    has_number: bool  # 수량·금액·날짜 주장이 있음(아라비아 숫자가 아니어도)
    judge: str  # v2 2차 방어 — judge_v2 기준 이름(NO_SPECULATION·NO_UNSUPPORTED_CLAIM)
    guard: Guard
    guard_note: str  # v4 에서 막는 장치 한 줄


_U, _S = "NO_UNSUPPORTED_CLAIM", "NO_SPECULATION"
COUNTEREXAMPLES: list[Counterexample] = [
    Counterexample("N1", "숫자 우회", SectionV2.PLACE, "상대 계좌는 三 곳임.", "fixture:multi_currency",
                   True, _U, "lint", "카탈로그 린트 digit — 숫자는 슬롯만"),
    Counterexample("N2", "숫자 우회", SectionV2.METHOD, "위 입금 합계는 一億 원임.", "fixture:fan_in",
                   True, _U, "lint", "카탈로그 린트 digit — 금액은 슬롯만"),
    Counterexample("N3", "숫자 우회", SectionV2.METHOD, "출금은 둘임.", "fixture:fan_in",
                   True, _U, "closed", "자유 문장 없음 — 건수는 슬롯만(린트 미검출)"),
    Counterexample("N4", "숫자 우회", SectionV2.METHOD, "건별 금액은 최대 삼점오 달러임.", "fixture:fan_in",
                   True, _U, "closed", "자유 문장 없음 — 금액은 슬롯만(린트 미검출)"),
    Counterexample("N5", "숫자 우회", SectionV2.DATE, "첫 입금은 구월 구일에 이루어짐.", "fixture:fan_in",
                   True, _U, "closed", "자유 문장 없음 — 날짜는 슬롯만(린트 미검출)"),
    Counterexample("F1", "플래그 변형", SectionV2.GROUNDS, "위 입금은 전부 타행 계좌에서 당일 들어옴.",
                   "fixture:multi_currency", False, _U, "lint", "카탈로그 린트 flag_topic — 플래그는 조건 항목만"),
    Counterexample("F2", "플래그 변형", SectionV2.METHOD, "거래는 출금으로만 이루어짐.", "fixture:fan_in",
                   False, _U, "closed", "자유 문장 없음 — 배타 플래그는 조건 항목만(린트 미검출)"),
    Counterexample("F3", "플래그 변형", SectionV2.PLACE, "상대 계좌는 모두 다른 금융기관 소속임.",
                   "fixture:multi_currency", False, _U, "closed", "자유 문장 없음 — 자행·타행은 슬롯만(린트 미검출)"),
    Counterexample("F4", "플래그 변형", SectionV2.DATE, "입금은 모두 같은 일시에 이루어짐.", "fixture:fan_in",
                   False, _U, "closed", "자유 문장 없음 — 같은 날은 single_day 조건 항목만(린트 미검출)"),
    Counterexample("S1", "추측", SectionV2.OPINION, "거래가 급격히 증가하였으며 범죄 수익을 감출 목적의 거래임.",
                   "fixture:fan_in", False, _S, "lint", "카탈로그 린트 forbidden_word"),
    Counterexample("P1", "전제 위반", SectionV2.GROUNDS, "자금이 출발 계좌로 돌아온 것으로 보임.",
                   "fixture:cycle_nopaths", False, _U, "requires", "requires cycle_verified — \"돌아온\"은 경로 확인 CYCLE 만"),
    Counterexample("P2", "전제 위반", SectionV2.METHOD, "위 입금은 상대 계좌에서 들어옴.", "build:internal_only",
                   False, _U, "requires", "requires has_inbound — \"위 입금\"은 입금 있을 때만"),
    Counterexample("A1", "부재·범위 과장", SectionV2.GROUNDS, "비교 기준값은 자료 없음.", "build:first_only",
                   False, _U, "claims", "주장 표 부재 — 모든 baseline 이 null 일 때만"),
    Counterexample("A2", "부재·범위 과장", SectionV2.INSTRUMENT, "거래 금액은 최소 100.00 미국 달러임.",
                   "build:internal_small", True, _U, "claims", "주장 표 집계 범위 — \"내부 거래를 뺀 입금·출금의\""),
]  # fmt: skip


@dataclass(frozen=True)
class Outcome:
    category: Category
    new_failures: list[str]  # 끼운 뒤 새로 생긴 실패 "CHECK:REASON" (끼우기 전 같은 facts 결과에 없던 것)


def facts_of(spec: FactsSpec) -> Facts:
    """FactsSpec → facts (픽스처는 `v4_slot_support.load_fixture`, build 는 `v4_claims_support.facts_for`)."""
    from tests.str.v4_claims_support import facts_for
    from tests.str.v4_slot_support import load_fixture

    match spec:
        case "fixture:fan_in" | "fixture:multi_currency" | "fixture:cycle_nopaths":
            return load_fixture(f"facts_{spec.split(':', 1)[1]}.json")
        case "build:internal_only":
            facts = facts_for(0, 0, 1, "none", None)
        case "build:first_only":
            facts = facts_for(1, 1, 0, "none", "FAN_IN", obs="first_only")
        case "build:internal_small":
            facts = facts_for(1, 1, 1, "none", "FAN_IN", internal="small")
        case _:
            raise ValueError(f"알 수 없는 facts 지정: {spec}")
    if facts is None:
        raise ValueError(f"facts를 만들 수 없는 지정: {spec}")
    return facts


def v2_body() -> list[NarrativeSection]:
    """v2 녹화 1건(a976ae216c7fb1bb)의 7섹션 본문(cites 그대로)."""
    import json
    from pathlib import Path

    path = Path(__file__).parent / "recorded/narrative_v2/a976ae216c7fb1bb.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    sections = {
        s.section: s
        for item in json.loads(record["text"])["narrative"]
        for s in [NarrativeSection.model_validate(item)]
    }
    return [sections[section] for section in SectionV2]


def insert(body: list[NarrativeSection], section: SectionV2, sentence: str) -> list[NarrativeSection]:
    """그 섹션 text 끝에 공백 하나 + 반례 문장. 다른 섹션·cites 는 그대로(새 목록)."""
    return [
        s.model_copy(update={"text": s.text + " " + sentence}) if s.section == section else s for s in body
    ]


def measure(ce: Counterexample) -> Outcome:
    """facts_of(ce.facts)로 끼우기 전·후 `run_code_checks`(transaction_ids = facts 의 거래 id 전부) → 새 실패로 분류."""
    from collections import Counter

    from aml_ai.str.domain.verification import run_code_checks

    facts = facts_of(ce.facts)
    groups = [
        facts.inbound,
        facts.outbound,
        facts.internal,
        facts.indirect,
        facts.counterparties,
        *facts.inbound.by_currency,
        *facts.outbound.by_currency,
        *facts.unmapped_currencies,
    ]
    if facts.paths is not None:
        groups.append(facts.paths)
    ids = sorted({tid for group in groups for tid in group.transaction_ids})
    before = run_code_checks(facts, v2_body(), ids)
    after = run_code_checks(facts, insert(v2_body(), ce.section, ce.sentence), ids)
    remaining = Counter((c.check, c.section, c.draft_value, c.reason) for c in before if c.match is False)
    new_failures = []
    for c in after:
        if c.match is not False:
            continue
        key = (c.check, c.section, c.draft_value, c.reason)
        if remaining[key]:
            remaining[key] -= 1
        else:
            new_failures.append(f"{c.check}:{c.reason}")
    if new_failures:
        return Outcome("caught", new_failures)
    return Outcome("silent" if ce.has_number else "not_target", [])
