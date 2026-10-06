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
Stream overlays: overlays as browser sources of OBS Studio, Streamlabs, XSplit, vMix... (disabled by default)

    GET /?token=<token>                             sources page (links to every source, to test in a browser)
    GET /overlay/<name>?token=<token>               one overlay, top left (browser source size: overlay size)
    GET /layout?token=<token>                       every stream overlay at its place on screen (size of screen)
    GET /results?token=<token>                      results of last race (game results files), pages & classes cycled
    GET /api/frames?token=&view=<name|layout>&seq=<n>&codec=<zraw|png>
                                                    overlay images changed since frame <n> (waits up to 1 s)
    GET /api/results?token=&session=<race|qualifying|any>   last session results (JSON)
    GET /fonts/<name>.ttf                           bundled fonts (results page)

Overlays look exactly as on screen: image of each overlay window as last painted (window backing store, no
repaint), copied in GUI thread only while a source is watching, only sent again when it changed. Images are
encoded in server threads: raw RGBA compressed with zlib ("zraw", browser inflates it), PNG for browsers
without DecompressionStream.

Frames bundle: 4 bytes header length (big endian), header JSON {"seq", "canvas": [width, height],
"overlays": [{"name", "x", "y", "w", "h", "opacity", "size"}]}, then image data of each overlay in header order
("size" bytes, 0: unchanged since frame "seq" asked). Positions & sizes in screen pixels.

Per overlay "stream_visibility" option: on screen & stream, stream only (window fully transparent on screen
while overlays are locked), screen only. Listens on 127.0.0.1 unless LAN access is enabled (streaming PC);
the access token is required in every address but fonts.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import struct
import threading
import time
import zlib
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NamedTuple
from urllib.parse import parse_qs, quote, urlparse

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QWidget

from . import app_signal
from .const_file import ConfigType, FontFile
from .i18n import current_language, tr
from .process import results_file as rf
from .process import results_text as rt
from .setting import cfg

logger = logging.getLogger(__name__)

STREAM_VISIBILITY = ("Screen & Stream", "Stream Only", "Screen Only")  # per overlay option choices
LAYOUT = "layout"  # view of every overlay
WATCH_SECONDS = 3.0  # view counted as watched this long after its last frames request
WAIT_SECONDS = 1.0  # frames request waits this long for a new frame
MAX_VIEWS = 256  # views remembered as watched (bounded)
CODECS = ("zraw", "png")
VIEW_NAME = re.compile(r"^[a-z0-9_]{1,64}$")
FONT_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}\.ttf$")
RESULT_KINDS = {"race": ("R",), "qualifying": ("Q",), "any": ("P", "Q", "W", "R")}
RESULTS_SCANNED = 60  # newest results files looked at for last session of a kind
TOKEN_BYTES = 18  # access token: 24 url-safe characters


def stream_visibility(wcfg) -> str:
    value = wcfg.get("stream_visibility", STREAM_VISIBILITY[0]) if wcfg is not None else STREAM_VISIBILITY[0]
    return value if value in STREAM_VISIBILITY else STREAM_VISIBILITY[0]


def shown_on_stream(wcfg) -> bool:
    return stream_visibility(wcfg) != "Screen Only"


def stream_only(wcfg) -> bool:
    return stream_visibility(wcfg) == "Stream Only"


# Capture (GUI thread)
class Placement(NamedTuple):
    """Overlay shown on stream: place on canvas (screen pixels) & opacity"""

    name: str
    x: int
    y: int
    opacity: float


def window_image(widget: QWidget) -> QImage | None:
    """Image of overlay window as last painted (window backing store: no repaint), rendered again if not available"""
    store = widget.backingStore()
    device = store.paintDevice() if store is not None else None
    if isinstance(device, QImage) and not device.isNull():
        ratio = device.devicePixelRatio()
        width, height = round(widget.width() * ratio), round(widget.height() * ratio)
        if 0 < width <= device.width() and 0 < height <= device.height():
            return device.copy(0, 0, width, height)
    pixmap = widget.grab()
    return pixmap.toImage() if not pixmap.isNull() else None


def image_checksum(image: QImage) -> int:
    pixels = memoryview(image.constBits())[:image.sizeInBytes()]  # type: ignore[arg-type]
    return zlib.crc32(pixels, image.width() << 16 | image.height())


def stream_overlays() -> list[tuple[str, QWidget]]:
    """Overlay windows shown now & shown on stream: (widget name, window)"""
    overlays = []
    for widget in QApplication.topLevelWidgets():
        name = getattr(widget, "widget_name", None)  # closed overlay lost its attributes
        wcfg = getattr(widget, "wcfg", None)
        if isinstance(name, str) and wcfg is not None and shown_on_stream(wcfg) and widget.isVisible():
            overlays.append((name, widget))
    return overlays


