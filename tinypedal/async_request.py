#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Asynchronous request
"""

from __future__ import annotations

import asyncio
import logging
import threading
from asyncio import StreamReader, create_task, open_connection, wait_for
from collections.abc import Awaitable
from contextlib import asynccontextmanager, suppress
from functools import partial
from time import monotonic, perf_counter
from typing import NamedTuple

logger = logging.getLogger(__name__)

RESOLVED_HOLD = 300.0  # seconds a resolved local address is reused (re-resolved after failure)
UNRESOLVED_HOLD = 5.0  # seconds before probing again when nothing answered (game not running)
_resolved_hosts: dict[tuple[str, int], tuple[str, float]] = {}  # (host, port): (address, expiry time)
_resolved_lock = threading.Lock()


def is_local_host(host: str) -> bool:
    """Whether host is a loopback name, resolved by probing"""
    return host == "localhost" or host.startswith("127.")


def _cached_hostname(host: str, port: int) -> str | None:
    """Cached address of host, None if not cached or expired"""
    with _resolved_lock:
        cached = _resolved_hosts.get((host, port))
    if cached is not None and monotonic() < cached[1]:
        return cached[0]
    return None


def _store_hostname(host: str, port: int, resolved: str) -> str:
    """Cache probing result, returns address to use (host itself if unresolved)"""
    hold = RESOLVED_HOLD if resolved else UNRESOLVED_HOLD
    address = resolved or host
    with _resolved_lock:
        _resolved_hosts[(host, port)] = (address, monotonic() + hold)
    return address


def forget_hostname(host: str, port: int) -> None:
    """Drop cached address of host (connection failed), next request probes again"""
    with _resolved_lock:
        _resolved_hosts.pop((host, port), None)


def clear_resolved_hosts() -> None:
    """Drop every cached address"""
    with _resolved_lock:
        _resolved_hosts.clear()


def resolve_hostname(host: str, port: int, timeout: float = 3) -> str:
    """Resolve hostname, cached (probing opens connections, see localhost_resolve)"""
    if not is_local_host(host):
        return host
    cached = _cached_hostname(host, port)
    if cached is not None:
        return cached
    resolved = asyncio.run(localhost_resolve({host, "localhost", "127.0.0.1"}, port, timeout))
    return _store_hostname(host, port, resolved)


async def resolve_hostname_async(host: str, port: int, timeout: float = 3) -> str:
    """Resolve hostname in running event loop (cancellable), cached"""
    if not is_local_host(host):
        return host
    cached = _cached_hostname(host, port)
    if cached is not None:
        return cached
    resolved = await localhost_resolve({host, "localhost", "127.0.0.1"}, port, timeout)
    return _store_hostname(host, port, resolved)


def set_header_get(uri: str = "/", host: str = "localhost", *headers: str) -> bytes:
    """Set GET request header"""
    # "Accept: application/json"
    extra_headers = "\r\n" + "\r\n".join(headers) if headers else ""
    return f"GET {uri} HTTP/1.1\r\nHost: {host}{extra_headers}\r\n\r\n".encode()


class HttpResponse(NamedTuple):
    """HTTP response

    Attributes:
        status: status code, 0 if invalid status line.
        body: body bytes (status 200 only, empty otherwise).
        keep_alive: whether connection can be reused for next request.
    """

    status: int
    body: bytes
    keep_alive: bool


def parse_status_line(line: bytes) -> tuple[bytes, int]:
    """HTTP version & status code from status line ("HTTP/1.1 200 OK"), status 0 if invalid"""
    parts = line.split(None, 2)
    if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
        return b"", 0
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return parts[0], 0


async def read_response(reader: StreamReader) -> HttpResponse:
    """Read complete response (status line, headers, body)"""
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    lines = header_bytes[:-4].split(b"\r\n")
    version, status = parse_status_line(lines[0])
    headers = {}
    for line in lines[1:]:
        name, separator, value = line.partition(b":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    connection = headers.get(b"connection", b"").lower()
    keep_alive = (version == b"HTTP/1.1" and connection != b"close") or connection == b"keep-alive"
    if b"chunked" in headers.get(b"transfer-encoding", b"").lower():
        body = await read_chunked(reader)
    else:
        try:
            body_length = int(headers.get(b"content-length", b"-1"))
        except ValueError:
            body_length = -1
        if body_length < 0:  # body until connection closes: not read, connection not reusable
            body = b""
            keep_alive = False
        elif body_length:
            # Note: read(n) returns only data already received (can be less than n),
            # readexactly(n) waits for complete body
            body = await reader.readexactly(body_length)
        else:
            body = b""
    return HttpResponse(status, body if status == 200 else b"", keep_alive)


async def read_chunked(reader: StreamReader) -> bytes:
    """Read chunked body: "size(hex)\r\n" + data + "\r\n", ends with zero size chunk & optional trailers"""
    temp_bytes = bytearray()
    while True:
        size_line = await reader.readuntil(b"\r\n")
        chunk_size = int(size_line[:-2].split(b";")[0], 16)  # ignore chunk extension
        if chunk_size <= 0:
            break
        temp_bytes.extend(await reader.readexactly(chunk_size))
        await reader.readexactly(2)  # CRLF after chunk data
    while await reader.readuntil(b"\r\n") != b"\r\n":  # trailers, until empty line
        pass
    return bytes(temp_bytes)


async def parse_response(reader: StreamReader) -> bytes:
    """Parse response, returns body of status 200 response, empty otherwise"""
    return (await read_response(reader)).body


class HttpConnection:
    """HTTP connection to one host, kept open between requests (keep-alive)

    Reconnects once if server closed the kept connection meanwhile. Falls back to one connection
    per request if a kept connection is not answered (server not keeping connections properly).
    """

    __slots__ = (
        "host",
        "port",
        "timeout",
        "_stream",
        "_reuse",
    )

    def __init__(self, host: str, port: int, timeout: float):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._stream: tuple[StreamReader, asyncio.StreamWriter] | None = None
        self._reuse = True

    async def get(self, request: bytes) -> bytes:
        """Body of GET request response (empty if status is not 200)

        Raises:
            OSError, EOFError, asyncio.TimeoutError, ValueError: connection error or invalid response.
        """
        reused = self._stream is not None
        try:
            return await self._get(request)
        except (TimeoutError, OSError, EOFError, ValueError) as error:
            self.close()
            if not reused:
                raise
            if isinstance(error, asyncio.TimeoutError):
                self._reuse = False  # kept connection not answered: new connection per request
            return await self._get(request)

    async def _get(self, request: bytes) -> bytes:
        if self._stream is None:
            self._stream = await wait_for(open_connection(self.host, self.port), self.timeout)
        reader, writer = self._stream
        writer.write(request)
        await writer.drain()
        response = await wait_for(read_response(reader), self.timeout)
        if not (self._reuse and response.keep_alive):
            self.close()
        return response.body

    def close(self) -> None:
        """Close connection (opened again by next request)"""
        if self._stream is not None:
            self._stream[1].close()
            self._stream = None


@asynccontextmanager
async def http_get(request: bytes, host: str, port: int, time_out: float):
    """Async request - HTTP get response"""
    writer = None
    try:
        reader, writer = await wait_for(open_connection(host, port), time_out)
        writer.write(request)
        await writer.drain()
        yield await wait_for(parse_response(reader), time_out)
    finally:
        if writer is not None:
            writer.close()
            with suppress(OSError):  # ignore close error (ssl close notify), data already received
                await writer.wait_closed()


@asynccontextmanager
async def https_get(request: bytes, host: str, port: int, time_out: float):
    """Async request - HTTPS get response"""
    writer = None
    try:
        reader, writer = await wait_for(open_connection(host, port, ssl=True), time_out)
        writer.write(request)
        await writer.drain()
        yield await wait_for(parse_response(reader), time_out)
    finally:
        if writer is not None:
            writer.close()
            with suppress(OSError):  # ignore close error (ssl close notify), data already received
                await writer.wait_closed()


async def get_response(request: bytes, host: str, port: int, time_out: float, ssl: bool = False) -> bytes:
    """Get response data (bytes)"""
    try:
        func_get = https_get if ssl else http_get
        async with func_get(request, host, port, time_out) as raw_bytes:
            return raw_bytes
    except (TimeoutError, OSError, EOFError, ValueError):  # connection, ssl, incomplete data
        return b""


async def latency_test(request: bytes, host: str, port: int, time_out: float, ssl: bool = False) -> tuple[str, float]:
    """Test hostname connection latency, returns hostname, latency (seconds)

    Raises OSError if nothing accepts the connection: a refused connection returns at once
    (on Linux), and must not win the race against hosts that really answer.
    """
    start = perf_counter()
    try:
        _, writer = await wait_for(open_connection(host, port, ssl=ssl), time_out)
    except TimeoutError as error:
        raise OSError(f"{host}:{port} timed out") from error
    try:
        writer.write(request)
        await writer.drain()
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
    return host, perf_counter() - start


def cancel_tasks(current_task: asyncio.Task, task_group: list[asyncio.Task], result: list) -> None:
    """Cancel task group once a probe answered

    Runs as a done callback, which must never raise: asyncio would only log it and the
    other probes would be left running, so a cancelled or failed probe is skipped here.
    """
    if current_task.cancelled() or current_task.exception() is not None:
        if current_task in task_group:  # failed probe: let the others run
            task_group.remove(current_task)
        return
    if not result:
        result.append(current_task.result())
    if task_group:
        for task in reversed(task_group):
            task.cancel()
            task_group.remove(task)


async def localhost_resolve(hostnames: set[str], port: int, timeout: float = 3) -> str:
    """Resolve localhost name, returns fastest address (or empty if none)"""
    # Set task, each probe sends a complete GET request (bytes) with its own Host header
    task_group = [
        create_task(latency_test(set_header_get("/", hostname), hostname, port, timeout))
        for hostname in hostnames
    ]
    # Cancel all task on first response
    result: list[tuple[str, float]] = []
    cancel_func = partial(cancel_tasks, task_group=task_group, result=result)
    for task in task_group:
        task.add_done_callback(cancel_func)
    # Wait every probe. Done callbacks remove failed probes from task group meanwhile,
    # so wait on a copy: a slower probe that answers must not be skipped.
    await asyncio.gather(*tuple(task_group), return_exceptions=True)
    # Get fastest host name
    if result:
        host, latency = result[0]
        if latency < 1:  # accept response time less than 1 second
            logger.info(
                "RestAPI: local hostname resolved as '%s' (response %sms)",
                host,
                latency * 1000000 // 1 / 1000,
            )
            return host
    logger.warning("RestAPI: unable to resolve local hostname")
    return ""


async def _print_result(test_func: Awaitable):
    """Test result"""
    start = perf_counter()
    result = await test_func
    end = perf_counter()
    is_timeout = " (timeout)" if not result else " (done)"
    print(f"{end - start:.6f}s{is_timeout},", result)


async def _test_async_get(timeout: float):
    """Test run"""
    req1 = set_header_get("/rest/sessions/setting/SESSSET_race_timescale")
    req2 = set_header_get("/rest/sessions/weather")
    rf2_host = await localhost_resolve({"localhost", "127.0.0.1"}, 5397, timeout)
    task_rf2 = [
        _print_result(get_response(req1, rf2_host, 5397, timeout)),  # RF2
        _print_result(get_response(req2, rf2_host, 5397, timeout)),  # RF2
    ]
    req3 = set_header_get("/rest/sessions/weather")
    req4 = set_header_get("/rest/strategy/pitstop-estimate")
    lmu_host = await localhost_resolve({"localhost", "127.0.0.1"}, 6397, timeout)
    task_lmu = [
        _print_result(get_response(req3, lmu_host, 6397, timeout)),  # LMU
        _print_result(get_response(req4, lmu_host, 6397, timeout)),  # LMU
    ]
    await asyncio.gather(*task_rf2, *task_lmu)


if __name__ == "__main__":
    asyncio.run(_test_async_get(1))
