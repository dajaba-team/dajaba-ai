"""SCRUM-340 summary_v2 — 요약 LLM 입력 금액 표기(`62,992,819.38 유로(EUR)`) · 원본 그대로 · 생성기 입력 (05 summary_v2)."""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import SUMMARY_PROMPT
from aml_ai.str.domain.summary_amounts import display_amount, with_display_amounts
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_generator import FEWSHOT_ROOT, SummaryGenerator, load_summary_fewshot

FIXTURES = Path(__file__).parent / "fixtures"
LABELS = load_display_labels()
_BARE = re.compile(r'"(?:total|min|max)": "\d+\.\d+"')  # 쉼표·통화 없는 옛 금액 칸


def _facts(name: str) -> Facts:
    return Facts.model_validate(json.loads((FIXTURES / f"facts_{name}.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("amount", "code", "expected"),
    [
        ("62992819.38", "EUR", "62,992,819.38 유로(EUR)"),  # Jira 예시
        ("999.00", "USD", "999.00 미국 달러(USD)"),  # 999 이하 쉼표 없음
        ("1000.00", "USD", "1,000.00 미국 달러(USD)"),
        ("1234567890123.50", "JPY", "1,234,567,890,123.50 일본 엔(JPY)"),  # 큰 금액
        ("12.345678", "BTC", "12.345678 비트코인(BTC)"),  # 소수 6자리 그대로
        (
            "42750.500000",
            "CHF",
            "42,750.500000 스위스 프랑(CHF)",
        ),  # 소수는 facts 문자열 그대로(반올림·자르기 0)
        ("0.00", "ILS", "0.00 이스라엘 셰켈(ILS)"),
    ],
)
def test_display_amount(amount: str, code: str, expected: str) -> None:
    assert display_amount(amount, code, LABELS) == expected


def test_unknown_currency_falls_back_to_code() -> None:
    assert display_amount("1500.00", "XXX", LABELS) == "1,500.00 XXX"
    llm = {"inbound": {"by_currency": [{"currency": "XXX", "total": "1500.00"}]}, "amount_range": []}
    out, missing = with_display_amounts(llm, LABELS)
    assert out["inbound"]["by_currency"][0]["total"] == "1,500.00 XXX" and missing == ["XXX"]


def test_every_money_field_changes_and_original_untouched() -> None:
    facts = _facts("multi_currency")
    before = facts.model_dump(mode="json")
    masked = masking.mask_for_llm(facts)
    masked_before = copy.deepcopy(masked)
    out, missing = with_display_amounts(masked, LABELS)
    assert missing == [] and masked == masked_before and facts.model_dump(mode="json") == before
    assert [c["total"] for c in out["inbound"]["by_currency"]] == [
        "9,800.25 유로(EUR)",
        "42,750.50 미국 달러(USD)",
    ]
    assert out["amount_range"][1] == {
        "currency": "USD",
        "min": "12,500.00 미국 달러(USD)",
        "max": "30,250.50 미국 달러(USD)",
    }
    assert not _BARE.search(json.dumps(out, ensure_ascii=False))  # 쉼표 없는 금액 칸 0
    rest = {k: v for k, v in out.items() if k not in ("inbound", "outbound", "amount_range")}
    assert rest == {k: v for k, v in masked.items() if k not in ("inbound", "outbound", "amount_range")}


def test_fact_amounts_are_never_negative() -> None:
    """금액 칸 패턴 `^\\d+\\.\\d{2,6}$` — 음수는 facts 에 못 들어옴(표기 함수는 부호를 다루지 않음)."""
    raw = json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8"))
    raw["inbound"]["by_currency"][0]["total"] = "-1.00"
    with pytest.raises(ValueError):
        Facts.model_validate(raw)


class _Capture:
    def __init__(self, text: str) -> None:
        self.text, self.users, self.tags = text, [], []

    def complete_json(self, *, system, user, model, max_tokens, tag, timeout_s=None) -> LlmResult:  # noqa: ANN001
        self.users.append(user)
        self.tags.append(tag)
        return LlmResult(text=self.text, model="stub", tokens_in=1, tokens_out=1, latency_ms=1)


def test_generator_sends_display_amounts_and_v2() -> None:
    facts = _facts("multi_currency")
    llm_facts, _ = with_display_amounts(masking.mask_for_llm(facts), LABELS)
    stub = _Capture(json.dumps({"summary_lines": ["입금 합계는 9,800.25 유로(EUR)임."], "model_focus": None}))
    gen = SummaryGenerator(stub, get_settings(), labels=LABELS)
    examples = load_summary_fewshot(facts.typology, prompt=SUMMARY_PROMPT)
    res = gen.generate(llm_facts, [], examples, deadline=time.monotonic() + 60)
    user = stub.users[0]
    assert (
        SUMMARY_PROMPT == "summary_v2" and res.prompt_version == "summary_v2" and stub.tags == ["summary_v2"]
    )
    assert "42,750.50 미국 달러(USD)" in user and "85,400.00 유로(EUR)" in user  # 본 FACTS · few-shot FACTS
    assert not _BARE.search(user)
    assert res.few_shot_ids == [e.example_id for e in examples] and set(res.few_shot_ids) <= {3, 4}


def test_v2_fewshot_lines_fit_and_pass_checks() -> None:
    for path in sorted((FEWSHOT_ROOT / "summary_v2").glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        facts = Facts.model_validate(d["facts"])
        assert all(len(line) <= 80 for line in d["summary_lines"])
        ids = facts.inbound.transaction_ids + facts.outbound.transaction_ids
        checks = run_summary_code_checks(facts, d["summary_lines"], ids)
        assert checks and all(c.match for c in checks), path.name
        assert "유로(EUR)" in "".join(d["summary_lines"]) or "미국 달러(USD)" in "".join(d["summary_lines"])


def test_v1_files_kept() -> None:
    root = FEWSHOT_ROOT.parent
    assert (root / "prompts" / "summary_v1.md").exists() and len(
        list((FEWSHOT_ROOT / "summary_v1").glob("*.json"))
    ) == 2
    assert (Path(__file__).parent / "recorded" / "summary_v1").is_dir()


def test_longest_label_one_currency_line_fits_80() -> None:
    """가장 긴 표기·큰 금액 한 통화 한 줄은 80자 안 · 두 통화를 한 줄에 쓰면 넘음(→ 프롬프트 "통화마다 따로 줄")."""
    longest = max(LABELS["currency"], key=lambda c: len(LABELS["currency"][c]))
    big = display_amount("999999999999.999999", longest, LABELS)
    assert len(f"같은 기간 입금 합계는 {big}임.") <= 80
    assert len(f"같은 기간 입금 합계는 {big}, {display_amount('999999999999.999999', 'SAR', LABELS)}임.") > 80


def test_record_tool_user_equals_service_user() -> None:
    """녹화 도구와 서비스가 같은 user 를 만들어야 녹화 키가 맞음(summary_v2 녹화 재생)."""
    from types import SimpleNamespace

    from tools.record_summary import _build_summary_prompt

    from aml_ai.str.application.summary_service import SummaryService

    facts = _facts("fan_in")
    line = json.dumps({"summary_lines": ["입금 3건이 들어옴."], "model_focus": None}, ensure_ascii=False)
    stub = _Capture(line)
    s = get_settings()
    svc = SummaryService(
        settings=s, session=None, reader=None, generator=SummaryGenerator(stub, s), repo=None
    )  # type: ignore[arg-type]
    req = SimpleNamespace(evidence_transaction_ids=facts.inbound.transaction_ids, case_no="CASE-T")
    svc._generate_and_check(req, "g-test", facts, time.monotonic() + 60)  # type: ignore[arg-type]  # noqa: SLF001
    assert stub.users[0] == _build_summary_prompt(facts)[1]
