"""COUNT_MATCH 종류 분류 (SCRUM-60) — 단위 선검색 → 관측값 우선 → 숫자별 최근접(동률 UNPARSED).

상위 스캔은 `verification_count_scan.py`, 거리·방향·결제는 `verification_count_distance.py`.
자행/타행·방향 단어는 **숫자 위치 기준 최근접** 으로 결정(Codex adversarial 3차).
"""

from __future__ import annotations

from enum import StrEnum

from aml_ai.str.domain.constants import (
    BANK_COUNT_UNITS,
    COUNT_OBSERVATION_WORDS,
    COUNT_UNITS_COUNT,
    COUNT_UNITS_SMALL,
    COUNTERPARTY_WORDS,
    OTHER_BANK_WORDS,
    PATH_HOP_UNITS,
    PATH_WORDS,
    PRIOR_ALERT_WORDS,
    SAME_BANK_WORDS,
)
from aml_ai.str.domain.verification_count_distance import (
    UNPARSED as _UNPARSED,
)
from aml_ai.str.domain.verification_count_distance import (
    Direction,
    any_word_in,
    direction_for_number,
    nearest_distance,
    payment_format_in,
)


class Kind(StrEnum):
    PRIOR_ALERT = "PRIOR_ALERT"
    OBSERVATION = "OBSERVATION"
    PATH = "PATH"  # paths.count 와만 비교
    PATH_HOPS = "PATH_HOPS"  # paths.max_hops 와만 비교 (단위 홉·단계)
    COUNTERPARTY = "COUNTERPARTY"
    TX_COUNT = "TX_COUNT"
    PAYMENT_FORMAT = "PAYMENT_FORMAT"
    SAME_BANK = "SAME_BANK"
    OTHER_BANK = "OTHER_BANK"


_Result = tuple[Kind | None, Direction, str | None, bool]
_NO_RESULT: _Result = (None, Direction.NONE, None, False)
_UNPARSED_RESULT: _Result = (None, Direction.NONE, None, True)


def classify(
    *,
    clause: str,
    num_span: tuple[int, int],
    unit: str,
    obs_in_clause: bool,
    prior_in_clause: bool,
    first_obs_already: bool,
) -> _Result:
    """단위 선검색 → 관측값 우선(첫 번째만) → 숫자별 최근접 → 동률 UNPARSED."""
    before, after = clause[: num_span[0]], clause[num_span[1] :]
    if unit in PATH_HOP_UNITS:
        return Kind.PATH_HOPS, Direction.NONE, None, False
    pfmt_result = _classify_payment_format(clause, before, after, unit)
    if pfmt_result is not None:
        return pfmt_result
    candidates = _candidates_for_unit(unit)
    if not candidates:
        return _NO_RESULT
    obs_result = _classify_observation(before, obs_in_clause, prior_in_clause, first_obs_already)
    if obs_result is not None:
        return obs_result
    bank_result = _classify_bank(before, after, unit, candidates)
    if bank_result is not None:
        return bank_result
    # 단위 `계좌` 는 그 자체가 상대 수 문맥(SCRUM-60 Codex adversarial 4차) — `3계좌를 거친 경로 2개`
    # 의 `3계좌` 가 PATH 로 분류돼 오탐되는 것을 막음. `3개 계좌` 처럼 단위가 `개` 일 때는 종전대로
    # 최근접 단어(`계좌`) 로 COUNTERPARTY 분류. `곳` 은 "2곳 지점" 같은 메타 문장이 결과 없음이어야
    # 하므로 자동 COUNTERPARTY 로 묶지 않는다(06 경계 문구 "지원 표현만 대조").
    if unit == "계좌" and Kind.COUNTERPARTY in candidates:
        return Kind.COUNTERPARTY, Direction.NONE, None, False
    return _classify_remaining(before, after, candidates)


