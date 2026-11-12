"""SCRUM-126 ★L-2 사후 계산 — 블라인드 md A/B 본문 + 픽스처 → unsupported_candidate_count.

LLM 호출 **0** — md 파싱만. 진희 선택 뒤 key 파일로 RAG ON/OFF 매핑은 별도 단계
(`tests.str.rag_onoff_reveal`). 블라인드 md 자체는 안 바꿈.

**두 형식 지원 (추가 검토 1차 반영)** — 예전 06:35 결과 재현용과 지금 생성기 둘 다 읽는다.
- 새 형식(현재 `_blind_md`): 사건 제목 `### case_... (TYPE)`, 구분 `**A**`·`**B**`
- 예전 형식(06:35 저장본): 사건 제목 `## case_... (TYPE)`, 구분 `### A`·`### B`

저장 전 전체 사건·A/B 가 모두 파싱됐는지 검증 — 부족하면 raise(기존 결과 파일은 안 건드림).

사용:
    uv run --frozen --extra dev python -m tests.str.rag_onoff_unsupported_post \\
        ../_claude/ai/rag_onoff_blind_SCRUM-126.md

출력: `../_claude/ai/rag_onoff_unsupported_SCRUM-126.json`
    {"case_1_fan_in": {"A": N, "B": N}, ...}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from aml_ai.shared.schemas.str import Facts, NarrativeSection, SectionV2
from tests.str.rag_onoff_live_support import FIXTURE_FILES
from tests.str.rag_onoff_unsupported import unsupported_candidate_count

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO / "tests" / "str" / "fixtures"

# `##` 또는 `###` 둘 다 사건 제목으로 (예전·새 형식 호환)
CASE_RE = re.compile(r"^#{2,3} (case_\d+_\w+)\s*\([^)]*\)\s*$", re.M)
# `### A/B` 또는 `**A**`·`**B**` 둘 다 구분자로
SIDE_RE = re.compile(r"^(?:###\s+([AB])|\*\*([AB])\*\*)\s*$", re.M)
BULLET_RE = re.compile(r"^-\s*\*\*(\w+)\*\*:\s*(.*)$")


def _parse_blind(md: str) -> dict[str, dict[str, list[NarrativeSection]]]:
    """블라인드 md → {case_id: {"A": [NarrativeSection], "B": [...]}}."""
    out: dict[str, dict[str, list[NarrativeSection]]] = {}
    parts = CASE_RE.split(md)
    # parts = ['preamble', case_id1, body1, case_id2, body2, ...]
    for i in range(1, len(parts), 2):
        case_id = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out[case_id] = _parse_case_body(body)
    return out


def _parse_case_body(body: str) -> dict[str, list[NarrativeSection]]:
    """`### A`·`### B` 또는 `**A**`·`**B**` 블록을 섹션 리스트로.

    `SIDE_RE` 그룹 2 (`###` 쪽) 또는 그룹 3 (`**` 쪽) 중 매치된 쪽이 side.
    `re.split` 이 각 그룹별로 칸을 내므로 `preamble`·(g1·g2)·body 식으로 2+1 흐름.
    """
    out: dict[str, list[NarrativeSection]] = {}
    pieces = SIDE_RE.split(body)
    # pieces = ['preamble', side_g1_or_none, side_g2_or_none, block, ...]
    i = 1
    while i < len(pieces):
        side = pieces[i] or (pieces[i + 1] if i + 1 < len(pieces) else None)
        block = pieces[i + 2] if i + 2 < len(pieces) else ""
        if side in ("A", "B"):
            out[side] = _bullets_to_sections(block)
        i += 3
    return out


def _bullets_to_sections(block: str) -> list[NarrativeSection]:
    """섹션 글머리 한 줄 + 둘째 줄부터 다음 글머리·구분자(`---`) 전까지 이어 붙임 (SCRUM-225)."""
    parts: list[tuple[str, list[str]]] = []
    for line in block.splitlines():
        m = BULLET_RE.match(line)
        if m:
            parts.append((m.group(1), [m.group(2).strip()]))
        elif line.strip() == "---":
            break
        elif parts:
            parts[-1][1].append(line)
    out: list[NarrativeSection] = []
    for name, lines in parts:
        try:
            sec = SectionV2(name)
        except ValueError:
            continue  # v1 섹션 이름 또는 미지원
        out.append(NarrativeSection(section=sec, text="\n".join(lines).rstrip(), cites=[]))
    return out


def _load_facts(case_id: str) -> Facts:
    name = dict(FIXTURE_FILES)[case_id]
    return Facts.model_validate(json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8")))


def _compute(parsed: dict[str, dict[str, list[NarrativeSection]]]) -> dict[str, dict[str, int]]:
    """파싱 결과 → `{case_id: {A/B: count}}` — 저장 전 검증은 호출자가."""
    results: dict[str, dict[str, int]] = {}
    for case_id, sides in parsed.items():
        facts = _load_facts(case_id)
        results[case_id] = {}
        for side in ("A", "B"):
            if side in sides and sides[side]:
                results[case_id][side] = unsupported_candidate_count(sides[side], facts)
    return results


def _validate(results: dict[str, dict[str, int]], expected_cases: list[str]) -> list[str]:
    """부족한 `case_id/side` 목록. 비면 통과."""
    missing: list[str] = []
    for case_id in expected_cases:
        for side in ("A", "B"):
            if case_id not in results or side not in results.get(case_id, {}):
                missing.append(f"{case_id}:{side}")
    return missing


def main() -> int:
    md_path = Path(sys.argv[1] if len(sys.argv) > 1
                   else "../_claude/ai/rag_onoff_blind_SCRUM-126.md")  # fmt: skip
    parsed = _parse_blind(md_path.read_text(encoding="utf-8"))
    results = _compute(parsed)
    expected = [cid for cid, _ in FIXTURE_FILES]
    missing = _validate(results, expected)
    if missing:
        print(f"[fatal] blind md 파싱 부족: {missing}", file=sys.stderr)
        print("기존 결과 파일은 덮어쓰지 않음.", file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    out = Path("../_claude/ai/rag_onoff_unsupported_SCRUM-126.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
