"""SCRUM-265 (1/2) — v2 표기 통일 흔적 정리 (09 2026-11-17 "SCRUM-265 1/2 표기 정리"). LLM·DB 0.

반례 = 228 공개 md(v4blind_20261116-202556)에 흔적을 남긴 v2 원본 문장 그대로. 숫자 덩이 불변 · 멱등.
"""

from __future__ import annotations

import re

import pytest

from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_blind_support import unify_notation
from tests.str.v4_slot_support import load_raw_fixture as load_fixture

LABELS = load_display_labels()
FACTS = load_fixture("facts_scatter_gather.json")  # inflow_outflow_ratio_2h → 유입액에서 유출액을 뺀 값
_NUM = re.compile(r"\d+")
# (v2 원본, 정리 뒤) — 228 공개 md 흔적: 개인사업자(개인사업자)·소매업(소매업)·매출대금 입금(매출 대금 수납)·값는·자료는 자료 없음
COUNTER = [
    (
        "보고 대상자는 Sole Proprietorship #50438이며 엔티티 유형은 개인사업자(SOLE_PROPRIETORSHIP), 업종은 소매업(RETAIL)임.",
        "보고 대상자는 Sole Proprietorship #50438이며 엔티티 유형은 개인사업자, 업종은 소매업임.",
    ),
    (
        "보고 대상자는 Sole Proprietorship #50438이며 엔티티 유형은 SOLE_PROPRIETORSHIP, 업종은 소매업(RETAIL)임.",
        "보고 대상자는 Sole Proprietorship #50438이며 엔티티 유형은 개인사업자, 업종은 소매업임.",
    ),
    (
        "고객 위험등급은 LOW이며 계좌 목적은 매출대금 입금(SALES_DEPOSIT)임.",
        "고객 위험등급은 낮음이며 계좌 목적은 매출대금 입금임.",
    ),
    (
        "상대방 3곳으로부터 대상 계좌로 입금 3건이 유입된 집중 입금(FAN_IN) 유형으로 보임.",
        "상대방 3곳으로부터 대상 계좌로 입금 3건이 유입된 집중 입금(FAN_IN) 유형으로 보임.",
    ),
    (
        "분산 송금(FAN_OUT) 유형으로 보여 자금세탁 의심 여부에 대한 검토가 필요함.",
        "분산 송금(FAN_OUT) 유형으로 보여 자금세탁 의심 여부에 대한 검토가 필요함.",
    ),
    (
        "유형 표시는 CYCLE이나 이를 뒷받침하는 순환·연쇄 이체 경로 자료는 자료 없음.",
        "유형 표시는 자금 순환(CYCLE)이나 이를 뒷받침하는 순환·연쇄 이체 경로 자료는 없음.",
    ),
    (
        "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-02T02:00:00 기준)에서 inflow_outflow_ratio_2h는 1.0으로 제시됨.",
        "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-02T02:00:00 기준)에서 유입액에서 유출액을 뺀 값은 1.0으로 제시됨.",
    ),
    ("모델 관측값과 평소 거래 비교 자료는 자료 없음.", "모델 관측값과 평소 거래 비교 자료는 없음."),
]  # fmt: skip


@pytest.mark.parametrize(("raw", "want"), COUNTER)
def test_counterexamples_from_228_are_cleaned(raw: str, want: str) -> None:
    assert unify_notation(raw, LABELS, FACTS).text == want


