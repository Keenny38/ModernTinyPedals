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
    from tinypedal.async_request import clear_resolved_hosts

    clear_resolved_hosts()
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



def test_failed_probe_does_not_cancel_others():
    """A refused probe (instant on Linux) must not stop a probe that may still answer"""
    import asyncio

    from tinypedal.async_request import cancel_tasks

    async def scenario():
        async def refused():
            raise OSError("refused")

        async def slow():
            await asyncio.sleep(0.05)
            return "localhost", 0.05

        failed, good = asyncio.create_task(refused()), asyncio.create_task(slow())
        group, result = [failed, good], []
        await asyncio.gather(failed, return_exceptions=True)
        cancel_tasks(failed, group, result)
        assert not good.cancelled() and result == []
        await good
        cancel_tasks(good, group, result)
        return result

    assert asyncio.run(scenario()) == [("localhost", 0.05)]


# --- Audit fixes (package A)
def test_status_read_from_status_line():
    """"200" elsewhere in headers is not a success status"""
    from tinypedal.async_request import parse_status_line

    assert run_parse(b"HTTP/1.1 404 Not Found\r\nX-Request-Id: 200\r\nContent-Length: 2\r\n\r\n{}") == b""
    assert run_parse(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n{}") == b"{}"  # header name case ignored
    assert parse_status_line(b"HTTP/1.0 503 Busy") == (b"HTTP/1.0", 503)
    assert parse_status_line(b"garbage") == (b"", 0)


def test_failed_first_probe_keeps_slower_answer(monkeypatch):
    """First probe refused before a slower one answers: resolving must not return nothing"""
    from tinypedal import async_request

    async def probe(request, host, port, timeout, ssl=False):
        if host == "127.0.0.1":
            raise OSError("refused")
        await asyncio.sleep(0.05)
        return host, 0.05

    monkeypatch.setattr(async_request, "latency_test", probe)
    for _ in range(5):  # probe order of set varies
        assert asyncio.run(async_request.localhost_resolve({"127.0.0.1", "localhost"}, 1)) == "localhost"


def test_resolved_host_cached_until_forgotten():
    from tinypedal.async_request import clear_resolved_hosts, forget_hostname

    clear_resolved_hosts()
    server = LoopbackServer()
    try:
        first = resolve_hostname("localhost", server.port, timeout=2)
        probes = len(server.requests)
        assert probes and resolve_hostname("localhost", server.port, timeout=2) == first
        assert len(server.requests) == probes  # no new probing connection
        forget_hostname("localhost", server.port)  # connection failed: resolved again
        resolve_hostname("localhost", server.port, timeout=2)
        assert len(server.requests) > probes
    finally:
        server.close()
        clear_resolved_hosts()


def make_http_server(protocol: str, connections: list):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        protocol_version = protocol

        def setup(self):
            super().setup()
            connections.append(self.client_address)

        def do_GET(self):  # http.server API name
            body = b'{"ok": 1}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_http_connection_kept_open():
    """Rest API polling reuses its connection (HTTP/1.1), reconnects when server closes it (HTTP/1.0)"""
    from tinypedal.async_request import HttpConnection

    for protocol, expected in (("HTTP/1.1", 1), ("HTTP/1.0", 3)):
        connections: list = []
        server = make_http_server(protocol, connections)
        try:
            async def requests(port):
                connection = HttpConnection("127.0.0.1", port, 2)
                bodies = [await connection.get(set_header_get("/rest/x", "127.0.0.1")) for _ in range(3)]
                connection.close()
                return bodies

            assert asyncio.run(requests(server.server_address[1])) == [b'{"ok": 1}'] * 3
            assert len(connections) == expected
        finally:
            server.shutdown()
            server.server_close()


def test_chunked_trailer_consumed():
    """Kept connection: data after chunked body (trailers) must not remain for next response"""
    async def main():
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nok\r\n0\r\nX-T: 1\r\n\r\nNEXT")
        reader.feed_eof()
        body = await parse_response(reader)
        return body, await reader.read()

    assert asyncio.run(main()) == (b"ok", b"NEXT")


def test_header_over_reader_limit_is_invalid_response():
    """Header or chunk size line over StreamReader limit (64 KiB): ValueError like other invalid
    response (caught by callers), not asyncio.LimitOverrunError"""
    import pytest

    from tinypedal.async_request import HttpConnection, get_response

    huge = b"X-Big: " + b"a" * (70 * 1024) + b"\r\n"
    with pytest.raises(ValueError, match="too long"):
        run_parse(b"HTTP/1.1 200 OK\r\n" + huge + b"Content-Length: 2\r\n\r\nok")
    with pytest.raises(ValueError, match="too long"):
        run_parse(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + b"0" * (70 * 1024) + b"1\r\nx\r\n")

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]

    def answer():
        for _ in range(2):
            client, _ = server.accept()
            with client:
                client.recv(4096)
                client.sendall(b"HTTP/1.1 200 OK\r\n" + huge + b"Content-Length: 2\r\n\r\nok")

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    request = set_header_get("/", "127.0.0.1")

    async def main():
        connection = HttpConnection("127.0.0.1", port, 3)
        try:
            with pytest.raises(ValueError):
                await connection.get(request)
        finally:
            connection.close()
        return await get_response(request, "127.0.0.1", port, 3)

    try:
        assert asyncio.run(main()) == b""
    finally:
        thread.join(5)
        server.close()
