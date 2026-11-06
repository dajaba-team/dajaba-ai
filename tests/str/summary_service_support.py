"""test_summary_service 공용 — Stub LLM·Reader·서비스 조립·샘플 LLM 응답 (SCRUM-129)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.str.application.summary_service import SummaryService
from aml_ai.str.domain.models import Customer, Subject, Transaction
from aml_ai.str.infrastructure.summary_generator import SummaryGenerator
from aml_ai.str.infrastructure.summary_repository import SummaryRepository


@dataclass
class StubLlm:
    """SummaryGenerator 가 쓰는 LlmClient — complete_json 한 메서드."""

    responses: list[str] = field(default_factory=list)
    exc_at: dict[int, Exception] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)

    def complete_json(self, *, system, user, model, max_tokens, tag, timeout_s=None) -> LlmResult:
        idx = len(self.calls)
        self.calls.append({"tag": tag})
        if idx in self.exc_at:
            raise self.exc_at[idx]
        return LlmResult(
            text=self.responses[idx], model="stub-summary", tokens_in=100, tokens_out=50, latency_ms=100
        )


@dataclass
class StubReader:
    """TransactionReader stub — fixtures/facts_fan_in.json 과 같은 숫자."""

    def load_transactions(self, ids: list[int]) -> list[Transaction]:
        amounts = {104221: "12500.00", 104233: "14000.00", 104301: "16250.50"}
        return [
            Transaction(
                transaction_id=tid,
                ts=datetime(2022, 9, 2, i * 7, 14 if i == 0 else 51, 0),
                from_account_key=f"OTHER_{tid}",
                to_account_key="010_8000EBD30",
                amount_paid=Decimal(amounts.get(tid, "14250.17")),
                currency_paid="USD",
                amount_received=Decimal(amounts.get(tid, "14250.17")),
                currency_received="USD",
                payment_format="ACH",
                is_self_transfer=False,
            )
            for i, tid in enumerate(ids)
        ]

    def load_subject(self, alert, txs: list[Transaction]) -> Subject:  # noqa: ARG002
        return Subject(
            account_key="010_8000EBD30",
            entity_id="80062E240",
            entity_name="Sole Proprietorship #50438",
            entity_type="SOLE_PROPRIETORSHIP",
            bank_name="Portugal Bank #4507",
            account_entities={"010_8000EBD30": "80062E240"},
            customer=Customer(
                industry="RETAIL",
                risk_level="LOW",
                account_purpose="SALES_DEPOSIT",
                onboarded_at=None,
                country_code="PT",
            ),
        )


class _NullRepo(SummaryRepository):
    def save(self, **_kw) -> None:
        pass


def ok_text() -> str:
    """facts_fan_in 과 맞는 코드 검사 통과 응답."""
    return json.dumps(
        {
            "summary_lines": [
                "2022-09-02 보고 대상 계좌로 ACH 입금 3건이 들어옴.",
                "같은 날 합계 42750.50 USD 입금이 발생함.",
            ],
            "model_focus": "모델은 account_in_counterparties_24h 신호를 가장 크게 봄",
        },
        ensure_ascii=False,
    )


def bad_amount_text() -> str:
    return json.dumps(
        {"summary_lines": ["같은 날 99999.99 USD 입금이 발생함."], "model_focus": None}, ensure_ascii=False
    )


def build_service(stub: StubLlm, *, clock=None) -> SummaryService:
    s = get_settings()
    gen = SummaryGenerator(stub, s, clock=clock or time.monotonic)
    return SummaryService(
        settings=s,
        session=None,
        reader=StubReader(),
        generator=gen,
        repo=_NullRepo(session=None),
        clock=clock or time.monotonic,
    )
