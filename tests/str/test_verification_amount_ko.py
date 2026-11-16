"""AMOUNT_MATCH 한국어 통화 이름·안전망·source_value (SCRUM-131 1/n). 정본 docs/str/06 "AMOUNT_MATCH".

W4 재현: `954831.63 일본 엔(JPY)` 값을 틀리게 바꿔도 AMOUNT_MATCH 줄이 없어 PASSED.
develop 에서 실패: `일본 엔` 별칭 없음 → 결과 0줄 · 안전망 없음 · source_value None.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts, SectionV1
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.domain.verification_amount_scan import find_pairs
from tests.conftest import FIXTURES, load_json
from tests.str.verification_support import amount

REPRO = "합계는 954831.63 일본 엔(JPY)임"

# 코드 → (국가명 붙은 이름, `~화` 모양). CAD·AUD 는 `달러화` 가 USD 라 국가명 + 화.
KO_NAMES: dict[str, tuple[str, str | None]] = {
    "USD": ("미국 달러", "달러화"),
    "EUR": ("유로", "유로화"),
    "CNY": ("중국 위안", "위안화"),
    "ILS": ("이스라엘 셰켈", "셰켈화"),
    "CAD": ("캐나다 달러", "캐나다 달러화"),
    "GBP": ("영국 파운드", "파운드화"),
    "RUB": ("러시아 루블", "루블화"),
    "AUD": ("호주 달러", "호주 달러화"),
    "CHF": ("스위스 프랑", "프랑화"),
    "JPY": ("일본 엔", "엔화"),
    "MXN": ("멕시코 페소", "페소화"),
    "INR": ("인도 루피", "루피화"),
    "BRL": ("브라질 헤알", "헤알화"),
    "SAR": ("사우디아라비아 리얄", "리얄화"),
    "BTC": ("비트코인", None),
}


def _facts(code: str, total: str, rng: tuple[str, str] | None = None) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    base = data["inbound"]["by_currency"][0]
    data["inbound"]["by_currency"] = [{**base, "currency": code, "total": total}]
    lo, hi = rng or (total, total)
    data["amount_range"] = [{"currency": code, "min": lo, "max": hi}]
    return Facts.model_validate(data)


JPY = _facts("JPY", "954831.63", ("1200.00", "15800.00"))


def _shapes() -> list[tuple[str, str]]:
    out = []
    for code, (name, hwa) in KO_NAMES.items():
        out += [(code, f"입금 100 {name} 확인"), (code, f"입금 100 {name}({code}) 확인")]
        if hwa:
            out.append((code, f"입금 100 {hwa} 확인"))
    return out


# ---------- 재현 ----------


def test_repro_japanese_yen_match() -> None:
    checks = amount(JPY, SectionV1.SUMMARY, REPRO)
    assert len(checks) == 1 and checks[0].match


def test_repro_japanese_yen_wrong_value_is_mismatch() -> None:
    checks = amount(JPY, SectionV1.SUMMARY, REPRO.replace("954831.63", "945831.63"))
    assert len(checks) == 1
    assert not checks[0].match and checks[0].reason is CheckReason.MISMATCH


# ---------- 15 통화 × 모양 ----------


@pytest.mark.parametrize(("code", "text"), _shapes())
def test_korean_currency_shapes_one_pair(code: str, text: str) -> None:
    assert [(p.currency, p.value) for p in find_pairs(text)] == [(code, Decimal("100"))]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("100 헤알", "BRL"),
        ("100 셰켈", "ILS"),
        ("100 이스라엘 쉐켈", "ILS"),
        ("100 사우디아라비아 리얄", "SAR"),
    ],
)
def test_standard_spellings(text: str, code: str) -> None:
    assert [(p.currency, p.value) for p in find_pairs(text)] == [(code, Decimal("100"))]


def test_aliases_live_in_constants_currency() -> None:
    from aml_ai.str.domain.constants_currency import CURRENCY_ALIASES

    assert "일본 엔" in CURRENCY_ALIASES["JPY"]


# ---------- 안전망 ----------


def test_safety_net_unknown_korean_name_is_unparsed() -> None:
    checks = amount(JPY, SectionV1.SUMMARY, "합계는 954831.63 일본국 엔임")
    assert len(checks) == 1
    assert not checks[0].match and checks[0].reason is CheckReason.UNPARSED


@pytest.mark.parametrize(
    "text",
    [
        "상대 계좌 31개 미국 달러 입금",
        "2건 일본 엔 입금",
        "2022-09-02 일본국 엔 입금",  # 안전망 숫자도 날짜 모양 제외
        "24 시간 미국 달러 입금",
        "3 계좌에서 미국 달러로 입금",
        "3 건의 미국 달러 입금",
    ],
)
def test_safety_net_no_false_positive(text: str) -> None:
    assert find_pairs(text) == []


def test_date_before_new_alias_same_as_existing_alias() -> None:
    """`2022-09-02 일본 엔` 은 기존 `2022-09-02 미국 달러` 와 같은 결과(SCRUM-58 끊긴 숫자 토큰 ⑤ — UNPARSED)."""
    jpy = [(p.raw, p.value) for p in find_pairs("2022-09-02 일본 엔 입금")]
    usd = [(p.raw, p.value) for p in find_pairs("2022-09-02 미국 달러 입금")]
    assert jpy == usd


def test_number_glued_to_currency_is_normal_pair() -> None:
    assert [(p.currency, p.value) for p in find_pairs("31 미국 달러")] == [("USD", Decimal("31"))]


# ---------- source_value ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("954831.63 일본 엔", "inbound.amount.JPY=954831.63"),
        ("건당 1500.00 일본 엔", "amount_range.JPY=1200.00~15800.00"),
        ("954831.00 일본 엔", "inbound.amount.JPY=954831.63 · amount_range.JPY=1200.00~15800.00"),
        ("100.00 유로", "facts에 EUR 없음 (JPY)"),
    ],
)
def test_source_value(text: str, expected: str) -> None:
    checks = amount(JPY, SectionV1.SUMMARY, text)
    assert len(checks) == 1 and checks[0].source_value == expected


def test_summary_path_catches_japanese_yen_mismatch() -> None:
    checks = run_summary_code_checks(JPY, [REPRO.replace("954831.63", "945831.63")], transaction_ids=[1])
    amounts = [c for c in checks if c.check is CodeCheckName.AMOUNT_MATCH]
    assert len(amounts) == 1 and amounts[0].reason is CheckReason.MISMATCH


def test_verifier_version_bumped() -> None:
    from aml_ai.str.domain.constants import VERIFIER_VERSION

    assert VERIFIER_VERSION == "verify-2026.11.4"


# ---------- 안전망 좁히기 (추가 검토 1차 — 본문·요약 둘 다) ----------

USD = _facts("USD", "42750.50")
NO_RESULT = [
    "모델 관측값 31.0 기준 미국 달러로 입금",
    "입금 47 건을 미국 달러로 처리",
    "입금은 47 건이며 미국 달러로 이루어짐",
]


def _amount_lines(facts: Facts, text: str, *, summary: bool) -> list:
    if summary:
        checks = run_summary_code_checks(facts, text.split("\n"), transaction_ids=[1])
        return [c for c in checks if c.check is CodeCheckName.AMOUNT_MATCH]
    return amount(facts, SectionV1.SUMMARY, text)


@pytest.mark.parametrize("summary", [False, True])
def test_number_already_paired_not_reused(summary: bool) -> None:
    lines = _amount_lines(USD, "총액은 42,750.50 미국 달러이며 일본 엔은 사용하지 않았다", summary=summary)
    assert [(c.draft_value, c.match) for c in lines] == [("42,750.50 (USD)", True)]


@pytest.mark.parametrize("summary", [False, True])
@pytest.mark.parametrize("text", [*NO_RESULT, "모델 관측값은 31.0\n입금 통화는 미국 달러임"])
def test_safety_net_narrowed_no_result(text: str, summary: bool) -> None:
    assert _amount_lines(USD, text, summary=summary) == []


@pytest.mark.parametrize("summary", [False, True])
def test_safety_net_still_catches_unknown_name(summary: bool) -> None:
    lines = _amount_lines(JPY, "합계는 954831.63 일본국 엔임", summary=summary)
    assert [c.reason for c in lines] == [CheckReason.UNPARSED]
