"""SCRUM-126 ★L-2 · SCRUM-225 2차 — RAG 켬/끔 비교 (손 실행, pytest 수집 X).

facts 5건 × `rag=True/False` 각 1회 = 10 초안. 평가자는 207 verify 경로 `Judge(votes=3)` 중앙값.
**첫 생성만** (고쳐 쓰기 안 돌림 — RAG 효과·고쳐 쓰기 효과 섞임 방지).

**블라인드 분리 (추가 검토 1차 반영)** — 생성 결과 JSON 은 `A`·`B` 라벨만, `rag` 키 **없음**.
키 파일은 진희 선택 확정 뒤에만 열어 `rag_onoff_reveal` 로 매핑한다. 생성 단계 결과만으로는
평가자가 어느 쪽이 ON 인지 복원할 수 없어야 한다.

**진단 분리 (SCRUM-225)** — `retrieval_status`·`references`·`references_count` 는 ON/OFF 를 드러내므로
공개용 결과 JSON 에서 빼고 진단 파일로. reveal 단계에서 키와 같이 엶.

사용 (진희 터미널, `AI_LLM_MOCK=false`·`RAG_ENABLED=true`, v3 는 `NARRATIVE_PROMPT=narrative_v3`):
    uv run --frozen --extra dev python -m tests.str.rag_onoff_live

결과 (`tests/str/recorded/_tmp/`, `<tag>` = `<prompt_version>_<stamp>`):
- `rag_onoff_<tag>.json` — A/B 지표만 (rag·검색 진단 없음·본문 없음)
- `rag_onoff_blind_<tag>.md` — 사건마다 A/B 두 초안 본문만
- `rag_onoff_diag_<tag>.json` · `rag_onoff_blind_key_<tag>.json` — **진희 선택 확정 전엔 CLI 가 열지 않음**

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
    """결과 JSON 블라인드 레코드 — `rag` 키·검색 진단 **없음**, `side` ∈ {`A`,`B`} 만.

    선택 확정 전 공개해도 ON/OFF 복원 불가능해야 함 (추가 검토 1차·SCRUM-225 반영).
    narrative 본문은 담지 않음 (관문 6).
    """
    return {
        "case_id": case_id,
        "typology": typology,
        "side": side,
        "code_checks_all_match": result["code_checks_all_match"],
        "code_checks_failed": result["code_checks_failed"],
        "judge_scores_median": result["judge_scores_median"],
        "typology_consistent": result["typology_consistent"],
        "no_unsupported_claim": result["no_unsupported_claim"],
        "grounds_signal_mentions": result["grounds_signal_mentions"],
        "unsupported_candidate_count": result["unsupported_candidate_count"],
        "fact_coverage": result["fact_coverage"],
        "status": result["status"],
        "few_shot_ids": result["few_shot_ids"],
        "prompt_version": result["prompt_version"],
        "judge_prompt_version": result["judge_prompt_version"],
        "llm_model_generate": result["llm_model_generate"],
        "llm_model_judge": result["llm_model_judge"],
    }  # noqa: E501


def _record_diag(case_id: str, side: str, result: dict) -> dict:
    """진단 레코드 (SCRUM-225) — 검색 상태·참고 사례 id. reveal 때 키와 같이 엶."""
    keys = ("retrieval_status", "references_count", "references")
    return {"case_id": case_id, "side": side, **{k: result[k] for k in keys}}


_BLIND_INTRO = [
    "# RAG 켬/끔 블라인드 비교 (5 사건, A/B)",
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


def _one_case(case_id: str, facts, rng, llm, embedder, session, settings, out):  # type: ignore[no-untyped-def]
    print(f"[rag_onoff] {case_id} ({facts.typology}) — RAG ON+OFF")
    r_on = generate_one(facts=facts, rag=True, llm=llm, embedder=embedder,
                        session=session, settings=settings)  # fmt: skip
    r_off = generate_one(facts=facts, rag=False, llm=llm, embedder=embedder,
                         session=session, settings=settings)  # fmt: skip
    if rng.random() < 0.5:
        a, b, akey, bkey = r_on, r_off, True, False
    else:
        a, b, akey, bkey = r_off, r_on, False, True
    for side, r in (("A", a), ("B", b)):
        out["runs"].append(_record_blind(case_id, facts.typology.value, side, r))
        out["diag"].append(_record_diag(case_id, side, r))
    out["pairs"].append({
        "case_id": case_id, "typology": facts.typology.value,
        "narrative_A": a["narrative"], "narrative_B": b["narrative"],
    })  # fmt: skip
    out["key"][case_id] = {"A_rag": akey, "B_rag": bkey}


def _save_outputs(tag: str, result: dict, out: dict) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        f"rag_onoff_{tag}.json": json.dumps(result, ensure_ascii=False, indent=2),
        f"rag_onoff_blind_{tag}.md": _blind_md(out["pairs"]),
        f"rag_onoff_diag_{tag}.json": json.dumps({"runs": out["diag"]}, ensure_ascii=False, indent=2),
        f"rag_onoff_blind_key_{tag}.json": json.dumps(out["key"], ensure_ascii=False, indent=2),
    }
    for name, body in files.items():
        (TMP_DIR / name).write_text(body, encoding="utf-8")
        print(f"[rag_onoff] saved → {TMP_DIR / name}")
    print("[rag_onoff] diag·key 는 선택 확정 전 열지 않음")


def main() -> int:
    settings = get_settings()
    tag = f"{settings.narrative_prompt}_{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    llm = make_llm_client(settings)
    embedder = make_embedding_client(settings)
    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    rng = random.SystemRandom()  # 시드 고정 금지 — 배정은 key 파일에만 (진희 지시 2)
    out: dict = {"runs": [], "diag": [], "pairs": [], "key": {}}
    with session_factory() as session:
        for case_id, facts in load_fixtures():
            _one_case(case_id, facts, rng, llm, embedder, session, settings, out)
    result = {
        "retrieval_version": retrieval_version(settings),
        "embedding_model": settings.embedding_model,
        "llm_model_generate": settings.llm_model_generate,
        "llm_model_judge": settings.llm_model_judge,
        "prompt_version": settings.narrative_prompt,
        "judge_votes": 3,
        "runs": out["runs"],
    }
    _save_outputs(tag, result, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
