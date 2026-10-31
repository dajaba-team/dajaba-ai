"""fact 키 — LLM 이 cites 에 쓰고 코드가 거래 ID 로 바꾼다. 정본 docs/str/04 "fact 키" 표. 순수 함수.

LLM 이 거래 ID 를 직접 고르지 않는다. null fact·UNVERIFIED 경로는 키가 없다(인용할 게 없다).
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection, NarrativeSection, PathStatus

FactKeys = dict[str, list[int]]


def fact_keys(facts: Facts) -> FactKeys:
    """인용 가능한 키 → 그 키의 근거 거래 ID(오름차순). 프롬프트 FACT_KEYS 는 이 dict 의 키 목록."""
    flows = _union(facts.inbound.transaction_ids, facts.outbound.transaction_ids)
    keys: FactKeys = {"subject": [], "subject.account_key": []}
    if facts.subject.entity_name is not None:
        keys["subject.entity_name"] = []
    if facts.subject.entity_type is not None:  # SCRUM-47
        keys["subject.entity_type"] = []
    keys["period"] = _union(flows, facts.internal.transaction_ids, facts.indirect.transaction_ids)
    _add_flow_keys(keys, facts)
    _add_extension_keys(keys, facts, flows)
    _add_customer_observation_keys(keys, facts, flows)
    _add_paths_and_unmapped_keys(keys, facts)
    return keys


def _add_flow_keys(keys: FactKeys, facts: Facts) -> None:
    for name, flow in (("inbound", facts.inbound), ("outbound", facts.outbound)):
        keys[f"{name}.count"] = list(flow.transaction_ids)
        for c in flow.by_currency:
            keys[f"{name}.amount.{c.currency}"] = list(c.transaction_ids)  # 그 통화 거래만
    keys["internal.count"] = list(facts.internal.transaction_ids)
    keys["counterparties.count"] = list(facts.counterparties.transaction_ids)


def _add_extension_keys(keys: FactKeys, facts: Facts, flows: list[int]) -> None:
    """SCRUM-47 facts 확장 — counterparty_banks·payment_format_counts·amount_range."""
    cp_ids = list(facts.counterparties.transaction_ids)
    keys["counterparty_banks.same_bank_accounts"] = cp_ids
    keys["counterparty_banks.other_bank_accounts"] = cp_ids
    for p in facts.payment_format_counts:
        keys[f"payment_format_counts.{p.format}"] = flows
    for a in facts.amount_range:
        cur_ids = _by_currency_ids(facts, a.currency)
        keys[f"amount_range.{a.currency}.min"] = cur_ids
        keys[f"amount_range.{a.currency}.max"] = cur_ids


def _add_customer_observation_keys(keys: FactKeys, facts: Facts, flows: list[int]) -> None:
    keys["direction"] = flows
    keys["payment_formats"] = flows
    if facts.typology is not None:
        keys["typology"] = flows
    if facts.customer is not None:
        for field, value in facts.customer.model_dump().items():
            if value is not None:
                keys[f"customer.{field}"] = []
    keys["prior_alert_count"] = []
    for o in facts.observations:
        keys[f"observations.{o.name}"] = []
    if facts.model_signals:
        keys["model_signals"] = []


def _add_paths_and_unmapped_keys(keys: FactKeys, facts: Facts) -> None:
    if facts.paths is not None and facts.paths.status is PathStatus.VERIFIED:
        for field in ("count", "max_hops", "max_accounts"):
            keys[f"paths.{field}"] = list(facts.paths.transaction_ids)
        if facts.paths.kind is not None:
            keys["paths.kind"] = list(facts.paths.transaction_ids)
    for u in facts.unmapped_currencies:  # SCRUM-47: 미등록 통화 원문 이름 → 그 거래 ID (금액 없음)
        keys[f"unmapped_currencies.{u.name}"] = list(u.transaction_ids)


def attach_evidence(narrative: list[LlmNarrativeSection], facts: Facts) -> list[NarrativeSection]:
    """섹션마다 cites 의 fact 키 → 거래 ID 합집합 = evidence_ids. 목록 밖 키는 근거에 기여하지 않는다.

    cites 자체는 그대로 둔다 — 목록 밖 키는 생성기(NarrativeOut 검증)와 EVIDENCE_IN_SCOPE 가 잡는다.
    """
    keys = fact_keys(facts)
    return [
        NarrativeSection(
            section=s.section,
            text=s.text,
            cites=list(s.cites),
            evidence_ids=_union(*(keys[c] for c in s.cites if c in keys)),
        )
        for s in narrative
    ]


def _union(*groups: list[int]) -> list[int]:
    return sorted({i for g in groups for i in g})


def _by_currency_ids(facts: Facts, currency: str) -> list[int]:
    """inbound.by_currency + outbound.by_currency 중 그 통화 거래 ID 합집합 (SCRUM-47 amount_range)."""
    ids: list[int] = []
    for flow in (facts.inbound, facts.outbound):
        for c in flow.by_currency:
            if c.currency == currency:
                ids.extend(c.transaction_ids)
    return sorted(set(ids))
