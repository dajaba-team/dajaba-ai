"""SCRUM-310 승인 STR 색인 요청·응답 스키마 — 섹션 두 세트·섞임·중복·문서번호·길이·상태별 칸 (shared/01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str import SectionV1, SectionV2, StrIndexRequest, StrIndexResponse
from tests.str.str_index_support import body


def _sections(names: list[str]) -> list[dict]:
    return [{"section": n, "text": f"{n} 섹션 본문입니다."} for n in names]


@pytest.mark.parametrize(
    "names", [[s.value for s in SectionV2], [s.value for s in SectionV1], ["METHOD"], ["HOW"]]
)
def test_both_section_sets_accepted(names: list[str]) -> None:
    r = StrIndexRequest.model_validate(body(sections=_sections(names)))
    assert r.section_set == ("V2" if names[0] in {s.value for s in SectionV2} else "V1")


@pytest.mark.parametrize(
    "patch",
    [
        {"sections": _sections(["SUBJECT", "WHO"])},  # 세트 섞임
        {"sections": _sections(["METHOD", "METHOD"])},  # 같은 섹션 두 번
        {"sections": _sections(["NOT_A_SECTION"])},
        {"sections": []},
        {
            "sections": [{"section": "METHOD", "text": "가" * 5001}]
        },  # SCRUM-361 — 상한 5000(STR_INDEX_TEXT_MAX)
        {"sections": [{"section": "METHOD", "text": ""}]},
        {"report_no": "STR-26-12"},
        {"report_no": "DRF-2026-000012"},
        {"typologies": ["FAN_IN", "FAN_IN"]},
        {"typologies": ["FAN_IN", "FAN_OUT", "CYCLE", "SCATTER_GATHER"]},
        {"approved_at": "2026-11-24T01:00:00"},  # 시간대 없음
        {"extra": 1},
    ],
)
def test_bad_requests_rejected(patch: dict) -> None:
    with pytest.raises(ValidationError):
        StrIndexRequest.model_validate(body(**patch))


def test_boundaries_pass() -> None:
    StrIndexRequest.model_validate(body(sections=[{"section": "METHOD", "text": "가" * 1200}], typologies=[]))


def _resp(**kw) -> dict:  # noqa: ANN003
    base = {"produced_at": "2026-11-24T01:00:03Z", "report_no": "STR-2026-000012", "status": "INDEXED",
            "skip_reason": None, "chunk_count": 4, "retrieval_version": "m@12345678"}  # fmt: skip
    return {**base, **kw}


@pytest.mark.parametrize(
    "patch",
    [
        {"chunk_count": 0},
        {"skip_reason": "RAW_ACCOUNT"},
        {"retrieval_version": None},
        {"status": "SKIPPED", "skip_reason": None, "chunk_count": 0},
        {"status": "SKIPPED", "skip_reason": "TOO_SHORT", "chunk_count": 1},
    ],
)
def test_response_status_rules(patch: dict) -> None:
    with pytest.raises(ValidationError):
        StrIndexResponse.model_validate(_resp(**patch))


def test_disabled_response_may_have_null_version() -> None:
    StrIndexResponse.model_validate(
        _resp(status="SKIPPED", skip_reason="DISABLED", chunk_count=0, retrieval_version=None)
    )
