"""SCRUM-310 추가 검토 2 회귀 — 실제 계좌 대조(원문 사례 임베딩 0·저장 0 / 정상 사례 INDEXED) · NO_FACTS · 기동 버전 주입."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import Facts, StrIndexRequest, StrIndexSkipReason, StrIndexStatus
from aml_ai.str.domain import masking
from aml_ai.str.infrastructure import str_index_runtime
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.str_index_support import Embed, Repo, body, req, svc, with_text

FIXTURES = Path(__file__).parent / "fixtures"
REAL = {"100_31415926", "7_87654321", "20_0100AAF7C"}  # 원천 계좌 표에만 있는(케이스 밖) 계좌


def _boundary(end: str, start: str) -> StrIndexRequest:
    b = body()
    b["sections"] = [*b["sections"][:2], {"section": "PLACE", "text": end}, {"section": "INSTRUMENT", "text": start},
                     *b["sections"][2:]]  # fmt: skip
    return StrIndexRequest.model_validate(b)


RAW = [
    pytest.param(_boundary("상대 계좌 0100AAF7C", "USD 입금이 이어짐."), id="H1-next-section-currency"),
    pytest.param(with_text("상대 계좌 3141-59-26 로 보냄."), id="H2-date-shaped-real"),
    pytest.param(with_text("상대 계좌 #31415926 로 보냄."), id="H2-hash-real"),
    pytest.param(with_text("상대 계좌 87654321 원장 대조."), id="H2-won-ledger-real"),
    pytest.param(with_text("상대 계좌 10_12345 로 보냄."), id="H3-short-explicit-key"),
    pytest.param(with_text("상대 계좌 20_0100AAF7C 로 보냄."), id="real-key-exact"),
    pytest.param(with_text("상대 계좌 앞자리 8000EB 로 보냄."), id="case-prefix-6"),
    pytest.param(with_text("상대 계좌 0100-AAF-7C 로 보냄."), id="real-hyphen-split"),
]


@pytest.mark.parametrize("r", RAW)
def test_raw_cases_not_embedded_not_stored(r: StrIndexRequest) -> None:
    repo, embed = Repo(case={"10_8000EBD30"}, accounts=REAL), Embed()
    out = svc(repo, embed).index(r)
    assert out.skip_reason is StrIndexSkipReason.RAW_ACCOUNT and embed.calls == [] and repo.inserts == []


def _v4_with_ratio() -> list[str]:
    raw = json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8"))
    raw["observations"][0]["value"] = 1 / 3
    sections = build_v4(masking.mask_for_llm(Facts.model_validate(raw)), load_display_labels())
    return [s.text for s in sections]


def test_v4_ratio_one_third_indexes() -> None:
    texts = _v4_with_ratio()
    assert any("0.333" in t for t in texts)  # 비율 값이 본문에 들어감
    b = body(sections=[{"section": n, "text": t} for n, t in zip(
        ["SUBJECT", "DATE", "PLACE", "INSTRUMENT", "METHOD", "GROUNDS", "OPINION"], texts, strict=False)])  # fmt: skip
    out = svc(Repo(case={"10_8000EBD30", "020_C0000001", "020_C0000002", "020_C0000003"})).index(
        StrIndexRequest.model_validate(b)
    )
    assert out.status is StrIndexStatus.INDEXED


@pytest.mark.parametrize(
    "line",
    [
        "2022-09-02 00:14 · 2022년 9월 2일",
        "합계 62,992,819.38 유로(EUR) · 12.345678 비트코인(BTC)",
        "대상 10_****BD30 · ****BD30",
        "Sole Proprietorship #50438",
        "지어낸 번호 1234-5678-9012",
    ],  # fmt: skip
)
def test_normal_cases_index(line: str) -> None:
    assert (
        svc(Repo(case={"10_8000EBD30"}, accounts=REAL)).index(with_text(line)).status
        is StrIndexStatus.INDEXED
    )


def test_no_facts_skipped() -> None:
    repo, embed = Repo(no_facts=True), Embed()
    out = svc(repo, embed).index(req())
    assert out.skip_reason is StrIndexSkipReason.NO_FACTS and out.chunk_count == 0 and embed.calls == []


def test_version_pinned_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """기동 때 읽은 버전 — 기동 뒤 manifest 읽기가 실패해도 재요청·새 색인에 영향 없음(M6)."""
    from aml_ai.shared import versioning
    from aml_ai.shared.config import Settings
    from tests.str.str_index_support import ON

    str_index_runtime.start(Settings(_env_file=None, **ON))
    pinned = str_index_runtime.version()
    monkeypatch.setattr(
        versioning, "base_retrieval_version", lambda *a, **kw: (_ for _ in ()).throw(OSError("gone"))
    )
    try:
        s = svc()
        s.retrieval_version = str_index_runtime.version()
        assert pinned and s.index(req()).retrieval_version == pinned
    finally:
        str_index_runtime.stop()
