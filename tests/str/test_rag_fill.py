"""SCRUM-275 빈칸만 채우기 규칙 (docs/str/10 "빈칸만 채우기"). 순수 — DB·LLM 0."""

from __future__ import annotations

import pytest

from aml_ai.str.domain.rag_fill import fill_order, needs_fill


@pytest.mark.parametrize(
    ("found", "k", "expected"),
    [
        (0, 3, False),  # 규칙 3 — 0건이면 채우지 않음
        (1, 3, True),
        (2, 3, True),  # CYCLE (태그 2)
        (3, 3, False),  # 규칙 1 — 다 찼으면 그대로
        (4, 3, False),
    ],
)
def test_needs_fill(found: int, k: int, expected: bool) -> None:
    assert needs_fill(found, k) is expected


def test_fill_order_skips_first_and_keeps_fused_order() -> None:
    assert fill_order(["a", "b"], ["b", "x", "a", "y", "z"]) == ["x", "y", "z"]


def test_fill_order_dedupes_fused() -> None:
    assert fill_order(["a"], ["x", "x", "a", "y"]) == ["x", "y"]


def test_fill_order_empty_when_nothing_new() -> None:
    assert fill_order(["a", "b"], ["a", "b"]) == []
    assert fill_order(["a"], []) == []
