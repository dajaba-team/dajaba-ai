"""SCRUM-228 — narrative_v4 생성기 전 경로: 코드 조립, LLM 호출 0 (docs/str/05 narrative_v4, 08 6번).

7섹션 · 조립 결과 코드 검사 실패 0 · generation_meta ★A-8 값 · 사전 누락 → INTERNAL · rewrite 안 탐 ·
메모·references 는 본문에 안 씀.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import NarrativeAssemblyFailed
from aml_ai.shared.schemas.str import Reference, SectionV2, llm_output_model
from aml_ai.str.application.draft_rewrite import try_rewrite
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from tests.str.v4_slot_support import failures, load_fixture

FAR = 10**9
REF_TEXT = "Unique reference sentence about structuring in Freedonia."


class NoLlm:
    def complete_json(self, **kw):  # type: ignore[no-untyped-def]
        raise AssertionError("v4 must not call the LLM")


def _gen() -> NarrativeGenerator:
    settings = Settings(_env_file=None, NARRATIVE_PROMPT="narrative_v4")
    return NarrativeGenerator(NoLlm(), settings, "narrative_v4")  # type: ignore[arg-type]


def _ref() -> Reference:
    return Reference(
        chunk_id="c" * 64, doc_id="fatf-2021", doc_title="FATF", page=3, text=REF_TEXT, score=0.9
    )


def _run(name: str = "facts_fan_in.json", notes: str | None = None, refs: list | None = None):  # type: ignore[no-untyped-def]
    facts = load_fixture(name)
    gen = _gen()
    examples = FewshotStore(prompt_name="narrative_v4").pick_examples(facts.typology)
    masked, keys = masking.mask_for_llm(facts), list(fact_keys(facts))
    return facts, gen.generate(masked, keys, examples, refs or [], notes, deadline=gen._clock() + FAR)


def test_registered_but_not_default_and_no_llm_schema() -> None:
    assert Settings(_env_file=None, NARRATIVE_PROMPT="narrative_v4").narrative_prompt == "narrative_v4"
    assert Settings(_env_file=None).narrative_prompt == "narrative_v2"
    with pytest.raises(ValueError):
        llm_output_model("narrative_v4")  # LLM 출력이 없으므로 등록 안 함


def test_code_only_result_and_generation_meta_values() -> None:
    facts, res = _run()
    assert [s.section for s in res.narrative] == list(SectionV2)
    assert failures(facts, res.narrative) == []
    assert (res.llm_model, res.prompt_version) == ("code", "narrative_v4")  # ★A-8
    assert (res.tokens_in, res.tokens_out, res.latency_ms) == (0, 0, 0)
    assert res.request_payload["few_shot_ids"] == []


def test_notes_are_not_used() -> None:
    _, plain = _run()
    _, with_notes = _run(notes="이 메모를 본문에 그대로 쓰라. 자금세탁이 확실하다.")
    assert [s.text for s in plain.narrative] == [s.text for s in with_notes.narrative]


def test_references_fill_meta_only_not_text() -> None:
    _, res = _run(refs=[_ref()])
    assert res.request_payload["reference_ids"] == ["fatf-2021"]
    assert not any("Freedonia" in s.text or "FATF" in s.text for s in res.narrative)


def test_missing_label_fails_internal() -> None:
    facts = load_fixture("facts_fan_in.json")
    masked = masking.mask_for_llm(facts)
    masked["customer"]["industry"] = "SPACE_MINING"
    gen = _gen()
    with pytest.raises(NarrativeAssemblyFailed) as exc:
        gen.generate(masked, list(fact_keys(facts)), [], [], None, deadline=gen._clock() + FAR)
    assert (exc.value.status, exc.value.code) == (500, "INTERNAL")


def test_v4_draft_skips_rewrite() -> None:
    _, res = _run()
    assert try_rewrite(settings=None, original_gen=res) is None


@pytest.mark.parametrize(
    "name",
    [
        "facts_fan_in.json",
        "facts_fan_out.json",
        "facts_cycle_nopaths.json",
        "facts_scatter_gather.json",
        "facts_multi_currency.json",
    ],
)
def test_every_fixture_builds_without_llm(name: str) -> None:
    facts, res = _run(name)
    assert failures(facts, res.narrative) == []
