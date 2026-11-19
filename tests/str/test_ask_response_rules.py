"""AskResponse 정상·허용 경계·모양 — SCRUM-288 ★A 3 (docs/shared/01 질문 답변 절).

백엔드 `requireAskResponse` 와 같은 규칙. 예시 파일과 따로, 조립한 응답(ask_response_support)으로 본다.
(a) ANSWERED 빈 evidence_ids 허용 · (b) code_checks 짝 · (c) prompt_version·bundles. 위반은 test_ask_response_violations.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str import ASK_ANSWER_MAX, AskResponse
from tests.str.ask_response_support import BUILDERS, EMOJI, answered, check, parent_of, unverified, with_


@pytest.mark.parametrize("status", BUILDERS)
def test_each_status_valid(status: str) -> None:
    assert AskResponse.model_validate(BUILDERS[status]()).status == status


# ── 허용되는 경계 ──


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("evidence_ids", []),  # (a) typology 같은 키는 거래가 안 달림
        ("code_checks", []),  # (b) ANSWERED 는 빈 목록 허용
        ("answer", "가" * ASK_ANSWER_MAX),
        ("answer", "가" * (ASK_ANSWER_MAX - 2) + EMOJI),  # 400
        ("generation_meta.bundles", ["flows", "counterparties", "subject"]),
    ],
    ids=["empty-evidence", "empty-checks", "answer-400", "answer-398+emoji", "bundles-3"],
)
def test_answered_allowed(path: str, value: object) -> None:
    AskResponse.model_validate(with_(answered(), path, value))


def test_unverified_mixed_checks_allowed() -> None:
    AskResponse.model_validate(with_(unverified(), "code_checks", [check(True), check(False)]))


def test_answer_keeps_surrounding_whitespace() -> None:
    raw = " 입금 상대 계좌는 3개예요. "
    assert AskResponse.model_validate(with_(answered(), "answer", raw)).answer == raw


# ── 모양 ──


@pytest.mark.parametrize(
    "path",
    ["cites", "evidence_ids", "code_checks", "kind", "answer", "generation_meta.prompt_version"],
)
def test_fields_required_no_default(path: str) -> None:
    d = answered()
    parent, last = parent_of(d, path)
    del parent[last]
    with pytest.raises(ValidationError):
        AskResponse.model_validate(d)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("generation_meta.few_shot_ids", [1, 2]),  # 초안·요약 메타 칸은 없음
        ("generation_meta.references", []),
        ("facts", {}),  # 설계 5.3 — facts 는 응답에 안 넣음
        ("status", "FAILED"),
        ("out_of_scope_reason", "OTHER"),
    ],
)
def test_unknown_or_bad_value_rejected(path: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AskResponse.model_validate(with_(answered(), path, value))
