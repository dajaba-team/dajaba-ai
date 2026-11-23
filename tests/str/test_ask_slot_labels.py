"""질문 답변 자리표 이름표 표 — 한 줄 = 테스트 하나 (SCRUM-362, 정본 docs/str/04 "답 자리표" 표).

값은 마스킹 조각에서만(계좌는 가린 모양). 합성 픽스처라 이름·값은 테스트 데이터.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_slot_labels import slot
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json

LABELS = load_display_labels()
ALL = ["subject", "flows", "counterparties"]


def _content(case: str, bundles: list[str], rule: str = "R02_FAN_IN") -> dict:
    return extract(
        Facts.model_validate(load_json(FIXTURES / f"facts_{case}.json")), rule, bundles, LABELS
    ).content


MIXED = _content("ask_mixed", ALL)
MULTI = _content("multi_currency", ["flows", "formats"])
PATHS = _content("ask_paths", ["paths", "rule_facts", "score_reasons"], "R05_SCATTER_GATHER")
MIXED_FMT = _content("ask_mixed_formats", ["formats"], "R01_FAN_OUT")


@pytest.mark.parametrize(
    ("key", "content", "want"),
    [
        ("inbound.count", MIXED, ("입금 거래", "2건")),
        ("outbound.count", MIXED, ("출금 거래", "3건")),
        ("internal.count", MIXED, ("내부 거래", "0건")),
        ("inbound.amount.USD", MIXED, ("입금 합계", "27,250.50 USD")),
        ("outbound.amount.USD", MIXED, ("출금 합계", "24,500.25 USD")),
        ("amount_range.USD.max", MIXED, ("입출금 중 최대 거래 금액", "15,000.00 USD")),
        ("amount_range.USD.min", MIXED, ("입출금 중 최소 거래 금액", "7,000.00 USD")),
        ("counterparties.count", MIXED, ("입출금 전체 상대 계좌", "4개")),
        ("counterparty_banks.same_bank_accounts", MIXED, ("입출금 전체 상대 중 자행 계좌", "0개")),
        ("counterparty_banks.other_bank_accounts", MIXED, ("입출금 전체 상대 중 타행 계좌", "4개")),
        ("counterparties_by_direction.inbound.count", MIXED, ("입금 상대 계좌", "2개")),
        ("counterparties_by_direction.outbound.count", MIXED, ("출금 상대 계좌", "3개")),
        ("counterparties_by_direction.inbound.other_bank_accounts", MIXED, ("입금 상대 중 타행 계좌", "2개")),
        ("counterparties_by_direction.outbound.same_bank_accounts", MIXED, ("출금 상대 중 자행 계좌", "0개")),
        ("direction", MIXED, ("거래 방향", "입금·출금 모두")),
        ("period", MIXED, ("거래 기간", "2022년 9월 3일 01:05 ~ 2022년 9월 3일 21:40")),
        ("subject.account_key", MIXED, ("대상 계좌", "10_****BD30")),
        ("subject.entity_type", MIXED, ("대상자 유형", "개인사업자")),
        ("subject.entity_name", MIXED, ("보고 대상자", "Sole Proprietorship #50438")),
        ("subject", MIXED, ("보고 대상자", "Sole Proprietorship #50438(개인사업자)")),
        ("customer.industry", MIXED, ("업종", "소매업")),
        ("customer.risk_level", MIXED, ("고객 위험등급", "낮음")),
        ("customer.account_purpose", MIXED, ("계좌 목적", "매출 대금 수납")),
        ("customer.onboarded_at", MIXED, ("고객 등록일", "2021년 3월 14일")),
        ("customer.country_code", MIXED, ("고객 국가 코드", "PT")),
        ("prior_alert_count", MIXED, ("과거 경보", "1건")),
        ("inbound.amount.EUR", MULTI, ("입금 합계", "9,800.25 EUR")),
        ("unmapped_currencies.Peso Uruguay", MULTI, ("Peso Uruguay 통화 거래", "1건(대응 미확인)")),
        ("period", MULTI, ("거래 기간", "2022년 9월 2일 00:14 ~ 2022년 9월 4일 22:51:30")),
        ("payment_formats", MIXED_FMT, ("결제 방식", "ACH, 전신환(Wire) (대외 거래 기준)")),
        ("payment_format_counts.Wire", MIXED_FMT, ("결제 방식 전신환(Wire)", "2건 (대외 거래 기준)")),
        ("paths.count", PATHS, ("확인된 경로", "3개")),
        ("paths.max_hops", PATHS, ("경로 최대", "2단계")),
        ("paths.max_accounts", PATHS, ("경로 하나가 거친 계좌 최대", "3개")),
        ("paths.kind", PATHS, ("경로 형태", "분산 후 집중(SCATTER_GATHER)")),
        ("typology", PATHS, ("탐지 유형", "분산 후 집중(SCATTER_GATHER)")),
        (
            "model_signals",
            PATHS,
            ("모델이 주목한 지표", "inflow_outflow_ratio_2h"),
        ),  # 표기 사전에 없음 → 코드값
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_label_table_row(key: str, content: dict, want: tuple[str, str]) -> None:
    assert slot(key, content, LABELS) == want


def test_observation_with_label_unit_and_window() -> None:
    content = {
        "observations": [
            {
                "name": "evidence_count",
                "value": 3.0,
                "unit": None,
                "window_start": "2022-09-02T00:14:00Z",
                "window_end": "2022-09-02T22:51:00Z",
            }
        ]
    }
    title, value = slot("observations.evidence_count", content, LABELS)
    assert title == f"{LABELS['observation_name']['evidence_count']} 관측값"
    assert value == "3건(2022-09-02T00:14:00Z~2022-09-02T22:51:00Z 기준)"


def test_observation_without_label_uses_code_and_unit_label() -> None:
    title, value = slot("observations.inflow_outflow_ratio_2h", PATHS, LABELS)
    assert (
        title == "inflow_outflow_ratio_2h 관측값" and value == "1"
    )  # ratio 단위 표기는 빈 글자, score_reasons 는 구간 없음


@pytest.mark.parametrize(
    "key",
    ["inbound.amount.EUR", "inbound.total", "amount_range.USD.avg", "nope", "customer.industry"],
)
def test_missing_or_unknown_is_none(key: str) -> None:
    assert slot(key, PATHS, LABELS) is None