def stream_opacity(widget: QWidget) -> float:
    """Opacity on stream: overlay opacity (fading on screen too), set opacity for stream only overlays"""
    wcfg = getattr(widget, "wcfg", None)
    if stream_only(wcfg):
        try:
            return min(max(float(wcfg["opacity"]), 0.0), 1.0)  # type: ignore[index]
        except (KeyError, TypeError, ValueError):
            return 1.0
    return min(max(widget.windowOpacity(), 0.0), 1.0)


def canvas_screen(widgets: list[QWidget]):
    """Screen of stream canvas: screen holding most stream overlays, primary screen if none"""
    counts: dict[Any, int] = {}
    for widget in widgets:
        screen = QGuiApplication.screenAt(widget.geometry().center())
        if screen is not None:
            counts[screen] = counts.get(screen, 0) + 1
    if counts:
        return max(counts, key=lambda screen: counts[screen])
    return QGuiApplication.primaryScreen()


class OverlayCapture(QObject):
    """Overlay images copied while a source is watching (GUI thread), handed to frame store"""

    def __init__(self, store: FrameStore):
        super().__init__()
        self.store = store
        self._checksums: dict[str, int] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.capture)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self, frame_rate: int):
        self._timer.start(max(int(1000 / min(max(frame_rate, 1), 60)), 16))

    def stop(self):
        self._timer.stop()
        self._checksums.clear()

    def capture(self):
        watched = self.store.watched()
        if not watched:
            if self._checksums:  # nobody watching: next source gets fresh images
                self._checksums.clear()
                self.store.clear()
            return
        overlays = stream_overlays()
        everything = LAYOUT in watched
        screen = canvas_screen([widget for _, widget in overlays])
        if screen is not None:
            origin, ratio = screen.geometry().topLeft(), screen.devicePixelRatio()
            canvas = (round(screen.geometry().width() * ratio), round(screen.geometry().height() * ratio))
        else:  # no screen (headless)
            origin, ratio, canvas = QPoint(0, 0), 1.0, (0, 0)
        images: dict[str, QImage] = {}
        shown: list[Placement] = []
        for name, widget in overlays:
            if not everything and name not in watched:
                continue
            image = window_image(widget)
            if image is None:
                continue
            checksum = image_checksum(image)
            if self._checksums.get(name) != checksum:
                self._checksums[name] = checksum
                images[name] = image
            position = widget.pos() - origin
            shown.append(Placement(name, round(position.x() * ratio), round(position.y() * ratio),
                                   round(stream_opacity(widget), 3)))
        names = {placement.name for placement in shown}
        for name in [name for name in self._checksums if name not in names]:
            del self._checksums[name]  # gone: image sent again when back
        self.store.publish(images, shown, canvas)


# Frames (shared by GUI & server threads)
class StoredFrame:
    """Overlay image, encoded once per codec when first asked (server thread)"""

    __slots__ = ("seq", "image", "_encoded", "_lock")

    def __init__(self, seq: int, image: QImage):
        self.seq = seq
        self.image = image
        self._encoded: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def payload(self, codec: str) -> bytes:
        with self._lock:
            data = self._encoded.get(codec)
            if data is None:
                data = self._encoded[codec] = encode_image(self.image, codec)
            return data


def encode_image(image: QImage, codec: str) -> bytes:
    """Image data: zlib compressed RGBA (not premultiplied, ImageData layout), or PNG"""
    if codec == "png":
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")  # type: ignore[call-overload]  # device save refuses bytes format at run time
        buffer.close()
        return bytes(data.data())
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return zlib.compress(memoryview(rgba.constBits())[:rgba.sizeInBytes()], 1)  # type: ignore[arg-type]


