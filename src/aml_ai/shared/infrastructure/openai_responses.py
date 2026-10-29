"""OpenAI Responses API 요청·응답 헬퍼. 길이 가이드 때문에 llm_client.py 에서 분리."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from aml_ai.shared.errors import BudgetExceeded, LlmInvalidOutput, LlmUnavailable

log = logging.getLogger(__name__)

# 외부 응답 메시지는 **고정 상수** — 공급자가 반사하는 민감 내용(SCRUM-15 adversarial H1).
# 공급자 code·message 는 서버 로그로만, HTTP body·예외 message 로 흘려보내지 않는다.
_SAFE_MSG_INVALID = "llm invalid output"
_SAFE_MSG_UNAVAILABLE = "llm unavailable"
_SAFE_MSG_BUDGET = "llm rate_limited"
_ALLOWED_PROVIDER_CODE_FRAGMENTS = (
    "rate_limit",
    "insufficient_quota",
    "server_error",
    "model_overloaded",
    "invalid_request",
    "invalid_json_schema",
    "unsupported_parameter",
    "unsupported_value",
)


def parse_response(resp: httpx.Response) -> dict[str, Any]:
    """상태 코드 분류를 **본문 파싱보다 먼저** — HTML/빈 body 429·408·5xx 도 올바른 분류 (SCRUM-15 M1).

    외부 메시지는 상수. 공급자 code 는 로그로만.
    """
    status = resp.status_code
    if status == 200:
        return _json_or_invalid(resp, _SAFE_MSG_INVALID)
    if status == 429:
        # 일 토큰 한도 초과만 BudgetExceeded(재시도 0), 나머지 rate_limit 은 LlmUnavailable(재시도 1).
        # 규약 6.3 LLM_BUDGET_EXCEEDED vs LLM_UNAVAILABLE 구분 (SCRUM-15 10/29).
        code = _safe_code(resp)
        _log_bad(resp, status, "quota" if "insufficient_quota" in code else "unavailable")
        if "insufficient_quota" in code:
            raise BudgetExceeded(_SAFE_MSG_BUDGET)
        raise LlmUnavailable(_SAFE_MSG_UNAVAILABLE)
    if status == 408 or 500 <= status < 600:
        _log_bad(resp, status, "unavailable")
        raise LlmUnavailable(_SAFE_MSG_UNAVAILABLE)
    # 4xx — insufficient_quota 는 BudgetExceeded, 그 외는 LlmInvalidOutput
    code = _safe_code(resp)
    _log_bad(resp, status, "invalid")
    if "insufficient_quota" in code:
        raise BudgetExceeded(_SAFE_MSG_BUDGET)
    raise LlmInvalidOutput(_SAFE_MSG_INVALID)


def _json_or_invalid(resp: httpx.Response, safe_msg: str) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise LlmInvalidOutput(safe_msg) from exc
    if not isinstance(data, dict):
        raise LlmInvalidOutput(safe_msg)
    return data


def _safe_code(resp: httpx.Response) -> str:
    """공급자 응답 body 에서 code 만 꺼낸다. message 는 안 본다 — 허용 목록으로 제한."""
    try:
        data = resp.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    code = ((data.get("error") or {}).get("code") or "").lower()
    for fragment in _ALLOWED_PROVIDER_CODE_FRAGMENTS:
        if fragment in code:
            return code
    return ""


def _log_bad(resp: httpx.Response, status: int, kind: str) -> None:
    """공급자 code 는 서버 로그로만 (HTTP body·예외 message 로 흘려보내지 않음)."""
    log.warning(
        "llm_bad_response",
        extra={"status": status, "kind": kind, "provider_code": _safe_code(resp)},
    )


def extract_output_text(raw: dict[str, Any]) -> str:
    """Responses API output 에서 JSON 문자열만. 모양이 어긋나면 LlmInvalidOutput."""
    direct = raw.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    for item in raw.get("output") or []:
        for part in item.get("content") or []:
            if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                return part["text"]
    raise LlmInvalidOutput("llm output_text missing")


def build_body(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    schema: dict[str, Any],
    *,
    temperature_supported: bool,
    reasoning_effort: str,
) -> dict[str, Any]:
    """결정성 설정 하나로 고정 — 지원하면 `temperature=0`, 아니면 `reasoning.effort`."""
    body: dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema["name"],
                "schema": schema["schema"],
                "strict": True,
            }
        },
        "max_output_tokens": max_tokens,
    }
    if temperature_supported:
        body["temperature"] = 0.0
    else:
        body["reasoning"] = {"effort": reasoning_effort}
    return body


def json_schema_for(model_cls: type, *, name: str) -> dict[str, Any]:
    """Pydantic JSON Schema → OpenAI strict json_schema. 모든 property 를 required 로."""
    raw = model_cls.model_json_schema()
    return {"name": name.replace(".", "_"), "schema": _to_strict(raw)}


def _to_strict(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: v for k, v in node.items() if k not in ("title", "default")}
        node = {k: _to_strict(v) for k, v in node.items()}
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        return node
    if isinstance(node, list):
        return [_to_strict(v) for v in node]
    return node
