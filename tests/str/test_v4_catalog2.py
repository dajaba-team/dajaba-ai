"""SCRUM-269 v4-catalog-2 — 고객 등록일 · 흐름 문장 · 가중 평균 표기 · 판정 문장·C0 고정 (docs/str/05, 09 SCRUM-269). LLM·DB 0.

③-1 "고객 등록일은 …" 은 06 DATE 가 개설일 용도(onboarded_at)로 읽음 — 정상 match · 날짜 변조 MISMATCH · 부재는 DATE 결과 없음.
③-3 흐름 문장 표 = 05 표 · 전제 하나라도 거짓이면 없음. 판정 문장·C0 는 develop d57f05a(v4-catalog-1)와 글자까지 같음.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import grounds_flow, masking
from aml_ai.str.domain.constants_v4 import V4_CATALOG_VERSION
from aml_ai.str.domain.grounds_flow import FLOW_ITEMS, flow_item
from aml_ai.str.domain.typology_support_text import c0_template, support_sentence
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.judge_stability_v4 import build_cases
from tests.str.judge_stability_v4_live import run_meta
from tests.str.test_judge_v4_criteria import DEMO
from tests.str.v4_slot_support import assembled, code_checks, load_fixture

ROOT = Path(__file__).resolve().parents[2]
FROZEN = json.loads(
    (Path(__file__).resolve().parent / "v4_verdict_c0_frozen.json").read_text(encoding="utf-8")
)
LABELS = load_display_labels()


@pytest.fixture(scope="module")
def cases() -> list[Any]:
    return [c for c in build_cases(DEMO) if c.kind == "v4"]


def _section(case: Any, name: str) -> str:
    return next(s.text for s in case.narrative if s.section.value == name)


def test_verdict_and_c0_unchanged_from_develop(cases: list[Any]) -> None:
    """254 v4 18건 — GROUNDS 첫 문장(판정)·OPINION 둘째(C0) 가 269 전 값과 글자까지 같음."""
    assert {c.case_id for c in cases} == set(FROZEN["cases"]) and len(cases) == 18
    for c in cases:
        want = FROZEN["cases"][c.case_id]
        masked = masking.mask_for_llm(c.facts)
        assert support_sentence(masked, LABELS).text == want["verdict"], c.case_id  # type: ignore[union-attr]
        assert _section(c, "GROUNDS").startswith(want["verdict"]), c.case_id
        opinion = [s if s.endswith(".") else f"{s}." for s in _section(c, "OPINION").split(". ")]
        assert (opinion[1] if c0_template(masked) else None) == want["c0"], c.case_id


def test_flow_only_on_supported_cases(cases: list[Any]) -> None:
    """뒷받침됨 6건(sup 4 · mix · demo_7)만 흐름 문장이 GROUNDS 둘째."""
    texts = [i.variants[0] for i in FLOW_ITEMS.values()]
    with_flow = set()
    for c in cases:
        grounds = _section(c, "GROUNDS")
        item = flow_item(masking.mask_for_llm(c.facts))
        if item is None:
            assert not any(t in grounds for t in texts), c.case_id
            continue
        with_flow.add(c.case_id)
        assert grounds.startswith(f"{FROZEN['cases'][c.case_id]['verdict']} {item.variants[0]}"), c.case_id
    assert with_flow == {
        "blind2:sup_fan_in",
        "blind2:sup_fan_out",
        "blind2:sup_cycle",
        "blind2:sup_scatter_gather",
        "blind2:mix_fan_in",
        "demo_7",
    }


def _doc_flow_rows() -> dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    rows = {}
    for line in (ROOT / "docs/str/05_prompts.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| `G-FLOW-"):
            cells = [x.strip() for x in line.strip("|").split("|")]
            cites = tuple(re.findall(r"`([^`]+)`", cells[3]))
            requires = tuple(x.strip() for x in cells[4].split("·"))
            rows[cells[0].strip("`")] = (cells[1], cells[2], cites, requires)
    return rows


def test_flow_table_matches_05() -> None:
    doc = _doc_flow_rows()
    assert len(doc) == len(FLOW_ITEMS) == 4
    for typology, item in FLOW_ITEMS.items():
        assert doc[item.id] == (typology, item.variants[0], item.cites, item.requires), item.id
        assert item.required and len(item.variants) == 1


@pytest.mark.parametrize("typology", list(FLOW_ITEMS))
def test_each_false_premise_drops_flow(typology: str, monkeypatch: pytest.MonkeyPatch) -> None:
    item = FLOW_ITEMS[typology]
    facts = {"typology": typology}
    names = ("has_inbound", "has_outbound", "has_counterparty", "path_verified", "cycle_verified",
             "typology_supported", "typology_unsupported")  # fmt: skip
    monkeypatch.setattr(grounds_flow, "premises", lambda f: dict.fromkeys(names, True))
    assert flow_item(facts) is item
    for name in item.requires:
        monkeypatch.setattr(grounds_flow, "premises", lambda f, n=name: {k: k != n for k in names})
        assert flow_item(facts) is None, (typology, name)


def _date_checks(facts: Any, sections: list[Any]) -> list[Any]:
    return [
        c
        for c in code_checks(facts, sections)
        if c.check.value == "DATE_MATCH" and c.section.value == "SUBJECT"
    ]


def test_customer_registration_date_is_onboard_use() -> None:
    """거래 기간(2022-09-02) 밖 날짜지만 개설일 용도로 읽혀 match — 바꾸면 MISMATCH."""
    facts = load_fixture("facts_fan_in.json")
    sections = assembled(facts)
    subject = next(s for s in sections if s.section is SectionV2.SUBJECT)
    assert "고객 등록일은 2021년 3월 14일임." in subject.text and "계좌 개설일" not in subject.text
    [ok] = _date_checks(facts, sections)
    assert ok.match and ok.source_value == "onboarded_at 2021-03-14"
    bad = [
        s.model_copy(update={"text": s.text.replace("2021년 3월 14일", "2021년 3월 15일")})
        if s is subject
        else s
        for s in sections
    ]
    [miss] = _date_checks(facts, bad)
    assert not miss.match


def test_missing_registration_date_has_no_date_check() -> None:
    facts = load_fixture("facts_multi_currency.json")
    sections = assembled(facts)
    subject = next(s for s in sections if s.section is SectionV2.SUBJECT)
    assert "고객 등록일은 자료 없음." in subject.text
    assert _date_checks(facts, sections) == []


def test_weighted_average_wording_removed_values_kept() -> None:
    """표기만 — 피처 이름·단위 그대로, 괄호 설명 없음."""
    names, units = LABELS["observation_name"], LABELS["observation_name_unit"]
    assert names["evidence_paid_max_share"] == "통화별 최대 지급 금액 비중"
    assert names["evidence_received_max_share"] == "통화별 최대 수취 금액 비중"
    assert units["evidence_paid_max_share"] == units["evidence_received_max_share"] == ""
    assert not any("가중 평균" in v or v.endswith(")") for v in names.values())


def test_catalog_version_is_recorded_in_05() -> None:
    assert V4_CATALOG_VERSION == "v4-catalog-3"
    assert f"`{V4_CATALOG_VERSION}` = SCRUM-269" in (ROOT / "docs/str/05_prompts.md").read_text(
        encoding="utf-8"
    )


def test_254_result_meta_records_catalog_version() -> None:
    meta = run_meta([7, 48], 19, {"prompt": "judge_v4"}, "registered", [])
    assert meta["catalog_version"] == V4_CATALOG_VERSION and meta["mode"] == "registered"
