"""승인 STR 청크 나누기 — 순수 (SCRUM-361, 정본 docs/str/10 "승인 STR 색인" · 청크 나누기·상한 식).

청크 ≤1200(코드 포인트) · 문장 끝에서 앞부터 채움 · 1200 넘는 한 문장만 자르고 꼬리는 다음 문장과 이어 채움 ·
공백만인 청크 없음 — 공백만 조각은 앞 청크 남은 자리 → 보관했다 다음 청크 앞, 둘 다 꽉 찼을 때만 버림(추가 검토 1 M1 · 2 M) ·
청크 수 ≤ ⌊글자 수 ÷ 600⌋ + 1(백엔드 응답 확인과 같은 식).
"""

from __future__ import annotations

import random

import pytest

from aml_ai.shared.schemas.str import StrIndexRequest
from aml_ai.str.domain.constants_rag_query import STR_INDEX_CHUNK_MAX
from aml_ai.str.domain.str_index import chunk_bound, chunk_id, chunks, split_text
from tests.str.str_index_support import body


def _only_space_dropped(text: str, pieces: list[str]) -> bool:
    """이어 붙인 글 = 원문에서 공백 글자만 몇 개 뺀 것(순서 그대로, 겹침 없음)."""
    joined, k = "".join(pieces), 0
    for ch in text:
        if k < len(joined) and joined[k] == ch:
            k += 1
        elif not ch.isspace():
            return False
    return k == len(joined)


def _lens(text: str) -> list[int]:
    return [len(c) for c in split_text(text)]


@pytest.mark.parametrize(
    ("text", "lens"),
    [
        ("가" * 1200, [1200]),  # 1200 딱 — 1청크
        ("가" * 1201, [1200, 1]),  # 한 문장 1201 — 1200 에서 자름
        ("가나. " + "다" * 1201 + ". 라마", [4, 1200, 5]),  # 2·1201·2 → 3 (꼬리를 따로 닫으면 4)
        ("가" * 2500, [1200, 1200, 100]),
        ("가" * 5000, [1200, 1200, 1200, 1200, 200]),
        ("짧은 문장. 또 짧은 문장.", [15]),
    ],
)
def test_boundaries(text: str, lens: list[int]) -> None:
    assert _lens(text) == lens
    assert "".join(split_text(text)) == text
    assert len(lens) <= chunk_bound(text)


def test_sentences_split_at_sentence_end_and_join_back() -> None:
    sentence = "가" * 499 + ". "  # 501자 문장 다섯 개 = 2505
    text = sentence * 5
    pieces = split_text(text)
    assert [len(p) for p in pieces] == [1002, 1002, 501]  # 문장 끝에서만 나뉨
    assert all(p.endswith(". ") for p in pieces)
    assert "".join(pieces) == text


def test_newline_is_sentence_end() -> None:
    text = ("가" * 700 + "\n") * 2
    assert _lens(text) == [701, 701]


@pytest.mark.parametrize(
    "text",
    [
        "\n\n\n",
        "   ",
        "가" * 1200 + "\n\n",
        "가" * 1199 + ". " + "나" * 1200,
        "\n\n" + "가" * 1199 + ". " + "나" * 1200,
    ],
)
def test_no_whitespace_only_chunk(text: str) -> None:
    """공백만인 청크는 끝에도 중간에도 만들지 않음(진희 ★A ③)."""
    assert all(p.strip() for p in split_text(text))


def test_review1_m1_inner_blank_line_kept() -> None:
    """추가 검토 1 M1 반례 — 2400자를 1200 두 개로, 가운데 빈 줄을 잃지 않음."""
    text = "가" * 1198 + "\n \n" + "나" * 1199
    assert _lens(text) == [1200, 1200] and "".join(split_text(text)) == text


def test_space_dropped_only_when_both_sides_full() -> None:
    """1200 에서 잘린 꼬리가 공백 1자 — 앞 청크도 다음 문장도 1200 이라 붙일 곳이 없을 때만 버림."""
    text = "가" * 1199 + ". " + "나" * 1200
    pieces = split_text(text)
    assert [len(p) for p in pieces] == [1200, 1200] and len("".join(pieces)) == len(text) - 1
    assert _only_space_dropped(text, pieces)


def test_review2_m_cut_blank_piece_carried_to_next_chunk() -> None:
    """추가 검토 2 M 반례 — 1200 에서 잘린 공백만 조각의 남은 몫을 다음 청크 앞에 붙임, 못 붙인 101자만 빠짐."""
    text = "가" * 100 + "\n" + " " * 2300 + "나" * 100
    pieces = split_text(text)
    assert [len(p) for p in pieces] == [1200, 1200] and len(text) - len("".join(pieces)) == 101
    assert _only_space_dropped(text, pieces)


def test_leading_space_goes_to_next_sentence() -> None:
    text = "\n\n" + "가" * 1199 + ". " + "나" * 10
    assert "".join(split_text(text)) == text


def test_chunks_keys_and_order() -> None:
    b = body()
    b["sections"] = [{"section": "SUBJECT", "text": "가" * 1300}, {"section": "DATE", "text": "  "},
                     {"section": "METHOD", "text": "나. 다."}]  # fmt: skip
    req = StrIndexRequest.model_validate(b)
    got = [(s, n, len(t)) for s, n, t in chunks(req)]
    assert got == [("SUBJECT", 1, 1200), ("SUBJECT", 2, 100), ("METHOD", 1, 5)]
    assert chunk_id("STR-2026-000012", "SUBJECT", 2) == "STR-2026-000012:SUBJECT:2"


@pytest.mark.parametrize(("seed", "letters"), [(361, "가a "), (362, "가a \n")])  # 뒤 = 큰 공백·줄바꿈 덩어리
def test_property_count_never_exceeds_bound(seed: int, letters: str) -> None:
    """무작위 단락(시드 고정) — 청크 1~1200 · 공백만 청크 없음 · 청크 수 ≤ 상한 식 · 이어 붙이면 원문(다르면 빠진 건 공백뿐)."""
    rng = random.Random(seed)
    for _ in range(3000):
        parts = []
        for _ in range(rng.randint(1, 12)):
            n = rng.choice([rng.randint(1, 30), rng.randint(1, 1300), rng.randint(1150, 2600)])
            parts.append(
                rng.choice(letters) * n + rng.choice([". ", "? ", "! ", "\n", "", ".\n", "  ", "\n \n"])
            )
        text = "".join(parts)[:5000]
        if not text.strip():
            continue
        pieces = split_text(text)
        assert all(1 <= len(p) <= STR_INDEX_CHUNK_MAX and p.strip() for p in pieces)
        if "".join(pieces) != text:  # 앞뒤가 꽉 차 못 붙인 공백만 빠질 수 있음
            assert _only_space_dropped(text, pieces)
        assert len(pieces) <= chunk_bound(text)


def test_bound_formula() -> None:
    assert [chunk_bound(t) for t in ("가", "가" * 599, "가" * 600, "가" * 5000, "  ")] == [1, 1, 2, 9, 0]
