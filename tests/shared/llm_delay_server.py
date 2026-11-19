"""SCRUM-322 로컬 TCP 지연 서버 — 요청 하나를 받고 정해진 모양으로 늦게 답한다. 외부 네트워크 0.

모드: `late_header`(헤더·본문을 `delay` 뒤 한 번에) · `header_chunks`(헤더를 조각으로 `delay` 간격) ·
`body_chunks`(헤더는 바로, 본문을 조각으로 `delay` 간격) · `ok`(바로) · `status_500`(바로 500).
기다리는 동안 클라이언트가 연결을 닫으면 그 시각을 `closed_at`(시작 기준 초)에 남기고 보내기를 멈춘다.
"""

from __future__ import annotations

import json
import select
import socket
import threading
import time

BODY = json.dumps(
    {
        "model": "gpt-test",
        "output_text": json.dumps({"kind": "OUT_OF_SCOPE", "out_of_scope_reason": "JUDGMENT", "bundles": []}),
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
).encode()
CHUNK = 8
HEADER_PAD = 400  # 헤더 조각 모드에서 헤더를 길게 — 조각 수 = 헤더 길이 / CHUNK


def _head(status: str, length: int, pad: int = 0) -> bytes:
    extra = b"X-Pad: " + b"p" * pad + b"\r\n" if pad else b""
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n".encode()
        + extra
        + f"Content-Length: {length}\r\nConnection: close\r\n\r\n".encode()
    )


class DelayServer:
    def __init__(self, mode: str, delay: float = 0.0) -> None:
        self.mode, self.delay = mode, delay
        self.closed_at: float | None = None
        self.sent_all = False
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.base_url = f"http://127.0.0.1:{self._sock.getsockname()[1]}/v1"
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def join(self, timeout: float = 5.0) -> None:
        self._thread.join(timeout)
        self._sock.close()

    def _serve(self) -> None:
        conn, _ = self._sock.accept()
        with conn:
            _read_request(conn)
            for part, wait in self._plan():
                if not self._wait_open(conn, wait):
                    return
                try:
                    conn.sendall(part)
                except OSError:
                    self._mark_closed()
                    return
            self.sent_all = True
            self._wait_open(conn, 1.0)

    def _plan(self) -> list[tuple[bytes, float]]:
        if self.mode == "ok":
            return [(_head("200 OK", len(BODY)) + BODY, 0.0)]
        if self.mode == "status_500":
            return [(_head("500 Internal Server Error", 2) + b"{}", 0.0)]
        if self.mode == "late_header":
            return [(_head("200 OK", len(BODY)) + BODY, self.delay)]
        if self.mode == "header_chunks":
            head = _head("200 OK", len(BODY), HEADER_PAD)
            return [(head[i : i + CHUNK], self.delay) for i in range(0, len(head), CHUNK)] + [(BODY, 0.0)]
        if self.mode == "body_chunks":
            parts = [(BODY[i : i + CHUNK], self.delay) for i in range(0, len(BODY), CHUNK)]
            return [(_head("200 OK", len(BODY)), 0.0), *parts]
        raise ValueError(self.mode)

    def _wait_open(self, conn: socket.socket, seconds: float) -> bool:
        """`seconds` 동안 기다리며 클라이언트가 닫았는지 본다. 닫혔으면 False."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([conn], [], [], 0.005)
            if ready:
                try:
                    data = conn.recv(1)
                except OSError:
                    data = b""
                if not data:
                    self._mark_closed()
                    return False
        return True

    def _mark_closed(self) -> None:
        if self.closed_at is None:
            self.closed_at = time.monotonic() - self._t0


def _read_request(conn: socket.socket) -> None:
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += conn.recv(65536)
    head, rest = buf.split(b"\r\n\r\n", 1)
    length = next(
        int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")
    )
    while len(rest) < length:
        rest += conn.recv(65536)


def closed_port_url() -> str:
    """연결 실패용 — 잡았다 바로 놓은 포트."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/v1"
