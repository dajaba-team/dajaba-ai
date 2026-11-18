"""SCRUM-272 — stdout JSON 로그를 그대로 받아 보는 공용 도구 (docs/shared/04 "로그").

`setup_logging` 을 진짜로 돌려 root 핸들러가 `sys.stdout`(capsys 가 바꿔 둔 것)에 쓰게 한다.
alembic `fileConfig` 가 이미 만들어진 `aml_ai.*` 로거를 꺼 둘 수 있어(-m db) 블록 동안 다시 켜고 되돌린다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from aml_ai.shared.config import get_settings
from aml_ai.shared.logging import setup_logging

REQUIRED_FIELDS = ("ts", "level", "service", "logger", "msg", "request_id")
OLD_FIELDS = ("asctime", "levelname", "name", "message")


@contextmanager
def stdout_json_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    loggers = [lg for lg in logging.Logger.manager.loggerDict.values() if isinstance(lg, logging.Logger)]
    disabled = [lg for lg in loggers if lg.disabled and lg.name != "uvicorn.access"]
    for lg in disabled:
        lg.disabled = False
    setup_logging(get_settings())
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        for lg in disabled:
            lg.disabled = True


def parse_lines(out: str) -> list[dict]:
    """빈 줄을 뺀 모든 줄이 JSON 객체여야 한다 — 아니면 json 오류로 테스트가 실패."""
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert all(isinstance(line, dict) for line in lines)
    return lines


def by_msg(lines: list[dict], msg: str) -> list[dict]:
    return [line for line in lines if line.get("msg") == msg]
