"""SCRUM-225 — narrative_v3 REFERENCES 렌더링 (docs/str/05 narrative_v3 · 10 「프롬프트에서」).

v3 만: 최대 2건 · 유형 패턴 문장 1~2개(겹침 기준, 원문 순서) · 못 찾으면 앞 300자. v2 는 그대로.
"""

from __future__ import annotations

from types import SimpleNamespace

from aml_ai.shared.schemas.str import Reference
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.domain.constants_references import REFERENCE_SNIPPET_FALLBACK_CHARS, REFERENCES_PROMPT_MAX
from aml_ai.str.infrastructure.narrative_generator import load_prompt, render_user
from aml_ai.str.infrastructure.reference_snippet import prompt_references, render_references, snippet

FUNNEL = (
    "This report covers funnel accounts. "
    "Many senders deposit cash into one account in different states. "
    "Funds are then withdrawn quickly. "
    "Unrelated closing remark."
)
LOREM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10


def _ref(i: int, text: str | None = FUNNEL) -> Reference:
    return Reference(chunk_id=f"c{i}", doc_id=f"d{i}", doc_title=f"Doc {i}", page=i, score=0.4, text=text)


def test_prompt_references_v3_keeps_top_two() -> None:
    refs = [_ref(1), _ref(2), _ref(3)]
    assert REFERENCES_PROMPT_MAX == 2
    assert [r.chunk_id for r in prompt_references("narrative_v3", refs)] == ["c1", "c2"]


def test_prompt_references_v2_unchanged() -> None:
    refs = [_ref(1), _ref(2), _ref(3)]
    assert prompt_references("narrative_v2", refs) == refs
    assert prompt_references("narrative_v3", []) == []


def test_snippet_picks_overlap_sentences_in_original_order() -> None:
    out = snippet(FUNNEL, "FAN_IN")
    assert (
        out
        == "This report covers funnel accounts. Many senders deposit cash into one account in different states."
    )


def test_snippet_falls_back_to_head_when_no_overlap() -> None:
    assert snippet(LOREM, "FAN_IN") == LOREM[:REFERENCE_SNIPPET_FALLBACK_CHARS].strip()


def test_snippet_falls_back_when_typology_has_no_pattern() -> None:
    assert snippet(FUNNEL, "HIGH_VALUE") == FUNNEL[:REFERENCE_SNIPPET_FALLBACK_CHARS].strip()
    assert snippet(FUNNEL, None) == FUNNEL[:REFERENCE_SNIPPET_FALLBACK_CHARS].strip()


def test_snippet_empty_text() -> None:
    assert snippet(None, "FAN_IN") == ""
    assert snippet("", "FAN_IN") == ""


def test_render_references_v3_and_empty() -> None:
    assert render_references([], "FAN_IN", snippet_mode=True) == "(없음)"
    out = render_references([_ref(1), _ref(2)], "FAN_IN", snippet_mode=True)
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[1] Doc 1 p.1: This report covers funnel accounts. Many senders")
    assert "Funds are then withdrawn" not in out


def test_render_user_v3_uses_snippet() -> None:
    _, tpl = load_prompt("narrative_v3")
    user = render_user(
        tpl, facts_masked={"typology": "FAN_IN"}, fact_keys=[], notes=None,
        references=[_ref(1)], examples=[], typology="FAN_IN", reference_snippet=True,
    )  # fmt: skip
    assert "Unrelated closing remark" not in user
    assert "[1] Doc 1 p.1: This report covers funnel accounts." in user


class _Retriever:
    def retrieve(self, _facts):  # type: ignore[no-untyped-def]
        return [_ref(1), _ref(2), _ref(3)]


def _service(prompt: str) -> DraftService:
    return DraftService(
        settings=None, session=None, reader=None, fewshot=None, retriever=_Retriever(),
        generator=SimpleNamespace(prompt_version=prompt), judge=None, rewriter=None, generations=None,
    )  # type: ignore[arg-type]  # fmt: skip


def test_draft_service_cuts_once_for_v3_only() -> None:
    """프롬프트와 generation_meta.references 가 같은 리스트 — 자르는 곳은 _references 한 번."""
    assert [r.chunk_id for r in _service("narrative_v3")._references(None)] == ["c1", "c2"]  # type: ignore[arg-type]
    assert len(_service("narrative_v2")._references(None)) == 3  # type: ignore[arg-type]
