"""SCRUM-265 (2/2) — v4 슬롯 문구 정리 정상·변조 (docs/str/05 슬롯 표, 09 "SCRUM-265 2/2 문구"). LLM·DB 0.

영업점 삭제 · 자행/타행 0 생략 · 관측값 반복 줄임(같은 window — 관측값·날짜 변조 둘 다 잡힘) ·
부재 합침(둘 다 전부 null 만) · 관측값 없음 문장 · 최소 = 최대 "모두". 변조는 06 검사가 잡아야 함.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain.display_slots import place_slots
from tests.str.v4_blind2_cases import case_facts, load_cases
from tests.str.v4_claims_support import facts_for
from tests.str.v4_real_names import real_names
from tests.str.v4_slot_support import assembled, failures, load_fixture

CASES = case_facts(load_cases())
MERGED = "모델 관측값의 관측 구간과 비교 기준값은 제공된 자료로 확인되지 않음."


def _text(f: Facts, sec: SectionV2) -> str:
    return next(s.text for s in assembled(f) if s.section is sec)


def _mutated(f: Facts, sec: SectionV2, old: str, new: str) -> list[LlmNarrativeSection]:
    out = []
    for s in assembled(f):
        if s.section is sec:
            assert old in s.text, (old, s.text)
            s = s.model_copy(update={"text": s.text.replace(old, new, 1)})
        out.append(s)
    return out


def _built(**kw) -> Facts:  # type: ignore[no-untyped-def]
    f = facts_for(**({"n_in": 1, "n_out": 1, "n_int": 0, "path": "none", "typology": "FAN_IN"} | kw))
    assert f is not None
    return f


def test_no_branch_sentence_anywhere() -> None:
    for f in (*CASES.values(), real_names(load_fixture("facts_fan_in.json"))):
        assert all("영업점" not in s.text for s in assembled(f))


def _place(same: int, other: int) -> str:
    d = {"counterparty_banks": {"same_bank_accounts": same, "other_bank_accounts": other},
         "subject": {"account_key": "10_****0001"}, "counterparties": {"count": same + other}}  # fmt: skip
    return " ".join(s.text for s in place_slots(d))


def test_zero_bank_side_is_omitted() -> None:
    assert "이 가운데 타행 계좌는 3개임." in _place(0, 3) and "자행" not in _place(0, 3)
    assert "이 가운데 자행 계좌는 2개임." in _place(2, 0) and "타행" not in _place(2, 0)
    assert "이 가운데 자행 계좌는 1개, 타행 계좌는 1개임." in _place(1, 1)
    assert "이 가운데 자행 계좌는 0개, 타행 계좌는 0개임." in _place(0, 0)


def test_bank_count_mutation_caught() -> None:
    f = CASES["sup_fan_in"]  # 타행 7
    assert "이 가운데 타행 계좌는 7개임." in _text(f, SectionV2.PLACE) and failures(f, assembled(f)) == []
    assert failures(f, _mutated(f, SectionV2.PLACE, "타행 계좌는 7개", "타행 계좌는 6개"))


def test_observation_repeat_reduced_when_windows_equal_null() -> None:
    f = CASES["sup_fan_in"]  # 관측값 3 · window·baseline 전부 null
    g = _text(f, SectionV2.GROUNDS)
    assert g.count("모델 관측값에서") == 1 and "대상 계좌로 들어온 근거 거래 수 관측값은 7건임." in g
    assert failures(f, assembled(f)) == []
    assert failures(
        f,
        _mutated(
            f, SectionV2.GROUNDS, "들어온 근거 거래 수 관측값은 7건", "들어온 근거 거래 수 관측값은 9건"
        ),
    )


def test_observation_repeat_reduced_with_same_window_keeps_date_check() -> None:
    f = real_names(_built(obs="both"))  # 두 관측값 window 같음(W0~W1), baseline 있음
    g = _text(f, SectionV2.GROUNDS)
    assert (
        g.count("2022-09-02T00:00:00~2022-09-03T00:00:00 기준") == 1 and "근거 거래 수 관측값은 4건임." in g
    )
    assert failures(f, assembled(f)) == []
    assert failures(
        f, _mutated(f, SectionV2.GROUNDS, "근거 거래 수 관측값은 4건", "근거 거래 수 관측값은 5건")
    )
    assert failures(f, _mutated(f, SectionV2.GROUNDS, "2022-09-03T00:00:00 기준", "2022-09-05T00:00:00 기준"))


def test_different_windows_keep_parentheses_each() -> None:
    f = real_names(_built(obs="half_window"))  # window 한쪽씩 — 서로 다름
    g = _text(f, SectionV2.GROUNDS)
    assert g.count("모델 관측값(") == 2 and " 관측값은 " not in g
    assert failures(f, assembled(f)) == []


def test_absence_merged_only_when_both_all_null() -> None:
    assert MERGED in _text(CASES["sup_fan_in"], SectionV2.GROUNDS)
    real = real_names(_built(obs="real"))  # window·baseline 전부 null
    assert MERGED in _text(real, SectionV2.GROUNDS) and "비교 기준값은 자료 없음" not in _text(
        real, SectionV2.GROUNDS
    )
    obs = [o.model_copy(update={"baseline": 2.0}) for o in real.observations]
    with_base = real.model_copy(update={"observations": obs})  # window 만 null
    g = _text(with_base, SectionV2.GROUNDS)
    assert MERGED not in g and "모델 관측값의 관측 구간은 자료 없음." in g
    windowed = real_names(_built(obs="all_null"))  # baseline 만 null
    g = _text(windowed, SectionV2.GROUNDS)
    assert MERGED not in g and "비교 기준값은 자료 없음." in g


def test_no_observation_sentence() -> None:
    g = _text(_built(obs="none"), SectionV2.GROUNDS)
    assert (
        "점수를 높인 모델 관측값은 제공된 자료로 확인되지 않음." in g and "모델 관측값은 자료 없음" not in g
    )


def test_min_equals_max_amount_sentence() -> None:
    f = _built()  # 입금·출금 100.00 USD
    m = _text(f, SectionV2.METHOD)
    assert "내부 거래를 뺀 입금·출금의 거래 금액은 모두 100.00 미국 달러임." in m and "최소" not in m
    assert failures(f, assembled(f)) == []
    assert failures(f, _mutated(f, SectionV2.METHOD, "모두 100.00", "모두 101.00"))


def test_min_differs_keeps_range_sentence() -> None:
    f = real_names(load_fixture("facts_fan_in.json"))
    assert "최소 12,500.00 미국 달러, 최대 16,250.50 미국 달러임." in _text(f, SectionV2.METHOD)
