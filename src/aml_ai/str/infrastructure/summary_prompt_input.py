"""요약 프롬프트 입력 — 버전별 (SCRUM-340 추가 검토 1 M4). 서비스·녹화 도구가 같은 함수를 써 녹화 키가 같다.

`summary_v1` 은 develop 과 같은 입력(금액 문자열 그대로), `summary_v2` 만 금액 칸을 `62,992,819.38 유로(EUR)` 로 —
본 FACTS 와 few-shot FACTS 둘 다(`summary_amounts.llm_amounts`). few-shot 폴더는 `fewshot/{prompt}/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain import masking
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.domain.models import SummaryExample
from aml_ai.str.domain.summary_amounts import llm_amounts, uses_display_amounts
from aml_ai.str.infrastructure.display_labels import load_display_labels

FEWSHOT_ROOT = Path(__file__).resolve().parent.parent / "fewshot"
SUMMARY_FEWSHOT_COUNT = 2  # fewshot/{prompt}/001·002 (같은 유형 1 + 다른 유형 1)


@dataclass(frozen=True)
class SummaryInput:
    facts_llm: dict[str, Any]
    fact_keys: list[str]
    examples: list[SummaryExample]
    missing_labels: list[str]  # 표기 사전에 없던 통화 코드(v2 만)


def labels_for(prompt: str) -> Labels | None:
    """표기 버전일 때만 표기 사전을 읽음 — v1 되돌림은 사전 없이도 돎(검토 2 M6)."""
    return load_display_labels() if uses_display_amounts(prompt) else None


def prepare_summary_input(prompt: str, facts: Facts, labels: Labels | None) -> SummaryInput:
    facts_llm, missing = llm_amounts(prompt, masking.mask_for_llm(facts), labels)
    keys = list(fact_keys(facts).keys())
    return SummaryInput(facts_llm, keys, load_summary_fewshot(facts.typology, prompt=prompt), missing)


def render_summary_user(
    template: str,
    *,
    facts_masked: dict[str, Any],
    fact_keys: list[str],
    examples: list[SummaryExample],
    labels: Labels | None,
    prompt: str,
) -> str:
    """draft 와 같은 자리 치환 — few-shot 은 요약 모양. `facts_masked` 는 `prepare_summary_input` 의 LLM 복사본."""
    shots = "\n\n".join(
        f"FACTS:\n{json.dumps(_shot_facts(e, labels, prompt), ensure_ascii=False, indent=2)}\n"
        f"SUMMARY:\n{json.dumps({'summary_lines': e.summary_lines, 'model_focus': e.model_focus}, ensure_ascii=False)}"
        for e in examples
    )
    return (
        template.replace("{{facts_json}}", json.dumps(facts_masked, ensure_ascii=False, indent=2))
        .replace("{{fact_keys}}", "\n".join(fact_keys) or "(없음)")
        .replace("{{few_shot}}", shots)
    )


def _shot_facts(example: SummaryExample, labels: Labels | None, prompt: str) -> dict[str, Any]:
    return llm_amounts(prompt, example.facts.model_dump(mode="json"), labels)[0]


def load_summary_fewshot(
    typology: Typology | None, *, prompt: str, directory: Path | None = None
) -> list[SummaryExample]:
    """fewshot/{prompt}/*.json — 같은 유형 1 + 다른 유형 1 (총 2)."""
    directory = directory or (FEWSHOT_ROOT / prompt)
    all_examples: list[SummaryExample] = sorted(
        (_load_example(p) for p in directory.glob("*.json")), key=lambda e: e.example_id
    )
    same = [e for e in all_examples if e.typology == typology][:1]
    other = [e for e in all_examples if e.typology != typology][:1]
    picked = (same + other)[:SUMMARY_FEWSHOT_COUNT]
    return picked


def _load_example(path: Path) -> SummaryExample:
    d = json.loads(path.read_text(encoding="utf-8"))
    return SummaryExample(
        example_id=int(d["example_id"]),
        typology=d["typology"],
        facts=Facts.model_validate(d["facts"]),
        summary_lines=list(d["summary_lines"]),
        model_focus=d.get("model_focus"),
    )
