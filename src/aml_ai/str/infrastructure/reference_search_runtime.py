"""SCRUM-309 참고 사례 검색 — 앱 수명 자원 (추가 검토 2, docs/str/10 "참고 사례 검색").

- 기동 검사 때 읽은 `retrieval_version`(모델@manifest 8자) — 요청마다 파일을 안 읽음
- 검색 임베딩용 이벤트 루프 하나(전용 스레드) — 요청 스레드는 `run_coroutine_threadsafe(...).result(timeout)` 로 기다리고,
  만료면 future 를 취소하고 바로 돌아감(DNS 처럼 남은 작업은 이 루프 쪽에서 끝남). 요청마다 `asyncio.run` 을 쓰지 않음.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from aml_ai.shared.config import Settings
from aml_ai.shared.versioning import base_retrieval_version

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_version: str | None = None


def start(settings: Settings) -> None:
    """lifespan — 켬 + RAG 켬일 때만. manifest 를 읽어 버전을 고정(없으면 OSError — 기동 실패)."""
    global _version  # noqa: PLW0603 — 프로세스 하나에 한 번(기동)
    _version = base_retrieval_version(settings, strict=True)
    _ensure_loop()


def version() -> str:
    if _version is None:
        raise RuntimeError("reference search not started")
    return _version


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread  # noqa: PLW0603
    with _lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, name="reference-embed-loop", daemon=True)
            _thread.start()
        return _loop


def submit(coro: Coroutine[Any, Any, Any]) -> Future:
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop())


def stop() -> None:
    global _loop, _thread, _version  # noqa: PLW0603
    with _lock:
        loop, thread, _loop, _thread, _version = _loop, _thread, None, None, None
    if loop is not None:
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=1.0)
