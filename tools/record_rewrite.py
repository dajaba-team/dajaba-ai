"""rewrite_v1 녹화 — tools/record.py --rewrite 분기 (SCRUM-147).

사용: --rewrite --from-recorded narrative_v2/<key>.json --from-judge judge_v3/<key>.json
rule_id 는 facts.typology ↔ PATH_RULE_KIND 역조회로 자동 추론 (서비스와 같은 값).

프롬프트 조립은 draft_rewrite 가 쓰는 함수(`render_rewrite_prompts`·`build_paths_notice`·
`assemble_critique`·`serialize_original_narrative`) 를 그대로 재사용. 별도 조립 금지 —
녹화 키가 서비스 호출 키와 어긋나면 재생이 안 된다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, recording_key
from aml_ai.shared.schemas.str import Facts, JudgeOutV2, NarrativeOut, llm_output_model
from aml_ai.str.application.draft_rewrite import build_paths_notice, render_rewrite_prompts
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, NARRATIVE_MAX_TOKENS, PATH_RULE_KIND
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys


def rule_id_from_facts(facts: Facts) -> str:
    """facts.typology ↔ PATH_RULE_KIND 역조회. 매칭 없으면 '' (paths_notice 빈 문자열).

    서비스에서는 req.alert.rule_id 를 쓰지만 녹화 도구는 facts 만 받으므로 typology 로 derive.
    """
    for rule_id, kind in PATH_RULE_KIND.items():
        if kind == facts.typology:
            return rule_id
    return ""


REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDED = REPO_ROOT / "tests" / "str" / "recorded"


def build_rewrite_prompt(
    facts: Facts, narrative: list, judge_out: JudgeOutV2, alert_rule_id: str
) -> tuple[str, str, list[str]]:
    """draft_service → try_rewrite → NarrativeRewriter.rewrite 가 호출하는 render_rewrite_prompts 와 동일.

    녹화 도구·서비스가 같은 (system, user) 를 조립해야 recording_key 가 일치한다.
    """
    keys = list(fact_keys(facts).keys())
    system, user = render_rewrite_prompts(
        facts_masked=masking.mask_for_llm(facts),
        fact_keys=keys,
        examples=[],
        references=[],
        notes=None,
        original_narrative=narrative,
        critique=judge_out,
        paths_notice=build_paths_notice(alert_rule_id=alert_rule_id, facts=facts),
    )
    return system, user, keys


def _load_inputs(
    facts: Facts, from_recorded: str | None, from_judge: str | None
) -> tuple[list, JudgeOutV2] | None:
    """녹화 입력 둘 다 로드 — 하나라도 없으면 stderr 로 이유 출력 뒤 None."""
    if not from_recorded or not from_judge:
        print(
            "ERROR: --rewrite 는 --from-recorded narrative_v2/<key>.json 과 "
            "--from-judge judge_v3/<key>.json 둘 다 필요",
            file=sys.stderr,
        )
        return None
    narrative = _load_narrative(RECORDED / from_recorded, facts)
    if narrative is None:
        return None
    judge_out = _load_judge(RECORDED / from_judge)
    if judge_out is None:
        return None
    return narrative, judge_out


def record_rewrite(
    settings: Settings,
    facts: Facts,
    from_recorded: str | None,
    from_judge: str | None,
    save,  # type: ignore[no-untyped-def]
    print_ok,  # type: ignore[no-untyped-def]
) -> int:
    loaded = _load_inputs(facts, from_recorded, from_judge)
    if loaded is None:
        return 2
    narrative, judge_out = loaded
    if not any(c.score < JUDGE_PASS_SCORE for c in judge_out.checks):
        print("고쳐 쓰기 조건 아님 — 평가자 모든 항목이 JUDGE_PASS_SCORE 이상. 녹화 안 함.", file=sys.stderr)
        return 0
    alert_rule_id = rule_id_from_facts(facts)  # facts.typology 로 자동 추론
    system, user, keys = build_rewrite_prompt(facts, narrative, judge_out, alert_rule_id)
    res = HttpLlmClient(settings).complete_json(
        system=system, user=user, model=settings.llm_model_generate,
        max_tokens=NARRATIVE_MAX_TOKENS, tag="rewrite_v1",
    )  # fmt: skip
    err = _validate_rewrite(res.text, keys)
    if err:
        print(f"ERROR: {err} — 녹화 안 함", file=sys.stderr)
        return 3
    out_path = save(recording_key(system, user), res.text, res.model, "rewrite_v1")
    print_ok(out_path, res)
    return 0


def _load_narrative(path: Path, facts: Facts) -> list | None:
    if not path.exists():
        print(f"ERROR: recorded narrative not found: {path}", file=sys.stderr)
        return None
    recorded = json.loads(path.read_text(encoding="utf-8"))
    out = NarrativeOut.model_validate_json(recorded["text"])
    return attach_evidence(out.narrative, facts)


def _load_judge(path: Path) -> JudgeOutV2 | None:
    if not path.exists():
        print(f"ERROR: recorded judge not found: {path}", file=sys.stderr)
        return None
    recorded = json.loads(path.read_text(encoding="utf-8"))
    try:
        return JudgeOutV2.model_validate_json(recorded["text"])
    except ValidationError as exc:
        print(f"ERROR: judge 녹화 스키마 파싱 실패: {exc}", file=sys.stderr)
        return None


def _validate_rewrite(text: str, keys: list[str]) -> str:
    try:
        out = llm_output_model("rewrite_v1").model_validate_json(text)
    except ValidationError as exc:
        return f"rewrite_v1 출력 검증 실패: {exc}"
    scope = set(keys)
    for sec in out.narrative:
        bad = [c for c in sec.cites if c not in scope]
        if bad:
            return f"{sec.section.value} cites 가 FACT_KEYS 밖: {sorted(bad)[:5]}"
    return ""
