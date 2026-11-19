"""LLM 호출 전체 제한 — `complete_json(total_timeout_s=)` 일 때만 (SCRUM-290 추가 검토 1, docs/str/03).

httpx timeout 은 연결·읽기 작업마다 다시 걸리는 제한이라, 응답 조각이 제한보다 짧은 간격으로 오면 호출 전체가
끝없이 늘 수 있다. 여기서는 요청·본문 읽기를 작업 스레드에서 하고, 호출 전체가 `total_timeout_s` 를 넘기면
열린 응답을 닫아 읽기를 끊고 `LlmUnavailable`. 그 뒤 도착한 결과는 버린다(재시도 없음).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import suppress

import httpx

from aml_ai.shared.errors import LlmUnavailable


def post_within(
    http: httpx.Client, url: str, *, body: dict, headers: dict[str, str], total_timeout_s: float
) -> httpx.Response:
    """본문까지 다 읽은 응답. 작업별 timeout 도 total 로 둬서 한 읽기가 그보다 오래 막히지 않게."""
    opened: list[httpx.Response] = []

    def run() -> httpx.Response:
        req = http.build_request("POST", url, json=body, headers=headers, timeout=total_timeout_s)
        resp = http.send(req, stream=True)
        opened.append(resp)
        try:
            resp.read()
        finally:
            resp.close()
        return resp

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-total-timeout")
    future = pool.submit(run)
    try:
        return future.result(timeout=total_timeout_s)
    except FutureTimeout:
        for resp in opened:
            _close_quietly(resp)
        raise LlmUnavailable("llm total timeout") from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _close_quietly(resp: httpx.Response) -> None:
    """다른 스레드가 읽는 중인 응답을 닫는다 — 실패해도 결과는 이미 버림."""
    with suppress(Exception):  # 끊기 시도일 뿐, 호출 측은 이미 LlmUnavailable
        resp.close()
