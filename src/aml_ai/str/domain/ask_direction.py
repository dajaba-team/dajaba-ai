"""질문 답변 상대 수·자행·타행 — 방향·근거 키 판정 (docs/str/06 "질문 답변" 10번, SCRUM-358·359 · 추가 검토 2). 순수 함수.

공용 COUNT_MATCH(초안·검증·요약)는 방향을 안 본다(develop 그대로). 질문 답변만 COUNTERPARTY·SAME_BANK·OTHER_BANK 줄을
여기서 다시 판정한다 — 숫자마다 **값이 같은 인용 키**가 있어야 하고, 그 키의 방향이 숫자를 바로 꾸미는 말의 방향과 같아야 한다.
꾸미는 말: 숫자 바로 앞 명사구(`입금 상대`·`수취인 계좌`, 마지막 `중`·`중에서`·`가운데` 뒤만) 또는 바로 뒤(`N명의 수취인`·
`N개 (계좌)가 보낸`=입금). 원칙(추가 검토 3): **판정 못 하면 통과 안 시킴** — 범위가 미확정이면 UNPARSED.
범위 = 입금·출금·전체(꾸밈 없음 — 그 절에 방향·역할 낱말이 하나도 없을 때만)·명시 전체(`전체`·`입출금` …)·미확정.
질문이 한 방향만 물으면 꾸밈 없는 숫자는 그 방향으로, 명시 전체는 미확정. `이 가운데`류는 바로 앞 상대 수 주장의 범위.
칸이 없고 그 방향 거래가 0건이면 기대값 {0}.
공용 스캔(`verification_count_scan`)의 숫자 순서를 그대로 따라 줄을 1:1 로 바꾼다 — 공용 파일은 고치지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts, PathStatus
from aml_ai.str.domain.constants import COUNT_CLAUSE_SPLIT
from aml_ai.str.domain.constants_ask import (
    ASK_CP_BOTH_WORDS,
    ASK_CP_IN_WORDS,
    ASK_CP_OUT_WORDS,
    COUNTERPARTY_IN_WORD,
    COUNTERPARTY_OUT_WORD,
)
from aml_ai.str.domain.verification_count_kind import Kind
from aml_ai.str.domain.verification_count_scan import (  # 공용 스캔과 같은 순서 — 공용 파일 그대로 두려고 내부 이름을 씀
    _RE_HANGUL_NUMERAL,
    _RE_NUMBER_UNIT,
    _number_tokens,
    _strip_non_count_spans,
)

_FIELD = {
    Kind.COUNTERPARTY: "count",
    Kind.SAME_BANK: "same_bank_accounts",
    Kind.OTHER_BANK: "other_bank_accounts",
}
_SUBSET = re.compile(r"\s(?:중에서|가운데서|중|가운데)\s|(?:이|그)\s?(?:중에서|가운데서|중|가운데)")
_AFTER_ROLE = re.compile(rf"^[가-힣]{{0,2}}의\s*({COUNTERPARTY_OUT_WORD}|{COUNTERPARTY_IN_WORD})")
_AFTER_SENDER = re.compile(  # 상대가 주어 → 대상 쪽에서 입금 — `3개가 보낸` · `3개 계좌가 보낸`
    r"^[가-힣]{0,2}\s*(?:(?:상대|상대방|계좌|상대 계좌)\s*)?(?:가|이)\s*(?:보낸|송금한|보내온|입금한)"
)
SIDES = ("inbound", "outbound")
TOTAL, EXPLICIT_TOTAL, UNKNOWN = "total", "explicit_total", "unknown"


@dataclass(frozen=True)
class Claim:
    """상대 수·자행·타행 숫자 하나 — scope 는 inbound·outbound·total·explicit_total·unknown."""

    kind: Kind
    value: float
    scope: str


def recheck(
    facts: Facts, answer: str, cites: Sequence[str], checks: list[CodeCheck], question: str = ""
) -> list[CodeCheck]:
    """COUNT 줄 중 상대·자행·타행 줄을 범위·근거 키로 다시 판정."""
    claims = iter(_claims(answer, question))
    out: list[CodeCheck] = []
    for check in checks:
        if check.check is CodeCheckName.COUNT_MATCH:
            claim = next(claims)
            if claim is not None:
                check = _judge(facts, claim, cites, check)
        out.append(check)
    return out


def has_claims(answer: str) -> bool:
    return any(c is not None for c in _claims(answer, ""))


def used_keys(facts: Facts, answer: str, cites: Sequence[str], question: str = "") -> set[str]:
    """상대·자행·타행 숫자를 뒷받침한 인용 키 합집합(근거 거래용)."""
    out: set[str] = set()
    for claim in _claims(answer, question):
        expected = _expected(facts, claim) if claim is not None else None
        if expected:
            out |= {k for k, v in expected.items() if v == claim.value and k in cites}
    return out


def _judge(facts: Facts, claim: Claim, cites: Sequence[str], row: CodeCheck) -> CodeCheck:
    expected = _expected(facts, claim)
    if expected is None:
        return _row(row, False, "상대 수 범위(방향)를 정할 수 없음", CheckReason.UNPARSED)
    if expected == {}:  # 칸 없음 + 그 방향 0건 → {0}
        ok = claim.value == 0
        return _row(row, ok, "그 방향 거래 0건 → {0}", None if ok else CheckReason.MISMATCH)
    source = " · ".join(f"{k}={int(v)}" for k, v in expected.items())
    if any(v == claim.value and k in cites for k, v in expected.items()):
        return _row(row, True, source, None)
    reason = CheckReason.MISSING if claim.value in expected.values() else CheckReason.MISMATCH
    return _row(row, False, source, reason)


def _expected(facts: Facts, claim: Claim) -> dict[str, float] | None:
    """범위에 맞는 키 → 값. None = 판정 못 함 · {} = 칸 없음 + 그 방향 0건(호출자가 {0})."""
    field = _FIELD[claim.kind]
    if claim.scope == UNKNOWN:
        return None
    if claim.scope in SIDES:
        if facts.counterparties_by_direction is not None:
            side = getattr(facts.counterparties_by_direction, claim.scope)
            return {f"counterparties_by_direction.{claim.scope}.{field}": float(getattr(side, field))}
        other = SIDES[1 - SIDES.index(claim.scope)]
        if getattr(facts, claim.scope).count == 0:
            return {}
        if getattr(facts, other).count != 0:
            return None  # 칸 없음 + 양방향 — 방향 값을 모름
    if claim.kind is Kind.COUNTERPARTY:
        out = {"counterparties.count": float(facts.counterparties.count)}
        if facts.paths is not None and facts.paths.status is PathStatus.VERIFIED:
            out["paths.max_accounts"] = float(facts.paths.max_accounts)
        return out
    return {f"counterparty_banks.{field}": float(getattr(facts.counterparty_banks, field))}


def _row(row: CodeCheck, ok: bool, source: str, reason: CheckReason | None) -> CodeCheck:
    return row.model_copy(update={"match": ok, "source_value": source, "reason": reason})


def _claims(answer: str, question: str) -> list[Claim | None]:
    """공용 COUNT 줄과 같은 순서 — 줄을 만드는 토큰마다 하나(상대·자행·타행이 아니면 None)."""
    q_side = _flow_side(question)
    out: list[Claim | None] = []
    last: str | None = None
    for clause in COUNT_CLAUSE_SPLIT.split(_strip_non_count_spans(answer)):
        out += [None] * len(_RE_HANGUL_NUMERAL.findall(clause))  # 한글 수사 = UNPARSED 줄
        for m, tok in zip(_RE_NUMBER_UNIT.finditer(clause), _number_tokens(clause), strict=True):
            if not (tok.unparsed or tok.kind is not None):
                continue  # 줄 없음
            if tok.kind not in _FIELD or tok.unparsed or tok.value is None:
                out.append(None)
                continue
            scope = _scope(clause, clause[: m.start()], clause[m.end() :], last)
            if q_side is not None and scope == TOTAL:
                scope = q_side  # 질문이 한 방향 — 꾸밈 없는 숫자는 그 방향(추가 검토 3 H4)
            elif q_side is not None and scope == EXPLICIT_TOTAL:
                scope = UNKNOWN  # 한 방향을 물었는데 전체로 답함 — 전체 키 match 불가
            out.append(Claim(tok.kind, tok.value, scope))
            last = scope
    return out


def _scope(clause: str, before: str, after: str, last: str | None) -> str:
    """바로 뒤 역할·주어 → 마지막 `중`·`가운데` 뒤 조각 → 그 앞 조각 → (`이 가운데`처럼 앞이 비면) 앞 주장 범위 →
    꾸밈 없음: 절에 방향·역할 낱말이 없으면 전체, 있으면 미확정."""
    role = _AFTER_ROLE.match(after)
    if role:
        return "outbound" if role.group(1) == COUNTERPARTY_OUT_WORD else "inbound"
    if _AFTER_SENDER.match(after):
        return "inbound"
    parts = _SUBSET.split(before)
    decided = _segment_scope(parts[-1])
    if decided is None and len(parts) > 1:
        decided = _segment_scope(parts[-2]) if parts[-2].strip() else last or UNKNOWN
    if decided is not None:
        return decided
    return UNKNOWN if _flow_words(_strip_both(clause)) else TOTAL


def _segment_scope(seg: str) -> str | None:
    if any(w in seg for w in ASK_CP_BOTH_WORDS):
        return EXPLICIT_TOTAL
    return _flow_side(seg)


def _flow_side(text: str) -> str | None:
    has_in, has_out = any(w in text for w in ASK_CP_IN_WORDS), any(w in text for w in ASK_CP_OUT_WORDS)
    return ("inbound" if has_in else "outbound") if has_in != has_out else None


def _flow_words(text: str) -> bool:
    return any(w in text for w in (*ASK_CP_IN_WORDS, *ASK_CP_OUT_WORDS))


def _strip_both(text: str) -> str:
    for w in ASK_CP_BOTH_WORDS:
        text = text.replace(w, " ")
    return text
