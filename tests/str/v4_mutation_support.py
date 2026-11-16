"""narrative_v4 슬롯 변조 표 도우미 (docs/str/08 narrative_v4 2번).

슬롯 문장 안 숫자 덩이를 하나씩 ±1 바꿔 다시 돌림 → 그 섹션에 match=false 가 생기면 잡힘, 아니면 조용한 통과.
조용한 통과는 06 검사기 포함·집합 판정 여섯 가지(`Mutation.known_limit`)로 분류 — 그 밖은 0 이어야 함.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain import masking
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_slot_support import assembled, code_checks

_RE_NUM = re.compile(r"\d+")


@dataclass(frozen=True)
class Mutation:
    source: str
    section: str
    sentence: str
    original: str
    mutated: str
    start: int  # 문장 안 위치
    caught_by: str  # check·reason, 비면 조용한 통과
    range_hit: bool = False  # 바꾼 금액을 AMOUNT_MATCH 가 amount_range(min~max 포함)로 맞춤
    path_accounts_hit: bool = False  # 바꾼 상대·경로 계좌 수가 같은 COUNT 집합의 다른 값과 같음
    obs_value_hit: bool = False  # 바꾼 관측값이 다른 관측값의 값과 같음(관측값 둘 이상)

    @property
    def known_limit(self) -> str:
        """조용한 통과가 06 검사기의 **포함 판정** 설계 때문이면 그 이름, 아니면 "". 문형으로 못 막음(★C)."""
        if self.caught_by:
            return ""
        if self.section == "DATE":
            return "DATE 거래 날짜는 period 안이면 match"
        if self.sentence.startswith("입금은 "):
            return "COUNT 방향 건수는 총건수·통화별 건수 어느 쪽과 같아도 match"
        if self.obs_value_hit:
            return "COUNT 관측값은 observations[].value 어느 것과 같아도 match(관측값 둘 이상)"
        if self.path_accounts_hit:
            return "COUNT 상대 수는 counterparties.count·paths.max_accounts 어느 쪽과 같아도 match"
        if self.range_hit:
            return "AMOUNT amount_range 는 min~max 안이면 match"
        if self.section == "GROUNDS" and self.sentence.find(")") > self.start > self.sentence.find("("):
            return "DATE 관측 구간은 window_start·window_end 어느 쪽과 같아도 match"
        if self.section == "GROUNDS" and not self.sentence.endswith("개임."):
            return "COUNT 단위 없는 관측값은 결과 없음"
        return ""


def _obs_value_hit(facts: Facts, sentence: str, value: int, start: int) -> bool:
    """06 COUNT 관측값 집합 = observations[].value 전부 — 괄호 밖 관측값 숫자를 다른 관측값의 값으로 바꾼 경우."""
    return (
        start > sentence.find(")")
        and sentence.startswith("모델 관측값")
        and len(facts.observations) > 1
        and any(float(o.value) == value for o in facts.observations)
    )


def _path_accounts_hit(facts: Facts, sentence: str, value: int) -> bool:
    """06 COUNT 상대 수 집합 = {counterparties.count, paths.max_accounts(VERIFIED)} — 바꾼 값이 그 집합 안."""
    paths = facts.paths
    if paths is None or paths.status.value != "VERIFIED":
        return False
    on_kind = sentence.startswith(("상대 계좌는", "경로 하나가 거친 계좌는"))
    return on_kind and value in {facts.counterparties.count, paths.max_accounts}


def _range_hit(check: Any, sentence: str) -> bool:
    """AMOUNT_MATCH 가 이 문장의 금액을 amount_range 로 맞췄나(source_value `amount_range.X=min~max`)."""
    amount = str(check.draft_value or "").split(" ")[0]
    source = str(check.source_value or "")
    return (
        check.check == "AMOUNT_MATCH"
        and check.match
        and source.startswith("amount_range")
        and amount in sentence
    )


def _protected(facts: Facts, sentence: str) -> list[tuple[int, int]]:
    """이름 속 숫자(`#50438`)·미등록 통화 원문은 숫자 사실이 아니라 변조 대상에서 뺌."""
    names = [facts.subject.entity_name or ""] + [u.name for u in facts.unmapped_currencies]
    spans = []
    for n in filter(None, names):
        i = sentence.find(n)
        if i >= 0:
            spans.append((i, i + len(n)))
    return spans


def mutations(source: str, facts: Facts) -> list[Mutation]:
    base = assembled(facts)
    slots = build_slots(masking.mask_for_llm(facts), load_display_labels())
    out: list[Mutation] = []
    for idx, sec in enumerate(base):
        for sent in (s.text for s in slots[sec.section]):
            prot = _protected(facts, sent)
            for m in _RE_NUM.finditer(sent):
                if any(a <= m.start() < b for a, b in prot):
                    continue
                for delta in (1, -1):
                    n = int(m.group()) + delta
                    if n < 0:
                        continue
                    new = str(n).zfill(len(m.group()))
                    changed = sent[: m.start()] + new + sent[m.end() :]
                    secs = list(base)
                    secs[idx] = sec.model_copy(update={"text": sec.text.replace(sent, changed, 1)})
                    rows = [c for c in code_checks(facts, secs) if c.section == sec.section]
                    caught = ", ".join(sorted({f"{c.check}:{c.reason}" for c in rows if not c.match}))
                    hit = any(_range_hit(c, changed) for c in rows)
                    acc = _path_accounts_hit(facts, sent, n)
                    obs_hit = _obs_value_hit(facts, sent, n, m.start())
                    out.append(
                        Mutation(
                            source,
                            sec.section.value,
                            sent,
                            m.group(),
                            new,
                            m.start(),
                            caught,
                            hit,
                            acc,
                            obs_hit,
                        )
                    )
    return out
