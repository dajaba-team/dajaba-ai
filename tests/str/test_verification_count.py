"""SCRUM-60 — COUNT_MATCH 단위 테스트 (기본: 정상·결과 없음). docs/str/06.

분류 순서: ① 단위 선검색 → ② 관측값 우선(첫 번째 숫자만) → ③ 거리 최근접 (앞뒤, 같으면 UNPARSED).
단위 밖과 종류 단어 없는 `개·곳·명` 은 결과 없음. 녹화 두 개·draft_response·narrative_ok 전부 통과.

경계 (관측값 우선·MISMATCH·UNPARSED·경로) 는 `test_verification_count_edge.py`.
녹화 통과는 `test_verification_count_recorded.py`.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import (
    CodeCheck,
    CodeCheckName,
    SectionV1,
)
from tests.str.verification_support import count, facts_fan_in


def _by_name(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in checks if c.check is CodeCheckName.COUNT_MATCH]


def _only_fail(checks: list[CodeCheck]) -> list[CodeCheck]:
    return [c for c in _by_name(checks) if not c.match]


# ── 정상 (facts_fan_in: inbound=3, outbound=0, internal=0, cp=3, same_bank=0, other_bank=3, ACH=3, prior=1, obs=3.0) ──


@pytest.mark.parametrize(
    "text",
    [
        "서로 다른 3개 계좌에서 3건",  # ★ 단위 선검색: 3개=상대 수, 3건=거래 건수
        "상대방 3곳",  # ④ 단어 목록 보강
        "상대방은 3곳이고 타행 상대 계좌는 3개로 확인됨",  # 거리 분리: 3곳=cp, 3개=타행
        "과거 경보 이력 1건",  # ① 단어 사이 `이력` 허용
        "과거 경보 이력은 1건임",
        "타행 분포는 3개",  # ⑦ 단위 `개` 로 확장
        "결제 방식은 ACH이며 거래 건수는 3건임",  # ⑥ ACH + ⑤ 거래 건수
        "입금은 3건으로 합계",  # ⑤ 입금
        "출금은 0건, 내부거래는 0건임",  # ⑤ 출금·내부
    ],
)
def test_count_match_passes_recorded_phrases(text: str) -> None:
    checks = count(facts_fan_in(), SectionV1.SUMMARY, text)
    bad = _only_fail(checks)
    assert not bad, f"기대한 match 가 실패함: {[(c.draft_value, c.reason) for c in bad]}"


# ── 결과 없음 (단위 밖·종류 단어 없음) ──


@pytest.mark.parametrize(
    "text",
    [
        "10_****BD30",  # 계좌 식별자
        "#50438",  # 엔티티 ID
        "42750.50 USD",  # 금액
        "2022-09-02T00:14:00",  # 시각
        "24시간",  # `시간` 접미어
        "3.0으로 제시됨",  # 단위 없음
        "R04_CYCLE",  # 룰 ID
        "하나의 계좌",  # 한글 "하나"
        "3개 섹션",  # 단위 `개` 이지만 종류 단어 없음
        "2곳 지점",  # 단위 `곳` 이지만 종류 단어 없음
    ],
)
def test_count_match_skips_non_count_tokens(text: str) -> None:
    checks = _by_name(count(facts_fan_in(), SectionV1.SUMMARY, text))
    assert checks == [], f"결과 없음이어야 하는데 뽑힘: {[(c.draft_value, c.reason) for c in checks]}"
