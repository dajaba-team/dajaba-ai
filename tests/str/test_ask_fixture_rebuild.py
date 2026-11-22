"""질문 답변 평가 픽스처 재현 — build_facts 가 기존 칸을 글자 그대로 만들고, 새 칸은 그 코드가 만든 값 (SCRUM-358·359 ★B2-1).

`tests/str/ask_fixture_txs.py` 의 거래 → build_facts. 기준 픽스처(RAG 308-2 가드가 묶은 바이트)는 그대로 두고,
질문 답변 전용 복사본·ask_* 픽스처의 `counterparties_by_direction` 이 재현 값과 같은지 본다.
multi_currency 는 재현 안 됨(관측값 2 · model_signals 1 — 같은 reasons 에서 나오는 둘이 어긋남) → 복사본 없음.
"""

from __future__ import annotations

import pytest

from tests.conftest import EXAMPLES, FIXTURES, load_json
from tests.str.ask_fixture_txs import CASES, rebuild

BASE = {"fan_in": "facts_fan_in.json", "fan_out": "facts_fan_out.json"}  # 기준 픽스처(바이트 그대로) → 복사본
COPY = {"fan_in": "facts_ask_fan_in.json", "fan_out": "facts_ask_fan_out.json"}
OWN = ("ask_paths", "ask_mixed", "ask_mixed_formats")  # 질문 답변 전용 픽스처 — 자기 자신과 대조


ASK_ONLY_FACT_FIELDS = frozenset({"counterparties_by_direction"})  # 질문 답변 전용 칸


def _without(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ASK_ONLY_FACT_FIELDS}


def _full(f) -> dict:  # noqa: ANN001
    """칸은 직렬화에서 빠짐(exclude, 추가 검토 1 H3) — 픽스처 JSON 과 대조하려고 따로 꺼냄."""
    return {
        **f.model_dump(mode="json"),
        "counterparties_by_direction": f.counterparties_by_direction.model_dump(mode="json"),
    }


REPRODUCED = sorted(set(CASES) - {"multi_currency"})


@pytest.mark.parametrize("case", REPRODUCED)
def test_rebuild_reproduces_existing_fields(case: str) -> None:
    source = BASE.get(case, f"facts_{case}.json")
    assert _without(rebuild(case).model_dump(mode="json")) == _without(load_json(FIXTURES / source))


@pytest.mark.parametrize("case", sorted(COPY))
def test_copy_is_rebuild_output(case: str) -> None:
    assert load_json(FIXTURES / COPY[case]) == _full(rebuild(case))


@pytest.mark.parametrize("case", OWN)
def test_ask_fixture_field_is_rebuild_value(case: str) -> None:
    made = _full(rebuild(case))["counterparties_by_direction"]
    assert load_json(FIXTURES / f"facts_{case}.json")["counterparties_by_direction"] == made


def test_base_fixtures_have_no_field() -> None:
    """기준 픽스처는 칸 없음 = 옛 스냅샷 경로(06 물러남) — RAG 308-2 가드 바이트 그대로."""
    for name in ("facts_fan_in.json", "facts_fan_out.json", "facts_multi_currency.json"):
        assert "counterparties_by_direction" not in load_json(FIXTURES / name)


def test_multi_currency_not_reproducible_only_model_signals() -> None:
    """재현 안 됨을 고정 — 다른 칸은 전부 같고 model_signals 만 다름(관측값 이름은 늘 model_signals 에도 들어감)."""
    got = _without(rebuild("multi_currency").model_dump(mode="json"))
    want = load_json(FIXTURES / "facts_multi_currency.json")
    assert sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k)) == ["model_signals"]
    assert not (FIXTURES / "facts_ask_multi_currency.json").exists()


def test_draft_path_facts_dump_has_develop_shape() -> None:
    """초안·요약 build_facts 는 칸을 안 채우고, 직렬화에도 없음 — 저장 행·응답이 이전 버전(계약 예시) 모양 그대로."""
    from tests.str.facts_support import CASES as FACT_CASES
    from tests.str.facts_support import build

    built = build(FACT_CASES["mixed"])
    assert built.counterparties_by_direction is None
    dumped = built.model_dump(mode="json")
    assert "counterparties_by_direction" not in dumped
    example = set(load_json(EXAMPLES / "draft_response.json")["facts"])
    assert set(dumped) == example
