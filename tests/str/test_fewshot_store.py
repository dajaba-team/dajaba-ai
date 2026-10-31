"""`FewshotStore` 활성 버전 폴더만 읽기 + 선택 규칙 (SCRUM-47 ★A 7).

v1·v2 가 섞이지 않는지, 같은 유형 1 + 다른 유형 2 순서, null 유형이면 근거 약한 예시가 뽑히는지.
`narrative_v1/` 샘플 1개·`narrative_v2/` 5개가 커밋돼 있다는 전제.
"""

from __future__ import annotations

from aml_ai.str.infrastructure.fewshot_store import FEWSHOT_ROOT, FewshotStore


def test_v1_folder_loads_only_v1_examples() -> None:
    store = FewshotStore(prompt_name="narrative_v1")
    assert len(store.all()) == 1
    assert store.all()[0].example_id == 1


def test_v2_folder_loads_only_v2_examples() -> None:
    store = FewshotStore(prompt_name="narrative_v2")
    ids = [e.example_id for e in store.all()]
    assert ids == [2, 3, 4, 5, 6]
    assert all(len(e.narrative) == 7 for e in store.all()), "v2 는 섹션 7개"


def test_pick_examples_same_typology_first_then_others() -> None:
    """같은 유형 1 + 다른 유형 2 — FAN_IN 경보면 002(FAN_IN) 가 먼저, 그다음 다른 유형 2 개."""
    store = FewshotStore(prompt_name="narrative_v2")
    picked = store.pick_examples("FAN_IN")
    assert picked[0].typology == "FAN_IN"
    assert len(picked) == 3
    assert all(e.typology != "FAN_IN" for e in picked[1:])


def test_pick_examples_null_typology_picks_weak_evidence_first() -> None:
    """null 경보면 006(typology null, 근거 약한 예시) 가 '같은 유형'으로 뽑힘."""
    store = FewshotStore(prompt_name="narrative_v2")
    picked = store.pick_examples(None)
    assert picked[0].typology is None
    assert picked[0].example_id == 6


def test_fewshot_root_has_both_version_folders() -> None:
    """v1·v2 폴더가 공존 — 반영일 전 승인본 보존."""
    assert (FEWSHOT_ROOT / "narrative_v1").is_dir()
    assert (FEWSHOT_ROOT / "narrative_v2").is_dir()
