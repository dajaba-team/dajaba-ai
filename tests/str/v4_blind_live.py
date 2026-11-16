"""SCRUM-228 (2/2) 1단계 — v4 vs v2 블라인드 생성 (손 실행, pytest 수집 X).

진희 터미널 `AI_LLM_MOCK=false`. 사건마다 v2 첫 생성 1회(NARRATIVE_PROMPT=narrative_v2·RAG 끔·고쳐 쓰기 안 함) →
표기 통일 → v4 조립(LLM 0) → `build_blind` 로 좌우 무작위·대조쌍. 시드는 시스템 난수, 키 파일에만.

사용:
    uv run --frozen --extra dev python -m tests.str.v4_blind_live
결과 (`tests/str/recorded/_tmp/`, `<tag>` = `v4blind_<stamp>`):
- `v4_blind_<tag>.md` — 배포용(평가자 3명)
- `v4_blind_<tag>.json` — 쌍 번호·같은 고객 묶음만
- `v4_blind_responses_<tag>.json` — 빈 응답 양식 — 채워서 reveal 입력
- `v4_blind_diag_<tag>.json` — A/B 자동 지표, **진희 선택 확정 전엔 열지 않음**
- `v4_blind_key_<tag>.json` — **진희 선택 확정 전엔 열지 않음**
"""

from __future__ import annotations

import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.v4_blind_reveal_io import responses_template
from tests.str.v4_blind_support import BlindCase, CaseDrafts, blind_cases, build_blind, unify_notation

TMP_DIR = Path(__file__).resolve().parent / "recorded" / "_tmp"
SEED_LIMIT = 2**31


def draft_case(case: BlindCase, llm: Any, settings: Any) -> CaseDrafts:
    """v2 첫 생성(RAG 끔, 고쳐 쓰기 없음, 스키마 재생성은 기본 설정) + 표기 통일 + v4 조립."""
    facts_masked = masking.mask_for_llm(case.facts)
    labels = load_display_labels()
    generator = NarrativeGenerator(llm, settings, prompt_name="narrative_v2")
    result = generator.generate(
        facts_masked=facts_masked,
        fact_keys=list(fact_keys(case.facts)),
        examples=FewshotStore(prompt_name="narrative_v2").pick_examples(case.facts.typology),
        references=[],
        notes=None,
        deadline=time.monotonic() + settings.draft_budget_s,
    )
    original = attach_evidence(result.narrative, case.facts)
    unified = [unify_notation(s.text, labels, case.facts) for s in original]
    sections = [s.model_copy(update={"text": u.text}) for s, u in zip(original, unified, strict=True)]
    replaced = list(dict.fromkeys(pair for u in unified for pair in u.replaced))
    unknown = list(dict.fromkeys(code for u in unified for code in u.unknown))
    assembled = attach_evidence(build_v4(facts_masked, labels), case.facts)
    return CaseDrafts(case, original, sections, assembled, replaced, unknown)


def main() -> int:
    settings = get_settings()
    llm = make_llm_client(settings)
    drafts = [draft_case(case, llm, settings) for case in blind_cases()]
    seed = random.SystemRandom().randrange(SEED_LIMIT)
    result = build_blind(drafts, seed)
    tag = "v4blind_" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        f"v4_blind_{tag}.md": result.md,
        f"v4_blind_{tag}.json": json.dumps(result.public, ensure_ascii=False, indent=2) + "\n",
        f"v4_blind_responses_{tag}.json": json.dumps(
            responses_template(result.public),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        f"v4_blind_diag_{tag}.json": json.dumps(result.diag, ensure_ascii=False, indent=2) + "\n",
        f"v4_blind_key_{tag}.json": json.dumps(result.key, ensure_ascii=False, indent=2) + "\n",
    }
    for name, body in files.items():
        (TMP_DIR / name).write_text(body, encoding="utf-8")
    print(f"키 v4_blind_key_{tag}.json과 진단 v4_blind_diag_{tag}.json은 선택 확정 전 열지 마세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
