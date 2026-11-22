"""SCRUM-340 ★L 뒤 — v2 "결제 방식별 건수도 한 줄에 한 방식" (공용 COUNT 검사기는 그대로).

실측: 결제 방식 4개를 한 줄에 나열한 v2 요약에서 COUNT 가 건수를 한 방식에 몰아 짝지어 MISMATCH(v1 0건) →
프롬프트 규칙으로 막음. 여기서는 한 줄 한 방식 문장이 COUNT match 인지와 v2 few-shot·프롬프트 문구를 고정.
"""

from __future__ import annotations

import json
from pathlib import Path

from aml_ai.shared.schemas.str import CodeCheckName, Facts
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_generator import FEWSHOT_ROOT

LABELS = load_display_labels()
ROOT = Path(__file__).resolve().parents[2]


def _four_formats() -> Facts:
    """fan_in 3건을 결제 방식 3종으로 나눈 facts(★L 경보처럼 방식 여러 개)."""
    raw = json.loads((ROOT / "tests" / "str" / "fixtures" / "facts_fan_in.json").read_text(encoding="utf-8"))
    raw["payment_format_counts"] = [
        {"format": "ACH", "count": 1},
        {"format": "Cheque", "count": 1},
        {"format": "Wire", "count": 1},
    ]
    return Facts.model_validate(raw)


def test_one_format_per_line_count_matches() -> None:
    facts = _four_formats()
    lines = ["ACH 결제는 1건임.", "Cheque 결제는 1건임.", "Wire 결제는 1건임."]
    checks = run_summary_code_checks(facts, lines, facts.inbound.transaction_ids, display_labels=LABELS)
    counts = [c for c in checks if c.check is CodeCheckName.COUNT_MATCH]
    assert len(counts) == 3 and all(c.match for c in checks)


def test_v2_fewshot_all_checks_pass() -> None:
    for path in sorted((FEWSHOT_ROOT / "summary_v2").glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        facts = Facts.model_validate(d["facts"])
        ids = facts.inbound.transaction_ids + facts.outbound.transaction_ids
        checks = run_summary_code_checks(facts, d["summary_lines"], ids, display_labels=LABELS)
        assert checks and all(c.match for c in checks), path.name


def test_prompt_has_one_format_per_line_rule() -> None:
    text = (ROOT / "src" / "aml_ai" / "str" / "prompts" / "summary_v2.md").read_text(encoding="utf-8")
    assert "결제 방식별 건수도 한 줄에 한 방식만" in text
