"""명시 호출만 Langfuse 에 기록. 기록 실패는 원래 호출에 영향을 주지 않는다."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock, Thread
from typing import TYPE_CHECKING, Protocol

from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider

from aml_ai.shared.config import Settings
from aml_ai.shared.logging import current_request_id

if TYPE_CHECKING:
    from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
    from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult

LANGFUSE_HTTP_TIMEOUT_S: int = 2
LANGFUSE_FLUSH_TIMEOUT_S: float = 3.0
log = logging.getLogger(__name__)
_lock = Lock()
_tracer: Tracer | None = None
_initialized = False
_warned: set[str] = set()


class Observation(Protocol):
    def update(self, **kwargs: object) -> object: ...
    def end(self) -> object: ...


class Tracer(Protocol):
    def start_observation(self, **kwargs: object) -> Observation: ...
    def shutdown(self) -> None: ...


def get_tracer(settings: Settings) -> Tracer | None:
    global _tracer, _initialized
    if not settings.langfuse_enabled:
        return None
    with _lock:
        if _initialized:
            return _tracer
        _initialized = True
        if not settings.langfuse_public_key or not settings.langfuse_secret_key:
            log.warning("langfuse_disabled", extra={"reason": "missing_key"})
            return None
        try:
            _tracer = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                base_url=settings.langfuse_base_url,
                timeout=LANGFUSE_HTTP_TIMEOUT_S,
                tracer_provider=TracerProvider(),
            )
        except Exception:
            log.warning("langfuse_disabled", extra={"reason": "init_failed"})
        return _tracer


def set_tracer(tracer: Tracer | None) -> None:
    global _tracer, _initialized
    with _lock:
        _tracer, _initialized = tracer, True


def reset_tracing() -> None:
    global _tracer, _initialized
    with _lock:
        _tracer, _initialized = None, False
        _warned.clear()


def trace_context_for(request_id: str) -> dict[str, str] | None:
    return None if request_id == "-" else {"trace_id": Langfuse.create_trace_id(seed=request_id)}


def _warn_error(exc: Exception) -> None:
    reason = type(exc).__name__
    with _lock:
        if reason not in _warned:
            _warned.add(reason)
            log.warning("tracing_error", extra={"reason": reason})


def _safe_call(call: Callable[..., object], **kwargs: object) -> None:
    try:
        call(**kwargs)
    except Exception as exc:
        _warn_error(exc)


@contextmanager
def _observe(tracer: Tracer, metadata: dict[str, object], **kwargs: object) -> Iterator[Observation | None]:
    observation = None
    try:
        rid = current_request_id()
        observation = tracer.start_observation(
            trace_context=trace_context_for(rid), metadata={"request_id": rid, **metadata}, **kwargs
        )
    except Exception as exc:
        _warn_error(exc)
    try:
        yield observation
    except Exception as exc:
        if observation is not None:
            _safe_call(observation.update, level="ERROR", status_message=type(exc).__name__)
        raise
    finally:
        if observation is not None:
            _safe_call(observation.end)


class TracedLlmClient:
    def __init__(self, inner: LlmClient, tracer: Tracer, *, server_version: str) -> None:
        self._inner, self._tracer, self._version = inner, tracer, server_version

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        tag: str,
        timeout_s: float | None = None,
        total_timeout_s: float | None = None,  # SCRUM-290 — 질문 답변만 값
    ) -> LlmResult:
        with _observe(
            self._tracer,
            {"server_version": self._version, "prompt_version": tag},
            name=tag,
            as_type="generation",
            model=model,
            input={"system": system, "user": user},
        ) as obs:
            # 값이 있을 때만 넘김 — 초안·검증·요약 호출 모양은 그대로(SCRUM-290)
            limits = {"total_timeout_s": total_timeout_s} if total_timeout_s is not None else {}
            result = self._inner.complete_json(
                system=system,
                user=user,
                model=model,
                max_tokens=max_tokens,
                tag=tag,
                timeout_s=timeout_s,
                **limits,
            )
            if obs is not None:
                usage = {"input": result.tokens_in, "output": result.tokens_out}
                _safe_call(obs.update, output=result.text, model=result.model, usage_details=usage)
            return result


class TracedEmbeddingClient:
    def __init__(self, inner: EmbeddingClient, tracer: Tracer, *, server_version: str) -> None:
        self._inner, self._tracer, self._version = inner, tracer, server_version

    @property
    def model(self) -> str:
        return self._inner.model

    def embed(self, texts: list[str]) -> list[list[float]]:
        with _observe(
            self._tracer,
            {
                "server_version": self._version,
                "text_count": len(texts),
                "char_total": sum(len(text) for text in texts),
            },
            name="embedding",
            as_type="embedding",
            model=self.model,
        ):
            return self._inner.embed(texts)


def wrap_llm_client(client: LlmClient, settings: Settings) -> LlmClient:
    tracer = get_tracer(settings)
    if tracer is None:
        return client
    return TracedLlmClient(client, tracer, server_version=settings.server_version)


def wrap_embedding_client(client: EmbeddingClient, settings: Settings) -> EmbeddingClient:
    tracer = get_tracer(settings)
    if tracer is None:
        return client
    return TracedEmbeddingClient(client, tracer, server_version=settings.server_version)


def shutdown_tracer(timeout_s: float = LANGFUSE_FLUSH_TIMEOUT_S) -> None:
    with _lock:
        tracer = _tracer
    if tracer is not None:
        worker = Thread(target=_safe_call, args=(tracer.shutdown,), daemon=True)
        worker.start()
        worker.join(timeout_s)
