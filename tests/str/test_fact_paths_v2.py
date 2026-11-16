"""SCRUM-182 — 경로형 룰 v2: R05_SCATTER_GATHER 확인·FX_RELAY 받기 (docs/str/04 "경로", shared/01).

develop 에서 실패: PATH_RULE_KIND 에 R05_SCATTER_GATHER 없음(kind null) · Typology 에 FX_RELAY 없음(400).
"""

from __future__ import annotations

from typing import Any

import pytest

from aml_ai.shared.schemas.alerts import ScoreRequest
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import DraftRequest, PathKind, PathStatus
from aml_ai.str.infrastructure.narrative_rewriter import build_paths_notice
from aml_ai.str.infrastructure.retriever import TYPOLOGY_KO
from tests.conftest import EXAMPLES, load_json
from tests.str.facts_support import CASES, build

SG = CASES["scatter_gather"]

V2_RULE_TYPOLOGIES = ["FAN_OUT", "FAN_IN", "FX_RELAY", "CYCLE", "SCATTER_GATHER", "GATHER_SCATTER"]


def _build(case: dict[str, Any]):
    return build(case, rule_id=case["rule_id"], paths=case["paths"])


def test_scatter_gather_facts_split_inbound_and_indirect() -> None:
    """S→Mᵢ 는 대상 T 가 안 낀 거래라 indirect, Mᵢ→T 는 inbound. 상대 수 = Mᵢ 수 = paths.count."""
    f = _build(SG)
    exp = SG["expect"]
    assert f.indirect.transaction_ids == exp["indirect_ids"]
    assert f.inbound.transaction_ids == exp["inbound_ids"]
    assert f.counterparties.count == exp["counterparties"] == f.paths.count


@pytest.mark.parametrize("name", CASES["kind_null_cases"])
def test_non_path_rule_kind_null(name: str) -> None:
    """옛 R05_STACK·R03_FX_RELAY(paths 모양 〔제안〕) 는 경로 모양이 맞아도 kind null·UNVERIFIED."""
    f = _build(CASES["unverified_cases"][name])
    assert f.paths is not None
    assert f.paths.kind is None and f.paths.status is PathStatus.UNVERIFIED


@pytest.mark.parametrize("name", [n for n in CASES["unverified_cases"] if n.startswith("sg_")])
def test_scatter_gather_rule_break_is_unverified_with_kind(name: str) -> None:
    """SG 6종(3건·S 다름·끝 ≠ T·Mᵢ 중복·같은 분·연결 끊김) — kind 는 SCATTER_GATHER, status 만 UNVERIFIED."""
    f = _build(CASES["unverified_cases"][name])
    assert f.paths is not None
    assert f.paths.kind is PathKind.SCATTER_GATHER and f.paths.status is PathStatus.UNVERIFIED


def test_path_kind_has_no_stack() -> None:
    assert [k.value for k in PathKind] == ["CYCLE", "SCATTER_GATHER"]


def test_scatter_gather_notice_only_when_unverified() -> None:
    verified = _build(SG)
    bad = CASES["unverified_cases"]["sg_same_minute"]
    unverified = build(bad, rule_id=bad["rule_id"], paths=bad["paths"])
    assert build_paths_notice("R05_SCATTER_GATHER", verified) == ""
    assert "경로는 확인 필요" in build_paths_notice("R05_SCATTER_GATHER", unverified)
    assert "경로는 확인 필요" not in build_paths_notice("R05_STACK", unverified)


def test_r03_fx_relay_alert_passes_draft_schema() -> None:
    d = load_json(EXAMPLES / "draft_request.json")
    d["alert"].update(rule_id="R03_FX_RELAY", typology_hint="FX_RELAY")
    assert DraftRequest.model_validate(d).alert.typology_hint is Typology.FX_RELAY


def test_score_batch_with_one_fx_relay_alert_passes() -> None:
    """R03 경보 1건이 섞여도 500건 묶음 전체가 400 이 되지 않는다."""
    d = load_json(EXAMPLES / "score_request.json")
    one = d["alerts"][0]
    alerts = [{**one, "alert_id": f"ALT-20220903-{i:06d}"} for i in range(500)]
    alerts[123] = {**alerts[123], "rule_id": "R03_FX_RELAY", "typology_hint": "FX_RELAY"}
    req = ScoreRequest.model_validate({**d, "alerts": alerts})
    assert req.alerts[123].typology_hint is Typology.FX_RELAY


def test_typology_first_six_are_v2_rule_order() -> None:
    """앞 6개 = v2 룰 typology_hint(rules.md 순서), 원천 pattern_type·후보 값은 지우지 않고 뒤에 (★A-6)."""
    values = [t.value for t in Typology]
    assert values[:6] == V2_RULE_TYPOLOGIES
    assert {"STACK", "BIPARTITE", "RANDOM", "PASS_THROUGH"} <= set(values[6:])
    assert list(TYPOLOGY_KO)[:6] == V2_RULE_TYPOLOGIES
