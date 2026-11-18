"""SCRUM-228 — 카탈로그 문장 린트 (docs/str/08 narrative_v4 4번).

모든 카탈로그 문장·변형·짧은 꼴·연결어가 숫자·수 낱말·플래그 주제 낱말·금지 어간·인과/대립 연결어에 안 걸림.
예외 둘(조건이 사실 보장): G-PURPOSE-OUT 의 `출금만`, B1 의 `자행`. 자리표시는 중립 값으로 렌더
(실제 값은 사전 표기 — 표기 쪽은 test_v4_labels 가 봄).
"""

from __future__ import annotations

import itertools

import pytest

from aml_ai.str.domain.catalog_types import render
from aml_ai.str.domain.constants_v4 import CONNECTIVES
from aml_ai.str.domain.display_format import topic
from aml_ai.str.domain.grounds_catalog import GROUNDS_ITEMS, NOT_CONFIRMED
from aml_ai.str.domain.grounds_flow import FLOW_ITEMS
from aml_ai.str.domain.opinion_catalog import CHECK_ITEMS
from aml_ai.str.domain.opinion_heads import HEADS
from tests.str.v4_catalog_lint import lint

CTX = {
    "purpose": "운영 자금",
    "purpose_ro": "운영 자금으로",
    "purpose_imyeo": "운영 자금이며",
    "purpose_imeuro": "운영 자금이므로",
    "typology": "자금 통과",
}
EXEMPT = {"G-PURPOSE-OUT": {"flag_topic"}, "B1": {"flag_topic"}}
ITEMS = [*GROUNDS_ITEMS, *FLOW_ITEMS.values(), *HEADS.values(), *CHECK_ITEMS]
_NOUNS = [i.noun for i in GROUNDS_ITEMS if i.noun]
BUNDLES = [  # 묶기 문장 — 명사구 둘 이상 전부 조합(순서는 우선순위대로)
    ("bundle", f"{', '.join(c[:-1])}, {topic(c[-1])} {NOT_CONFIRMED}")
    for n in range(2, len(_NOUNS) + 1)
    for c in itertools.combinations(_NOUNS, n)
]
SENTENCES = [
    (item.id, render(text, CTX))
    for item in ITEMS
    for text in (*item.variants, *([item.short] if item.short else []))
] + BUNDLES


@pytest.mark.parametrize(
    ("item_id", "text"), SENTENCES, ids=[f"{i}:{n}" for n, (i, _) in enumerate(SENTENCES)]
)
def test_catalog_sentence_is_clean(item_id: str, text: str) -> None:
    assert set(lint(text)) <= EXEMPT.get(item_id, set()), text


def test_exempt_items_really_hit_only_their_exception() -> None:
    """예외가 실제로 필요한 곳에만 있는지 — 없어도 되는 예외를 남기지 않음."""
    for item_id, allowed in EXEMPT.items():
        hits = {p for i, t in SENTENCES if i == item_id for p in lint(t)}
        assert hits == allowed, item_id


@pytest.mark.parametrize("word", [w for w in CONNECTIVES.values() if w])
def test_connectives_are_neutral(word: str) -> None:
    assert lint(f"{word} 해당 거래의 관계는 제공된 자료로 확인되지 않음.") == []


@pytest.mark.parametrize(
    ("text", "reason"),
    [  # 린트 자체 회귀 — 1·2차 추가 검토 반례는 걸려야 함
        ("상대 계좌는 三 곳임.", "digit"),
        ("위 입금 합계는 一億 원임.", "digit"),
        ("위 입금은 전부 타행 계좌에서 당일 들어옴.", "flag_topic"),
        ("거래가 급격히 증가하였으며 범죄 수익을 감출 목적의 거래임.", "forbidden_word"),
        ("백 곳에서 들어옴.", "korean_numeral"),
        ("위 입금은 한 건임.", "korean_numeral"),
        ("따라서 검토가 필요함.", "causal_or_contrast"),
        ("목적이 있으나 확인되지 않음.", "forbidden_word"),
        ("등록되어 있는데, 관계는 확인되지 않음.", "causal_or_contrast"),
    ],
)
def test_lint_catches_known_bad(text: str, reason: str) -> None:
    assert reason in lint(text)


@pytest.mark.parametrize(
    "text", ["이 건은 검토가 필요함.", "한 계좌로 모인 자금임.", "이전 경보와의 관련성."]
)
def test_lint_passes_ordinary(text: str) -> None:
    assert lint(text) == []


def test_return_claim_only_in_cycle_verified_items() -> None:
    """ "돌아온"(자금 복귀를 사실로 전제)은 cycle_verified 를 전제로 하는 항목에서만(구조 변경 뒤 추가 검토 1차)."""
    verified = {i.id for i in ITEMS if "cycle_verified" in i.requires}
    for item_id, text in SENTENCES:
        if "돌아온" in text:
            assert item_id in verified, (item_id, text)
