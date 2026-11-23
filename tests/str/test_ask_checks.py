"""질문 답변 코드 검사·근거 — EVIDENCE_IN_SCOPE 1줄·고정 표시 순서 (SCRUM-290 · SCRUM-362, 정본 docs/str/06 "질문 답변")."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_checks import cited_evidence_ids, opposite_direction_keys, question_side, run
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json

LABELS = load_display_labels()
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
PIECE = extract(MIXED, "R02_FAN_IN", ["flows", "counterparties"], LABELS)
CASE = "CASE-2022-000057"


def _check(answer: str, question: str = "이 케이스 거래 알려 줘"):
    (c,) = run(render(answer, PIECE, LABELS), question, CASE)
    assert c.check is CodeCheckName.EVIDENCE_IN_SCOPE and c.section is None and c.source_value is None
    return c


def test_pass_is_one_matching_line() -> None:
    c = _check("이 케이스에는 {{inbound.count|이}} 있어요.")
    assert (c.match, c.reason, c.draft_value) == (True, None, None)


@pytest.mark.parametrize(
    ("answer", "mark", "reason"),
    [
        ("{{paths.count}} {{customer.industry}}", "인용 키 범위 밖 2개", CheckReason.OUT_OF_SCOPE),
        ("{{inbound.count", "자리표 오류 1개", CheckReason.UNPARSED),
        ("{{inbound.count|만}}", "자리표 오류 1개", CheckReason.UNPARSED),
        ("CASE-2022-000058 의 {{inbound.count|이에요}}", "다른 케이스 번호 1개", CheckReason.OUT_OF_SCOPE),
        ("{{inbound.count|이에요}} 5건이에요.", "자리표 밖 숫자 1개", CheckReason.UNPARSED),
        ("입금은 모두 다섯 건이에요.", "자리표 밖 숫자 1개", CheckReason.UNPARSED),
        ("입금이 수천 달러예요.", "자리표 밖 숫자 1개", CheckReason.UNPARSED),
        ("입금은 확인돼요.", "자리표 없음", CheckReason.MISSING),
        (
            "{{inbound.count|을}} 송금했어요.",
            "자리표 밖 서술어 1개",
            CheckReason.UNPARSED,
        ),  # 추가 검토 3 허용 목록
        (
            "{{inbound.count|이에요}}" + " 확인돼요." * 100,
            "답 길이 넘침",
            CheckReason.UNPARSED,
        ),  # 허용 끝맺음(추가 검토 3)
    ],
    ids=[
        "scope",
        "no-close",
        "particle",
        "other-case",
        "arabic",
        "korean-numeral",
        "rough",
        "no-slot",
        "predicate",
        "long",
    ],
)
def test_failure_marks(answer: str, mark: str, reason: CheckReason) -> None:
    c = _check(answer)
    assert (c.match, c.draft_value, c.reason) == (False, mark, reason)


def test_order_scope_before_error_before_numbers() -> None:
    assert _check("{{paths.count}} {{inbound.count 3건").draft_value == "인용 키 범위 밖 1개"
    assert _check("{{inbound.count 3건").draft_value == "자리표 오류 1개"


@pytest.mark.parametrize(
    "answer",
    [
        "{{inbound.count|이에요}} 세 곳이에요.",
        "{{inbound.count|이에요}} 한 번에 받았어요.",
        "{{inbound.count|이에요}} 두 계좌예요.",
        "{{inbound.count|이에요}} 2022-09-03 이에요.",
        "{{inbound.count|이에요}} 10_****BD30 이에요.",
        "{{inbound.count|이에요}} CASE-2022-000057 이에요.",  # 자기 케이스 번호도(★A 5)
        "{{inbound.count|이에요}} R02 룰이에요.",
        "{{inbound.count|이에요}} １２건이에요.",  # 전각 — NFKC 뒤
    ],
    ids=["se-got", "han-beon", "du-gyejwa", "date", "account", "own-case", "rule-id", "fullwidth"],
)
def test_outside_numbers_are_caught(answer: str) -> None:
    assert _check(answer).draft_value.startswith("자리표 밖 숫자")


@pytest.mark.parametrize(
    "answer",
    [
        "{{inbound.count|이에요}} 두 방향 모두 있어요.",
        "{{inbound.count|이에요}} 이 케이스 근거예요.",
        "{{inbound.count|이에요}} 세부 내역은 없어요.",
        "{{inbound.count|이에요}} 대한 건은 없어요.",  # '한 건' 앞이 한글 — 낱말 안
    ],
    ids=["du-banghyang", "i-case", "sebu", "daehan-geon"],
)
def test_words_without_unit_are_not_numbers(answer: str) -> None:
    assert _check(answer).match


@pytest.mark.parametrize(
    ("question", "side"),
    [
        ("입금 상대 계좌는 몇 개야?", "inbound"),
        ("보낸 돈은 얼마야?", "outbound"),
        ("입출금 상대 계좌는 모두 몇 개야?", "both"),  # 추가 검토 2 H4 — 양방향도 검사(★B5 때 None)
        ("입금과 출금은 각각 몇 건이야?", "both"),
        ("출금 말고 입금만 몇 건이야?", "inbound"),
        ("입금 전체 합계는?", "inbound"),
        ("상대 계좌는 몇 개야?", None),
    ],
)
def test_question_side(question: str, side: str | None) -> None:
    assert question_side(question) == side


def _opp(keys: list[str], q: str) -> int:
    answer = " ".join("{{" + k + "}}." for k in keys)
    return opposite_direction_keys(render(answer, PIECE, LABELS), q)


def test_opposite_direction_keys_only() -> None:
    q = "입금 상대 계좌는 몇 개야?"
    assert _opp(["counterparties_by_direction.outbound.count"], q) == 1
    assert _opp(["outbound.count", "counterparties_by_direction.outbound.count"], q) == 2
    # 추가 검토 1 H3 — 지표가 다르면 덮지 못함(★B2 때는 0 = 통과였음, 구현을 따라 쓴 단언)
    assert _opp(["counterparties_by_direction.inbound.count", "outbound.count"], q) == 1
    assert (
        _opp(["counterparties_by_direction.inbound.count", "counterparties_by_direction.outbound.count"], q)
        == 0
    )
    assert _opp(["counterparties.count"], q) == 0  # 방향 없는 키는 안 셈
    # 추가 검토 2 H4 — 양방향 질문도 검사: 한쪽만 쓰면 실패(★B5 때는 0 = 건너뜀)
    assert _opp(["outbound.count"], "입출금 상대는?") == 1
    assert _opp(["outbound.count", "inbound.count"], "입출금 상대는?") == 0


def test_opposite_direction_mark_and_premise_correction_passes() -> None:
    c = _check("{{counterparties_by_direction.outbound.count|이에요}}", "입금 상대 계좌는 몇 개야?")
    assert (c.match, c.draft_value, c.reason) == (False, "반대 방향 키만 1개", CheckReason.MISMATCH)
    ok = _check(
        "{{inbound.count|이라}}", "입금 상대 계좌는 몇 개야?"
    )  # 모르는 조사 → 오류가 먼저(이고 는 ★B7-3 에 목록 안)
    assert ok.draft_value == "자리표 오류 1개"
    fixed = _check(
        "이 케이스에는 {{counterparties_by_direction.inbound.count|이}} 있어요. "
        "{{counterparties_by_direction.outbound.count|이에요}}",
        "입금 상대 계좌는 몇 개야?",
    )
    assert fixed.match


def test_evidence_ids_are_union_of_slot_keys() -> None:
    inbound = cited_evidence_ids(MIXED, ["counterparties_by_direction.inbound.count"])
    assert inbound == sorted(MIXED.inbound.transaction_ids)
    both = cited_evidence_ids(MIXED, ["inbound.count", "outbound.count", "typology", "no.such"])
    assert both == sorted({*MIXED.inbound.transaction_ids, *MIXED.outbound.transaction_ids})
    assert cited_evidence_ids(MIXED, ["prior_alert_count"]) == []
