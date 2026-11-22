"""SCRUM-340 추가 검토 1 회귀 — v2 금액 표기 대조(H1 괄호 코드·H2 범위 안 다른 숫자) · 버전별 입력(M4) · 한 줄에 금액 하나(M5).

H2 의 방향 바꿔 쓰기는 검토 2 에서 대조를 빼고 "통과(알려진 한계)" 로 고정."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools.record_summary import _build_summary_prompt

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import RecordedLlmClient, recording_key
from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts
from aml_ai.str.application.summary_service import SummaryService
from aml_ai.str.domain.summary_amounts import display_amount
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_generator import FEWSHOT_ROOT, SummaryGenerator
from tests.str.summary_service_support import StubLlm

LABELS = load_display_labels()
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"
V1_KEY = "61197a2180216230"  # 보존된 recorded/summary_v1 녹화


def _fixture(name: str) -> Facts:
    return Facts.model_validate(json.loads((FIXTURES / f"facts_{name}.json").read_text(encoding="utf-8")))


def _shot(name: str) -> dict:
    return json.loads((FEWSHOT_ROOT / "summary_v2" / name).read_text(encoding="utf-8"))


def _eur_only() -> Facts:
    raw = json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8"))
    raw["inbound"]["by_currency"] = [
        {**raw["inbound"]["by_currency"][0], "currency": "EUR", "total": "62992819.38"}
    ]
    raw["amount_range"] = [{"currency": "EUR", "min": "1000.00", "max": "30000000.00"}]
    return Facts.model_validate(raw)


def _v2_amount_rows(facts: Facts, lines: list[str]) -> list:
    ids = facts.inbound.transaction_ids + facts.outbound.transaction_ids
    base = run_summary_code_checks(facts, lines, ids)
    return run_summary_code_checks(facts, lines, ids, display_labels=LABELS)[len(base) :]


# --- H1 ------------------------------------------------------------------------------------------


def test_h1_name_and_paren_code_disagree_is_mismatch() -> None:
    (row,) = _v2_amount_rows(_eur_only(), ["입금 합계는 62,992,819.38 유로(USD)임."])
    assert row.check is CodeCheckName.AMOUNT_MATCH and not row.match and row.reason is CheckReason.MISMATCH


def test_h1_paren_code_only_wrong_amount_is_checked() -> None:
    rows = _v2_amount_rows(_eur_only(), ["입금 합계는 62,992,819.39 (EUR)임."])
    assert len(rows) == 1 and not rows[0].match  # 검사 0개 아님
    assert rows[0].reason in (CheckReason.MISMATCH, CheckReason.UNPARSED)


# --- H2 ------------------------------------------------------------------------------------------


def test_h2_pass_through_swapped_totals_known_limit() -> None:
    """검토 2 에서 방향 대조를 뺌 — 줄을 나눠 입금·출금 합계를 맞바꾸면 통과(알려진 한계, 08·09).
    한 줄에 둘을 맞바꾸면 "한 줄에 금액 하나" 로 MISMATCH(test_summary_review2)."""
    facts = Facts.model_validate(_shot("002_pass_through.json")["facts"])
    rows = _v2_amount_rows(
        facts, ["입금 합계는 29,800.00 미국 달러(USD)임.", "출금 합계는 30,000.00 미국 달러(USD)임."]
    )
    assert len(rows) == 2 and all(r.match for r in rows)  # 통과(알려진 한계)


def test_h2_in_range_made_up_amount_mismatch() -> None:
    rows = _v2_amount_rows(_fixture("multi_currency"), ["입금 합계는 21,000.123456 미국 달러(USD)임."])
    assert len(rows) == 1 and not rows[0].match and rows[0].reason is CheckReason.MISMATCH


# --- 정상 문장 오탐 0 ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["001_fan_in.json", "002_pass_through.json"])
def test_v2_fewshot_lines_all_match(name: str) -> None:
    d = _shot(name)
    facts = Facts.model_validate(d["facts"])
    ids = facts.inbound.transaction_ids + facts.outbound.transaction_ids
    checks = run_summary_code_checks(facts, d["summary_lines"], ids, display_labels=LABELS)
    assert len(_v2_amount_rows(facts, d["summary_lines"])) >= 1 and all(c.match for c in checks)


def test_contract_example_v1_shape_fails_under_v2() -> None:
    """계약 예시 요약 줄(`42,750.50 USD` — 완성 표기가 아닌 v1 모양)은 v2 허용 문자열 대조에서 MISMATCH(검토 3).
    예시 JSON·응답 모양은 그대로 — 예시 검사(`test_summary_example_code_checks`)는 공용 4종만 돎."""
    resp = json.loads((EXAMPLES / "summary_response.json").read_text(encoding="utf-8"))
    facts = Facts.model_validate(
        json.loads((EXAMPLES / "draft_response.json").read_text(encoding="utf-8"))["facts"]
    )
    rows = _v2_amount_rows(facts, resp["summary_lines"])
    assert len(rows) == 1 and not rows[0].match and rows[0].reason is CheckReason.MISMATCH


def test_service_regenerates_once_on_v2_amount_failure() -> None:
    bad = json.dumps({"summary_lines": ["같은 날 입금 합계는 42,750.50 유로(USD)임."], "model_focus": None})
    good = json.dumps(
        {"summary_lines": ["같은 날 입금 합계는 42,750.50 미국 달러(USD)임."], "model_focus": None}
    )
    stub = StubLlm(responses=[bad, good])
    s = get_settings()
    svc = SummaryService(
        settings=s, session=None, reader=None, generator=SummaryGenerator(stub, s), repo=None
    )  # type: ignore[arg-type]
    facts = _fixture("fan_in")
    req = SimpleNamespace(evidence_transaction_ids=facts.inbound.transaction_ids, case_no="CASE-T")
    out = svc._generate_and_check(req, "g-t", facts, time.monotonic() + 60)  # type: ignore[arg-type]  # noqa: SLF001
    assert len(stub.calls) == 2 and all(c.match for c in out.code_checks)


# --- M4 ------------------------------------------------------------------------------------------


def test_m4_v1_input_key_equals_preserved_recording() -> None:
    assert recording_key(*_build_summary_prompt(_fixture("fan_in"), "summary_v1")) == V1_KEY


def test_m4_v1_replays_preserved_recording() -> None:
    s = get_settings()
    gen = SummaryGenerator(RecordedLlmClient(s.recorded_dir), s, prompt="summary_v1")
    facts = _fixture("fan_in")
    inp = gen.prepare(facts)
    assert (
        inp.facts_llm["inbound"]["by_currency"][0]["total"] == facts.inbound.by_currency[0].total
    )  # v1 은 변환 0
    res = gen.generate(inp.facts_llm, inp.fact_keys, inp.examples, deadline=time.monotonic() + 60)
    checks = run_summary_code_checks(facts, res.summary_lines, facts.inbound.transaction_ids)
    assert res.prompt_version == "summary_v1" and all(c.match for c in checks)


# --- M5 ------------------------------------------------------------------------------------------


def test_m5_one_amount_per_line_fits_with_longest_label() -> None:
    labels = load_display_labels()
    for line in _shot("002_pass_through.json")["summary_lines"]:
        assert line.count("(USD)") <= 1  # 한 줄에 금액 하나
    for template in ("입금 합계는 {}임.", "출금 합계는 {}임."):
        long_line = template.format(display_amount("1234567890.123456", "ILS", labels))
        assert len(long_line) <= 80