def _classify_payment_format(clause: str, before: str, after: str, unit: str) -> _Result | None:
    pfmt = payment_format_in(clause)
    if not (pfmt and unit in COUNT_UNITS_COUNT):
        return None
    direction = direction_for_number(before, after)
    if direction == _UNPARSED:
        return _UNPARSED_RESULT
    return Kind.PAYMENT_FORMAT, direction, pfmt, False


def _classify_observation(
    before: str, obs_in_clause: bool, prior_in_clause: bool, first_obs_already: bool
) -> _Result | None:
    if not (obs_in_clause and not first_obs_already and any_word_in(before, COUNT_OBSERVATION_WORDS)):
        return None
    if prior_in_clause:
        return _UNPARSED_RESULT  # 종류 중첩
    return Kind.OBSERVATION, Direction.NONE, None, False


def _classify_bank(before: str, after: str, unit: str, candidates: set[Kind]) -> _Result | None:
    if unit not in BANK_COUNT_UNITS or Kind.SAME_BANK not in candidates:
        return None
    bank = _nearest_bank_kind(before, after)
    if bank is None:
        return None
    if bank == _UNPARSED:
        return _UNPARSED_RESULT
    return bank, Direction.NONE, None, False


def _classify_remaining(before: str, after: str, candidates: set[Kind]) -> _Result:
    nearest = _nearest_kind(before, after, candidates)
    if nearest is None:
        return _NO_RESULT
    if nearest == _UNPARSED:
        return _UNPARSED_RESULT
    if nearest is Kind.TX_COUNT:
        direction = direction_for_number(before, after)
        if direction == _UNPARSED:
            return _UNPARSED_RESULT
        return Kind.TX_COUNT, direction, None, False
    return nearest, Direction.NONE, None, False


def _candidates_for_unit(unit: str) -> set[Kind]:
    if unit in COUNT_UNITS_COUNT:
        return {Kind.PRIOR_ALERT, Kind.OBSERVATION, Kind.PAYMENT_FORMAT, Kind.TX_COUNT}
    if unit in COUNT_UNITS_SMALL or unit == "계좌":
        return {Kind.COUNTERPARTY, Kind.PATH, Kind.SAME_BANK, Kind.OTHER_BANK, Kind.OBSERVATION}
    return set()


def _nearest_kind(before: str, after: str, candidates: set[Kind]) -> Kind | str | None:
    """후보 종류 단어의 최근접 거리로 결정. 거리 같으면 UNPARSED. 없고 TX_COUNT 후보면 기본값."""
    cands: list[tuple[int, Kind]] = []
    kind_words: list[tuple[Kind, tuple[str, ...]]] = []
    if Kind.PRIOR_ALERT in candidates:
        kind_words.append((Kind.PRIOR_ALERT, PRIOR_ALERT_WORDS))
    if Kind.PATH in candidates:
        kind_words.append((Kind.PATH, PATH_WORDS))
    if Kind.COUNTERPARTY in candidates:
        kind_words.append((Kind.COUNTERPARTY, COUNTERPARTY_WORDS))
    for kind, words in kind_words:
        d = nearest_distance(before, after, words)
        if d is not None:
            cands.append((d, kind))
    if not cands and Kind.TX_COUNT in candidates:
        return Kind.TX_COUNT
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    if len(cands) >= 2 and cands[0][0] == cands[1][0]:
        return _UNPARSED
    return cands[0][1]


def _nearest_bank_kind(before: str, after: str) -> Kind | str | None:
    """자행·타행 단어의 숫자별 최근접. 둘 다 없으면 None, 거리 동률이면 UNPARSED."""
    d_same = nearest_distance(before, after, SAME_BANK_WORDS)
    d_other = nearest_distance(before, after, OTHER_BANK_WORDS)
    if d_same is None and d_other is None:
        return None
    if d_same is None:
        return Kind.OTHER_BANK
    if d_other is None:
        return Kind.SAME_BANK
    if d_same < d_other:
        return Kind.SAME_BANK
    if d_other < d_same:
        return Kind.OTHER_BANK
    return _UNPARSED
