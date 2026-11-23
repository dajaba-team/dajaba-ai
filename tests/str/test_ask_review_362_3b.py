"""추가 검토 3(SCRUM-362) 반례 2 — ★B7-3 연결 조사 이며/며 · 이고/고 · 문장부호 뒤 받침 (정본 docs/str/04 "답 자리표" 조사).

v6 녹화 P6·K2 꼴(`{{키|이며}}`)을 본 뒤 고치기 전에 넣어 실패를 확인. LLM 없음(가짜 LLM).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_scope import AskScope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

LABELS = load_display_labels()
WHOLE = AskScope(
    whole_alert=True, ownership_known=True
)  # 범위 표시가 아닌 렌더링 시험 — 근거 = 경보 전체(★B8)
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
FAN_IN = Facts.model_validate(load_json(FIXTURES / "facts_ask_fan_in.json"))


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _status(question: str, answer: str, bundles: list[str], facts: Facts, kind: str = "FACT") -> AskStatus:
    llm = StubLlm([plan_text(kind, None, bundles), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")).status


# ---------- ★B7-3 연결 조사 이며/며 · 이고/고 · 문장부호 뒤 받침 ----------


def test_v6_p6_shape_with_imyeo_particle_is_answered() -> None:
    answer = "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이며}}, {{inbound.count|이}} 확인돼요."
    assert _status("2023년 1월에 들어온 거래는 몇 건이야?", answer, ["flows"], FAN_IN) is AskStatus.ANSWERED


def test_v6_k2_shape_with_imyeo_particle_is_answered() -> None:
    answer = (
        "{{direction|이며}} {{typology|으로}} 탐지된 케이스예요. {{payment_format_counts.ACH|이}} 확인돼요."
    )
    status = _status(
        "왜 이 룰에 걸렸는지랑 결제 방식도 알려 줘", answer, ["rule_facts", "formats"], FAN_IN, "WHY"
    )
    assert status is AskStatus.ANSWERED


@pytest.mark.parametrize("particle", ["이며", "며", "이고", "고"])
def test_connective_particles_render_by_last_hangul(particle: str) -> None:
    piece = extract(FAN_IN, "R02_FAN_IN", ["formats"], LABELS, scope=WHOLE)
    text = render("{{payment_format_counts.ACH|" + particle + "}} 확인돼요.", piece, LABELS).text
    want = "이며" if particle in ("이며", "며") else "이고"
    assert text == f"결제 방식 ACH 3건 (대외 거래 기준){want} 확인돼요."


@pytest.mark.parametrize("particle", ["이라", "이랑", "하고", "라서", "이나"])
def test_other_particles_still_slot_error(particle: str) -> None:
    piece = extract(MIXED, "R02_FAN_IN", ["flows"], LABELS)
    assert render("{{inbound.count|" + particle + "}} 확인돼요.", piece, LABELS).errors == 1


@pytest.mark.parametrize(
    ("answer", "want"),
    [
        ("{{direction|으로}}", "거래 방향 입금 우세 (근거 거래 기준)으로"),  # 괄호 안 마지막 한글 `준`
        ("{{direction|이며}}", "거래 방향 입금 우세 (근거 거래 기준)이며"),
        ("{{typology|은}}", "탐지 유형 자금 집중(FAN_IN)은"),  # 괄호 안이 영문 → 괄호 앞 한글 `중`
        ("{{payment_formats|이에요}}", "결제 방식 ACH (대외 거래 기준)이에요"),
    ],
)
def test_particle_after_closing_paren_uses_last_hangul(answer: str, want: str) -> None:
    piece = extract(
        FAN_IN, "R02_FAN_IN", ["flows", "formats", "rule_facts"], LABELS, scope=AskScope(True, False)
    )  # 평가 픽스처와 같은 범위 — 방향은 우세 꼴(괄호)
    assert render(answer, piece, LABELS).text == want
