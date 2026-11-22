"""SCRUM-340 추가 검토 3 회귀 — v2 허용 문자열 대조: 범위 기호 · 미등록 코드 · 공백 낀 부호·괄호 · 날짜 뒤 괄호 ·
관측값·건수·날짜 섞인 정상 문장. 검사 결과와 서비스 LLM 호출 횟수를 함께 고정."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts
from aml_ai.str.application.summary_service import SummaryService
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_generator import SummaryGenerator
from tests.str.summary_service_support import StubLlm

LABELS = load_display_labels()
FAN_IN = Facts.model_validate(
    json.loads((Path(__file__).parent / "fixtures" / "facts_fan_in.json").read_text(encoding="utf-8"))
)  # USD 입금 합계 42,750.50 · 범위 12,500.00~16,250.50
GOOD = ["입금 합계는 42,750.50 미국 달러(USD)임."]


def _checks(lines: list[str]) -> list:
    return run_summary_code_checks(FAN_IN, lines, FAN_IN.inbound.transaction_ids, display_labels=LABELS)


def _calls(first: list[str]) -> int:
    stub = StubLlm(responses=[json.dumps({"summary_lines": x, "model_focus": None}) for x in (first, GOOD)])
    s = get_settings()
    svc = SummaryService(
        settings=s, session=None, reader=None, generator=SummaryGenerator(stub, s), repo=None
    )  # type: ignore[arg-type]
    req = SimpleNamespace(evidence_transaction_ids=FAN_IN.inbound.transaction_ids, case_no="C")
    svc._generate_and_check(req, "g-t", FAN_IN, time.monotonic() + 60)  # type: ignore[arg-type]  # noqa: SLF001
    return len(stub.calls)


BAD = [
    pytest.param(["입금 3건의 건별 금액은 1.00~16,250.50 미국 달러(USD)임."], id="H1-range-wrong-first"),
    pytest.param(["입금 3건, 합계는 8,881.00 NZD임."], id="H2-unregistered-code"),
    pytest.param(["입금 합계는 - 42,750.50 미국 달러(USD)임."], id="H3-spaced-sign"),
    pytest.param(["입금 합계는 42,750.50 미국 달러  (EUR)임."], id="H3-spaced-paren-code"),
]


@pytest.mark.parametrize("lines", BAD)
def test_bad_lines_have_failing_amount_row(lines: list[str]) -> None:
    amount = [c for c in _checks(lines) if c.check is CodeCheckName.AMOUNT_MATCH]
    assert amount and any(not c.match and c.reason is CheckReason.MISMATCH for c in amount)


@pytest.mark.parametrize("lines", BAD)
def test_bad_lines_regenerate(lines: list[str]) -> None:
    assert _calls(lines) == 2


GOOD_LINES = [
    pytest.param(["2022-09-02(ACH) 입금 합계는 42,750.50 미국 달러(USD)임."], id="H4-date-then-paren"),
    pytest.param(
        ["2022-09-02 보고 대상 계좌(10_****BD30)로 ACH 입금 3건이 들어옴.", "관측 비중은 0.85임.", *GOOD],
        id="obs-count-date",
    ),
    pytest.param(
        ["건별 최소 금액은 12,500.00 미국 달러(USD)임.", "건별 최대 금액은 16,250.50 미국 달러(USD)임."],
        id="range-lines",
    ),
    pytest.param(
        ["보고 대상자는 Sole Proprietorship #50438 이며, 입금 합계는 42,750.50 미국 달러(USD)임."],
        id="hash-id",
    ),
]


@pytest.mark.parametrize("lines", GOOD_LINES)
def test_good_lines_all_match(lines: list[str]) -> None:
    assert all(c.match for c in _checks(lines))


@pytest.mark.parametrize("lines", GOOD_LINES)
def test_good_lines_one_call(lines: list[str]) -> None:
    assert _calls(lines) == 1
