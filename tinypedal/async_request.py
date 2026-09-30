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
from asyncio import StreamReader, create_task, open_connection, wait_for
from collections.abc import Awaitable
from contextlib import asynccontextmanager, suppress
from functools import partial
from time import perf_counter

logger = logging.getLogger(__name__)


def resolve_hostname(host: str, port: int, timeout: float = 3) -> str:
    """Resolve hostname"""
    if host == "localhost" or host.startswith("127."):
        host_resolved = asyncio.run(
            localhost_resolve({host, "localhost", "127.0.0.1"}, port, timeout)
        )
        if host_resolved:
            return host_resolved
    return host


def set_header_get(uri: str = "/", host: str = "localhost", *headers: str) -> bytes:
    """Set GET request header"""
    # "Accept: application/json"
    extra_headers = "\r\n" + "\r\n".join(headers) if headers else ""
    return f"GET {uri} HTTP/1.1\r\nHost: {host}{extra_headers}\r\n\r\n".encode()


async def parse_response(reader: StreamReader) -> bytes:
    """Parse response"""
    # Get headers
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    if b"200" not in header_bytes:  # check http status code
        return b""
    # Get non-chunked data
    if b"chunked" not in header_bytes:
        # Get body length
        body_length = 0
        pos_beg = header_bytes.find(b"Content-Length")
        if pos_beg >= 0:
            try:
                pos_beg += 15  # offset
                pos_end = header_bytes.find(b"\r\n", pos_beg)
                body_length = int(header_bytes[pos_beg:pos_end])
            except (AttributeError, TypeError, IndexError, ValueError):
                body_length = 0
        if body_length <= 0:
            return b""
        # Note: read(n) returns only data already received (can be less than n),
        # readexactly(n) waits for complete body
        return await reader.readexactly(body_length)
    # Get chunked data: "size(hex)\r\n" + data + "\r\n", ends with zero size chunk
    temp_bytes = bytearray()
    while True:
        size_line = await reader.readuntil(b"\r\n")
        chunk_size = int(size_line[:-2].split(b";")[0], 16)  # ignore chunk extension
        if chunk_size <= 0:
            break
        temp_bytes.extend(await reader.readexactly(chunk_size))
        await reader.readexactly(2)  # CRLF after chunk data
    return bytes(temp_bytes)


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
    except (OSError, EOFError, asyncio.TimeoutError, ValueError):  # connection, ssl, incomplete data
        return b""


async def latency_test(request: bytes, host: str, port: int, time_out: float, ssl: bool = False) -> tuple[str, float]:
    """Test hostname connection latency, returns hostname, latency (seconds)"""
    start = perf_counter()
    await get_response(request, host, port, time_out, ssl)
    end = perf_counter()
    return host, end - start


def cancel_tasks(current_task: asyncio.Task, task_group: list[asyncio.Task], result: list) -> None:
    """Cancel task group once a probe answered

    Runs as a done callback, which must never raise: asyncio would only log it and the
    other probes would be left running, so a cancelled or failed probe is skipped here.
    """
    if not result and not current_task.cancelled() and current_task.exception() is None:
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
    # Start task
    for task in task_group:
        with suppress(asyncio.CancelledError, OSError, EOFError, asyncio.TimeoutError, ValueError):
            await task
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
