"""오류 주입 (docs/str/08 표). 활성/skip/live 세부는 08 표."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheckName,
    Facts,
    NarrativeSection,
    SectionV1,
)
from aml_ai.str.domain import verification
from tests.conftest import FIXTURES, load_json

ACTIVE = [1, 2, 3, 4, 5, 6, 15, 16, 17, 18, 19, 20, 21, 22, 24, 25, 26, 27, 28, 29, 30, 31]
SKIPPED_DET = [13, 32, 33, 34]
CASES_LIVE = [7, 8, 9, 10, 11, 12, 14, 23]


def _base_facts() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def _facts_total(total: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["inbound"]["by_currency"][0]["total"] = total
    return Facts.model_validate(data)


def _facts_with_range(min_: str, max_: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["amount_range"] = [{"currency": "USD", "min": min_, "max": max_}]
    return Facts.model_validate(data)


def _section(text: str) -> NarrativeSection:
    return NarrativeSection(section=SectionV1.SUMMARY, text=text, cites=[], evidence_ids=[])


def _check(fn: Callable, facts: Facts, text: str) -> list:
    return fn(facts, [_section(text)])


# ---------- 활성 (SCRUM-58) ----------


def test_injection_01_amount_value_mismatch() -> None:
    """금액 320,000,000 → 32,000,000 US Dollar."""
    checks = _check(verification.amount_match, _facts_total("320000000.00"), "입금 32,000,000 US Dollar")
    assert checks and all(not c.match for c in checks)
    assert all(c.reason is CheckReason.MISMATCH and c.check is CodeCheckName.AMOUNT_MATCH for c in checks)


def test_injection_02_korean_unit_pass() -> None:
    """금액을 한글 단위 `3억 2천만 US Dollar` — 통과해야 함 (거짓 양성 검사)."""
    checks = _check(verification.amount_match, _facts_total("320000000.00"), "입금 3억 2천만 US Dollar")
    assert checks and all(c.match for c in checks)


def test_injection_15_currency_mismatch() -> None:
    """값은 맞고 통화만 틀림 `320,000,000 EUR`."""
    checks = _check(verification.amount_match, _facts_total("320000000.00"), "입금 320,000,000 EUR")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


@pytest.mark.parametrize("text", ["입금 약 3억 US Dollar", "입금 삼억 이천만 US Dollar"])
def test_injection_17_unparsed(text: str) -> None:
    """근사·한글 수사 → UNPARSED (조용히 통과 안 함)."""
    checks = _check(verification.amount_match, _base_facts(), text)
    assert checks and all(not c.match and c.reason is CheckReason.UNPARSED for c in checks)


def test_injection_18_counterparty_account() -> None:
    """상대 계좌 식별자 `****A1F2` → MISMATCH."""
    checks = _check(verification.account_id_match, _base_facts(), "상대 계좌 ****A1F2 로 송금")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)
    assert all(c.check is CodeCheckName.ACCOUNT_ID_MATCH for c in checks)


def test_injection_29_amount_range_match() -> None:
    """amount_range min·max 사이 건당 `2,000,000 US Dollar` — 통과해야 함 (거짓 양성 검사)."""
    checks = _check(
        verification.amount_match,
        _facts_with_range("1500000.00", "22000000.00"),
        "건당 2,000,000 US Dollar 송금",
    )
    assert checks and all(c.match for c in checks)


# ---------- 활성 (SCRUM-59) ----------


def _wwh_section(text: str) -> NarrativeSection:
    """WHAT_WHEN_WHERE 섹션 — 날짜 주입 테스트는 거래 날짜 자리에서 돈다."""
    return NarrativeSection(section=SectionV1.WHAT_WHEN_WHERE, text=text, cites=[], evidence_ids=[])


def _who_section(text: str) -> NarrativeSection:
    return NarrativeSection(section=SectionV1.WHO, text=text, cites=[], evidence_ids=[])


def test_injection_03_date_out_of_period() -> None:
    """날짜를 기간 밖 `9월 5일` → MISMATCH."""
    checks = verification.date_match(_base_facts(), [_wwh_section("9월 5일 입금 47건")])
    bad = [c for c in checks if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH and c.check is CodeCheckName.DATE_MATCH for c in bad)


def test_injection_16_who_birthdate_pass() -> None:
    """WHO 섹션 개설일 `2021년 3월 14일` — 통과해야 함 (1차 검토가 잡은 오탐)."""
    checks = verification.date_match(_base_facts(), [_who_section("계좌 개설일은 2021년 3월 14일임")])
    assert checks and all(c.match for c in checks if c.check is CodeCheckName.DATE_MATCH)


def test_injection_19_birthdate_as_transaction_date() -> None:
    """개설일을 거래 날짜 자리에 `2021년 3월 14일에 47건 입금`(개설 단어 없음) → MISMATCH."""
    checks = verification.date_match(_base_facts(), [_wwh_section("2021년 3월 14일에 47건 입금")])
    bad = [c for c in checks if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_injection_21_two_dates_in_one_sentence_pass() -> None:
    """한 문장에 두 날짜 `2021년 3월 14일 개설, 2022년 9월 2일 47건 입금` — 가까운 쪽 규칙으로 둘 다 match."""
    checks = verification.date_match(
        _base_facts(), [_wwh_section("2021년 3월 14일 개설, 2022년 9월 2일 47건 입금")]
    )
    assert len([c for c in checks if c.match]) == 2


def test_injection_22_range_with_onboard_unparsed() -> None:
    """범위 표현에 개설 단어 `2021년 3월 14일과 2022년 9월 2일 사이 개설` → UNPARSED."""
    checks = verification.date_match(
        _base_facts(), [_who_section("2021년 3월 14일과 2022년 9월 2일 사이 개설")]
    )
    assert any(c.reason is CheckReason.UNPARSED for c in checks)


# ---------- SCRUM-60 활성(4·5·6·20·24~28·30·31)은 `test_injection_count.py` ----------
# ---------- 아직 skip (SCRUM-61 뒤 활성 또는 생성·평가자 영역) ----------


@pytest.mark.deterministic
@pytest.mark.parametrize("case", SKIPPED_DET)
def test_injection_deterministic_pending(case: int) -> None:
    pytest.skip(f"SCRUM-61/W4 — 오류 주입 #{case} (docs/str/08: RAG·스키마·생성·평가자)")


@pytest.mark.live
@pytest.mark.parametrize("prompt_name", ["judge_v2", "judge_v3"])
@pytest.mark.parametrize("case", [7, 8, 10, 11, 12])
def test_injection_live_judge_only(case: int, prompt_name: str) -> None:
    """SCRUM-127 live 하네스 — judge-only 5 케이스 × prompt(v2/v3) × N=3.

    진희 터미널에서 `uv run pytest tests/str/test_injection.py -m live` 로 돌림.
    모델 두 줄 비교는 `LLM_MODEL_JUDGE=<생성 모델>` 명령줄 환경변수로 두 번 실행(.env 안 건드림).
    assert 는 호출 성공만 — 점수 표는 결과 JSON 을 사람이 보고 08 표·09 결정에 반영.
    """
    from tests.str.injection_live_support import run_judge_only_case, save_results

    results = run_judge_only_case(case, n=3, prompt_name=prompt_name)
    path = save_results(results, f"{prompt_name}_c{case:02d}")
    assert path.exists() and len(results) == 3, f"saved to {path}"


@pytest.mark.live
@pytest.mark.parametrize("case", [9, 14, 23])
def test_injection_live_generate(case: int) -> None:
    """SCRUM-127 live 생성 케이스 — 모델①만, N=3, 08 표에만 기록(판정 안 씀).

    9 investigator_notes 지시문 / 14 REFERENCES FAN_OUT 사례 직접 주입 / 23 CYCLE paths=None.
    `LLM_MODEL_JUDGE` 덮어쓰기(모델②) 는 judge-only 만 돌림 — generate 는 모델① 한 번만.
    """
    from tests.str.injection_live_generate import run_generate_case
    from tests.str.injection_live_support import model_slot, save_results

    if model_slot() == "m2":
        pytest.skip("generate 케이스는 모델① 만 돌림 (SCRUM-127 — 판정 안 씀, 08 표용)")
    results = run_generate_case(case, n=3, prompt_name="judge_v3")
    path = save_results(results, f"gen_c{case:02d}")
    assert path.exists() and len(results) == 3, f"saved to {path}"


@pytest.mark.live
@pytest.mark.parametrize("case", [23])
def test_injection_live_rewrite(case: int) -> None:
    """SCRUM-147 live — 고쳐 쓰기(draft_service 흐름, DB 없이) 뒤 TYPO 재측정 (모델① N=3)."""
    from tests.str.injection_live_generate import run_generate_rewrite_case
    from tests.str.injection_live_support import model_slot, save_results

    if model_slot() == "m2":
        pytest.skip("rewrite 케이스는 모델① 만 돌림 (판정 재료)")
    results = run_generate_rewrite_case(case, n=3, prompt_name="judge_v3")
    path = save_results(results, f"rewrite_c{case:02d}")
    assert path.exists() and len(results) == 3, f"saved to {path}"
