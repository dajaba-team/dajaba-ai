"""SCRUM-125 — Retriever._search 테스트 공용 유틸·시드 (-m db).

reference_chunks 테이블에 임의 청크 삽입·가짜 임베더·시드 레시피.
"""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import text

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts

_DIM = 1536


def vec(x: float, y: float = 0.0, z: float = 0.0) -> list[float]:
    """1536차원 벡터 — 앞 세 축만 의미, 뒤는 0."""
    return [x, y, z] + [0.0] * (_DIM - 3)


def vec_literal(v: list[float]) -> str:
    """'[v0,v1,...]' pgvector 캐스트 리터럴."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class FakeEmbedder:
    def __init__(self, v: list[float]) -> None:
        self._vec = v

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec for _ in texts]


def chash(doc_id: str, page: int, text_norm: str) -> str:
    return sha256(f"{doc_id}\n{page}\n{text_norm}".encode()).hexdigest()


def insert_chunk(
    conn,
    *,
    doc_id: str,
    doc_title: str,
    page: int,
    typologies: list[str],
    text_body: str,
    v: list[float],
) -> str:
    chunk_id = chash(doc_id, page, text_body)
    conn.execute(
        text(
            "INSERT INTO ai.reference_chunks "
            "(chunk_id, doc_id, doc_title, page, typologies, text, embedding, embedding_model, content_hash) "
            "VALUES (:cid, :did, :dt, :pg, CAST(:ty AS text[]), :tx, CAST(:ve AS vector), :em, :ch)"
        ),
        {
            "cid": chunk_id,
            "did": doc_id,
            "dt": doc_title,
            "pg": page,
            "ty": "{" + ",".join(typologies) + "}",
            "tx": text_body,
            "ve": vec_literal(v),
            "em": "test-embed",
            "ch": chunk_id,
        },
    )
    return chunk_id


FAN_IN_FAN_OUT_SEED = [
    {
        "doc_id": "fincen-funnel-2014",
        "doc_title": "Funnel Accounts",
        "page": 1,
        "typologies": ["FAN_IN"],
        "text_body": "Funnel Account: receives multiple cash deposits ...",
        "v": vec(0.99, 0.01),
    },
    {
        "doc_id": "fincen-funnel-2014",
        "doc_title": "Funnel Accounts",
        "page": 2,
        "typologies": ["FAN_IN"],
        "text_body": "Multiple individuals deposit cash proceeds ...",
        "v": vec(0.90, 0.10),
    },
    {
        "doc_id": "ffiec-redflags",
        "doc_title": "BSA/AML Appendix F",
        "page": 2,
        "typologies": ["FAN_IN", "FAN_OUT", "CYCLE"],
        "text_body": "A customer deposits funds into several accounts ...",
        "v": vec(0.80, 0.20),
    },
    {
        "doc_id": "ffiec-redflags",
        "doc_title": "BSA/AML Appendix F",
        "page": 5,
        "typologies": ["FAN_OUT"],  # 거리상 가깝지만 유형이 다름 → 필터로 빠져야 함
        "text_body": "Unusually large number ... beneficiaries ... from one company.",
        "v": vec(0.99, 0.01),
    },
]


def facts_typology(mixed: Facts, typology: Typology | None) -> Facts:
    return mixed.model_copy(update={"typology": typology})


def seed_ef_search_boundary(conn) -> None:  # type: ignore[no-untyped-def]
    """FAN_IN 150개(쿼리에 가까움, 상위 ef_search 안) + FAN_OUT 1개(멀리) + ANALYZE.

    noise 150개는 묶음 실행 때 다른 테스트의 HNSW 통계 잔재와 섞여도 ef_search(기본 40) 를
    확실히 넘기게 하는 안전 margin.
    """
    for i in range(150):
        insert_chunk(
            conn,
            doc_id=f"fanin-{i:03d}",
            doc_title=f"FAN_IN noise {i}",
            page=1,
            typologies=["FAN_IN"],
            text_body=f"fan_in noise {i}",
            v=vec(0.999 - i * 0.00001, 0.001),
        )
    insert_chunk(
        conn,
        doc_id="rare-fanout",
        doc_title="Rare FAN_OUT",
        page=5,
        typologies=["FAN_OUT"],
        text_body="rare fan_out beyond ef_search",
        v=vec(0.5, 0.5, 0.5),
    )
    conn.execute(text("ANALYZE ai.reference_chunks"))
