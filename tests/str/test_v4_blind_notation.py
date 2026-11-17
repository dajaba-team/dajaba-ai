"""SCRUM-228 (2/2) 1단계 — 블라인드 v2 표기 통일 (docs/str/08 "narrative_v4 블라인드 비교 하네스" 생성 줄). LLM·DB 0.

숫자 불변(값 숫자 — 피처 이름 속 숫자 제외) · 멱등 · 사전 밖 보고 · 피처 이름·방향 코드(첫 생성 반례 문장 그대로).
"""

from __future__ import annotations

import re

import pytest

from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_blind_support import unify_notation
from tests.str.v4_slot_support import load_raw_fixture as load_fixture  # v2 쪽 — 지어낸 이름 그대로

LABELS = load_display_labels()
V2_SAMPLES = [
    "보고 대상자는 SOLE_PROPRIETORSHIP 이며 업종은 RETAIL, 위험등급은 LOW 임.",
    "입금 합계는 42,750.50 USD 이고 결제 방식은 Wire 2건, Credit Card 1건임.",
    "FAN_IN 유형으로 분류됨. 계좌 목적은 SALES_DEPOSIT 임. 2022-09-02T00:14:00 부터 3건.",
    "모델 관측값(2022-09-02T00:00:00~2022-09-03T00:00:00 기준) 31개, 금액 0.004200 BTC.",
]
_NUM = re.compile(r"\d+")
FACTS = load_fixture(
    "facts_scatter_gather.json"
)  # observations[0] inflow_outflow_ratio_2h, basis inflow_minus_outflow
# 첫 생성(v4blind_20261116-200111) 공개 md 에서 표기 미통일로 나온 문장 그대로
COUNTER_DIRECTION = (
    "거래 방향은 입금(INBOUND)이며 상대방 3곳으로부터 입금 3건이 이루어진 것으로 파악됨. "
    "출금은 0건, 내부 거래는 0건으로 제시됨. 건별 금액 범위는 12500.00 미국 달러(USD)부터 16250.50 미국 달러(USD)까지임."
)
COUNTER_FEATURE = (
    "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-02T02:00:00 기준)에서 입출금 차이를 기준으로 한 "
    "inflow_outflow_ratio_2h 값은 1.0으로 제시됨. 비교 기준값은 자료 없음. 모델이 주목한 항목은 "
    "inflow_outflow_ratio_2h이며, 해당 관측값만으로 자금세탁 여부를 단정하기는 어려운 것으로 보임."
)


@pytest.mark.parametrize("text", [*V2_SAMPLES, COUNTER_DIRECTION, COUNTER_FEATURE])
def test_unify_keeps_every_number(text: str) -> None:
    """값 숫자(금액·날짜·건수)는 불변. 피처 이름 속 숫자(`..._2h`)는 이름째 표기로 바뀌므로 비교에서 뺌."""
    names = {o.name for o in FACTS.observations} | set(FACTS.model_signals)
    values = re.sub("|".join(re.escape(n) for n in names), "", text)
    assert _NUM.findall(unify_notation(text, LABELS, FACTS).text) == _NUM.findall(values)


def test_unify_replaces_codes_with_labels() -> None:
    out = " ".join(unify_notation(t, LABELS, FACTS).text for t in V2_SAMPLES)
    for want in (
        "개인사업자",
        "소매업",
        "낮음",
        "미국 달러(USD)",
        "전신환",
        "신용카드",
        "자금 집중(FAN_IN)",
        "매출 대금 수납",
        "비트코인(BTC)",
    ):
        assert want in out, want
    for gone in ("SOLE_PROPRIETORSHIP", "RETAIL", "SALES_DEPOSIT", " Wire ", "Credit Card"):
        assert gone not in out, gone


@pytest.mark.parametrize(
    "text",
    [*V2_SAMPLES, COUNTER_DIRECTION, COUNTER_FEATURE, "이미 미국 달러(USD)·자금 집중(FAN_IN) 으로 쓴 문장."],
)
def test_unify_is_idempotent(text: str) -> None:
    once = unify_notation(text, LABELS, FACTS)
    twice = unify_notation(once.text, LABELS, FACTS)
    assert twice.text == once.text and twice.replaced == []


