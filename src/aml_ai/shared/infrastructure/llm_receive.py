"""LLM 응답 수신 — 상태 먼저, 본문은 그 뒤에 따로 읽음(SCRUM-308-2 검토 6).

200 을 받은 뒤 본문 압축 해제가 실패하면(`httpx.DecodingError`) 모델을 알 수 없는 "받은 응답" 으로
`LlmInvalidOutput(response_received=True, response_model=None)`. 200 이 아니면 지금 분류 그대로(예외를 그대로 올림).
연결·읽기 끊김·시간 초과(TransportError)는 그대로 — 호출자가 LlmUnavailable 로(백엔드 재시도 분류 유지).
"""

from __future__ import annotations

import httpx

from aml_ai.shared.errors import LlmInvalidOutput

_SAFE_MSG_INVALID = "llm invalid output"


def _received_invalid() -> LlmInvalidOutput:
    err = LlmInvalidOutput(_SAFE_MSG_INVALID)
    err.response_received = True
    return err


def send_and_read(http: httpx.Client, request: httpx.Request) -> httpx.Response:
    resp = http.send(request, stream=True)
    try:
        resp.read()
    except httpx.DecodingError:
        if resp.status_code != httpx.codes.OK:
            raise
        raise _received_invalid() from None
    finally:
        resp.close()
    return resp


async def send_and_read_async(http: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
    resp = await http.send(request, stream=True)
    try:
        await resp.aread()
    except httpx.DecodingError:
        if resp.status_code != httpx.codes.OK:
            raise
        raise _received_invalid() from None
    finally:
        await resp.aclose()
    return resp
