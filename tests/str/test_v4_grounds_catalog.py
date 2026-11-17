"""SCRUM-228 — 사유·종합의견 카탈로그 조건·짝·약화 없음 (docs/str/08 narrative_v4 3번)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_format import with_imeuro, with_imyeo
from aml_ai.str.domain.grounds_catalog import grounds_candidates
from aml_ai.str.domain.narrative_plan import Pick
from aml_ai.str.domain.opinion_catalog import opinion_candidates
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.v4_slot_support import load_fixture

LABELS = load_display_labels()
FAN_IN = masking.mask_for_llm(load_fixture("facts_fan_in.json"))
FAN_OUT = masking.mask_for_llm(load_fixture("facts_fan_out.json"))


def _with(base: dict, **changes: Any) -> dict:
    d = copy.deepcopy(base)
    for path, value in changes.items():
        node = d
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return d


def _gids(f: dict) -> list[str]:
    return [i.id for i in grounds_candidates(f, derive_flags(f))]


def _oids(f: dict) -> list[str]:
    return [i.id for i in opinion_candidates(f, derive_flags(f))]


def _texts(f: dict) -> dict[SectionV2, str]:
    return {s.section: s.text for s in build_v4(f, LABELS)}


@pytest.mark.parametrize(
    ("changes", "item", "present"),
    [
        ({}, "G-PURPOSE-IN", True),
        ({"customer": None}, "G-PURPOSE-IN", False),
        ({"customer__account_purpose": None}, "G-PURPOSE-IN", False),
        ({}, "G-COUNTERPARTY", True),
        ({"counterparties__count": 0}, "G-COUNTERPARTY", False),
        ({}, "G-PRIOR", True),
        ({"prior_alert_count": 0}, "G-PRIOR", False),
        ({"typology": "CYCLE"}, "G-CYCLE-PATH", False),  # 판정 문장이 대신(SCRUM-265 2/2)
        (
            {"typology": "CYCLE", "paths": {"kind": "CYCLE", "count": 1, "max_hops": 3, "max_accounts": 3}},
            "G-CYCLE-PATH",
            False,
        ),
        ({}, "G-CYCLE-PATH", False),
    ],
)
def test_grounds_item_follows_condition(changes: dict, item: str, present: bool) -> None:
    assert (item in _gids(_with(FAN_IN, **changes))) is present


def test_in_out_flip_switches_grounds_and_checks_together() -> None:
    """입금↔출금 뒤집은 짝 — 사유(G-PURPOSE-IN↔OUT)와 확인 사항(F*↔O*)이 같이 바뀜."""
    assert "G-PURPOSE-IN" in _gids(FAN_IN) and "G-PURPOSE-OUT" not in _gids(FAN_IN)
    assert "G-PURPOSE-OUT" in _gids(FAN_OUT) and "G-PURPOSE-IN" not in _gids(FAN_OUT)
    assert {"F1", "F2", "F3"} <= set(_oids(FAN_IN)) and not {"O1", "O2", "O3"} & set(_oids(FAN_IN))
    assert {"O1", "O2", "O3"} <= set(_oids(FAN_OUT)) and not {"F1", "F2", "F3"} & set(_oids(FAN_OUT))


def test_outbound_only_sentence_only_via_purpose_out() -> None:
    """출금만 문장은 G-PURPOSE-OUT 이 GROUNDS 에서 쓸 때만 — METHOD 슬롯엔 없음(숫자 문장과 반복, 05)."""
    t = _texts(FAN_OUT)
    assert "거래 기간 중 입금은 없고 출금만 있음." not in t[SectionV2.METHOD]
    assert t[SectionV2.GROUNDS].count("거래 기간 중 입금은 없고 출금만 있음.") == 1
    no_purpose = _texts(_with(FAN_OUT, customer=None))
    assert not any("출금만 있음" in v for v in no_purpose.values())


@pytest.mark.parametrize(
    "changes",
    [{"customer": None}, {"counterparties__count": 0}, {"observations": []}, {"prior_alert_count": 0}],
)
def test_removing_data_never_strengthens(changes: dict) -> None:
    """자료를 지우면 항목이 빠질 뿐 — 새 항목이 생기거나 단정 문장이 나오지 않음(C2 보완 요청만 예외)."""
    before, after = set(_gids(FAN_IN)), set(_gids(_with(FAN_IN, **changes)))
    assert after <= before
    added_checks = set(_oids(_with(FAN_IN, **changes))) - set(_oids(FAN_IN))
    assert added_checks <= {"C2"}  # 고객 정보가 없으면 "보완할 필요" 만 생김


@pytest.mark.parametrize(
    ("fixture", "pair", "check"),
    [
        ("facts_fan_in.json", "G-COUNTERPARTY", "송금인"),
        ("facts_fan_in.json", "G-PRIOR", "이전 경보와 이번 거래의 관련성"),
        ("facts_fan_out.json", "G-COUNTERPARTY", "수취인"),
        ("facts_scatter_gather.json", "G-COUNTERPARTY", "해당 상대 계좌와 대상자의 거래 관계를 확인"),
    ],
)
def test_paired_items_do_not_repeat_unconfirmed_phrase(fixture: str, pair: str, check: str) -> None:
    """짝이 같이 켜지면 확인 사항은 짧은 꼴 — "제공된 자료로 확인되지 않" 구절이 그 문장에 없음."""
    t = _texts(masking.mask_for_llm(load_fixture(fixture)))
    sentence = next(s for s in t[SectionV2.OPINION].split(". ") if check in s)
    assert "제공된 자료로 확인되지 않" not in sentence
    assert "과거 경보 이력이 있" not in t[SectionV2.OPINION] or pair != "G-PRIOR"


def test_cycle_path_limit_is_judgment_and_c0() -> None:
    """SCRUM-265 2/2 — 경로 없는 CYCLE 은 G-CYCLE-PATH·Y3 대신 판정 문장(GROUNDS 맨 앞) + C0(짧은 꼴과 같은 문장)."""
    f = _with(FAN_IN, typology="CYCLE", prior_alert_count=0)
    plan = {SectionV2.GROUNDS: [Pick("G-CYCLE-PATH")], SectionV2.OPINION: [Pick("O-HEAD-CYCLE"), Pick("Y3")]}
    t = {s.section: s.text for s in build_v4(f, LABELS, editor_plan=plan)}  # 후보 밖 → 코드 Plan
    assert t[SectionV2.GROUNDS].startswith(
        "자금 순환(CYCLE) 분류를 뒷받침하는 경로는 제공된 자료로 확인되지 않음."
    )
    assert "자금 순환을 뒷받침하는 경로" not in t[SectionV2.GROUNDS]
    assert ". 경로 확인 자료를 보완할 필요가 있음." in t[SectionV2.OPINION]
    assert "제공된 자료로" not in t[SectionV2.OPINION]


def test_particles_are_uniform() -> None:
    """`{목적}이며`·`이므로` — 받침과 상관없이 통일(05)."""
    assert with_imyeo("투자") == "투자이며" and with_imyeo("매출 대금 수납") == "매출 대금 수납이며"
    assert with_imeuro("투자") == "투자이므로" and with_imeuro("운영 자금") == "운영 자금이므로"


def test_unconfirmed_items_are_bundled_into_one_sentence() -> None:
    """확인 안 됨 항목 둘 이상 → 명사구 한 문장, 하나면 변형 문장 그대로, 나란히(G-PURPOSE-OUT)는 안 묶음."""
    g = _texts(FAN_IN)[SectionV2.GROUNDS]
    assert g.count("제공된 자료로 확인되지 않음") == 1
    assert g.endswith(
        "위 입금과 등록된 계좌 목적의 관계, 해당 상대 계좌와 대상자의 거래 관계, "
        "이번 거래와 과거 경보의 관련성은 제공된 자료로 확인되지 않음."
    )
    single = _texts(_with(FAN_IN, customer=None, prior_alert_count=0))[SectionV2.GROUNDS]
    assert single.endswith("해당 상대 계좌와 대상자의 거래 관계는 제공된 자료로 확인되지 않음.")
    out = _texts(FAN_OUT)[SectionV2.GROUNDS]
    assert "계좌 목적은 매출 대금 수납으로 등록되어 있음. 거래 기간 중 입금은 없고 출금만 있음." in out
    assert out.endswith(
        "해당 상대 계좌와 대상자의 거래 관계, 이번 거래와 과거 경보의 관련성은 제공된 자료로 확인되지 않음."
    )