@pytest.mark.parametrize(("raw", "want"), COUNTER)
def test_numbers_unchanged_and_idempotent(raw: str, want: str) -> None:
    names = {o.name for o in FACTS.observations} | set(FACTS.model_signals)
    values = re.sub("|".join(re.escape(n) for n in names), "", raw)
    once = unify_notation(raw, LABELS, FACTS).text
    assert _NUM.findall(once) == _NUM.findall(values)
    assert unify_notation(once, LABELS, FACTS).text == once


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("업종은 RETAIL은 아님.", "업종은 소매업은 아님."),  # 받침 있음 — 그대로
        ("위험등급 LOW는 확인됨.", "위험등급 낮음은 확인됨."),
        ("유형 CYCLE와 경로.", "유형 자금 순환(CYCLE)과 경로."),  # 괄호 앞 낱말 받침 기준
        ("결제 방식 Wire를 씀.", "결제 방식 전신환을 씀."),
        ("통화 USD를 씀.", "통화 미국 달러(USD)를 씀."),  # 받침 없음 — 그대로
        ("위험등급 HIGH이며 확인됨.", "위험등급 높음이며 확인됨."),  # 이며 는 조사 쌍이 아님
        ("엔티티 INDIVIDUAL가 보냄.", "엔티티 개인이 보냄."),
        ("목적 TRADE로 표시.", "목적 무역으로 표시."),
        ("목적 PAYROLL으로 표시.", "목적 급여 지급으로 표시."),  # 맞으면 그대로
    ],
)
def test_particle_follows_label_final_consonant(raw: str, want: str) -> None:
    assert unify_notation(raw, LABELS, FACTS).text == want


def test_field_noun_before_paren_keeps_label() -> None:
    """괄호 앞이 항목 이름(업종·목적 등)이면 지우면 뜻이 사라짐 — 표기를 괄호 안에 남김."""
    assert unify_notation("업종(RETAIL) 확인.", LABELS, FACTS).text == "업종(소매업) 확인."


def test_same_word_paren_collapses() -> None:
    assert unify_notation("업종은 소매업(소매업)임.", LABELS, FACTS).text == "업종은 소매업임."
    assert unify_notation("통화는 미국 달러(USD)임.", LABELS, FACTS).text == "통화는 미국 달러(USD)임."


def test_real_feature_name_uses_observation_name_label() -> None:
    """재블라인드 사건 — 실제 이름·basis model_feature 는 사전 observation_name 표기로(관측 항목 아님)."""
    from tests.str.v4_blind2_cases import case_facts, load_cases

    facts = case_facts(load_cases())["sup_fan_in"]
    out = unify_notation("모델이 주목한 항목은 focal_distinct_senders이며 값은 7임.", LABELS, facts)
    assert out.text == "모델이 주목한 항목은 대상 계좌에 송금한 서로 다른 계좌 수이며 값은 7임."
    assert "관측 항목" not in unify_notation("evidence_count는 7건임.", LABELS, facts).text


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("계좌목적(SALES_DEPOSIT)으로 등록됨.", "계좌목적(매출 대금 수납)으로 등록됨."),  # 추가 검토 1차 재현
        ("엔티티유형(SOLE_PROPRIETORSHIP)임.", "엔티티유형(개인사업자)임."),
        ("위험등급(LOW)이며 확인됨.", "위험등급(낮음)이며 확인됨."),
        ("매출 대금 입금(SALES_DEPOSIT)임.", "매출 대금 입금임."),  # 별칭 표
        ("비소매업(RETAIL)임.", "비소매업(소매업)임."),  # 표기로 끝나도 낱말 경계가 아니면 안 지움
    ],
)
def test_paren_code_dropped_only_after_confirmed_word(raw: str, want: str) -> None:
    """앞말이 사전 표기·별칭 표와 같을 때만 괄호째 지움, 아니면 표기를 괄호에 남김."""
    assert unify_notation(raw, LABELS, FACTS).text == want


def test_parenthesized_feature_name_keeps_label() -> None:
    from tests.str.v4_blind2_cases import case_facts, load_cases

    facts = case_facts(load_cases())["sup_fan_in"]
    out = unify_notation("모델 관측값(focal_distinct_senders)은 7임.", LABELS, facts).text
    assert out == "모델 관측값(대상 계좌에 송금한 서로 다른 계좌 수)은 7임."


def test_alias_table_is_fixed() -> None:
    from tests.str.v4_blind_notation_cleanup import PAREN_ALIASES

    assert PAREN_ALIASES == {"SALES_DEPOSIT": ("매출대금 입금", "매출 대금 입금")}
