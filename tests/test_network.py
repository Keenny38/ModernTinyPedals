"""HTTP response parsing tests (no network), local hostname resolving (loopback only)"""

import asyncio
import socket
import threading

from tinypedal.async_request import parse_response, resolve_hostname, set_header_get
from tinypedal.update import parse_release


def feed_in_pieces(data: bytes, piece: int = 7) -> asyncio.StreamReader:
    """Simulate data arriving over network in small pieces"""
    reader = asyncio.StreamReader()

    async def feeder():
        for pos in range(0, len(data), piece):
            reader.feed_data(data[pos:pos + piece])
            await asyncio.sleep(0)
        reader.feed_eof()

    asyncio.get_running_loop().create_task(feeder())
    return reader


def run_parse(data: bytes) -> bytes:
    async def main():
        return await parse_response(feed_in_pieces(data))
    return asyncio.run(main())


BODY = b'{"tag_name":"v2.51.3","published_at":"2026-09-20T10:00:00Z","body":"' + b"x" * 5000 + b'"}'


def test_content_length_body_complete():
    header = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(BODY)
    assert run_parse(header + BODY) == BODY


def test_chunked_body():
    chunks = [BODY[:3000], BODY[3000:]]
    payload = b"".join(b"%x\r\n%s\r\n" % (len(c), c) for c in chunks) + b"0\r\n\r\n"
    header = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
    assert run_parse(header + payload) == BODY


def test_error_status_returns_empty():
    assert run_parse(b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\n{}") == b""


def test_parse_release():
    assert parse_release(BODY) == ((2, 51, 3), (2026, 9, 20))
    assert parse_release(b"") == ((0, 0, 0), (0, 0, 0))


# --- Local hostname resolving (probes 127.0.0.1 & localhost, keeps the fastest)
class LoopbackServer:
    """Minimal HTTP server on loopback, answers 200 and records requests"""

    def __init__(self):
        self.requests: list[bytes] = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                self.requests.append(conn.recv(4096))
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    def close(self):
        self._sock.close()


def test_resolve_hostname_sends_valid_request():
    """Probes must send a complete GET request (bytes), not a bare path string:
    asyncio's writer rejects str, which used to crash the whole RestAPI thread"""
    server = LoopbackServer()
    try:
        resolved = resolve_hostname("localhost", server.port, timeout=2)
        assert resolved in ("localhost", "127.0.0.1")
        assert server.requests, "no probe reached the server"
        request = server.requests[0]
        assert request.startswith(b"GET / HTTP/1.1\r\n")
        assert b"Host: " in request
        assert request.endswith(b"\r\n\r\n")
    finally:
        server.close()


def test_resolve_hostname_falls_back_when_nothing_listens():
    """Game not running: keep the configured host instead of raising"""
    with socket.socket() as probe:  # bind then close, so the port is free but was valid
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert resolve_hostname("localhost", free_port, timeout=1) == "localhost"


def test_resolve_hostname_keeps_remote_host_untouched():
    """Only loopback names are probed"""
    assert resolve_hostname("example.invalid", 6397, timeout=1) == "example.invalid"


def test_set_header_get():
    request = set_header_get("/rest/garage", "127.0.0.1", "Accept: application/json")
    assert request == (
        b"GET /rest/garage HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: application/json\r\n\r\n")

