"""SCRUM-126 ★L-2 — RAG 켬/끔 비교 (손 실행, pytest 수집 X).

facts 5건 × `rag=True/False` 각 1회 = 10 초안. 평가자는 207 verify 경로 `Judge(votes=3)` 중앙값.
**첫 생성만** (고쳐 쓰기 안 돌림 — RAG 효과·고쳐 쓰기 효과 섞임 방지).

**블라인드 분리 (추가 검토 1차 반영)** — 생성 결과 JSON 은 `A`·`B` 라벨만, `rag` 키 **없음**.
키 파일은 진희 선택 확정 뒤에만 열어 `rag_onoff_reveal` 로 매핑한다. 생성 단계 결과만으로는
평가자가 어느 쪽이 ON 인지 복원할 수 없어야 한다.

사용 (진희 터미널, `AI_LLM_MOCK=false`·`RAG_ENABLED=true`):
    uv run --frozen --extra dev python -m tests.str.rag_onoff_live

결과:
- `tests/str/recorded/_tmp/rag_onoff_SCRUM-126_<stamp>.json` — A/B 지표만 (rag 키 없음·본문 없음)
- `tests/str/recorded/_tmp/rag_onoff_blind_SCRUM-126_<stamp>.md` — 사건마다 A/B 두 초안 본문만
- `tests/str/recorded/_tmp/rag_onoff_blind_key_SCRUM-126_<stamp>.json` — A/B → rag 매핑 **진희 열람 전엔 CLI 가 열지 않음**

진희가 블라인드 md 보고 "case_N: A|B" 를 알려 주면, `tests.str.rag_onoff_reveal` 로 키 파일을
열어 ON/OFF 매핑한 revealed JSON 을 만든다 (결과 표). 생성 단계는 매핑하지 않는다.

호출 수: 10 × (생성 1 + Judge 3 병렬) = 40 호출, wall-clock 5~7분.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from tests.str.rag_onoff_live_support import (
    generate_one,
    load_fixtures,
    retrieval_version,
)

REPO = Path(__file__).resolve().parents[2]
TMP_DIR = REPO / "tests" / "str" / "recorded" / "_tmp"


def _record_blind(case_id: str, typology: str, side: str, result: dict) -> dict:
    """결과 JSON 블라인드 레코드 — `rag` 키 **없음**, `side` ∈ {`A`,`B`} 만.

    선택 확정 전 공개해도 ON/OFF 복원 불가능해야 함 (추가 검토 1차 반영).
    narrative 본문은 담지 않음 (관문 6).
    """
    return {
        "case_id": case_id,
        "typology": typology,
        "side": side,
        "references_count": result["references_count"],
        "references": result["references"],
        "retrieval_status": result["retrieval_status"],
        "code_checks_all_match": result["code_checks_all_match"],
        "code_checks_failed": result["code_checks_failed"],
        "judge_scores_median": result["judge_scores_median"],
        "typology_consistent": result["typology_consistent"],
        "no_unsupported_claim": result["no_unsupported_claim"],
        "grounds_signal_mentions": result["grounds_signal_mentions"],
        "unsupported_candidate_count": result["unsupported_candidate_count"],
        "status": result["status"],
        "few_shot_ids": result["few_shot_ids"],
        "prompt_version": result["prompt_version"],
        "judge_prompt_version": result["judge_prompt_version"],
        "llm_model_generate": result["llm_model_generate"],
        "llm_model_judge": result["llm_model_judge"],
    }  # noqa: E501


_BLIND_INTRO = [
    "# SCRUM-126 켬/끔 블라인드 비교 (5 사건, A/B)",
    "",
    "**해석 전제 — n=5·1회, 방향성 근거, SG 쌍 차이(흔들림)와 비교.**",
    "",
    "각 사건마다 **4칸**:",
    "- **선택**(A/B/같음) — 전체 품질",
    "- **유형 설명**(A/B/같음) — 그 유형 그래프 패턴을 더 정확히 설명",
    "- **반입**(A에 있음/B에 있음/둘 다/없음) — 참고 사례 금액·이름·국가 등 반입 여부(규칙 8)",
    "- **한 줄 이유**",
    "",
    "두 번째 판단자(준영 또는 채영) 칸이 선택 열 바로 아래 비어 있음 — 없으면 09 알고 남김 한 줄.",
    "",
    "아래 선택 표를 채운 뒤 CLI 에 알려 주세요.",
    "",
    "## 선택 표 (진희가 직접 채움)",
    "",
    "| case_id | 유형 | 선택(진희) | 선택(2차) | 유형 설명 | 반입 | 한 줄 이유 |",
    "|---|---|---|---|---|---|---|",
]


def _blind_md(blind_pairs: list[dict]) -> str:
    lines = list(_BLIND_INTRO)
    for p in blind_pairs:
        lines.append(f"| {p['case_id']} | {p['typology']} | ( ) | ( ) | ( ) | ( ) | |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 본문 (narrative 섹션만 — references·generation_meta 없음)")
    lines.append("")
    for p in blind_pairs:
        lines.append(f"### {p['case_id']} ({p['typology']})")
        lines.append("")
        for side in ("A", "B"):
            lines.append(f"**{side}**")
            lines.append("")
            for s in p[f"narrative_{side}"]:
                lines.append(f"- **{s.section.value}**: {s.text}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _one_case(case_id: str, facts, rng, llm, embedder, session, settings, records, blind_pairs, blind_key):  # type: ignore[no-untyped-def]
    print(f"[rag_onoff] {case_id} ({facts.typology}) — RAG ON+OFF")
    r_on = generate_one(facts=facts, rag=True, llm=llm, embedder=embedder,
                        session=session, settings=settings)  # fmt: skip
    r_off = generate_one(facts=facts, rag=False, llm=llm, embedder=embedder,
                         session=session, settings=settings)  # fmt: skip
    if rng.random() < 0.5:
        a, b, akey, bkey = r_on, r_off, True, False
    else:
        a, b, akey, bkey = r_off, r_on, False, True
    records.append(_record_blind(case_id, facts.typology.value, "A", a))
    records.append(_record_blind(case_id, facts.typology.value, "B", b))
    blind_pairs.append({
        "case_id": case_id, "typology": facts.typology.value,
        "narrative_A": a["narrative"], "narrative_B": b["narrative"],
    })  # fmt: skip
    blind_key[case_id] = {"A_rag": akey, "B_rag": bkey}


def _save_outputs(stamp: str, result: dict, blind_pairs: list, blind_key: dict) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_json = TMP_DIR / f"rag_onoff_SCRUM-126_{stamp}.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md = TMP_DIR / f"rag_onoff_blind_SCRUM-126_{stamp}.md"
    out_md.write_text(_blind_md(blind_pairs), encoding="utf-8")
    out_key = TMP_DIR / f"rag_onoff_blind_key_SCRUM-126_{stamp}.json"
    out_key.write_text(json.dumps(blind_key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[rag_onoff] saved → {out_json}")
    print(f"[rag_onoff] blind → {out_md}")
    print(f"[rag_onoff] key(안 열림) → {out_key}")


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    settings = get_settings()
    llm = make_llm_client(settings)
    embedder = make_embedding_client(settings)
    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    rng = random.SystemRandom()  # 시드 고정 금지 — 배정은 key 파일에만 (진희 지시 2)
    records: list[dict] = []
    blind_pairs: list[dict] = []
    blind_key: dict[str, dict[str, bool]] = {}
    with session_factory() as session:
        for case_id, facts in load_fixtures():
            _one_case(case_id, facts, rng, llm, embedder, session, settings,
                      records, blind_pairs, blind_key)  # fmt: skip
    result = {
        "retrieval_version": retrieval_version(settings),
        "embedding_model": settings.embedding_model,
        "llm_model_generate": settings.llm_model_generate,
        "llm_model_judge": settings.llm_model_judge,
        "prompt_version": settings.narrative_prompt,
        "judge_votes": 3,
        "runs": records,
    }
    _save_outputs(stamp, result, blind_pairs, blind_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
