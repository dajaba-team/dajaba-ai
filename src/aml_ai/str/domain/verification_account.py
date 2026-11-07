"""ACCOUNT_ID_MATCH — 본문의 계좌 식별자가 subject.account_key 와 같은가.

규칙 정본 docs/str/06. 끝 4자리 + bank_id(붙어 있을 때) 둘 다 같아야 match.
`*` 가 뒤쪽에 있어 끝 4자리를 못 읽는 모양은 MISMATCH.
"""

from __future__ import annotations

from dataclasses import dataclass

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    NarrativeSectionBase,
)
from aml_ai.str.domain.constants import (
    RE_ACCOUNT_FULL,
    RE_ACCOUNT_MASKED_TAIL,
    RE_ACCOUNT_TAIL_KO,
)


def account_id_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    out: list[CodeCheck] = []
    subject_bank, subject_tail = _subject_parts(facts.subject.account_key)
    for section in narrative:
        for found in _find_ids(section.text):
            matched = _is_subject(found, subject_bank, subject_tail)
            reason = None if matched else CheckReason.MISMATCH
            out.append(
                CodeCheck(
                    check=CodeCheckName.ACCOUNT_ID_MATCH,
                    section=section.section,
                    draft_value=found.raw,
                    source_value=None,
                    match=matched,
                    reason=reason,
                )
            )
    return out


# ---------- 매치 ----------


@dataclass(frozen=True)
class _Found:
    raw: str  # 본문에서 뽑은 식별자 원문
    bank_id: str | None  # 숫자 bank_id, 없으면 None(마스킹 꼬리·끝자리 표현)
    tail: str | None  # 끝 4자리 영숫자, None 이면 못 읽음(뒤쪽 `*`)


def _find_ids(text: str) -> list[_Found]:
    """세 패턴, **긴 쪽 우선 1줄** — 겹치면 더 긴 매치만 쓴다 (★A 4)."""
    raw_matches: list[tuple[int, int, _Found]] = []
    for m in RE_ACCOUNT_FULL.finditer(text):
        raw_matches.append((m.start(), m.end(), _parse_full(m.group(0))))
    for m in RE_ACCOUNT_MASKED_TAIL.finditer(text):
        raw_matches.append((m.start(), m.end(), _parse_masked_tail(m.group(0))))
    for m in RE_ACCOUNT_TAIL_KO.finditer(text):
        raw_matches.append((m.start(), m.end(), _parse_tail_ko(m.group(0), m.group(1))))
    # 겹치면 긴 쪽 우선, 같은 길이면 먼저 나온 쪽
    raw_matches.sort(key=lambda r: (-(r[1] - r[0]), r[0]))
    picked: list[tuple[int, int, _Found]] = []
    for start, end, found in raw_matches:
        if any(not (end <= s or e <= start) for s, e, _ in picked):
            continue
        picked.append((start, end, found))
    picked.sort(key=lambda r: r[0])
    return [p[2] for p in picked]


def _parse_full(raw: str) -> _Found:
    """`10_8000EBD30` 또는 `10_****BD30`. bank_id + 꼬리 분리."""
    bank, _, body = raw.partition("_")
    tail = body[-4:] if body else ""
    # 뒤 4자가 전부 `*` 또는 글자가 아니면 못 읽음
    if "*" in tail or not tail.isalnum():
        return _Found(raw=raw, bank_id=bank, tail=None)
    return _Found(raw=raw, bank_id=bank, tail=tail.upper())


def _parse_masked_tail(raw: str) -> _Found:
    """`****BD30` — bank_id 없음, 끝 4자리만."""
    tail = raw[-4:]
    return _Found(raw=raw, bank_id=None, tail=tail.upper())


def _parse_tail_ko(raw: str, group1: str) -> _Found:
    """`끝자리 BD30` — bank_id 없음, 끝 4자리."""
    return _Found(raw=raw, bank_id=None, tail=group1.upper())


# ---------- 대조 ----------


def _subject_parts(account_key: str) -> tuple[str, str]:
    """`10_8000EBD30` → ("10", "BD30"). bank_id 는 앞 0 뗀 문자열(규약 v0.4 #4, SCRUM-160)."""
    bank, _, body = account_key.partition("_")
    return _norm_bank(bank), body[-4:].upper()


def _norm_bank(bank: str) -> str:
    """bank_id 앞 0 제거 — 규약 v0.4 #4(SCRUM-160). 전부 0 이면 `"0"`."""
    return bank.lstrip("0") or "0"


def _is_subject(found: _Found, subject_bank: str, subject_tail: str) -> bool:
    if found.tail is None:
        return False  # 뒤쪽 `*` 로 가려 못 읽는 모양
    if found.tail != subject_tail:
        return False
    return not (found.bank_id is not None and _norm_bank(found.bank_id) != subject_bank)


__all__ = ["account_id_match"]
