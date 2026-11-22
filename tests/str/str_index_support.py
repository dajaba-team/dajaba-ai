"""SCRUM-310 승인 STR 색인 테스트 공용 — 요청 조립·가짜 임베딩·가짜 저장소."""

from __future__ import annotations

import json
from pathlib import Path

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.schemas.str import StrIndexRequest
from aml_ai.str.application.str_index_service import StrIndexService
from aml_ai.str.infrastructure.str_index_repository import Stored
from tests.conftest import ROOT

EXAMPLE = Path(ROOT) / "contracts" / "examples" / "str_index_request.json"
ON = {
    "RAG_ENABLED": True,
    "STR_INDEX_ENABLED": True,
    "EMBEDDING_MODEL": "test-embed",
    "CORPUS_DIR": str(ROOT / "corpus"),
}


def body(**kw) -> dict:  # noqa: ANN003
    return {**json.loads(EXAMPLE.read_text(encoding="utf-8")), **kw}


def req(**kw) -> StrIndexRequest:  # noqa: ANN003
    return StrIndexRequest.model_validate(body(**kw))


def with_text(section_text: str, **kw) -> StrIndexRequest:  # noqa: ANN003
    b = body(**kw)
    b["sections"] = [*b["sections"], {"section": "OPINION", "text": section_text}]
    return StrIndexRequest.model_validate(b)


class Embed:
    model = "test-embed"

    def __init__(self, fail: bool = False, short: bool = False, dim: int = 1536) -> None:
        self.calls: list[list[str]] = []
        self.fail, self.short, self.dim = fail, short, dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise RetrievalUnavailable("down")
        out = [[1.0] + [0.0] * (self.dim - 1) for _ in texts]
        return out[:-1] if self.short else out


class Repo:
    """가짜 저장소 — 케이스 계좌·원천 계좌 표·같은 번호 부모 행."""

    def __init__(self, existing: Stored | None = None, case: set[str] | None = None, accounts: set[str] | None = None,
                 no_facts: bool = False) -> None:  # fmt: skip
        self.stored, self.inserts, self.reads = existing, [], 0
        self.case = {"10_8000EBD30", "20_0100AAF7C"} if case is None else case
        self.accounts = self.case | (accounts or set())
        self.no_facts, self.lookups = no_facts, 0

    def case_accounts(self, draft_id: str) -> set[str] | None:
        self.lookups += 1
        return None if self.no_facts else self.case

    def any_account(self, candidates: list[str]) -> bool:
        norm = {a.replace("_", "").upper() for a in self.accounts} | {
            a.split("_")[-1].upper() for a in self.accounts
        }
        return bool(norm & set(candidates))

    def existing(self, report_no: str) -> Stored | None:
        self.reads += 1
        return self.stored

    def release(self) -> None:
        self.releases = getattr(self, "releases", 0) + 1

    def insert(self, doc) -> Stored:  # noqa: ANN001
        self.inserts.append(doc)
        if self.stored is None:
            self.stored = Stored(doc.request_hash, len(doc.chunks), doc.retrieval_version)
        return self.stored


VERSION = "test-embed@00000000"


def svc(repo=None, embed=None, **env) -> StrIndexService:  # noqa: ANN001, ANN003
    s = Settings(_env_file=None, **{**ON, **env})
    return StrIndexService(
        settings=s, repo=repo or Repo(), embedder=embed or Embed(), retrieval_version=VERSION
    )