class FrameStore:
    """Overlay images & places of last capture, frames request waits for next one"""

    def __init__(self):
        self._condition = threading.Condition()
        self.seq = 0
        self._frames: dict[str, StoredFrame] = {}
        self._shown: tuple[Placement, ...] = ()
        self._canvas = (0, 0)
        self._requests: dict[str, float] = {}

    def touch(self, view: str):
        """View asked frames now: overlays captured while watched"""
        now = time.monotonic()
        with self._condition:
            if view not in self._requests and len(self._requests) >= MAX_VIEWS:
                oldest = min(self._requests, key=lambda name: self._requests[name])
                del self._requests[oldest]
            self._requests[view] = now

    def watched(self) -> set[str]:
        now = time.monotonic()
        with self._condition:
            return {view for view, last in self._requests.items() if now - last < WATCH_SECONDS}

    def watched_overlays(self) -> set[str]:
        """Overlays watched now (layout: every overlay shown)"""
        watched = self.watched()
        if LAYOUT in watched:
            with self._condition:
                return {placement.name for placement in self._shown} | watched
        return watched

    def clear(self):
        with self._condition:
            self._frames.clear()
            self._shown = ()
            self.seq += 1
            self._condition.notify_all()

    def publish(self, images: dict[str, QImage], shown: list[Placement], canvas: tuple[int, int]):
        """New images, places of overlays shown: frames requests waiting get them (nothing if nothing changed)"""
        with self._condition:
            placements = tuple(shown)
            if not images and placements == self._shown and canvas == self._canvas:
                return
            self.seq += 1
            for name, image in images.items():
                self._frames[name] = StoredFrame(self.seq, image)
            names = {placement.name for placement in placements}
            for name in [name for name in self._frames if name not in names]:
                del self._frames[name]
            self._shown = placements
            self._canvas = canvas
            self._condition.notify_all()

    def bundle(self, view: str, after: int, codec: str, timeout: float = WAIT_SECONDS) -> bytes:
        """Frames of view newer than "after" (see module doc), waits for a new frame up to timeout"""
        with self._condition:
            if after > self.seq:  # server started again since
                after = 0
            self._condition.wait_for(lambda: self.seq > after, timeout)
            seq = self.seq
            placements = [placement for placement in self._shown if view == LAYOUT or placement.name == view]
            frames = [(placement, self._frames.get(placement.name)) for placement in placements]
            canvas = self._canvas
        entries = []
        payloads = []
        for placement, frame in frames:
            if frame is None:
                continue
            data = frame.payload(codec) if frame.seq > after else b""
            entries.append({
                "name": placement.name, "x": placement.x, "y": placement.y,
                "w": frame.image.width(), "h": frame.image.height(), "opacity": placement.opacity, "size": len(data),
            })
            payloads.append(data)
        header = json.dumps({"seq": seq, "canvas": list(canvas), "overlays": entries}).encode("utf-8")
        return struct.pack(">I", len(header)) + header + b"".join(payloads)


# Race results (server threads)
class ResultsCache:
    """Last session results of a kind, file read again only when changed"""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple, rf.SessionResult]] = {}  # kind: (file key, result)
        self._skipped: set[tuple] = set()  # file keys of sessions without lap (not read again)

    def latest(self, kind: str) -> rf.SessionResult | None:
        codes = RESULT_KINDS.get(kind, RESULT_KINDS["race"])
        folders = rf.results_folders(rf.chosen_results_folder(cfg.path.config))
        paths: list[str] = []
        for folder in folders:
            paths.extend(rf.results_files(folder))
        paths.sort(key=os.path.basename, reverse=True)  # names start with date
        for path in paths[:RESULTS_SCANNED]:
            stem = os.path.splitext(os.path.basename(path))[0].rstrip("0123456789")
            if not stem or stem[-1] not in codes:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            key = (path, stat.st_size, stat.st_mtime)
            with self._lock:
                cached = self._cache.get(kind)
                skipped = key in self._skipped
            if cached is not None and cached[0] == key:
                return cached[1]
            if skipped:
                continue
            folder = os.path.dirname(path)
            names = rf.profile_player_names(folder) or [
                name for game in rf.find_results_folders().values() for name in rf.profile_player_names(game)]
            try:
                result = rf.read_results(path, names)
            except (OSError, ValueError):  # being written
                continue
            if not result.entries or result.most_laps <= 0:  # nobody completed a lap: skipped
                with self._lock:
                    if len(self._skipped) > RESULTS_SCANNED * 4:
                        self._skipped.clear()
                    self._skipped.add(key)
                continue
            with self._lock:
                self._cache[kind] = (key, result)
            return result
        return None


RESULTS_LABELS = {
    "pos": "Pos",
    "driver": "Driver",
    "car": "Team",  # team name shown (car model when none)
    "laps": "Laps",
    "gap": "Time / Gap",
    "best": "Best Lap",
    "pits": "Pit Stops",
    "unfinished": "Unfinished",
    "waiting": "Waiting for results…",
    "cars": "cars",
}


