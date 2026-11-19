"""AskResponse 테스트용 조립 — 상태별 정상 응답 + 칸 하나 바꾸기 (SCRUM-288).

test_ask_response_rules(정상·허용 경계·모양) · test_ask_response_violations(위반)가 같이 쓴다.
"""

from __future__ import annotations

import copy

EMOJI = "😀"  # UTF-16 2단위


def check(match: bool) -> dict:
    return {
        "check": "COUNT_MATCH",
        "section": None,
        "draft_value": "3개" if match else "4개",
        "source_value": "counterparties.count=3",
        "match": match,
        "reason": None if match else "MISMATCH",
    }


def _base(status: str) -> dict:
    return {
        "produced_at": "2026-11-27T02:10:00Z",
        "case_no": "CASE-2022-000057",
        "generation_id": "g-91ab33c0",
        "status": status,
        "kind": "FACT",
        "out_of_scope_reason": None,
        "answer": None,
        "cites": [],
        "evidence_ids": [],
        "code_checks": [],
        "generation_meta": {
            "llm_model": "(API가 돌려준 모델 ID)",
            "prompt_version": "ask_answer_v1",
            "plan_prompt_version": "ask_plan_v1",
            "bundles": ["counterparties"],
            "server_version": "a1b2c3d",
            "tokens_in": 1450,
            "tokens_out": 120,
            "latency_ms": 6200,
        },
    }


def answered() -> dict:
    d = _base("ANSWERED")
    d.update(
        answer="입금 상대 계좌는 3개예요.",
        cites=["counterparties.count"],
        evidence_ids=[104221, 104233, 104301],
        code_checks=[check(True)],
    )
    return d


def no_data() -> dict:
    return _base("NO_DATA")


def unverified() -> dict:
    d = _base("UNVERIFIED")
    d["code_checks"] = [check(False)]
    return d


def out_of_scope() -> dict:
    d = _base("OUT_OF_SCOPE")
    d.update(kind=None, out_of_scope_reason="JUDGMENT")
    d["generation_meta"].update(prompt_version=None, bundles=[], tokens_in=420, tokens_out=30)
    return d


BUILDERS = {"ANSWERED": answered, "NO_DATA": no_data, "UNVERIFIED": unverified, "OUT_OF_SCOPE": out_of_scope}


def parent_of(d: dict, path: str) -> tuple[dict, str]:
    """점으로 이은 경로 → (바로 위 dict, 마지막 키). 예: generation_meta.bundles."""
    *head, last = path.split(".")
    for key in head:
        d = d[key]
    return d, last


def with_(d: dict, path: str, value: object) -> dict:
    d = copy.deepcopy(d)
    parent, last = parent_of(d, path)
    parent[last] = value
    return d
