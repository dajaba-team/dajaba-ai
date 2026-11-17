"""재블라인드 응답 양식·읽기·입력 검사 (docs/str/08 "재블라인드" 응답 양식·집계, 09 SCRUM-265 1/2 추가 검토 2차).

228 양식 + 쌍마다 `support_a`·`support_b` · 사건 파일 기준 쌍 완전성 · 결과 경로(입력을 덮지 않음).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.str.v4_blind_reveal_io import responses_template

if TYPE_CHECKING:
    from tests.str.v4_blind2_reveal import Response2


def responses_template2(public: dict[str, Any]) -> list[dict[str, Any]]:
    """빈 양식 — 228 칸 그대로 + support_a·support_b 는 null(채우지 않으면 reveal 이 거부) + 실행 run_id."""
    extra = {"support_a": None, "support_b": None, "run_id": public["run_id"]}
    return [row | extra for row in responses_template(public)]


def load_responses2(path: Path) -> list[Response2]:
    """문장 목록은 JSON 배열만 튜플로 — 문자열을 쪼개지 않음."""
    from tests.str.v4_blind2_reveal import Response2

    result = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        for field in ("wrong_a", "wrong_b"):
            sentences = item.get(field, [])
            if not isinstance(sentences, list):
                raise ValueError("틀린 문장 입력은 문자열 배열이어야 함")
            item[field] = tuple(sentences)
        result.append(Response2(**item))
    return result


RESULT_PREFIX = "v4_blind2_revealed_"
KEY_PREFIX = "v4_blind_key_"
VERSION_PAIRS = ({"A": "v4", "B": "v2"}, {"A": "v2", "B": "v4"})


def validate_pairs(key: dict[str, Any], diag: dict[str, Any], doc: dict[str, Any]) -> None:
    """키·진단이 사건 파일과 맞는지 — 12쌍·case_id 각각 한 번·대조쌍 하나·pair_no 중복·버전 매핑."""
    numbers = [p["pair_no"] for p in key["pairs"]]
    diag_numbers = [p["pair_no"] for p in diag["pairs"]]
    expected = len(doc["cases"]) + 1  # 대조쌍 1
    if len(numbers) != expected or len(set(numbers)) != expected or sorted(diag_numbers) != sorted(numbers):
        raise ValueError("키·진단 쌍 수 또는 번호 오류")
    cases = sorted(p["case_id"] for p in key["pairs"] if not p["control"])
    if cases != sorted(c["case_id"] for c in doc["cases"]):
        raise ValueError("사건 파일의 사건이 각각 한 번씩 있어야 함")
    controls = [p for p in key["pairs"] if p["control"]]
    if len(controls) != 1 or controls[0]["case_id"] != doc["control_case_id"]:
        raise ValueError("대조쌍은 사건 파일의 대조 사건 하나여야 함")
    for p in key["pairs"]:
        sides = {"A": p["A"], "B": p["B"]}
        ok = sides == {"A": "v4", "B": "v4"} if p["control"] else sides in VERSION_PAIRS
        if not ok:
            raise ValueError("A/B 버전 매핑 오류")


def result_paths(key_path: Path, inputs: list[Path]) -> tuple[Path, Path]:
    """키 폴더의 `v4_blind2_revealed_<tag>.{json,md}`(tag = 키 파일 이름) — 입력 경로와 같으면 거절."""
    tag = key_path.stem.removeprefix(KEY_PREFIX)
    out = key_path.with_name(f"{RESULT_PREFIX}{tag}.json")
    paths = (out, out.with_suffix(".md"))
    taken = {p.resolve() for p in inputs}
    if any(p.resolve() in taken for p in paths):
        raise ValueError("결과 경로가 입력 파일과 같음")
    return paths


def diag_hash(diag: dict[str, Any]) -> str:
    """진단 내용 sha256 — 키에 기록해 다른 실행 진단이 섞이면 거절."""
    body = json.dumps(diag, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_run(key: dict[str, Any], diag: dict[str, Any], responses: list[Response2]) -> None:
    """키·진단·응답이 같은 실행인지 — run_id 셋 일치 + 진단 해시 일치(09 SCRUM-265 1/2 추가 검토 3차)."""
    run_id = key.get("run_id")
    if not run_id or diag.get("run_id") != run_id or any(r.run_id != run_id for r in responses):
        raise ValueError("키·진단·응답의 run_id 가 다름")
    if key.get("diag_sha256") != diag_hash(diag):
        raise ValueError("진단 파일 해시가 키와 다름")
