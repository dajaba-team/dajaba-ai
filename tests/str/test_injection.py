"""오류 주입 1~14 (docs/str/08). 결정적(1~6, 13)은 CI, LLM(7~12, 14)은 -m live.

W3 에 verification 구현과 함께 채운다. 지금은 표의 자리만.
"""

from __future__ import annotations

import pytest

CASES_DETERMINISTIC = [1, 2, 3, 4, 5, 6, 13]
CASES_LIVE = [7, 8, 9, 10, 11, 12, 14]


@pytest.mark.deterministic
@pytest.mark.parametrize("case", CASES_DETERMINISTIC)
def test_injection_deterministic(case: int) -> None:
    pytest.skip(f"W3 — 오류 주입 #{case} (docs/str/08 표)")


@pytest.mark.live
@pytest.mark.parametrize("case", CASES_LIVE)
def test_injection_live(case: int) -> None:
    pytest.skip(f"W4 수동 — 오류 주입 #{case}")
