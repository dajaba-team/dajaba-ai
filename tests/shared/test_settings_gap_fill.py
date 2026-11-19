"""SCRUM-275 — 빈칸 채우기·ES 설정과 retrieval_version 꼬리 (docs/shared/05 · shared/04 · str/10 "버전")."""

from __future__ import annotations

import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.versioning import retrieval_version

_BASE = "text-embedding-3-small"


def _settings(tmp_path, **over: object) -> Settings:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    base = {"RAG_ENABLED": True, "EMBEDDING_MODEL": _BASE, "CORPUS_DIR": str(tmp_path)}
    return Settings(_env_file=None, **{**base, **over})


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("RAG_GAP_FILL_ENABLED", "ELASTIC_URL", "ELASTIC_USERNAME", "ELASTIC_PASSWORD", "ELASTIC_INDEX",
                 "ELASTIC_TIMEOUT_S"):  # fmt: skip
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)  # 리포 .env 를 읽지 않음
    assert s.rag_gap_fill_enabled is False
    assert s.elastic_url == "http://elasticsearch:9200"
    assert s.elastic_username == "elastic"
    assert s.elastic_password == ""
    assert s.elastic_index == "ai_reference_chunks_v1"
    assert s.elastic_timeout_s == 1.0


def test_env_switch_turns_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_GAP_FILL_ENABLED", "true")
    assert Settings(_env_file=None).rag_gap_fill_enabled is True


@pytest.mark.parametrize(
    ("enabled", "prompt", "active"),
    [(True, "narrative_v4", True), (True, "narrative_v2", False), (True, "narrative_v3", False),
     (False, "narrative_v4", False)],
)  # fmt: skip
def test_active_only_on_v4(enabled: bool, prompt: str, active: bool) -> None:
    s = Settings(_env_file=None, RAG_GAP_FILL_ENABLED=enabled, NARRATIVE_PROMPT=prompt)
    assert s.rag_gap_fill_active is active


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, ELASTIC_TIMEOUT_S=0)


def test_password_not_in_repr() -> None:
    assert "pw-value" not in repr(Settings(_env_file=None, ELASTIC_PASSWORD="pw-value"))


def test_retrieval_version_unchanged_when_off(tmp_path) -> None:
    version = retrieval_version(_settings(tmp_path))
    assert version is not None and "+" not in version and version.startswith(f"{_BASE}@")


def test_retrieval_version_tail_when_active(tmp_path) -> None:
    version = retrieval_version(_settings(tmp_path, RAG_GAP_FILL_ENABLED=True, ELASTIC_INDEX="idx_v9"))
    assert version is not None and version.endswith("+fill:abc+kw:idx_v9")
    assert len(version) <= 128  # generations.retrieval_version String(128)


def test_retrieval_version_no_tail_on_v2_even_if_switch_on(tmp_path) -> None:
    s = _settings(tmp_path, RAG_GAP_FILL_ENABLED=True, NARRATIVE_PROMPT="narrative_v2")
    assert "+" not in (retrieval_version(s) or "")
