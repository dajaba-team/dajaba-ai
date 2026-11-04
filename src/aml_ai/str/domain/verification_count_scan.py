"""COUNT_MATCH 스캔 — 절 나누기·숫자 추출 (SCRUM-60, docs/str/06).

분류는 `verification_count_kind.py`. 판정은 `verification_count.py`.

관측값 "소비" 는 **단위 유무와 무관** — `모델 관측값은 31.0이며 입금은 3건` 처럼 단위 없는 숫자(31.0)
도 관측 단어 뒤 첫 숫자면 소비한 것으로 본다(Codex adversarial 3차). 그래야 뒤 거래 건수가
관측값 우선 규칙으로 번지지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aml_ai.str.domain.constants import (
    COUNT_CLAUSE_SPLIT,
    COUNT_OBSERVATION_WORDS,
    COUNT_UNITS_COUNT,
    COUNT_UNITS_SMALL,
    KOREAN_NUMERAL_COUNT,
    PATH_HOP_UNITS,
    PERIOD_UNITS,
    PRIOR_ALERT_WORDS,
    RE_DATE_DOT,
    RE_DATE_ISO,
    RE_DATE_KO,
    RE_DATE_KO_NOYEAR,
    RE_DATE_SLASH,
)
from aml_ai.str.domain.verification_count_kind import Direction, Kind, classify


@dataclass(frozen=True)
class CountToken:
    """절 안 숫자 하나의 추출 결과 — 판정이 이 값만 본다."""

    raw: str
    value: float | None
    unit: str
    kind: Kind | None
    direction: Direction
    payment_format: str | None
    unparsed: bool

    @property
    def draft_repr(self) -> str:
        return self.raw


_UNITS = ("계좌", *COUNT_UNITS_SMALL, *COUNT_UNITS_COUNT, *PATH_HOP_UNITS)
_RE_NUMBER_UNIT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(" + "|".join(_UNITS) + r")")
_RE_HANGUL_NUMERAL = re.compile(
    r"("
    + "|".join(sorted(KOREAN_NUMERAL_COUNT, key=len, reverse=True))
    + r")[가-힣]{0,3}\s*("  # 뒤 접미 수사 1~3자 허용 — `서른한`·`스물셋`
    + "|".join(_UNITS)
    + r")"
)
# 관측값 소비용 — 단위가 있든 없든 숫자 하나. `3`·`3.0`·`1,200`.
_RE_ANY_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?")
# 기간·기준 숫자 — 관측 단어 뒤 "첫 숫자" 찾기에서 건너뜀(실제 관측값은 아님).
# **단위가 숫자에 붙은 경우만**(공백 허용 안 함) + 단위 뒤 한글은 간·동안·이내·치 만 허용
# (SCRUM-60 Codex adversarial 5차: `31 일반`·`3 주요` 의 접두사 글자를 단위로 잘못 잡던 오탐 수정).
_RE_PERIOD_NUMBER = re.compile(
    r"\d+(?:\.\d+)?(?:" + "|".join(PERIOD_UNITS) + r")(?=간|동안|이내|치|[^가-힣]|$)"
    r"|\d+\s*기준"
)
# 날짜 span — DATE_MATCH 와 같은 정규식을 재사용(constants.py). 관측 소비·COUNT 토큰 추출에서 날짜
# 전체를 제외해 `10월 3일` 의 10·3 이 관측값·COUNT 로 번지지 않게(Codex adversarial 5차).
_DATE_PATTERNS = (RE_DATE_ISO, RE_DATE_KO, RE_DATE_SLASH, RE_DATE_DOT, RE_DATE_KO_NOYEAR)


def scan_text(text: str) -> list[CountToken]:
    """본문 전체를 절 단위로 나누고 각 절 안 숫자·한글 수사 전부를 CountToken 으로 뽑는다.

    **날짜 + 기간·기준 숫자는 스캔 전에 공백으로 지움** — `10월 3일` 의 10·3 과 `3개월 동안` 의
    `3개월` 이 COUNT 토큰이나 관측 소비에 끼어들지 않게(SCRUM-60 Codex adversarial 5차).
    """
    cleaned = _strip_non_count_spans(text)
    tokens: list[CountToken] = []
    for clause in COUNT_CLAUSE_SPLIT.split(cleaned):
        tokens.extend(_scan_clause(clause))
    return tokens


def _strip_non_count_spans(text: str) -> str:
    """날짜 + 기간·기준 숫자 매치를 같은 길이 공백으로 치환(위치·clause 분할 보존)."""
    for pattern in _DATE_PATTERNS:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    text = _RE_PERIOD_NUMBER.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _scan_clause(clause: str) -> list[CountToken]:
    hangul = [_hangul_token(m) for m in _RE_HANGUL_NUMERAL.finditer(clause)]
    numbers = _number_tokens(clause)
    return hangul + numbers


def _hangul_token(m: re.Match[str]) -> CountToken:
    return CountToken(
        raw=m.group(0),
        value=None,
        unit=m.group(2),
        kind=None,
        direction=Direction.NONE,
        payment_format=None,
        unparsed=True,
    )


def _number_tokens(clause: str) -> list[CountToken]:
    obs_in_clause = _has_word(clause, COUNT_OBSERVATION_WORDS)
    prior_in_clause = _has_word(clause, PRIOR_ALERT_WORDS)
    obs_consumed_at = _observation_consumed_at(clause) if obs_in_clause else None
    out: list[CountToken] = []
    for m in _RE_NUMBER_UNIT.finditer(clause):
        num_str, unit = m.group(1), m.group(2)
        start = m.start()
        first_obs_already = obs_consumed_at is not None and obs_consumed_at < start
        kind, direction, pfmt, unparsed = classify(
            clause=clause,
            num_span=m.span(),
            unit=unit,
            obs_in_clause=obs_in_clause,
            prior_in_clause=prior_in_clause,
            first_obs_already=first_obs_already,
        )
        out.append(
            CountToken(
                raw=m.group(0),
                value=float(num_str.replace(",", "")),
                unit=unit,
                kind=kind,
                direction=direction,
                payment_format=pfmt,
                unparsed=unparsed,
            )
        )
    return out


def _observation_consumed_at(clause: str) -> int | None:
    """관측 단어 뒤 **첫 숫자** 시작 위치(단위 유무 무관) — 괄호 안이든 밖이든.

    날짜·기간·기준 숫자는 `scan_text` 가 이미 공백으로 지워 전달하므로 여기서는 날 것 숫자만 본다.
    소비 유지 목적은 **뒤 거래 건수가 관측값 우선으로 번지지 않게** 하는 것(Codex adversarial 3~5차).
    """
    obs_pos = _first_word_pos(clause, COUNT_OBSERVATION_WORDS)
    if obs_pos is None:
        return None
    m = _RE_ANY_NUMBER.search(clause, obs_pos)
    return m.start() if m is not None else None


def _first_word_pos(text: str, words: tuple[str, ...]) -> int | None:
    best: int | None = None
    for w in words:
        i = text.find(w)
        if i == -1:
            continue
        if best is None or i < best:
            best = i
    return best


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)
