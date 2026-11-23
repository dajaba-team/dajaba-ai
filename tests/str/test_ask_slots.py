"""질문 답변 답 자리표 — 문법·허용 키·조사·cites (SCRUM-362, 정본 docs/str/04 "답 자리표"). 순수 함수."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.ask_bundles import AskPiece, extract
from aml_ai.str.domain.ask_scope import AskScope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json

LABELS = load_display_labels()
WHOLE = AskScope(
    whole_alert=True, ownership_known=True
)  # 범위 표시가 아닌 렌더링 시험 — 근거 = 경보 전체(★B8)
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
PIECE = extract(MIXED, "R02_FAN_IN", ["flows", "counterparties"], LABELS, scope=WHOLE)


def _r(answer: str, piece: AskPiece = PIECE):
    return render(answer, piece, LABELS)


def test_slot_becomes_label_and_value_and_key_is_cited() -> None:
    s = _r("이 케이스에는 {{counterparties_by_direction.inbound.count|이}} 있어요.")
    assert s.text == "이 케이스에는 입금 상대 계좌 2개가 있어요."
    assert s.keys == ("counterparties_by_direction.inbound.count",)
    assert (s.out_of_scope, s.errors) == (0, 0)


def test_cites_keep_answer_order_without_duplicates() -> None:
    s = _r("{{outbound.count|과}} {{inbound.count|이에요}}. 다시 {{outbound.count|이에요}}.")
    assert s.keys == ("outbound.count", "inbound.count")


def test_slot_without_particle_is_label_and_value_only() -> None:
    assert _r("{{inbound.amount.USD}}").text == "입금 합계 27,250.50 USD"


@pytest.mark.parametrize(
    ("answer", "want"),
    [
        ("{{inbound.count|은}}", "입금 거래 2건은"),  # 건 — 받침
        ("{{inbound.count|는}}", "입금 거래 2건은"),  # 쌍의 다른 쪽을 써도 같은 쌍
        ("{{inbound.amount.USD|이}}", "입금 합계 27,250.50 USD가"),  # 영문 끝 — 받침 없음
        ("{{direction|을}}", "거래 방향 입금·출금 모두를"),
        ("{{inbound.count|과}}", "입금 거래 2건과"),
        ("{{direction|와}}", "거래 방향 입금·출금 모두와"),
        ("{{inbound.count|으로}}", "입금 거래 2건으로"),
        ("{{period|로}}", "거래 기간 2022년 9월 3일 01:05 ~ 2022년 9월 3일 21:40으로"),  # 0 — 받침(영)
        ("{{inbound.count|예요}}", "입금 거래 2건이에요"),
        ("{{counterparties.count|이에요}}", "입출금 전체 상대 계좌 4개예요"),
    ],
)
def test_particle_follows_last_sound(answer: str, want: str) -> None:
    assert _r(answer).text == want


def test_rieul_takes_ro() -> None:
    piece = AskPiece(bundles=("flows",), content={"direction": "INBOUND"}, keys=("direction",))
    assert (
        _r("{{direction|으로}}", piece).text == "거래 방향 입금 우세 (근거 거래 기준)으로"
    )  # 범위 모름 → 우세 + 범위(추가 검토 3 H3) · 조사는 괄호 안 마지막 한글 `준` 기준(★B7-3)
    piece = AskPiece(
        bundles=("flows",),
        content={"direction": "INBOUND", "outbound": {"count": 0}},
        keys=("direction",),
        scope=AskScope(whole_alert=True, ownership_known=True),
    )
    assert (
        _r("{{direction|으로}}", piece).text == "거래 방향 대외 입금만으로"
    )  # 범위(대외)를 이름표에(추가 검토 2 H1)
    fan_out = Facts.model_validate(load_json(FIXTURES / "facts_fan_out.json"))
    piece = extract(fan_out, "R01_FAN_OUT", ["rule_facts"], LABELS)
    assert (
        _r("{{typology|으로}}", piece).text == "탐지 유형 자금 분산(FAN_OUT)으로"
    )  # 괄호 앞 말 기준(산 — ㄴ)


@pytest.mark.parametrize(
    "answer",
    ["{{inbound.count", "inbound.count}}", "{{}}", "{{inbound{{inbound.count}}}}", "{{inbound.count|만}}"],
    ids=["no-close", "no-open", "empty", "nested", "unknown-particle"],
)
def test_grammar_errors_are_counted(answer: str) -> None:
    assert _r(answer).errors >= 1


def test_single_braces_are_plain_text() -> None:
    s = _r("{정리} {{inbound.count|이에요}}")
    assert (s.errors, s.text) == (0, "{정리} 입금 거래 2건이에요")


@pytest.mark.parametrize(
    "key",
    ["paths.count", "customer.industry", "inbound.count ", "observations.none", "inbound.amount.EUR"],
    ids=["other-bundle", "other-bundle-2", "trailing-space", "not-in-case", "no-currency"],
)
def test_keys_outside_piece_are_out_of_scope(key: str) -> None:
    s = _r("{{" + key + "|이에요}}")
    assert (s.out_of_scope, s.keys, s.text) == (1, (), "")


def test_key_in_piece_without_value_is_error_not_scope() -> None:
    piece = AskPiece(bundles=("flows",), content={}, keys=("inbound.count",))
    s = _r("{{inbound.count}}", piece)
    assert (s.out_of_scope, s.errors, s.keys) == (0, 1, ())


def test_outside_text_drops_slots_only() -> None:
    s = _r("{{inbound.count|은}} 3건보다 적어요.")
    assert "{{" not in s.outside and "3건보다 적어요" in s.outside and "2건" not in s.outside
