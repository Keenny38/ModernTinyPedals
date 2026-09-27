"""HTTP response parsing tests (no network)"""

import asyncio

from tinypedal.async_request import parse_response
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