def test_unify_direction_codes_from_first_run() -> None:
    res = unify_notation(COUNTER_DIRECTION, LABELS, FACTS)
    assert "INBOUND" not in res.text and "거래 방향은 입금이며" in res.text
    assert ("입금(INBOUND)", "입금") in res.replaced
    for raw, want in (("OUTBOUND", "출금"), ("INTERNAL", "내부 거래"), ("MIXED", "입금·출금 혼합")):
        out = unify_notation(f"거래 방향은 {raw}임.", LABELS, FACTS)
        assert out.text == f"거래 방향은 {want}임." and (raw, want) in out.replaced
    assert unify_notation("방향은 출금(OUTBOUND)임.", LABELS, FACTS).text == "방향은 출금임."


def test_unify_feature_names_to_basis_label_from_first_run() -> None:
    res = unify_notation(COUNTER_FEATURE, LABELS, FACTS)
    assert "inflow_outflow_ratio_2h" not in res.text
    assert res.text.count("유입액에서 유출액을 뺀 값") == 2
    assert ("inflow_outflow_ratio_2h", "유입액에서 유출액을 뺀 값") in res.replaced and res.unknown == []


def test_unify_feature_without_basis_becomes_generic_item() -> None:
    obs = FACTS.observations[0].model_copy(update={"basis": None})
    facts = FACTS.model_copy(update={"observations": [obs]})
    assert unify_notation("항목은 inflow_outflow_ratio_2h 임.", LABELS, facts).text == "항목은 관측 항목 임."
    only_signal = FACTS.model_copy(update={"observations": [], "model_signals": ["burst_count_1h"]})
    assert unify_notation("주목 항목 burst_count_1h.", LABELS, only_signal).text == "주목 항목 관측 항목."


def test_unify_reports_unknown_codes_and_keeps_them() -> None:
    res = unify_notation("업종은 SPACE_MINING 이고 통화는 USD 임.", LABELS, FACTS)
    assert res.unknown == ["SPACE_MINING"]
    assert "SPACE_MINING" in res.text and "미국 달러(USD)" in res.text
    assert ("USD", "미국 달러(USD)") in res.replaced


def test_unify_merges_repeated_word_after_label_from_first_run() -> None:
    """바꾼 표기 끝 낱말과 바로 뒤 낱말이 같으면 하나로 — v2 만 비문이 되면 결과가 기욺."""
    res = unify_notation(COUNTER_FEATURE, LABELS, FACTS)
    assert "값 값" not in res.text
    assert "유입액에서 유출액을 뺀 값은 1.0으로" in res.text
    assert unify_notation(res.text, LABELS, FACTS).text == res.text  # 멱등
    fan_in = load_fixture("facts_fan_in.json")  # account_in_counterparties_24h → 서로 다른 송금인 계좌 수
    out = unify_notation("관측된 account_in_counterparties_24h 수는 3개임.", LABELS, fan_in)
    assert out.text == "관측된 서로 다른 송금인 계좌 수는 3개임."
    plain = unify_notation("관측된 account_in_counterparties_24h 수 3개.", LABELS, fan_in)
    assert plain.text == "관측된 서로 다른 송금인 계좌 수 3개."


def test_unify_merges_only_same_word_or_with_particle() -> None:
    """끝 낱말 그대로이거나 조사만 붙은 경우만 합침 — 다른 낱말(수취인·수치·값비싼)은 그대로."""
    fan_in = load_fixture("facts_fan_in.json")
    label = "서로 다른 송금인 계좌 수"
    for tail in ("수취인 기준임.", "수치는 3임."):
        assert (
            unify_notation(f"account_in_counterparties_24h {tail}", LABELS, fan_in).text == f"{label} {tail}"
        )
    for tail, want in (("수가 3임.", "수가 3임."), ("수와 같음.", "수와 같음."), ("수 3개.", "수 3개.")):
        assert (
            unify_notation(f"account_in_counterparties_24h {tail}", LABELS, fan_in).text
            == f"{label[:-2]} {want}"
        )
