"""SCRUM-308-3 추가 검토 3 회귀 — 재임베딩 두 벌로 가까운 쪽 비교(머리말 없는 새 표 벡터 거절) · 두 표 같은 벡터 행 거절."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from aml_ai.shared.config import Settings
from tests.str import rag_eval_v3_ctx_live as live
from tests.str import rag_eval_v3_ctx_recheck as pr
from tests.str.test_rag_eval_v3_ctx_review1 import factory  # noqa: F401 — 적재된 두 표

KEYED = {"LLM_API_KEY": "k", "AI_LLM_MOCK": False, "EMBEDDING_MODEL": "emb"}
B = [1.0, 0.0, 0.0]  # 본문 문장을 다시 임베딩한 벡터 B'
SKEW = math.sqrt(1 - 0.991**2)
H = [0.991, SKEW, 0.0]  # 머리말 문장 벡터 H' — cos(B', H') = 0.991(★C 최대 0.9914 근처)


def _run(
    monkeypatch: pytest.MonkeyPatch, cur_vec: list[float], ctx_vec: list[float], head: list[float] = H
) -> dict:
    cur, ctx = {"c": ("body", cur_vec)}, {"c": ("head\nbody", ctx_vec)}
    truth = {"body": B, "head\nbody": head}
    monkeypatch.setattr(pr.HttpEmbeddingClient, "embed", lambda self, texts: [truth[t] for t in texts])
    return pr.paired_recheck(cur, ctx, Settings(_env_file=None, **KEYED))


def test_as_loaded_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run(monkeypatch, B, H)
    assert pr.paired_problem(out) is None and out["ctx"]["closer_violations"] == 0


def test_ctx_row_with_body_vector_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run(monkeypatch, B, B)  # 새 표에 지금 표(본문) 벡터 — cos(N, H') 0.991 ≥ 0.99 라 예전엔 통과
    assert out["ctx"]["below"] == 0 and out["ctx"]["closer_violations"] == 1 and pr.paired_problem(out)


def test_headerless_embedding_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    near_b = [
        0.9995,
        math.sqrt(1 - 0.9995**2) * 0.1,
        math.sqrt(1 - 0.9995**2) * 0.995,
    ]  # 본문 쪽에 더 가까운 합성 벡터
    out = _run(monkeypatch, B, near_b)
    assert out["ctx"]["closer_violations"] == 1 and "ctx 표" in pr.paired_problem(out)


def test_current_row_with_header_vector_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run(monkeypatch, H, H)
    assert out["current"]["closer_violations"] == 1 and "current 표" in pr.paired_problem(out)


def test_indistinct_chunk_only_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _run(monkeypatch, B, B, head=B)  # 본문이 거의 없어 머리말이 임베딩을 안 바꾼 청크
    assert out["indistinct"] == 1 and pr.paired_problem(out) is None


def test_target_sets_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="다름"):
        pr.paired_recheck({"a": ("t", B)}, {"b": ("t", B)}, Settings(_env_file=None, **KEYED))


@pytest.mark.db
def test_same_vector_rows_counted(factory) -> None:  # noqa: ANN001, F811
    f, _, ids = factory
    with f() as s:
        assert pr.same_vector_rows(s) == 0
        s.execute(
            text(
                "UPDATE ai.reference_chunks_ctx b SET embedding = a.embedding FROM ai.reference_chunks a "
                "WHERE a.chunk_id = b.chunk_id AND b.chunk_id = :c"
            ),
            {"c": ids[0]},
        )
        assert pr.same_vector_rows(s) == 1
        s.rollback()


def test_checks_refuse_same_vector_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "db_problem", lambda s, c, p: (None,))
    monkeypatch.setattr(live.rg, "embedding_model_problem", lambda s, m: None)
    monkeypatch.setattr(live.ex, "table_problem", lambda s, t, e: None)
    monkeypatch.setattr(live, "ctx_table_problem", lambda s, m, d: None)
    monkeypatch.setattr(live.pr, "same_vector_rows", lambda s: 2)
    loaded = {live.cg.CANDIDATES: {}, live.rg.POSITIONS: {}}
    with pytest.raises(ValueError, match="완전히 같은 행 2"):
        live._checks(MagicMock(), loaded, Settings(_env_file=None, **KEYED), {}, dry=False)  # noqa: SLF001
    assert "완전히 같은 행" in live._checks(
        MagicMock(), loaded, Settings(_env_file=None, **KEYED), {}, dry=True
    )  # noqa: SLF001
