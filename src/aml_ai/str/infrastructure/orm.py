"""ai 스키마 ORM — str 쪽 (docs/shared/03). 점수 쪽 셋(model_versions·alert_features·predictions)은 scoring/infrastructure/orm.py."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from aml_ai.shared.db import Base

SCHEMA = "ai"


class Generation(Base):
    __tablename__ = "generations"
    __table_args__ = {"schema": SCHEMA}

    generation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # DRAFT / VERIFY / SUMMARY
    draft_id: Mapped[str | None] = mapped_column(String(64), index=True)
    case_no: Mapped[str | None] = mapped_column(String(64))
    facts: Mapped[dict | None] = mapped_column(JSON)
    request: Mapped[dict] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict | None] = mapped_column(JSON)
    llm_model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    few_shot_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    references: Mapped[list | None] = mapped_column(JSON)  # 10/26 RAG
    retrieval_version: Mapped[str | None] = mapped_column(String(128))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), server_default="PROCESSING"
    )  # PROCESSING / SUCCEEDED / FAILED
    error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    __table_args__ = {"schema": SCHEMA}

    verification_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    generation_id: Mapped[str] = mapped_column(String(32), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    code_checks: Mapped[list] = mapped_column(JSON)
    llm_checks: Mapped[list | None] = mapped_column(JSON)
    passed: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24))
    verifier_version: Mapped[str] = mapped_column(String(64))
    narrative_sha256: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = {"schema": SCHEMA}

    prompt_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(16), primary_key=True)
    file_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FewshotExample(Base):
    __tablename__ = "fewshot_examples"
    __table_args__ = {"schema": SCHEMA}

    example_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    typology: Mapped[str] = mapped_column(String(32), index=True)
    facts: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[list] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# reference_chunks (RAG, W4) 는 pgvector 확장 뒤 0004 마이그레이션에서 — 모델은 그때 retriever 옆에 추가.
