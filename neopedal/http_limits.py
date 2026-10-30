#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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
Limits of HTTP exchanges with other programs (no Qt): total time of a request & size of an answer

A socket timeout only bounds each read: a server sending a byte now and then holds the reader forever,
and an answer read whole can fill the memory. Used by the local servers (request of a client received in time),
game Rest API requests (another program may listen on the game port) and RaceControl requests.
"""

from __future__ import annotations

import http.client
import io
import socket
from collections.abc import Callable
from time import monotonic

MAX_BODY = 16 * 1024 * 1024  # answer body size limit (bytes), same as async_request.MAX_BODY
READ_CHUNK = 65536


class BodyTooLarge(ValueError):
    """Answer body above size limit (rest of it never read)"""


class DeadlineReader(socket.SocketIO):
    """Socket reader, reads fail (TimeoutError) once deadline passed (each read also bounded by socket timeout)

    Counted as a file of the socket, as socket.makefile does: socket closed meanwhile (urllib closes the connection
    once the answer headers are read) really closed once this reader is closed.
    """

    def __init__(self, sock: socket.socket):
        super().__init__(sock, "rb")
        sock._io_refs += 1  # type: ignore[attr-defined]  # released by SocketIO.close
        self.deadline: float | None = None  # monotonic time, None: socket timeout only

    def readinto(self, buffer):
        deadline = self.deadline
        if deadline is None:
            return super().readinto(buffer)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("not received in time")
        sock = self._sock  # type: ignore[attr-defined]
        timeout = sock.gettimeout()
        if timeout is not None and timeout <= remaining:
            return super().readinto(buffer)
        sock.settimeout(remaining)
        try:
            return super().readinto(buffer)
        finally:
            sock.settimeout(timeout)


class DeadlineResponse(http.client.HTTPResponse):
    """http.client answer whose status line, headers & body are read before deadline (monotonic time, None: socket
    timeout only), reads past it raise TimeoutError (an OSError)

    Set as response_class of a connection, deadline bound with functools.partial (see deadline_response_class).
    """

    def __init__(self, sock, *args, deadline: float | None = None, **kwargs):
        super().__init__(sock, *args, **kwargs)
        self.fp.close()  # buffered reader of socket replaced by one bounded by deadline
        reader = DeadlineReader(sock)
        reader.deadline = deadline
        self.fp = io.BufferedReader(reader)


def deadline_response_class(seconds: float) -> Callable[..., DeadlineResponse]:
    """response_class of an http.client connection: next answer read within seconds from now"""
    deadline = monotonic() + seconds

    def response(sock, *args, **kwargs) -> DeadlineResponse:
        return DeadlineResponse(sock, *args, deadline=deadline, **kwargs)

    return response


def read_body(read: Callable[[int], bytes], limit: int = MAX_BODY, length: int | None = None) -> bytes:
    """Body read in chunks until its end (read: answer read(amount), b"" at the end)

    Args:
        limit: largest body (bytes).
        length: declared length (Content-Length), None if unknown (chunked, until connection closed).

    Raises:
        BodyTooLarge: declared length or body above limit (never read further).
    """
    if length is not None and length > limit:
        raise BodyTooLarge(f"answer body too large: {length} bytes")
    data = bytearray()
    while True:
        chunk = read(min(READ_CHUNK, limit + 1 - len(data)))
        if not chunk:
            return bytes(data)
        data += chunk
        if len(data) > limit:
            raise BodyTooLarge(f"answer body above {limit} bytes")