def results_snapshot(cache: ResultsCache, kind: str) -> dict[str, Any]:
    """Last session results for results page (texts in app language)"""
    labels = {key: tr(text) for key, text in RESULTS_LABELS.items()}
    result = cache.latest(kind)
    if result is None:
        return {"available": False, "labels": labels}
    entries = result.entries
    leaders: dict[str, rf.Entry] = {}
    fastest: dict[str, float] = {}
    for entry in entries:
        leaders.setdefault(entry.car_class, entry)
        if entry.best_lap > 0:
            fastest[entry.car_class] = min(fastest.get(entry.car_class, entry.best_lap), entry.best_lap)
    overall_best = min(fastest.values(), default=0.0)
    classes = cfg.user.classes
    rows = []
    for rank, entry in enumerate(entries, 1):
        gap, tone = rt.entry_gap(result, entry, entries[0], rank == 1)
        class_gap, class_tone = rt.entry_gap(result, entry, leaders[entry.car_class],
                                             leaders[entry.car_class] is entry)
        rows.append({
            "pos": entry.position or rank,
            "classPos": entry.class_position,
            "cls": entry.car_class,
            "color": rt.class_color(entry.car_class, classes),
            "number": entry.number,
            "driver": entry.name,
            "team": entry.team or entry.vehicle,
            "car": entry.car,
            "laps": entry.laps_completed,
            "gap": gap,
            "gapTone": tone,
            "classGap": class_gap,
            "classGapTone": class_tone,
            "best": rt.lap_text(entry.best_lap),
            "fastest": entry.best_lap > 0 and entry.best_lap == overall_best,
            "classFastest": entry.best_lap > 0 and entry.best_lap == fastest.get(entry.car_class),
            "pits": entry.pitstops,
            "player": entry.player,
        })
    subtitle = next((name for name in (result.course, result.venue) if name and name != result.track), "")
    return {
        "available": True,
        "id": f"{os.path.basename(result.path)}:{len(entries)}:{result.most_laps}",
        "title": result.track,
        "subtitle": subtitle,
        "kind": rt.kind_text(result.kind),
        "race": result.kind == "Race",
        "partial": rf.race_unfinished(result),
        "classes": [{"name": name, "color": rt.class_color(name, classes),
                     "count": sum(1 for entry in entries if entry.car_class == name)} for name in result.classes],
        "rows": rows,
        "labels": labels,
    }


# Server
def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


