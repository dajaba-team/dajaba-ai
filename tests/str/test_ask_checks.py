"""질문 답변 코드 검사·근거 (SCRUM-290 2/2, 정본 docs/str/06 "질문 답변에 도는 코드 검사")."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts
from aml_ai.str.domain.ask_checks import cited_evidence_ids, run
from aml_ai.str.domain.fact_keys import fact_keys
from tests.conftest import FIXTURES, load_json

FAN_IN = Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))
PIECE_KEYS = ("period", "inbound.count", "inbound.amount.USD", "direction")


def _names(checks) -> list[str]:
    return [c.check.value for c in checks]


def test_cites_in_piece_add_one_matching_evidence_row() -> None:
    checks = run(FAN_IN, "입금 거래는 모두 3건이에요.", ["inbound.count"], PIECE_KEYS)
    assert _names(checks) == ["COUNT_MATCH", "EVIDENCE_IN_SCOPE"]
    assert all(c.match for c in checks)
    ev = checks[-1]
    assert ev.draft_value is None and ev.reason is None


def test_sentence_without_date_has_no_date_missing() -> None:
    checks = run(FAN_IN, "입금 상대 계좌는 3개예요.", ["inbound.count"], PIECE_KEYS)
    assert "DATE_MATCH" not in _names(checks)
    assert all(c.section is None for c in checks)


def test_answer_without_checked_numbers_still_gets_evidence_row() -> None:
    checks = run(FAN_IN, "거래 방향은 입금 쪽이에요.", ["direction"], PIECE_KEYS)
    assert _names(checks) == ["EVIDENCE_IN_SCOPE"]
    assert checks[0].match is True


@pytest.mark.parametrize(
    "cites, bad",
    [
        (["inbound.count", "no.such.key"], "no.such.key"),  # fact 키 밖
        (["inbound.count", "counterparties.count"], "counterparties.count"),  # fact 키 안·묶음 밖
    ],
    ids=["outside-facts", "outside-bundle"],
)
def test_cites_outside_scope_fail_with_out_of_scope(cites: list[str], bad: str) -> None:
    assert bad not in PIECE_KEYS
    checks = run(FAN_IN, "입금 거래는 모두 3건이에요.", cites, PIECE_KEYS)
    ev = checks[-1]
    assert ev.check is CodeCheckName.EVIDENCE_IN_SCOPE
    assert ev.match is False and ev.reason is CheckReason.OUT_OF_SCOPE
    assert ev.draft_value == "인용 키 범위 밖 1개" and ev.section is None  # 모델 문자열 반사 안 함


def test_piece_key_missing_from_facts_is_out_of_scope() -> None:
    """조각 키라도 이 케이스 fact 키 목록에 없으면 밖 — 교집합(06 2번)."""
    checks = run(FAN_IN, "경로는 확인됐어요.", ["paths.count"], (*PIECE_KEYS, "paths.count"))
    assert checks[-1].match is False and checks[-1].draft_value == "인용 키 범위 밖 1개"


def test_free_text_cites_are_not_reflected_in_draft_value() -> None:
    """추가 검토 1 high — cites 에 답 문장을 넣어도 draft_value 는 고정 표시(개수만)."""
    sentence = "입금 거래는 모두 5건이에요."
    ev = run(FAN_IN, sentence, [sentence, "no.such.key"], PIECE_KEYS)[-1]
    assert ev.draft_value == "인용 키 범위 밖 2개"
    assert sentence not in ev.model_dump_json()


def test_check_order_amount_date_count_account_evidence() -> None:
    text = "2022-09-02T00:14:00 부터 입금 3건, 42750.50 USD 가 대상 계좌 10_****BD30 으로 들어왔어요."
    checks = run(FAN_IN, text, ["inbound.count", "inbound.amount.USD", "period"], PIECE_KEYS)
    assert _names(checks) == [
        "AMOUNT_MATCH",
        "DATE_MATCH",
        "COUNT_MATCH",
        "ACCOUNT_ID_MATCH",
        "EVIDENCE_IN_SCOPE",
    ]
    assert all(c.match for c in checks)


def test_wrong_count_is_mismatch() -> None:
    checks = run(FAN_IN, "입금 거래는 모두 5건이에요.", ["inbound.count"], PIECE_KEYS)
    count = checks[0]
    assert count.check is CodeCheckName.COUNT_MATCH
    assert count.match is False and count.reason is CheckReason.MISMATCH


def test_cited_evidence_ids_union_and_keys_without_transactions() -> None:
    keys = fact_keys(FAN_IN)
    want = sorted(set(keys["inbound.count"]) | set(keys["period"]))
    assert cited_evidence_ids(FAN_IN, ["inbound.count", "period"]) == want
    assert cited_evidence_ids(FAN_IN, ["subject.entity_name"]) == []  # 거래 안 달리는 키
    assert cited_evidence_ids(FAN_IN, ["no.such.key"]) == []


# ───────── SCRUM-290 2/2 F3 회귀 — `거래 시작` 은 개설 단어가 아님 (06 · 09 2026-11-20) ─────────


@pytest.mark.parametrize(
    "text",
    [
        "거래 시작은 2022-09-02 00:14, 끝은 2022-09-02 22:51이에요.",
        "거래 시작일시는 2022-09-02T00:14:00, 거래 종료일시는 2022-09-02T22:51:00으로 보여요.",
    ],
    ids=["space-time", "iso-t"],
)
def test_transaction_start_word_is_period_not_onboarding(text: str) -> None:
    checks = run(FAN_IN, text, ["period"], PIECE_KEYS)
    dates = [c for c in checks if c.check is CodeCheckName.DATE_MATCH]
    assert len(dates) == 2 and all(c.match for c in dates)
    assert all("period" in (c.source_value or "") for c in dates)


@pytest.mark.parametrize("text", ["개설일은 2021-03-14 이에요.", "고객 등록일은 2021-03-14 이에요."])
def test_onboarding_words_still_match_onboarded_at(text: str) -> None:
    checks = run(FAN_IN, text, ["customer.onboarded_at"], ("customer.onboarded_at",))
    (d,) = [c for c in checks if c.check is CodeCheckName.DATE_MATCH]
    assert d.match and "onboarded_at" in (d.source_value or "")


@pytest.mark.parametrize(
    "text",
    [
        "입금 거래 개시일시는 2021-03-14, 거래 종료일시는 2022-09-02T22:51:00이에요.",
        "당행 고객과의 첫 거래 시작일시는 2022-09-02T00:14:00이에요.",
    ],
    ids=["gaesi-ilsi", "customer-ilsi"],
)
def test_review2_start_wordings_do_not_pass(text: str) -> None:
    """추가 검토 2 반례 — 질문 답변 경로에서도 통과(ANSWERED) 안 됨."""
    checks = run(FAN_IN, text, ["period"], PIECE_KEYS)
    assert not all(c.match for c in checks)
