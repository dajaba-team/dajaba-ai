from __future__ import annotations

import hashlib
import re
from datetime import datetime

import pytest

from aml_ai.scoring.domain.dl_evidence import evidence_digest, reference_text

SOURCE = "HI-Small_Trans.csv"
ROWS_000001 = (
    1986552, 2046999, 2047000, 2084563, 2098137, 2270959, 2270960, 2294529, 2324273, 2324274,
    2333352, 2333353, 2510223, 2606610, 2674739, 2674740, 2693683, 2693684, 2776966, 2796240,
    2961883, 2961884, 3010278, 3010279, 3040407, 3040408, 3059393, 3187179, 3187180, 3259121,
)  # fmt: skip
# 9/7 에서 행번호의 정수 정렬과 문자열 정렬이 갈리는 15건 중 하나(318130 < 1639618).
ROWS_001157 = (
    318130, 1639618, 1639619, 1892453, 1892455, 1984627, 1984628, 1984629, 2012558,
    2012559, 2073417, 2073418, 2073420, 2196201, 2196203, 2821099, 3123487, 3469218,
)  # fmt: skip
ROWS_001528 = (2332835, 2332837, 2332838, 2332840, 2332842, 2332843)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_sorts_file_as_string_and_row_as_integer() -> None:
    sources = [("b.csv", 1), ("a.csv", 1639618), ("B.csv", 2), ("a.csv", 318130), ("a.csv", 9)]
    expected = sha("B.csv:2\na.csv:9\na.csv:318130\na.csv:1639618\nb.csv:1")
    assert evidence_digest(sources) == expected
    assert evidence_digest(reversed(sources)) == expected


def test_row_number_is_not_sorted_as_text() -> None:
    assert evidence_digest([("a.csv", 100), ("a.csv", 20)]) == sha("a.csv:20\na.csv:100")
    assert evidence_digest([("a.csv", 100), ("a.csv", 20)]) != sha("a.csv:100\na.csv:20")


def test_single_line_has_no_trailing_newline_and_uses_utf8() -> None:
    assert evidence_digest([("dataset.csv", 10)]) == sha("dataset.csv:10")
    assert evidence_digest([("거래.csv", 3)]) == hashlib.sha256("거래.csv:3".encode()).hexdigest()


def test_digest_is_lowercase_hex_64() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", evidence_digest([("A.CSV", 1), ("A.CSV", 2)]))


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        pytest.param(
            ROWS_000001, "d277a2cdcb9bd308cd75c3cf55b4cb15f0a99e5cb894728bffe1c610960caade", id="000001"
        ),
        pytest.param(
            ROWS_001157,
            "099b951a700949628505e7f269b064b514727218dc37004b73df2196da6516e8",
            id="001157-int-and-text-sort-differ",
        ),
        pytest.param(
            ROWS_001528, "c9132814329f2e30d0dc16483ede794085f299f698f9b4102fbe0d525b3c33f1", id="001528"
        ),
    ],
)
def test_0907_snapshot_examples(rows, expected) -> None:
    # 9/7 스냅샷의 근거 행. 백엔드 테스트도 같은 기대값을 쓴다.
    assert evidence_digest((SOURCE, row) for row in reversed(rows)) == expected


def test_0907_example_differs_from_text_sort() -> None:
    text_sorted = sorted(f"{SOURCE}:{row}" for row in ROWS_001157)
    assert evidence_digest((SOURCE, row) for row in ROWS_001157) != sha("\n".join(text_sorted))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2022, 9, 7, 0, 29), "2022-09-07T00:29:00"),
        (datetime(2022, 9, 7, 23, 59, 59), "2022-09-07T23:59:59"),
        (datetime.fromisoformat("2022-09-07 06:58:00"), "2022-09-07T06:58:00"),
    ],
)
def test_reference_text_shape(value, expected) -> None:
    text = reference_text(value)
    assert text == expected
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text)
