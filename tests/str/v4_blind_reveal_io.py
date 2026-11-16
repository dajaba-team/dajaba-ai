"""집계 입력 파일의 문장 목록과 확인 목록을 모양에 맞게 읽는다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.str.v4_blind_reveal import Confirmed, Response


TEMPLATE_RATERS = 3  # 빈 양식의 평가자 칸 수(09 ★A-5 평가자 3명) — 이름은 진희가 채움


def responses_template(public: dict[str, Any], raters: int = TEMPLATE_RATERS) -> list[dict[str, Any]]:
    """공개 json(쌍 번호) → 빈 응답 양식. 평가자 칸 × 쌍마다 한 줄, Response 필드 그대로.

    rater 는 "평가자1"… 자리값, choice·reason 은 "", fix_a·fix_b 는 None, wrong_a·wrong_b 는 [].
    쌍 번호 밖 값(버전·대조쌍·묶음) 없음. 채우지 않은 채 load_responses → reveal 하면 거부됨.
    """
    return [
        {
            "rater": f"평가자{rater}",
            "pair_no": number,
            "choice": "",
            "fix_a": None,
            "fix_b": None,
            "wrong_a": [],
            "wrong_b": [],
            "reason": "",
        }
        for rater in range(1, raters + 1)
        for number in sorted(pair["pair_no"] for pair in public["pairs"])
    ]


def load_responses(path: Path) -> list[Response]:
    """문장 목록은 문자열을 쪼개지 않고 JSON 배열만 튜플로 바꾼다."""
    from tests.str.v4_blind_reveal import Response

    result = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        for field in ("wrong_a", "wrong_b"):
            sentences = item.get(field, [])
            if not isinstance(sentences, list):
                raise ValueError("틀린 문장 입력은 문자열 배열이어야 함")
            item[field] = tuple(sentences)
        result.append(Response(**item))
    return result


def load_confirmed(path: Path | None) -> Confirmed:
    """확인 값이 true 인 항목만 원문 식별자로 모은다."""
    if path is None:
        return set()
    return {
        (item["rater"], item["pair_no"], item["side"], item["text"])
        for item in json.loads(path.read_text(encoding="utf-8"))
        if item.get("confirmed") is True
    }
