"""SCRUM-265 — 재블라인드 생성 (손 실행, pytest 수집 X). **2/2(카탈로그·판정) 머지 뒤** 진희 터미널 `AI_LLM_MOCK=false`.

사건은 `v4_blind2_cases.json` 만(다시 뽑지 않음). 사건마다 v2 첫 생성 1회(RAG 끔·고쳐 쓰기 안 함, 228 `generate_v2`) →
**성공 즉시 체크포인트**(`_tmp/v4_blind2_checkpoint/<case_id>.json`) → 표기 통일·v4 조립(228 `assemble_case`) →
`build_blind2`. 중간에 실패하면 다시 실행 — 저장된 사건은 LLM 안 부르고 이어서(첫 생성만 조건, 09 추가 검토 3차).
쌍 순서·좌우 시드는 시스템 난수, 키 파일에만. run_id(태그 시각 부분)는 공개·진단·키·빈 응답 양식에 같이.

사용 (첫 실행 전 `_tmp/v4_blind2_checkpoint/` 가 비어 있는지 확인 — 예전 시험 실행 파일이 있으면 그게 첫 생성으로 쓰임):
    uv run --frozen --extra dev python -m tests.str.v4_blind2_live
결과 (`tests/str/recorded/_tmp/`, `<tag>` = `v4blind2_<stamp>`): 배포 md · 공개 json · 빈 응답 양식(support·run_id 칸) ·
진단·키(**진희 선택 확정 전엔 열지 않음**) — 228 과 같은 파일 이름 규칙(`v4_blind_*_<tag>`).
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import NarrativeSection
from tests.str.v4_blind2_build import blind2_cases, build_blind2
from tests.str.v4_blind2_cases import load_cases
from tests.str.v4_blind2_io import responses_template2
from tests.str.v4_blind_live import SEED_LIMIT, TMP_DIR, assemble_case, generate_v2
from tests.str.v4_blind_support import BlindCase

CHECKPOINT_DIR = TMP_DIR / "v4_blind2_checkpoint"
Generate = Callable[[BlindCase], list[NarrativeSection]]


def originals(cases: list[BlindCase], generate: Generate, store: Path = CHECKPOINT_DIR) -> dict[str, list]:
    """사건마다 저장된 원본이 있으면 읽고, 없으면 생성 → 바로 저장. 실패하면 그 앞까지 저장된 채로 예외."""
    store.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[NarrativeSection]] = {}
    for case in cases:
        path = store / f"{case.case_id}.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            out[case.case_id] = [NarrativeSection.model_validate(s) for s in raw]
            continue
        sections = generate(case)
        body = [s.model_dump(mode="json") for s in sections]
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out[case.case_id] = sections
    return out


def main() -> int:
    settings = get_settings()
    llm = make_llm_client(settings)
    doc = load_cases()
    cases = blind2_cases(doc)
    saved = originals(cases, lambda case: generate_v2(case, llm, settings))
    drafts = [assemble_case(case, saved[case.case_id]) for case in cases]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    result = build_blind2(drafts, doc, random.SystemRandom().randrange(SEED_LIMIT), run_id=stamp)
    tag = f"v4blind2_{stamp}"
    files = {
        f"v4_blind_{tag}.md": result.md,
        f"v4_blind_{tag}.json": result.public,
        f"v4_blind_responses_{tag}.json": responses_template2(result.public),
        f"v4_blind_diag_{tag}.json": result.diag,
        f"v4_blind_key_{tag}.json": result.key,
    }
    for name, body in files.items():
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2) + "\n"
        (TMP_DIR / name).write_text(text, encoding="utf-8")
    print(f"키 v4_blind_key_{tag}.json과 진단 v4_blind_diag_{tag}.json은 선택 확정 전 열지 마세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
