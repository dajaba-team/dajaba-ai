"""LLM 호출 전체 제한 — `complete_json(total_timeout_s=)` 일 때만 (SCRUM-322, docs/str/03).

httpx timeout 은 연결·읽기마다 다시 걸리는 작업별 제한이라 헤더·본문 조각이 제한보다 짧은 간격으로 오면 호출 전체가 늘 수 있다.
호출마다 비동기 클라이언트를 만들어 요청·본문 읽기 전체를 total 로 묶고, 마감이면 작업을 취소해 연결을 닫고 LlmUnavailable.
작업 스레드 없음. 마감 뒤 결과는 버린다(재시도 없음).
"""

from __future__ import annotations

import asyncio

import httpx

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.infrastructure.llm_receive import send_and_read_async


def post_within(
    async_transport: httpx.AsyncBaseTransport | None,
    url: str,
    *,
    body: dict,
    headers: dict[str, str],
    total_timeout_s: float,
) -> httpx.Response:
    """호출마다 비동기 클라이언트를 만들고 본문까지 읽은 뒤 닫는다.

    이미 이벤트 루프가 도는 스레드에서는 부르지 않는다 — 라우터가 동기 def 라 작업 스레드에서 부름.
    """
    return asyncio.run(
        _post_within(async_transport, url, body=body, headers=headers, total_timeout_s=total_timeout_s)
    )


async def _post_within(
    async_transport: httpx.AsyncBaseTransport | None,
    url: str,
    *,
    body: dict,
    headers: dict[str, str],
    total_timeout_s: float,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(transport=async_transport, timeout=total_timeout_s) as http:
            # 상태 먼저 → 본문 읽기까지 total 안에서(검토 6 — 200 뒤 압축 해제 실패는 받은 응답)
            request = http.build_request("POST", url, json=body, headers=headers)
            return await asyncio.wait_for(send_and_read_async(http, request), timeout=total_timeout_s)
    except TimeoutError:
        raise LlmUnavailable("llm total timeout") from None
