"""SCRUM-59 — DATE_MATCH 용도 분류 (docs/str/06 DATE_MATCH 줄).

괄호 안/바로 앞 OBSERVATION_WORDS → OBSERVATION, 개설 단어 ±N → ONBOARD, 그 밖 TRANSACTION.
괄호 안 관측 + 개설 둘 다 있거나 범위 표현에 개설 단어가 걸리면 UNPARSED.

추출(regex) 은 `verification_date_scan.py`, 판정은 `verification_date.py`.
"""

from __future__ import annotations

from aml_ai.str.domain.constants import (
    DATE_CONTEXT_WINDOW,
    OBSERVATION_WORDS,
    ONBOARD_WORDS,
    RE_DATE_DOT,
    RE_DATE_ISO,
    RE_DATE_KO,
    RE_DATE_KO_NOYEAR,
    RE_DATE_SLASH,
)
from aml_ai.str.domain.verification_date_scan import DateMention, DatePurpose


def assign_purpose(text: str, m: DateMention) -> DateMention:
    """괄호 안/바로 앞 OBSERVATION_WORDS → OBSERVATION. 개설 단어 ±N → ONBOARD."""
    if m.purpose == DatePurpose.UNPARSED:
        return m
    bracket = _enclosing_bracket(text, m.span)
    if bracket is not None:
        has_obs = _bracket_has_observation(text, bracket)
        has_onboard = _text_has_word(text[bracket[0] : bracket[1]], ONBOARD_WORDS)
        if has_obs and has_onboard:
            return _replace_purpose(m, DatePurpose.UNPARSED)
        if has_obs:
            return _replace_purpose(m, DatePurpose.OBSERVATION)
    verdict = _onboard_verdict(text, m)
    if verdict == "UNPARSED":
        return _replace_purpose(m, DatePurpose.UNPARSED)
    if verdict == "ONBOARD":
        return _replace_purpose(m, DatePurpose.ONBOARD)
    return m


def _replace_purpose(m: DateMention, purpose: str) -> DateMention:
    return DateMention(
        span=m.span,
        raw=m.raw,
        date_=m.date_,
        time=m.time,
        time_was_zero_seconds=m.time_was_zero_seconds,
        purpose=purpose,
    )


def _enclosing_bracket(text: str, span: tuple[int, int]) -> tuple[int, int] | None:
    """span 을 둘러싼 가장 가까운 `(...)` 범위. 없으면 None."""
    depth = 0
    left = -1
    for i in range(span[0] - 1, -1, -1):
        if text[i] == ")":
            depth += 1
        elif text[i] == "(":
            if depth == 0:
                left = i
                break
            depth -= 1
    if left == -1:
        return None
    depth = 0
    right = -1
    for i in range(span[1], len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            if depth == 0:
                right = i + 1
                break
            depth -= 1
    if right == -1:
        return None
    return left, right


def _bracket_has_observation(text: str, bracket: tuple[int, int]) -> bool:
    """괄호 안 OBSERVATION_WORDS 가 있거나 여는 괄호 바로 앞(공백 제외)이 그 단어로 끝나면 True."""
    inside = text[bracket[0] + 1 : bracket[1] - 1]
    if _text_has_word(inside, OBSERVATION_WORDS):
        return True
    before = text[: bracket[0]].rstrip()
    return any(before.endswith(w) for w in OBSERVATION_WORDS)


def _text_has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _onboard_verdict(text: str, m: DateMention) -> str:
    """개설 단어가 가장 가까운 날짜 하나에만 붙는다. 범위에 걸리면·거리 같으면 UNPARSED."""
    for word in ONBOARD_WORDS:
        wlen = len(word)
        for idx in _find_all(text, word):
            word_span = (idx, idx + wlen)
            if _in_range_expression(text, idx, m.span):
                return "UNPARSED"
            if _distance(word_span, m.span) > DATE_CONTEXT_WINDOW:
                continue
            closer, equal = _rival_distance(text, word_span, m.span)
            if equal:
                return "UNPARSED"
            if closer:
                continue  # 개설 단어가 다른 날짜에 더 가까움 → 이 날짜는 거래
            return "ONBOARD"
    return "TRANSACTION"


def _find_all(text: str, word: str) -> list[int]:
    out: list[int] = []
    start = 0
    while True:
        i = text.find(word, start)
        if i == -1:
            return out
        out.append(i)
        start = i + 1


def _in_range_expression(text: str, word_idx: int, span: tuple[int, int]) -> bool:
    """개설 단어가 `A와 B 사이`·`A~B`·`A부터 B까지` 안에 있고 span 이 그 범위의 끝 날짜인지."""
    tail = text[span[1] : span[1] + 6]
    if word_idx > span[1] and ("까지" in tail or "사이" in text[span[1] : word_idx]):
        prefix = text[: span[0]]
        if any(w in prefix[-20:] for w in ("부터", "~", "와", "과")):
            return True
    return False


def _distance(word_span: tuple[int, int], span: tuple[int, int]) -> int:
    """word 와 날짜 사이 글자 수(공백·구두점 포함). 겹치면 0."""
    if word_span[1] <= span[0]:
        return span[0] - word_span[1]
    if span[1] <= word_span[0]:
        return word_span[0] - span[1]
    return 0


def _rival_distance(text: str, word_span: tuple[int, int], span: tuple[int, int]) -> tuple[bool, bool]:
    """다른 날짜가 더 가까운지(closer) · 거리가 같은지(equal).

    `other` 가 현재 `span` 과 **겹치면**(자기 날짜의 짧은 regex 매치 또는 시각 포함 확장) 건너뜀 —
    아니면 `_attach_trailing_time` 로 확장된 span 이 자기 자신과 경쟁해 UNPARSED 로 떨어짐
    (SCRUM-59 2차 Codex adversarial).
    """
    my_dist = _distance(word_span, span)
    closer, equal = False, False
    for other in _rough_date_spans(text):
        if _spans_overlap(other, span):
            continue
        d = _distance(word_span, other)
        if d < my_dist:
            closer = True
        elif d == my_dist:
            equal = True
    return closer, equal


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _rough_date_spans(text: str) -> list[tuple[int, int]]:
    """다른 날짜의 span 목록 — 겹치는 매치는 긴 쪽만(같은 날짜의 짧은 매치가 '다른 날짜'로 안 세게)."""
    raw: list[tuple[int, int]] = []
    for pat in (RE_DATE_ISO, RE_DATE_KO, RE_DATE_SLASH, RE_DATE_DOT, RE_DATE_KO_NOYEAR):
        raw.extend(m.span() for m in pat.finditer(text))
    raw.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out: list[tuple[int, int]] = []
    last_end = -1
    for s in raw:
        if s[0] >= last_end:
            out.append(s)
            last_end = s[1]
    return out
