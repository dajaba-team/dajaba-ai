"""SCRUM-340 추가 검토 2 회귀 — 방향 대조 뺌(정상 문장 통과·방향/종류 바꿔 쓰기는 알려진 한계) · 괄호 통째로 읽기 ·
부호 · 한 줄에 금액 하나 · v2 일 때만 표기 사전(v1 되돌림) · 서비스 재생성 여부."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools.record_summary import _build_summary_prompt

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import RecordedLlmClient, recording_key
from aml_ai.shared.schemas.str import CheckReason, Facts
from aml_ai.str.application.summary_service import SummaryService
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.infrastructure import summary_prompt_input
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_generator import FEWSHOT_ROOT, SummaryGenerator
from tests.str.summary_service_support import StubLlm

LABELS = load_display_labels()
FIXTURES = Path(__file__).parent / "fixtures"
V1_KEY = "61197a2180216230"
PASS = Facts.model_validate(
    json.loads((FEWSHOT_ROOT / "summary_v2" / "002_pass_through.json").read_text(encoding="utf-8"))["facts"]
)  # 입금 합계 30,000.00 · 출금 합계 29,800.00 · 범위 14,800.00~15,000.00 (USD)


def _rows(lines: list[str], facts: Facts = PASS) -> list:
    ids = facts.inbound.transaction_ids + facts.outbound.transaction_ids
    base = run_summary_code_checks(facts, lines, ids)
    return run_summary_code_checks(facts, lines, ids, display_labels=LABELS)[len(base) :]


def _all(lines: list[str], facts: Facts = PASS) -> list:
    ids = facts.inbound.transaction_ids + facts.outbound.transaction_ids
    return run_summary_code_checks(facts, lines, ids, display_labels=LABELS)


# --- H1 방향 대조 뺌 ------------------------------------------------------------------------------


def test_h1_normal_outbound_sentence_matches() -> None:
    assert all(c.match for c in _all(["입금 2건이 있었고 총 29,800.00 미국 달러(USD)가 출금됨."]))


def test_h1_wrong_direction_known_limit() -> None:
    assert all(c.match for c in _all(["29,800.00 미국 달러(USD)가 입금됨."]))  # 통과(알려진 한계)


# --- H2 종류 바꿔 쓰기 — 기록만 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "line", ["입금 합계는 14,800.00 미국 달러(USD)임.", "건별 최소 금액은 30,000.00 미국 달러(USD)임."]
)
def test_h2_kind_swap_known_limit(line: str) -> None:
    assert all(c.match for c in _all([line]))  # 통과(알려진 한계)


# --- H3 괄호 통째로 -----------------------------------------------------------------------------


def test_h3_spaced_paren_wrong_code_mismatch() -> None:
    (row,) = _rows(["입금 합계는 30,000.00 미국 달러( EUR )임."])
    assert not row.match and row.reason is CheckReason.MISMATCH


def test_h3_paren_only_with_spaces_is_checked() -> None:
    rows = _rows(["14,900.00 ( USD )"])
    assert len(rows) == 1 and not rows[0].match  # 검사 0개 아님


def test_h3_unreadable_paren_fails() -> None:
    """검토 3 — 허용 문자열이 아니면 나머지 금액 모양 규칙으로 MISMATCH(검토 2 땐 UNPARSED)."""
    (row,) = _rows(["입금 합계는 30,000.00 미국 달러(US D)임."])
    assert not row.match and row.reason is CheckReason.MISMATCH


def test_h3_spaced_paren_right_code_fails() -> None:
    """검토 3 — 글자 그대로가 아니면(괄호 안 공백) 실패 → 재생성. 검토 2 땐 통과였음."""
    assert not any(r.match for r in _rows(["입금 합계는 30,000.00 미국 달러( USD )임."]))


# --- M4 부호 --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line", ["입금 합계는 −30,000.00 미국 달러(USD)임.", "입금 합계는 -30,000.00 (USD)임."]
)
def test_m4_signed_amount_mismatch(line: str) -> None:
    (row,) = _rows([line])
    assert not row.match and row.reason is CheckReason.MISMATCH and row.draft_value.lstrip()[0] in "−-"


# --- M7 한 줄에 금액 하나 ---------------------------------------------------------------------------


def test_m7_two_amounts_in_one_line_mismatch() -> None:
    line = "입금 합계는 30,000.00 미국 달러(USD), 출금 합계는 29,800.00 미국 달러(USD)임."
    rows = _rows([line])
    assert (
        len(line) <= 80
        and len(rows) == 2
        and all(not r.match and r.reason is CheckReason.MISMATCH for r in rows)
    )


# --- M6 v2 일 때만 표기 사전 ------------------------------------------------------------------------


def _broken_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom():  # noqa: ANN202
        raise FileNotFoundError("display labels missing")

    monkeypatch.setattr(summary_prompt_input, "load_display_labels", boom)


def test_m6_v1_without_labels_keeps_key_and_replays(monkeypatch: pytest.MonkeyPatch) -> None:
    _broken_labels(monkeypatch)
    facts = Facts.model_validate(json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8")))
    assert recording_key(*_build_summary_prompt(facts, "summary_v1")) == V1_KEY
    s = get_settings()
    gen = SummaryGenerator(RecordedLlmClient(s.recorded_dir), s, prompt="summary_v1")
    inp = gen.prepare(facts)
    res = gen.generate(inp.facts_llm, inp.fact_keys, inp.examples, deadline=time.monotonic() + 60)
    assert gen.labels is None and res.prompt_version == "summary_v1"


def test_m6_v2_still_needs_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    _broken_labels(monkeypatch)
    with pytest.raises(FileNotFoundError):
        SummaryGenerator(StubLlm(), get_settings(), prompt="summary_v2")


# --- 서비스: 정상은 1회, 오류 문장은 재생성 ------------------------------------------------------------


def _service_calls(first: list[str]) -> int:
    good = ["입금 합계는 30,000.00 미국 달러(USD)임.", "출금 합계는 29,800.00 미국 달러(USD)임."]
    stub = StubLlm(
        responses=[json.dumps({"summary_lines": lines, "model_focus": None}) for lines in (first, good)]
    )
    s = get_settings()
    svc = SummaryService(
        settings=s, session=None, reader=None, generator=SummaryGenerator(stub, s), repo=None
    )  # type: ignore[arg-type]
    req = SimpleNamespace(
        evidence_transaction_ids=PASS.inbound.transaction_ids + PASS.outbound.transaction_ids, case_no="C"
    )
    svc._generate_and_check(req, "g-t", PASS, time.monotonic() + 60)  # type: ignore[arg-type]  # noqa: SLF001
    return len(stub.calls)


@pytest.mark.parametrize(
    "lines",
    [
        ["입금 합계는 30,000.00 미국 달러(USD)임.", "출금 합계는 29,800.00 미국 달러(USD)임."],
        ["입금 2건이 있었고 총 29,800.00 미국 달러(USD)가 출금됨."],
    ],
)
def test_service_normal_lines_one_call(lines: list[str]) -> None:
    assert _service_calls(lines) == 1


@pytest.mark.parametrize(
    "lines",
    [
        ["입금 합계는 30,000.00 미국 달러( EUR )임."],
        ["입금 합계는 −30,000.00 미국 달러(USD)임."],
        ["입금 합계는 30,000.00 미국 달러(USD), 출금 합계는 29,800.00 미국 달러(USD)임."],
    ],
)
def test_service_error_lines_regenerate(lines: list[str]) -> None:
    assert _service_calls(lines) == 2
