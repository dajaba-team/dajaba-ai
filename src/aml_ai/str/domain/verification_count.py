"""COUNT_MATCH 판정 (SCRUM-60) — docs/str/06 "COUNT_MATCH" 줄.

스캔은 `verification_count_scan.py`. 판정은 CountToken 의 (kind, value, direction, payment_format)
을 facts 의 종류별 집합과 비교한다.

- 종류 못 정하면 UNPARSED(종류 중첩·한글 수사·거리 같음).
- 단위 밖 숫자는 결과 없음(검사 대상 아님).
- 관측값은 값만 비교(float 3.0 ≡ int 3).
- 경로 수(PATH)·max_hops·max_accounts 는 paths.status == VERIFIED 일 때만, 그 외엔 MISMATCH.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    NarrativeSectionBase,
    PathStatus,
)
from aml_ai.str.domain.verification_count_kind import Direction, Kind
from aml_ai.str.domain.verification_count_scan import CountToken, scan_text


def count_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    out: list[CodeCheck] = []
    for s in narrative:
        for tok in scan_text(s.text):
            check = _check_token(facts, s.section, tok)
            if check is not None:
                out.append(check)
    return out


def _check_token(facts: Facts, section, tok: CountToken) -> CodeCheck | None:
    if tok.unparsed:
        return _fail(section, tok, CheckReason.UNPARSED)
    if tok.kind is None:
        return None  # 결과 없음(검사 대상 아님)
    expected = _expected_set(facts, tok)
    if expected is None:  # 경로 단어인데 UNVERIFIED/None → MISMATCH
        return _fail(section, tok, CheckReason.MISMATCH)
    assert tok.value is not None
    if any(_eq(tok.value, v) for v in expected):
        return _match(section, tok, expected)
    return _fail(section, tok, CheckReason.MISMATCH, expected=expected)


def _expected_set(facts: Facts, tok: CountToken) -> set[float] | None:
    """종류·방향·결제 방식·경로 상태에 따라 facts 에서 꺼낸 비교 집합."""
    if tok.kind is Kind.PRIOR_ALERT:
        return {float(facts.prior_alert_count)}
    if tok.kind is Kind.OBSERVATION:
        return {float(o.value) for o in facts.observations if o.value is not None}
    if tok.kind is Kind.PATH:
        if facts.paths is None or facts.paths.status is not PathStatus.VERIFIED:
            return None
        return {float(facts.paths.count)}  # 경로 수 — max_hops 는 PATH_HOPS 전용
    if tok.kind is Kind.PATH_HOPS:
        if facts.paths is None or facts.paths.status is not PathStatus.VERIFIED:
            return None
        return {float(facts.paths.max_hops)}
    if tok.kind is Kind.COUNTERPARTY:
        s: set[float] = {float(facts.counterparties.count)}
        if facts.paths is not None and facts.paths.status is PathStatus.VERIFIED:
            s.add(float(facts.paths.max_accounts))
        return s
    if tok.kind is Kind.SAME_BANK:
        return {float(facts.counterparty_banks.same_bank_accounts)}
    if tok.kind is Kind.OTHER_BANK:
        return {float(facts.counterparty_banks.other_bank_accounts)}
    if tok.kind is Kind.PAYMENT_FORMAT:
        fmt = tok.payment_format
        return {float(p.count) for p in facts.payment_format_counts if p.format == fmt}
    if tok.kind is Kind.TX_COUNT:
        return _tx_count_set(facts, tok.direction)
    return None  # 안 쓰임


def _tx_count_set(facts: Facts, direction: Direction) -> set[float]:
    if direction is Direction.IN:
        s = {float(facts.inbound.count)}
        s.update(float(c.count) for c in facts.inbound.by_currency)
        return s
    if direction is Direction.OUT:
        s = {float(facts.outbound.count)}
        s.update(float(c.count) for c in facts.outbound.by_currency)
        return s
    if direction is Direction.INTERNAL:
        return {float(facts.internal.count)}
    # 방향 없음 → 전체 집합
    s = {
        float(facts.inbound.count),
        float(facts.outbound.count),
        float(facts.internal.count),
        float(facts.inbound.count + facts.outbound.count),
    }
    s.update(float(c.count) for c in facts.inbound.by_currency)
    s.update(float(c.count) for c in facts.outbound.by_currency)
    # max_hops 는 PATH_HOPS 전용 — TX_COUNT 에서 뺌(Codex adversarial 3차)
    return s


def _eq(a: float, b: float) -> bool:
    """값만 비교(unit 안 봄) — float 3.0 ≡ int 3 (SCRUM-60 ★A 6)."""
    return abs(a - b) < 1e-9


def _match(section, tok: CountToken, expected: set[float]) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.COUNT_MATCH,
        section=section,
        draft_value=tok.draft_repr,
        source_value=_repr_set(expected),
        match=True,
        reason=None,
    )


def _fail(section, tok: CountToken, reason: CheckReason, *, expected: set[float] | None = None) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.COUNT_MATCH,
        section=section,
        draft_value=tok.draft_repr,
        source_value=_repr_set(expected) if expected else None,
        match=False,
        reason=reason,
    )


def _repr_set(s: set[float] | None) -> str | None:
    if not s:
        return None
    return "{" + ",".join(str(int(v) if v.is_integer() else v) for v in sorted(s)) + "}"
