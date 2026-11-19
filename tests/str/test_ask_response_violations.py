"""AskResponse 상태별 칸 규칙 위반 — SCRUM-288 ★A 3 (docs/shared/01 질문 답변 절).

상태마다 정상 응답에서 칸 하나만 바꿔 거부되는지. (b) code_checks 짝 · (c) prompt_version·bundles · cites·bundles 원소(빈 값·중복) 포함.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str import ASK_ANSWER_MAX, ASK_BUNDLES_MAX, AskResponse
from tests.str.ask_response_support import BUILDERS, EMOJI, check, with_

ANSWERED_BAD = [
    ("answer", None),
    ("answer", ""),
    ("answer", "   "),
    ("answer", "가" * (ASK_ANSWER_MAX + 1)),
    ("answer", "가" * (ASK_ANSWER_MAX - 1) + EMOJI),  # 401
    ("cites", []),
    ("kind", None),
    ("out_of_scope_reason", "JUDGMENT"),
    ("code_checks", [check(True), check(False)]),  # (b) 어긋남이 있으면 UNVERIFIED
    ("generation_meta.prompt_version", None),  # (c)
    ("generation_meta.bundles", []),  # (c)
    ("generation_meta.bundles", ["flows"] * (ASK_BUNDLES_MAX + 1)),  # (c) 4개
    ("cites", [""]),  # 원소 — 빈 키
    ("cites", ["  "]),
    ("cites", ["counterparties.count", "counterparties.count"]),  # 중복
    ("generation_meta.bundles", [""]),
    ("generation_meta.bundles", [" "]),
    ("generation_meta.bundles", ["flows", "flows"]),  # 중복 — 1~3개 셈이 흐려짐
]

NOT_ANSWERED_BAD = [
    ("answer", "입금 상대 계좌는 3개예요."),
    ("answer", ""),
    ("cites", ["counterparties.count"]),
    ("evidence_ids", [104221]),
    ("kind", None),
    ("out_of_scope_reason", "OUTSIDE_CASE"),
    ("generation_meta.prompt_version", None),  # (c)
    ("generation_meta.bundles", []),  # (c)
    ("generation_meta.bundles", [""]),
    ("generation_meta.bundles", ["subject", "subject"]),
]

OUT_OF_SCOPE_BAD = [
    ("kind", "FACT"),
    ("kind", "WHY"),
    ("out_of_scope_reason", None),
    ("answer", "답"),
    ("cites", ["counterparties.count"]),
    ("evidence_ids", [104221]),
    ("code_checks", [check(True)]),  # (b)
    ("generation_meta.prompt_version", "ask_answer_v1"),  # (c)
    ("generation_meta.bundles", ["subject"]),  # (c)
]

BAD = (
    [("ANSWERED", p, v) for p, v in ANSWERED_BAD]
    + [(s, p, v) for s in ("NO_DATA", "UNVERIFIED") for p, v in NOT_ANSWERED_BAD]
    + [
        ("NO_DATA", "code_checks", [check(True)]),  # (b)
        ("UNVERIFIED", "code_checks", []),  # (b) 어긋남이 하나는 있어야
        ("UNVERIFIED", "code_checks", [check(True)]),  # (b)
    ]
    + [("OUT_OF_SCOPE", p, v) for p, v in OUT_OF_SCOPE_BAD]
)


@pytest.mark.parametrize(
    ("status", "path", "value"), BAD, ids=[f"{s}-{p}-{i}" for i, (s, p, _) in enumerate(BAD)]
)
def test_status_rule_violation(status: str, path: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AskResponse.model_validate(with_(BUILDERS[status](), path, value))