class StreamHandler(BaseHTTPRequestHandler):
    """Stream overlay request handler"""

    protocol_version = "HTTP/1.1"  # frames asked again and again on same connection
    server_version = "TinyPedal"
    timeout = 60  # idle connection closed
    token = ""
    store: FrameStore
    results: ResultsCache

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        query = parse_qs(url.query)
        if path.startswith("/fonts/"):
            self.send_font(path[7:])
            return
        if not self.authorized(query.get("token", [""])[0]):
            self.send_body(403, forbidden_html().encode("utf-8"), "text/html; charset=utf-8")
            return
        try:
            self.route(path, query)
        except (ConnectionError, TimeoutError):
            raise
        except Exception:  # never drop connection on data error
            logger.exception("STREAM OVERLAY: request %s failed", path)
            self.send_body(500, b"error", "text/plain")

    def route(self, path: str, query: dict[str, list[str]]):
        if path in ("/", "/index.html"):
            self.send_html(index_html(self.token))
        elif path == "/layout":
            self.send_html(source_html(LAYOUT, tr("Layout")))
        elif path.startswith("/overlay/") and VIEW_NAME.match(path[9:]):
            self.send_html(source_html(path[9:], overlay_label(path[9:])))
        elif path == "/results":
            self.send_html(results_html())
        elif path == "/api/frames":
            view = query.get("view", [LAYOUT])[0]
            if view != LAYOUT and not VIEW_NAME.match(view):
                self.send_body(400, b"invalid view", "text/plain")
                return
            codec = query.get("codec", [CODECS[0]])[0]
            try:
                after = max(int(query.get("seq", ["0"])[0]), 0)
            except ValueError:
                after = 0
            self.store.touch(view)
            body = self.store.bundle(view, after, codec if codec in CODECS else CODECS[0])
            self.send_body(200, body, "application/octet-stream")
        elif path == "/api/results":
            kind = query.get("session", ["race"])[0]
            data = results_snapshot(self.results, kind if kind in RESULT_KINDS else "race")
            self.send_body(200, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")
        else:
            self.send_body(404, b"not found", "text/plain")

    def authorized(self, token: str) -> bool:
        return bool(token) and bool(self.token) and hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))

    def send_font(self, name: str):
        path = os.path.join(FontFile.FOLDER, name)
        if not FONT_NAME.match(name) or not os.path.isfile(path):
            self.send_body(404, b"not found", "text/plain")
            return
        with open(path, "rb") as file:
            data = file.read()
        self.send_body(200, data, "font/ttf", cache=True)

    def send_html(self, page: str):
        self.send_body(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def send_body(self, status: int, body: bytes, content_type: str, cache: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")  # token in page address
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self'; connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # every frame is a request


class StreamServer(ThreadingHTTPServer):
    """Stream overlay HTTP server, client errors (dropped connection) only logged"""

    daemon_threads = True

    def handle_error(self, request, client_address):
        logger.debug("STREAM OVERLAY: request from %s failed", client_address[0], exc_info=True)


class StreamOverlay:
    """Stream overlay server & overlay capture control"""

    def __init__(self):
        self._server: StreamServer | None = None
        self._thread: threading.Thread | None = None
        self._address: tuple[str, int] | None = None
        self.store = FrameStore()
        self.results = ResultsCache()
        self._capture: OverlayCapture | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @staticmethod
    def setting() -> dict:
        return cfg.user.config["stream_overlay"]

    def access_token(self) -> str:
        """Access token, generated & saved on first use"""
        setting = self.setting()
        token = str(setting.get("access_token", "")).strip()
        if len(token) < 16:
            token = new_token()
            setting["access_token"] = token
            cfg.save(config_type=ConfigType.CONFIG)
        return token

    def new_access_token(self) -> str:
        """Replace access token (addresses given before stop working), server started again with it"""
        self.setting()["access_token"] = new_token()
        cfg.save(config_type=ConfigType.CONFIG)
        StreamHandler.token = self.access_token()
        return StreamHandler.token

    def host(self) -> str:
        return "0.0.0.0" if self.setting()["enable_lan_access"] else "127.0.0.1"

    def port(self) -> int:
        return int(self.setting()["stream_overlay_port"])

    def base_urls(self) -> list[str]:
        """Server addresses: this computer, then local network addresses if LAN access is enabled"""
        from .web_dashboard import local_addresses

        hosts = ["127.0.0.1"]
        if self.setting()["enable_lan_access"]:
            hosts.extend(local_addresses())
        return [f"http://{host}:{self.port()}" for host in hosts]

    def url(self, path: str, query: str = "", host: str = "") -> str:
        """Address of a source with access token"""
        base = host or self.base_urls()[0]
        extra = f"&{query}" if query else ""
        return f"{base}{path}?token={quote(self.access_token())}{extra}"

    def enable(self):
        """Start server & capture if enabled in setting (server kept if address unchanged)"""
        setting = self.setting()
        if not setting["enable_stream_overlay"]:
            self.disable()
            return
        address = (self.host(), self.port())
        if self._server is not None and self._address != address:
            self.disable()
        StreamHandler.token = self.access_token()
        StreamHandler.store = self.store
        StreamHandler.results = self.results
        if self._server is None:
            try:
                self._server = StreamServer(address, StreamHandler)
            except OSError as error:
                logger.error("STREAM OVERLAY: unable to listen on %s:%s (%s)", *address, error)
                app_signal.error.emit(f"Stream overlay: port {address[1]} unavailable ({error.strerror}).")
                return
            self._address = address
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="Stream overlay")
            self._thread.start()
            logger.info("ENABLED: stream overlay on http://%s:%s", *address)
        if self._capture is None:
            self._capture = OverlayCapture(self.store)
        self._capture.start(int(setting["frame_rate"]))

    def disable(self):
        """Stop server & capture"""
        if self._capture is not None:
            self._capture.stop()
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        self._address = None
        self.store.clear()
        logger.info("DISABLED: stream overlay")

    def watched(self) -> set[str]:
        """Overlays (and "layout") shown by a source now"""
        return self.store.watched_overlays() if self.running else set()


streamoverlay = StreamOverlay()


# Pages
def overlay_label(name: str) -> str:
    from .i18n.options import module_label

    return module_label(name)


def page_language() -> str:
    return current_language().replace("_", "-")


def forbidden_html() -> str:
    text = escape(tr("Invalid address: copy it again from the Stream Overlays page of Modern Tiny Pedals."))
    return (f'<!doctype html><html lang="{escape(page_language())}"><head><meta charset="utf-8"><title>403</title>'
            f'</head><body style="font-family:sans-serif;color:#ddd;background:#111">{text}</body></html>')


def index_html(token: str) -> str:
    """Sources page: links to layout, results & overlays shown on stream"""
    from .template.setting_widget import WIDGET_FILENAME

    link_token = quote(token)
    links = [(tr("Layout"), f"/layout?token={link_token}"), (tr("Race Results"), f"/results?token={link_token}")]
    setting = cfg.user.setting
    for name in WIDGET_FILENAME:
        wcfg = setting.get(name)
        if isinstance(wcfg, dict) and wcfg.get("enable") and shown_on_stream(wcfg):
            links.append((overlay_label(name), f"/overlay/{name}?token={link_token}"))
    items = "".join(f'<li><a href="{escape(href)}">{escape(label)}</a></li>' for label, href in links)
    title = escape(tr("Stream Overlays"))
    return (f'<!doctype html><html lang="{escape(page_language())}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>'
            'body{background:#0e1116;color:#e9ecf1;font-family:system-ui,sans-serif;margin:24px}'
            'a{color:#7cc4ff}li{margin:6px 0}</style></head>'
            f'<body><h1>{title}</h1><ul>{items}</ul></body></html>')


def source_html(view: str, title: str) -> str:
    return (SOURCE_HTML
            .replace("@@lang@@", escape(page_language()))
            .replace("@@title@@", escape(title))
            .replace("@@view@@", json.dumps(view)))


def results_html() -> str:
    return (RESULTS_HTML
            .replace("@@lang@@", escape(page_language()))
            .replace("@@title@@", escape(tr("Race Results"))))


# One overlay or whole layout: images of frames bundle drawn on a canvas (transparent page).
# Query: fit=1 scales canvas to page (default for layout), scale=<factor> (overlay).
SOURCE_HTML = """<!doctype html><html lang="@@lang@@"><head><meta charset="utf-8"><title>@@title@@</title>
<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden}
canvas{display:block}.fit{width:100vw;height:100vh;object-fit:contain;object-position:left top}</style></head>
<body><canvas id="c" width="0" height="0"></canvas><script>
"use strict";
const VIEW=@@view@@;
const query=new URLSearchParams(location.search);
const token=query.get("token")||"";
const scale=Math.max(parseFloat(query.get("scale")||"1")||1,0.1);
const fit=(query.get("fit")||(VIEW==="layout"?"1":"0"))==="1";
const codec=("DecompressionStream" in window)?"zraw":"png";
const canvas=document.getElementById("c");
const ctx=canvas.getContext("2d");
if(fit)canvas.className="fit";
const images=new Map();
let seq=0,shown=[],size=[0,0];
const sleep=ms=>new Promise(done=>setTimeout(done,ms));
async function inflate(bytes){
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Uint8ClampedArray(await new Response(stream).arrayBuffer());
}
async function decode(entry,bytes){
  if(codec==="png")return createImageBitmap(new Blob([bytes],{type:"image/png"}));
  return createImageBitmap(new ImageData(await inflate(bytes),entry.w,entry.h));
}
function draw(){
  const layout=VIEW==="layout";
  const first=shown[0];
  const width=Math.round((layout?size[0]:(first?first.w:0))*(layout?1:scale));
  const height=Math.round((layout?size[1]:(first?first.h:0))*(layout?1:scale));
  if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height}
  ctx.clearRect(0,0,canvas.width,canvas.height);
  for(const entry of shown){
    const image=images.get(entry.name);
    if(!image)continue;
    ctx.globalAlpha=entry.opacity;
    if(layout)ctx.drawImage(image,entry.x,entry.y);
    else ctx.drawImage(image,0,0,entry.w*scale,entry.h*scale);
  }
  ctx.globalAlpha=1;
}
async function run(){
  for(;;){
    try{
      const response=await fetch("/api/frames?view="+encodeURIComponent(VIEW)+"&seq="+seq+"&codec="+codec+
        "&token="+encodeURIComponent(token),{cache:"no-store"});
      if(!response.ok){await sleep(response.status===403?5000:1000);continue}
      const data=new Uint8Array(await response.arrayBuffer());
      const length=new DataView(data.buffer).getUint32(0);
      const head=JSON.parse(new TextDecoder().decode(data.subarray(4,4+length)));
      let offset=4+length;
      const jobs=[];
      for(const entry of head.overlays){
        if(entry.size>0){
          const bytes=data.subarray(offset,offset+entry.size);
          offset+=entry.size;
          jobs.push(decode(entry,bytes).then(image=>{
            const old=images.get(entry.name);images.set(entry.name,image);if(old)old.close()}));
        }
      }
      await Promise.all(jobs);
      const names=new Set(head.overlays.map(entry=>entry.name));
      for(const [name,image] of images){if(!names.has(name)){image.close();images.delete(name)}}
      shown=head.overlays;size=head.canvas;
      seq=head.overlays.some(entry=>!images.has(entry.name))?0:head.seq;
      draw();
    }catch(error){seq=0;await sleep(1000)}
  }
}
run();
</script></body></html>"""

# Results of last race: header (session, track), classification pages (rows per page), classes one after another
# (class=cycle), or one class (class=<name>), or every car (class=all, default). Query: rows=<per page>,
# cycle=<seconds per page>, session=race|qualifying|any, animate=0 (no animation). Data asked again every few
# seconds.
RESULTS_HTML = """<!doctype html><html lang="@@lang@@"><head><meta charset="utf-8"><title>@@title@@</title>
<style>
@font-face{font-family:"Barlow Semi Condensed";font-weight:500;src:url(/fonts/BarlowSemiCondensed-Medium.ttf)}
@font-face{font-family:"Barlow Semi Condensed";font-weight:600;src:url(/fonts/BarlowSemiCondensed-SemiBold.ttf)}
@font-face{font-family:"Barlow Semi Condensed";font-weight:700;src:url(/fonts/BarlowSemiCondensed-Bold.ttf)}
:root{--panel:rgba(12,14,20,.9);--line:rgba(255,255,255,.07);--text:#f4f6fa;--dim:rgba(232,236,244,.62);
--accent:#e5383b;--purple:#c084fc;--gain:#4ade80;--loss:#f87171;--row:3.9vh}
*{box-sizing:border-box}
html,body{margin:0;background:transparent;overflow:hidden;height:100%}
body{font-family:"Barlow Semi Condensed","Segoe UI",sans-serif;color:var(--text);font-weight:500;
font-variant-numeric:tabular-nums;font-size:calc(var(--row)*.56)}
#panel{position:absolute;left:5vw;right:5vw;top:6vh;background:var(--panel);border-radius:1.2vh;overflow:hidden;
box-shadow:0 1.2vh 4vh rgba(0,0,0,.45);opacity:0;transform:translateY(1.5vh);transition:opacity .5s,transform .5s}
#panel.on{opacity:1;transform:none}
header{display:flex;align-items:center;gap:1.6vh;padding:1.6vh 2.4vh;
background:linear-gradient(90deg,rgba(229,56,59,.95),rgba(229,56,59,.55) 40%,rgba(229,56,59,0) 85%)}
#kind{font-size:calc(var(--row)*.42);font-weight:700;letter-spacing:.18em;text-transform:uppercase;opacity:.92}
#title{font-size:calc(var(--row)*.95);font-weight:700;line-height:1.05}
#sub{font-size:calc(var(--row)*.5);color:var(--dim)}
#cls{margin-left:auto;display:flex;align-items:center;gap:1vh;font-weight:700;font-size:calc(var(--row)*.6)}
#cls i{display:inline-block;width:1.4vh;height:1.4vh;border-radius:50%}
#flag{padding:.3vh 1vh;border-radius:.6vh;background:rgba(251,146,60,.2);color:#fb923c;font-weight:700;
font-size:calc(var(--row)*.4);display:none}
.grid{display:grid;grid-template-columns:5.2vh .6vh 6vh minmax(0,1.5fr) minmax(0,1fr) 6vh 14vh 13vh 10vh;
align-items:center;column-gap:1.4vh;padding:0 2.4vh}
.head{height:3.6vh;color:var(--dim);font-size:calc(var(--row)*.4);letter-spacing:.12em;text-transform:uppercase;
border-bottom:1px solid var(--line)}
.head div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row{height:var(--row);border-bottom:1px solid var(--line);opacity:0;transform:translateX(-1.4vh);
transition:opacity .35s ease,transform .35s ease}
.row.on{opacity:1;transform:none}
.row.me{background:linear-gradient(90deg,rgba(229,56,59,.32),rgba(229,56,59,.08))}
.pos{font-weight:700;font-size:calc(var(--row)*.62);text-align:right}
.bar{height:62%;border-radius:.3vh}
.num{color:var(--dim)}
.name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:700}
.team{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--dim)}
.r{text-align:right}.dim{color:var(--dim)}.loss{color:var(--loss)}
.best.fast{color:var(--purple);font-weight:700}
footer{display:flex;align-items:center;justify-content:space-between;padding:1vh 2.4vh;color:var(--dim);
font-size:calc(var(--row)*.4);letter-spacing:.1em;text-transform:uppercase}
#progress{height:.35vh;background:var(--accent);width:0}
#wait{position:absolute;left:5vw;top:6vh;color:var(--dim);font-size:3vh;display:none}
.still #panel,.still .row,.still #progress{transition:none!important}
</style></head><body>
<div id="panel"><header><div><div id="kind"></div><div id="title"></div><div id="sub"></div></div>
<div id="flag"></div><div id="cls"></div></header>
<div class="grid head"><div class="r" id="lpos"></div><div></div><div>#</div><div id="ldriver"></div>
<div id="lcar"></div><div class="r" id="llaps"></div><div class="r" id="lgap"></div><div class="r" id="lbest"></div>
<div class="r" id="lpits"></div></div>
<div id="rows"></div><div id="progress"></div><footer><span id="page"></span><span id="count"></span></footer></div>
<div id="wait"></div>
<script>
"use strict";
const query=new URLSearchParams(location.search);
const token=query.get("token")||"";
const perPage=Math.max(parseInt(query.get("rows")||"15",10)||15,3);
const cycle=Math.max(parseFloat(query.get("cycle")||"10")||10,3)*1000;
const classMode=query.get("class")||"all";
const session=query.get("session")||"race";
const animate=query.get("animate")!=="0";
if(!animate)document.documentElement.classList.add("still");
const $=id=>document.getElementById(id);
document.documentElement.style.setProperty("--row",Math.min(78/(perPage+3.2),6)+"vh");
let data=null,views=[],viewIndex=0,timer=0;
const text=value=>String(value==null?"":value);
function cell(className,value){const div=document.createElement("div");div.className=className;div.textContent=text(value);return div}
function buildViews(){
  views=[];
  if(!data||!data.available)return;
  const classes=data.classes.map(item=>item.name);
  const groups=classMode==="cycle"&&classes.length>1?classes:
    (classMode!=="all"&&classes.includes(classMode)?[classMode]:[""]);
  for(const name of groups){
    const rows=data.rows.filter(row=>!name||row.cls===name);
    for(let start=0;start<rows.length;start+=perPage)views.push({cls:name,rows:rows.slice(start,start+perPage),
      page:Math.floor(start/perPage)+1,pages:Math.ceil(rows.length/perPage),total:rows.length});
  }
}
function show(){
  clearTimeout(timer);
  if(!views.length){$("panel").classList.remove("on");$("wait").style.display="block";return}
  $("wait").style.display="none";
  const view=views[viewIndex%views.length];
  const byClass=view.cls!=="";
  const info=data.classes.find(item=>item.name===view.cls);
  $("cls").innerHTML="";
  if(info){const dot=document.createElement("i");dot.style.background=info.color;$("cls").append(dot,info.name)}
  const rows=$("rows");rows.innerHTML="";
  view.rows.forEach((row,index)=>{
    const line=document.createElement("div");
    line.className="grid row"+(row.player?" me":"");
    const bar=cell("bar","");bar.style.background=row.color;
    const driver=document.createElement("div");driver.style.minWidth="0";
    driver.append(cell("name",row.driver));
    line.append(cell("pos",byClass?row.classPos:row.pos),bar,cell("num",row.number?"#"+row.number:""),driver,
      cell("team",row.team||row.car),cell("r",row.laps),
      cell("r "+(byClass?row.classGapTone:row.gapTone),byClass?row.classGap:row.gap),
      cell("r best"+((byClass?row.classFastest:row.fastest)?" fast":""),row.best),cell("r dim",data.race?row.pits:""));
    rows.append(line);
    if(animate)setTimeout(()=>line.classList.add("on"),60+index*40);else line.classList.add("on");
  });
  $("page").textContent=views.length>1?(viewIndex%views.length+1)+" / "+views.length:"";
  $("count").textContent=view.total+" "+(info?info.name:(data.labels.cars||""));
  $("panel").classList.add("on");
  const progress=$("progress");
  progress.style.transition="none";progress.style.width="0";
  if(views.length>1){
    if(animate)requestAnimationFrame(()=>requestAnimationFrame(()=>{progress.style.transition="width "+cycle+"ms linear";progress.style.width="100%"}));
    timer=setTimeout(()=>{viewIndex++;show()},cycle);
  }
}
async function load(){
  try{
    const response=await fetch("/api/results?session="+encodeURIComponent(session)+"&token="+encodeURIComponent(token),{cache:"no-store"});
    if(response.ok){
      const next=await response.json();
      const labels=next.labels||{};
      $("lpos").textContent=labels.pos||"";$("ldriver").textContent=labels.driver||"";$("lcar").textContent=labels.car||"";
      $("llaps").textContent=labels.laps||"";$("lgap").textContent=labels.gap||"";$("lbest").textContent=labels.best||"";
      $("lpits").textContent=next.race?(labels.pits||""):"";$("wait").textContent=labels.waiting||"";
      if(!data||next.id!==data.id||next.available!==data.available){
        data=next;
        if(data.available){
          $("kind").textContent=data.kind;$("title").textContent=data.title;$("sub").textContent=data.subtitle;
          $("flag").textContent=labels.unfinished||"";$("flag").style.display=data.partial?"block":"none";
        }
        buildViews();viewIndex=0;show();
      }
    }
  }catch(error){}
  setTimeout(load,5000);
}
load();
</script></body></html>"""
