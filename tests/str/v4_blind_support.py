"""SCRUM-228 (2/2) 1단계 — v4 vs v2 블라인드 하네스 공용 순수 함수 (docs/str/08 "narrative_v4 블라인드 비교 하네스").

LLM·DB 0. 생성(v4_blind_live)·공개(v4_blind_reveal)·테스트가 같이 쓴다.
- `unify_notation`: v2 본문 속 코드값을 표기 사전으로 바꿈(숫자·날짜·금액 불변, 멱등, 사전 밖 코드는 보고만)
- `blind_cases`: 사건 8개(픽스처 5 + build_facts 3) — 09 2026-11-17 2/2 1단계 ★A ④
- `build_blind`: 사건별 v2(통일본)·v4 → 좌우 무작위 + 대조쌍 1 → 배포용 md·공개 json·진단·키
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from aml_ai.shared.schemas.str import Facts, NarrativeSection
from tests.str.v4_blind_notation import translate
from tests.str.v4_blind_render import pair_md, side_metrics
from tests.str.v4_real_names import side_facts
from tests.str.v4_slot_support import load_raw_fixture as load_fixture  # 블라인드(11/17) 입력 그대로

Labels = dict[str, dict[str, str]]
PARTIAL_BASELINE_FEATURE_NAMES = ("distinct_senders_24h", "inflow_outflow_ratio_2h")
PARTIAL_BASELINE_WINDOW_HOURS = 2
PARTIAL_BASELINE_VALUE = 1.0
_FIRST = {"name": PARTIAL_BASELINE_FEATURE_NAMES[0], "value": PARTIAL_BASELINE_VALUE, "unit": "count"}
_FIRST_AS_BLINDED = _FIRST | {
    "basis": "distinct_inbound_counterparties"
}  # 11/17 그대로(SCRUM-264 claims 축 변경 무관)


@dataclass(frozen=True)
class UnifyResult:
    text: str
    replaced: list[tuple[str, str]] = field(
        default_factory=list
    )  # (코드값, 바꾼 표기) — 나온 순서, 중복 제거
    unknown: list[str] = field(default_factory=list)  # 코드 모양인데 사전에 없어 그대로 둔 값


def unify_notation(text: str, labels: Labels, facts: Facts) -> UnifyResult:
    """v2 본문 → 표기 통일본.

    - 통화 코드(`USD`)·유형 코드(`FAN_IN`)는 `표기(코드)` 꼴(`미국 달러(USD)`·`자금 집중(FAN_IN)`)
    - 결제 방식 원문(`Wire`·`Credit Card`)·계좌 목적·업종·위험등급·엔티티 유형 코드는 표기로(`전신환`·`매출 대금 수납`)
    - 숫자·날짜·금액은 한 글자도 안 바꿈(바꾸기 전·후 `\\d` 덩이 목록이 같음 — 피처 이름 속 숫자는 이름째 바뀌어 제외)
    - 이미 표기로 쓰인 것·이미 `표기(코드)` 꼴은 다시 안 바꿈(멱등)
    - 코드 모양(영문 대문자·밑줄 3자 이상)인데 사전에 없는 값은 그대로 두고 `unknown` 에
    - 피처 이름(`facts.observations[].name`·`facts.model_signals`) → 그 관측값 `basis` 의
      `labels["observation_basis"]` 표기(basis 없음·사전 밖·같은 이름 관측값 없음이면 "관측 항목")
    - 방향 코드: `입금(INBOUND)`→`입금`·`출금(OUTBOUND)`→`출금`, 맨 `INBOUND`·`OUTBOUND`·`INTERNAL`·`MIXED`
      → `입금`·`출금`·`내부 거래`·`입금·출금 혼합`
    - 바꾼 것은 모두 `replaced` 에 (원문, 표기)
    """
    body, replaced, unknown = translate(text, labels, facts)
    return UnifyResult(body, replaced, unknown)


@dataclass(frozen=True)
class BlindCase:
    case_id: str  # 사람이 읽는 이름(버전 단서 없음) — 예 "fan_in"
    group: str | None  # 같은 고객 변형 묶음 표시(md 에 "같은 고객 묶음 X"로만), 없으면 None
    facts: Facts


def _partial_baseline_observations(facts: Facts) -> Facts:
    """서로 다른 기준의 관측값 둘로 구성하고 일부 비교 기준값 부재를 유지한다."""
    first, second = facts.observations
    observations = [
        first.model_copy(update=_FIRST_AS_BLINDED),
        second.model_copy(
            update={
                "name": PARTIAL_BASELINE_FEATURE_NAMES[1],
                "value": 0.0,
                "unit": "ratio",
                "basis": "inflow_minus_outflow",
                "window_start": facts.period.start,
                "window_end": facts.period.start + timedelta(hours=PARTIAL_BASELINE_WINDOW_HOURS),
            }
        ),
    ]
    return facts.model_copy(
        update={"observations": observations, "model_signals": list(PARTIAL_BASELINE_FEATURE_NAMES)}
    )


def blind_cases() -> list[BlindCase]:
    """사건 8개 — 픽스처 5(fan_in·fan_in_b·fan_out·cycle_nopaths·scatter_gather) + build_facts 3
    (내부 거래 있음·관측값 baseline 일부 null·고객 정보 없음). case_id 고유, 순서 고정."""
    from tests.str.v4_claims_support import facts_for

    names = ("fan_in", "fan_in_b", "fan_out", "cycle_nopaths", "scatter_gather")
    sources = [(name, load_fixture(f"facts_{name}.json")) for name in names]
    variants = (
        ("internal_transfer", {"n_int": 1}),
        ("partial_baseline", {"obs": "first_only"}),
        ("customer_missing", {"customer": "none"}),
    )
    for name, changes in variants:
        args = {"n_in": 1, "n_out": 1, "n_int": 0, "path": "none", "typology": "FAN_IN"}
        facts = facts_for(**(args | changes))
        if facts is None:
            raise ValueError("사건 구성 실패")
        if name == "partial_baseline":
            facts = _partial_baseline_observations(facts)
        sources.append((name, facts))
    groups: dict[str, str] = {}
    cases = []
    for name, facts in sources:
        customer = facts.subject.entity_id or facts.subject.account_key
        group = groups.setdefault(customer, f"g{len(groups) + 1}")
        cases.append(BlindCase(name, group, facts))
    return cases


@dataclass(frozen=True)
class CaseDrafts:
    case: BlindCase
    v2_original: list[NarrativeSection]  # LLM 첫 생성 원본(키 파일에만)
    v2_unified: list[NarrativeSection]  # 표기 통일본(사람에게 보이는 쪽)
    v4: list[NarrativeSection]
    replaced: list[tuple[str, str]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BlindOutput:
    """공개물·진단·키 모양 (reveal 이 진단·키를 읽음).

    public = {"pairs": [{"pair_no": int, "group": str | None}]}  — 쌍 번호·같은 고객 묶음만, A/B 지표 없음
    diag   = {"pairs": [{"pair_no": int,
                         "A": {"code_check_failures": int, "chars": int, "sentences": {SECTION: int}},
                         "B": {…같은 키…}}]}  — 키와 같이 선택 확정 뒤에만 엶(rag_onoff_diag 방식)
    key    = {"seed": int,
              "pairs": [{"pair_no": int, "case_id": str, "control": bool, "A": "v2"|"v4", "B": "v2"|"v4"}],
              "v2_original": {case_id: [{"section", "text"}…]},
              "replaced": {case_id: [[코드, 표기]…]}, "unknown": {case_id: [코드…]}}
    """

    md: str  # 배포용 — 안내 + 쌍마다 A·B 7섹션 본문 + 응답 칸
    public: dict[str, Any]  # 공개 json — 쌍 번호·묶음만
    diag: dict[str, Any]  # 진단 — 쌍마다 A/B 자동 지표(코드 검사 실패 수·글자 수·섹션별 문장 수)
    key: dict[str, Any]  # 키 — 쌍 번호 → case_id·A/B → v2/v4·대조쌍 여부·시드·v2 원본·바꾼 코드값


def build_blind(drafts: list[CaseDrafts], seed: int) -> BlindOutput:
    """사건 → 쌍(사건 수 + 대조쌍 1). 쌍 순서·좌우·대조쌍 사건은 `seed` 로 정함(같은 seed → 같은 결과).

    공개물(md·public)에는 버전 단서 금지: prompt_version·generation_meta·llm_model·tokens·v2·v4·narrative_·
    대조·control·seed 값. 쌍은 "쌍 1"…"쌍 N" 번호로만, 대조쌍도 다른 쌍과 같은 모양. 같은 고객 묶음은 group 표시만.
    """
    if not drafts or len({d.case.case_id for d in drafts}) != len(drafts):
        raise ValueError("고유한 사건이 필요함")
    rng = random.Random(seed)
    pairs = [(d, False) for d in drafts] + [(rng.choice(drafts), True)]
    rng.shuffle(pairs)
    public: dict[str, Any] = {"pairs": []}
    diag: dict[str, Any] = {"pairs": []}
    key: dict[str, Any] = {"seed": seed, "pairs": [], "v2_original": {}, "replaced": {}, "unknown": {}}
    blocks = [BLIND_INTRO]
    for number, (draft, control) in enumerate(pairs, start=1):
        record, mapping, body = _pair(number, draft, control, rng)
        public["pairs"].append({"pair_no": number, "group": draft.case.group})
        diag["pairs"].append(record)
        key["pairs"].append(mapping)
        blocks.append(body)
    for draft in drafts:
        name = draft.case.case_id
        key["v2_original"][name] = [
            s.model_dump(mode="json", include={"section", "text"}) for s in draft.v2_original
        ]
        key["replaced"][name] = [list(pair) for pair in draft.replaced]
        key["unknown"][name] = list(draft.unknown)
    return BlindOutput("\n".join(blocks), public, diag, key)


BLIND_INTRO = (
    "# 초안 비교 평가\n\n각 쌍의 A와 B를 읽고 조사에 더 쓸 만한 쪽을 선택해 주세요. "
    "차이가 없으면 차이 없음을 선택해 주세요.\n"
    "그대로 쓰려면 고칠 문장 수와 사실에 틀린 문장 원문을 각각 적고, 한 줄 이유를 남겨 주세요.\n"
    "평가자: __\n"
)


def _pair(
    number: int,
    draft: CaseDrafts,
    control: bool,
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    a = "v4" if control else rng.choice(("v2", "v4"))
    b = "v4" if control or a == "v2" else "v2"
    sides = {"v2": draft.v2_unified, "v4": draft.v4}
    diag = {
        "pair_no": number,
        "A": side_metrics(side_facts(draft.case.facts, a), sides[a]),
        "B": side_metrics(side_facts(draft.case.facts, b), sides[b]),
    }
    key = {"pair_no": number, "case_id": draft.case.case_id, "control": control, "A": a, "B": b}
    return diag, key, pair_md(number, draft.case.group, sides[a], sides[b])
