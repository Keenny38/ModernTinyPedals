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
Custom image file function
"""

import atexit
import contextlib
import hashlib
import itertools
import logging
import os
import queue
import re
import threading
import weakref
from array import array
from collections import OrderedDict
from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap

from ..const_file import FileExt
from ..validator import image_exists

TINTED_FOLDER = "tinted"  # readable copies of logos (game image folder): on_dark_*.png, on_light_*.png
TINT_HEIGHT = 120  # pixels of readable copies (at most, 4 times as wide)
TINT_VERSION = 2  # copies made again once changed (2: margins trimmed)
TRIM_SHARE = 0.75  # logo drawn on less of picture width or height than this: copy without margins
DRAWN_ALPHA = 8  # pixels more opaque than this are part of logo (margins: less)
ON_LIGHT = QColor(28, 32, 39)  # light gray parts of logo on light background
ON_DARK_VALUE = 236  # dark parts of logo on dark background: same hue, this bright
MAIN_SHARE = 0.5  # logo too close to background: more than this share of its pixels...
OTHER_SHARE = 0.1  # ...less than this share contrasting (white lion of a black shield: kept)...
COLORED_SHARE = 0.35  # ...and less than this share in color (gold bull of a black shield: kept)
_tinted: dict[tuple[str, bool, float], str] = {}  # logo file, light background, file time -> logo shown
_tinted_lock = threading.Lock()  # guards _making (logo_for_background runs on GUI, loader, fetch & stream threads)
_making: dict[tuple[str, bool, float], threading.Lock] = {}  # logo being made -> lock its askers wait on
_deferred = threading.local()  # deferred_logos() state of thread
_pregenerated: set[str] = set()  # game image folders whose logos were given readable copies in background
_own_logos: dict[str, tuple[float, dict[str, str]]] = {}  # folder -> folder time, normalized name -> file
_NOT_WORD = re.compile(r"[^a-z0-9]+")
_DRAWN = bytes(value > DRAWN_ALPHA for value in range(256))  # alpha -> 1 if drawn
_watched_caches: weakref.WeakSet = weakref.WeakSet()  # game picture caches making readable copies on arrival
_watch_lock = threading.Lock()

logger = logging.getLogger(__name__)


def split_pixmap_image(
    image: QPixmap, size: int, h_offset: int = 0, v_offset: int = 0
) -> QPixmap:
    """Split pixmap icon set"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.drawPixmap(0, 0, image, size * h_offset, size * v_offset, 0, 0)
    return pixmap


def exceeded_max_logo_width(
    org_width: int, org_height: int, max_width: int, max_height: int
) -> bool:
    """Whether exceeded max logo width"""
    return org_width * max_height / max(org_height, 1) > max_width


def read_picture(path: str, max_width: float, max_height: float, ratio: float = 1.0) -> QImage:
    """Picture file (png, svg, webp...) fitted in max size (aspect kept), pixels for device pixel ratio:
    vector pictures drawn at that size (sharp), null image if not readable"""
    if not path or max_width <= 0 or max_height <= 0:
        return QImage()
    reader = QImageReader(path)
    size = reader.size()
    if size.isValid() and not size.isEmpty():
        scale = min(max_width / size.width(), max_height / size.height()) * ratio
        reader.setScaledSize(QSize(max(round(size.width() * scale), 1), max(round(size.height() * scale), 1)))
        image = reader.read()
    else:
        image = reader.read()
        if not image.isNull():
            image = image.scaled(max(round(max_width * ratio), 1), max(round(max_height * ratio), 1),
                                 Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not image.isNull():
        image.setDevicePixelRatio(ratio)
    return image


def load_picture(path: str, max_width: float, max_height: float, ratio: float = 1.0) -> QPixmap:
    """Picture file fitted in max size, see read_picture (UI thread)"""
    image = read_picture(path, max_width, max_height, ratio)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def is_dark_part(color: QColor) -> bool:
    """Part of logo unreadable on dark background (black, dark gray, navy...)"""
    return color.value() < 90


def is_light_part(color: QColor) -> bool:
    """Part of logo unreadable on light background (white, light gray)"""
    return color.value() > 200 and color.hsvSaturation() < 60


def logo_shares(image: QImage) -> tuple[float, float]:
    """Shares of dark & light parts in opaque pixels of logo (sampled), the rest is in color"""
    step = max(min(image.width(), image.height()) // 32, 1)
    dark = light = count = 0
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            if color.alpha() > 96:
                count += 1
                dark += is_dark_part(color)
                light += is_light_part(color)
    if not count:
        return 0.0, 0.0
    return dark / count, light / count


def is_light_logo(image: QImage) -> bool:
    """Whether logo is drawn in light gray or white (unreadable on light background)"""
    if image.isNull():
        return False
    dark, light = logo_shares(image)
    return light > MAIN_SHARE and dark < OTHER_SHARE and 1 - dark - light < COLORED_SHARE


def is_dark_logo(image: QImage) -> bool:
    """Whether logo is drawn in black or dark colors (unreadable on dark background)"""
    if image.isNull():
        return False
    dark, light = logo_shares(image)
    return dark > MAIN_SHARE and light < OTHER_SHARE and 1 - dark - light < COLORED_SHARE


def readable_copy(image: QImage, light_background: bool) -> QImage:
    """Copy of logo, parts too close to background recolored (colored parts of a black logo kept)

    Pixels read & written as a whole (ARGB32 words), each distinct color recolored once: no per-pixel
    Qt calls (logos have few distinct colors, a per-pixel loop froze painting).
    """
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    if image.isNull():
        return image
    pixels = array("I", bytes(image.constBits()))  # ARGB32: native 0xAARRGGBB words, no line padding
    recolored = {}
    for rgba in set(pixels):
        recolored[rgba] = rgba
        color = QColor.fromRgba(rgba)
        alpha = color.alpha()
        if not alpha:
            continue
        if light_background and is_light_part(color):
            recolored[rgba] = QColor(ON_LIGHT.red(), ON_LIGHT.green(), ON_LIGHT.blue(), alpha).rgba()
        elif not light_background and is_dark_part(color):
            hue = color.hsvHue()
            recolored[rgba] = QColor.fromHsv(
                max(hue, 0), color.hsvSaturation() // 2, ON_DARK_VALUE, alpha).rgba()
    memoryview(image.bits())[:] = array("I", map(recolored.__getitem__, pixels)).tobytes()
    return image


def drawn_rect(image: QImage) -> QRect:
    """Part of picture drawn (transparent margins left out), null rect if nothing drawn"""
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    width, line = alpha.width(), alpha.bytesPerLine()
    data = bytes(alpha.constBits())
    left, right, top, bottom = width, -1, -1, -1
    for y in range(alpha.height()):
        row = data[y * line:y * line + width].translate(_DRAWN)
        first = row.find(1)
        if first < 0:
            continue
        if top < 0:
            top = y
        bottom = y
        left = min(left, first)
        right = max(right, row.rfind(1))
    if top < 0:
        return QRect()
    return QRect(left, top, right - left + 1, bottom - top + 1)


def read_logo(path: str) -> QImage:
    """Logo picture without transparent margins (wordmarks drawn on square pictures), at most
    TINT_HEIGHT high: raster pictures read at their size (never enlarged), vector ones drawn big"""
    box = TINT_HEIGHT * 4
    reader = QImageReader(path)
    size = reader.size()
    if (size.isValid() and size.width() <= box and size.height() <= box
            and bytes(reader.format().data()).lower() not in (b"svg", b"svgz")):
        image = reader.read()
    else:
        image = read_picture(path, box, box)
    if image.isNull():
        return image
    image.setDevicePixelRatio(1.0)
    drawn = drawn_rect(image)
    if has_margins(image, drawn):
        image = image.copy(drawn)
    if image.height() > TINT_HEIGHT or image.width() > box:
        image = image.scaled(box, TINT_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image


def has_margins(image: QImage, drawn: QRect | None = None) -> bool:
    """Whether logo is drawn on a small part of picture (drawn part given if known)"""
    if drawn is None:
        drawn = drawn_rect(image)
    return not drawn.isNull() and (drawn.width() < image.width() * TRIM_SHARE
                                   or drawn.height() < image.height() * TRIM_SHARE)


class Deferral:
    """State of deferred_logos(): whether a readable copy not decided yet was asked for"""

    missed = False


@contextlib.contextmanager
def deferred_logos():
    """Within: logo_for_background (this thread) answers "" for a logo whose readable copy is not decided yet
    instead of making it (UI thread never waits for one); `missed` tells caller to look for it in background"""
    state = Deferral()
    previous = getattr(_deferred, "state", None)
    _deferred.state = state
    try:
        yield state
    finally:
        _deferred.state = previous


def logo_for_background(path: str, light_background: bool) -> str:
    """Logo file readable on background: copy without transparent margins, parts too close to background
    recolored (white logo on light background, black logo on dark one), made once in game image folder;
    else logo file itself (no margins, readable). Decision kept on disk (copy, or marker if none needed): later
    runs only check files."""
    if not path:
        return ""
    watch_game_logos()
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return path
    key = (path, light_background, stamp)
    found = _known_logo(key)
    if found is not None:
        return found
    state = getattr(_deferred, "state", None)
    if state is not None:
        state.missed = True
        return ""
    with _tinted_lock:
        lock = _making.setdefault(key, threading.Lock())
    with lock:  # one thread makes a copy, others asking for same logo wait & reuse it (other logos: no wait)
        found = _known_logo(key)
        if found is None:
            found = _tinted[key] = _make_logo_for_background(path, light_background, stamp)
    with _tinted_lock:
        if _making.get(key) is lock:
            del _making[key]
    return found


def _tinted_files(path: str, light_background: bool, stamp: float) -> tuple[str, str]:
    """Readable copy & "no copy needed" marker of logo in game image folder (either exists once decided)"""
    from .game_images import images

    digest = hashlib.sha1(f"{os.path.abspath(path)}|{stamp}|{TINT_VERSION}".encode()).hexdigest()[:16]
    stem = os.path.join(images.folder, TINTED_FOLDER, f"{'on_light' if light_background else 'on_dark'}_{digest}")
    return f"{stem}.png", f"{stem}.keep"


def _known_logo(key: tuple[str, bool, float]) -> str | None:
    """Logo shown for (logo file, light background, file time) if decided (this run or an earlier one: file
    checks only), else None"""
    path = key[0]
    found = _tinted.get(key)
    if found is not None and (found == path or os.path.isfile(found)):
        return found
    target, marker = _tinted_files(*key)
    if os.path.isfile(target):
        found = target
    elif os.path.isfile(marker):
        found = path
    else:
        return None
    _tinted[key] = found
    return found


def _make_logo_for_background(path: str, light_background: bool, stamp: float) -> str:
    """Readable copy of logo made in game image folder if needed (see logo_for_background), under its lock"""
    target, marker = _tinted_files(path, light_background, stamp)
    whole = read_picture(path, TINT_HEIGHT * 4, TINT_HEIGHT)
    if whole.isNull():  # unreadable (decided again next time)
        return path
    recolor = is_light_logo(whole) if light_background else is_dark_logo(whole)
    if not recolor and not has_margins(whole):  # readable as it is: remembered for next runs
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "wb"):
                pass
        return path
    image = read_logo(path)
    if recolor:
        image = readable_copy(image, light_background)
    if image.isNull():
        return path
    # Written under a temporary name then renamed: a copy cut half-way (crash, full disk) is never
    # taken for a finished one (reused as long as it exists)
    temp = f"{target}.{os.getpid()}-{threading.get_ident()}.tmp.png"  # format from extension
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if image.save(temp):
            os.replace(temp, target)
            return target
    except OSError:
        pass
    with contextlib.suppress(OSError):
        os.remove(temp)
    return path


def watch_game_logos():
    """Readable copies of game logos made as soon as the game image cache saves them (fetch thread), for
    light & dark backgrounds, so showing a logo never waits for one (once per cache); logos saved by earlier
    runs given theirs in background (once per game image folder, after any other logo job)"""
    from .game_images import images

    folder = images.folder
    if images in _watched_caches and folder in _pregenerated:
        return
    with _watch_lock:  # lookups run on several threads
        if folder not in _pregenerated:
            _pregenerated.add(folder)
            LOGO_LOADER.run(("pregenerate", folder), lambda: _pregenerate_folder(folder), background=True)
        if images in _watched_caches:
            return
        _watched_caches.add(images)
    images.add_file_listener(_picture_saved)


def _picture_saved(kind: str, path: str):
    """Game image cache saved a picture (fetch thread): readable copies of a logo made at once"""
    from .game_images import LOGO_KINDS

    if path and kind in LOGO_KINDS:
        pregenerate_logo(path)


def logo_files(folder: str) -> list[str]:
    """Logo files of game image folder"""
    from .game_images import LOGO_KINDS

    files = []
    for kind in LOGO_KINDS:
        try:
            entries = list(os.scandir(os.path.join(folder, kind)))
        except OSError:
            continue
        for entry in entries:
            with contextlib.suppress(OSError):  # removed meanwhile
                if entry.is_file() and not entry.name.endswith(".tmp"):
                    files.append(entry.path)
    return files


def pregenerate_logo(path: str) -> bool:
    """Readable copies (see logo_for_background) of logo for both backgrounds, True if any was not decided yet"""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return False
    made = False
    for light_background in (False, True):
        if _known_logo((path, light_background, stamp)) is None:
            logo_for_background(path, light_background)
            made = True
    return made


def pregenerate_logos(cache) -> int:
    """Readable copies of logos of game image cache not decided yet, for both backgrounds; number of logos
    concerned"""
    if cache is None:
        return 0
    return sum(pregenerate_logo(path) for path in logo_files(cache.folder))


def _pregenerate_folder(folder: str):
    """Logos of game image folder given readable copies one by one in background (logo jobs of overlays &
    pages run first)"""
    for path in logo_files(folder):
        LOGO_LOADER.run(("pregenerate", path), partial(pregenerate_logo, path), background=True)


class LogoLoader:
    """Logo lookups & decoding on a worker thread: painting never waits for files

    Jobs (file lookups, picture reading & SVG drawing, readable copies) run one after the other and return
    QImage based values (QPixmap only made on GUI thread). A key is asked for with its job: result once done
    (taken), None while running. `finished` grows with each result ready: asker knows when to ask again. Jobs
    whose result nobody takes (run) may wait for every other job (background). Worker ends after a while
    without job, started again by next one.
    """

    IDLE_SECONDS = 10.0
    MAX_RESULTS = 256  # results nobody took any more (widget closed) dropped, oldest first

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: queue.PriorityQueue = queue.PriorityQueue()
        self._order = itertools.count()  # same priority: first queued first
        self._running: set = set()
        self._results: OrderedDict = OrderedDict()
        self._thread: threading.Thread | None = None
        self._idle = threading.Condition(self._lock)
        self.finished = 0

    def result(self, key, job: Callable[[], Any]) -> tuple[bool, Any]:
        """(True, job result) once done, (False, None) while running (job queued if not yet)"""
        with self._lock:
            if key in self._results:
                return True, self._results.pop(key)
            if key in self._running:
                return False, None
            self._queue(key, job, 0, True)
        return False, None

    def run(self, key, job: Callable[[], Any], background: bool = False) -> bool:
        """Job queued unless key is queued already (result dropped), after every other job if background;
        True if queued"""
        with self._lock:
            if key in self._running:
                return False
            self._queue(key, job, 1 if background else 0, False)
        return True

    def _queue(self, key, job: Callable[[], Any], priority: int, keep: bool):
        """Job queued, worker started if none (under lock)"""
        self._running.add(key)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="Logo loader")
            self._thread.start()
        self._jobs.put((priority, next(self._order), key, job, keep))

    def wait(self, timeout: float = 5.0) -> bool:
        """Wait until every queued job is done (tests, app exit), True if done in time"""
        with self._idle:
            return self._idle.wait_for(lambda: not self._running, timeout)

    def _run(self):
        while True:
            try:
                _, _, key, job, keep = self._jobs.get(timeout=self.IDLE_SECONDS)
            except queue.Empty:
                with self._lock:
                    if self._jobs.empty():  # no job queued meanwhile: next one starts a new worker
                        self._thread = None
                        return
                continue
            try:
                value = job()
            except Exception:  # a failing job never stops the worker
                logger.exception("LOGO LOADER: job failed")
                value = None
            job = None  # objects held by job freed here, not with next job
            with self._lock:
                self._running.discard(key)
                if keep:
                    self._results[key] = value
                    while len(self._results) > self.MAX_RESULTS:
                        self._results.popitem(last=False)
                    self.finished += 1
                self._idle.notify_all()


LOGO_LOADER = LogoLoader()
atexit.register(LOGO_LOADER.wait, 1.0)  # job running at exit (picture read) ends first


def brand_logo_image(logo_folder: str, brand: str, light_background: bool, vehicle_name: str,
                     max_width: float, max_height: float, ratio: float) -> tuple[str, QImage]:
    """Logo file of car brand (see brand_logo_file) & its picture fitted in max size (any thread)"""
    path = brand_logo_file(logo_folder, brand, light_background, vehicle_name)
    return path, read_picture(path, max_width, max_height, ratio) if path else QImage()


def own_logo_file(logo_folder: str, *brands: str) -> str:
    """Own logo of brand logo folder for brand names given (most specific first): <brand>.png, else a logo
    whose name is a word of brand ("Chevrolet Corvette": Corvette.png before Chevrolet.png, last word
    first), then same for next brand name"""
    try:
        stamp = os.path.getmtime(logo_folder)
    except OSError:
        return ""
    cached = _own_logos.get(logo_folder)
    if cached is None or cached[0] != stamp:
        files = {}
        try:
            for name in os.listdir(logo_folder):
                stem, ext = os.path.splitext(name)
                if ext.lower() == FileExt.PNG:
                    files[_NOT_WORD.sub("", stem.lower())] = os.path.join(logo_folder, name)
        except OSError:
            pass
        cached = _own_logos[logo_folder] = (stamp, files)
    files = cached[1]
    for brand in brands:
        text = _NOT_WORD.sub("", brand.lower()) if brand else ""
        if not text:
            continue
        found = files.get(text)
        if found is None:
            matches = [(text.rfind(name), len(name), path) for name, path in files.items() if name and name in text]
            found = max(matches)[2] if matches else None
        if found and image_exists(found, FileExt.PNG, 5_120_000):
            return found
    return ""


def brand_logo_file(logo_folder: str, brand: str, light_background: bool = False, vehicle_name: str = "") -> str:
    """Logo file of car brand readable on background: own logo of brand logo folder first, else game
    logo (cached from game, fetched in background if not yet: "" until then)"""
    if not brand and not vehicle_name:
        return ""
    from .game_images import images

    watch_game_logos()  # before first lookup starts fetching
    canonical = images.brand(vehicle_name, brand)
    path = own_logo_file(logo_folder, brand, canonical) or images.brand_logo(canonical, dark=light_background)
    return logo_for_background(path, light_background) if path else ""


def load_brand_logo_image(
    filepath:str, filename: str, max_width: int, max_height: int, extension: str = FileExt.PNG
) -> QPixmap:
    """Load brand logo image (own *.png of brand logo folder, else logo cached from game), readable on
    dark cell background"""
    filename_full = brand_logo_file(filepath, filename)
    if not filename_full.lower().endswith(FileExt.PNG):
        return load_picture(filename_full, max_width, max_height)
    # Load and scale logo
    image = QPixmap(filename_full)
    if exceeded_max_logo_width(image.width(), image.height(), max_width, max_height):
        logo_scaled = image.scaledToWidth(max_width, mode=Qt.TransformationMode.SmoothTransformation)
    else:
        logo_scaled = image.scaledToHeight(max_height, mode=Qt.TransformationMode.SmoothTransformation)
    return logo_scaled


def cached_brand_logo(
    cache: dict, filepath: str, filename: str, max_width: int, max_height: int
) -> QPixmap:
    """Brand logo from widget cache {brand: (pixmap, game pictures version)}

    A missing logo is looked for again only once game pictures change (game logo may come),
    not on every row update: file checks & image reading run on GUI thread.
    """
    from .game_images import images

    cached = cache.get(filename)
    if cached is None or (cached[0].isNull() and cached[1] != images.version):
        cached = cache[filename] = (
            load_brand_logo_image(filepath, filename, max_width, max_height), images.version)
    return cached[0]


def brand_logo_picture(filepath: str, filename: str, max_width: int, max_height: int) -> tuple[str, QImage]:
    """Logo file of brand & its picture as load_brand_logo_image reads it (any thread), see brand_logo_pixmap"""
    path = brand_logo_file(filepath, filename)
    if not path.lower().endswith(FileExt.PNG):
        return path, read_picture(path, max_width, max_height)
    return path, QImage(path)


def brand_logo_pixmap(path: str, image: QImage, max_width: int, max_height: int) -> QPixmap:
    """Pixmap of brand_logo_picture, same pixels as load_brand_logo_image (GUI thread)"""
    pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
    if not path.lower().endswith(FileExt.PNG):
        return pixmap
    if exceeded_max_logo_width(pixmap.width(), pixmap.height(), max_width, max_height):
        return pixmap.scaledToWidth(max_width, mode=Qt.TransformationMode.SmoothTransformation)
    return pixmap.scaledToHeight(max_height, mode=Qt.TransformationMode.SmoothTransformation)


class BrandLogos:
    """Brand logos of a classic overlay column {brand: pixmap}

    Each brand looked for once (again once game logos change, if none). On screen, file lookup & reading run on
    logo loader thread: null pixmap until ready (as without logo), then `arrived(brand, pixmap)` tells widget to
    draw it (cells only redraw when their row changes). Off screen (preview, test render), read at once.
    """

    CHECK_MS = 150  # waited logos checked for at this interval

    def __init__(self, widget: Any, filepath: str, max_width: int, max_height: int,
                 arrived: Callable[[str, QPixmap], Any]):
        self._widget = weakref.ref(widget)
        self._arrived = weakref.WeakMethod(arrived)  # no reference cycle with widget
        self.filepath = filepath
        self.max_width = max_width
        self.max_height = max_height
        self._pixmaps: dict[str, tuple[QPixmap, int]] = {}
        self._waited: set[str] = set()
        self._timer: QTimer | None = None

    def get(self, brand: str) -> QPixmap:
        from .game_images import images

        version = images.logos_version
        cached = self._pixmaps.get(brand)
        if cached is not None and (not cached[0].isNull() or cached[1] == version):
            return cached[0]
        widget = self._widget()
        if widget is None or not widget.isVisible():
            pixmap = load_brand_logo_image(self.filepath, brand, self.max_width, self.max_height)
        else:
            found = self._loaded(brand, version)
            if found is None:
                self._wait(brand)
                return QPixmap()
            pixmap = found
        self._pixmaps[brand] = (pixmap, version)
        return pixmap

    def _loaded(self, brand: str, version: int) -> QPixmap | None:
        """Logo read on loader thread, None while not ready"""
        args = (self.filepath, brand, self.max_width, self.max_height)
        done, value = LOGO_LOADER.result(("classic brand", *args, version), lambda: brand_logo_picture(*args))
        if not done:
            return None
        path, image = value if value is not None else ("", QImage())
        return brand_logo_pixmap(path, image, self.max_width, self.max_height)

    def _wait(self, brand: str):
        self._waited.add(brand)
        if self._timer is None:
            widget = self._widget()
            if widget is None:
                return
            self._timer = QTimer(widget)
            self._timer.setSingleShot(True)
            self._timer.setInterval(self.CHECK_MS)
            logos = weakref.ref(self)
            self._timer.timeout.connect(lambda: (cache := logos()) is not None and cache.check())
        if not self._timer.isActive():
            self._timer.start()

    def check(self):
        """Waited logos ready given to widget, others checked again later"""
        from .game_images import images

        version = images.logos_version
        for brand in tuple(self._waited):
            pixmap = self._loaded(brand, version)
            if pixmap is None:
                continue
            self._waited.discard(brand)
            self._pixmaps[brand] = (pixmap, version)
            arrived = self._arrived()
            if arrived is not None and not pixmap.isNull():
                arrived(brand, pixmap)
        if self._waited and self._timer is not None:
            self._timer.start()


def load_custom_image(
    user_file: str, default_file: str, width: int = 0, height: int = 0, extension: str = FileExt.PNG
) -> QPixmap:
    """Load custom image (*.png)

    Scale to width if only width set;
    Scale to height if only height set;
    Scale to both if both set;
    """
    filename = default_file
    if user_file and image_exists(user_file, extension):
        filename = user_file
    image = QPixmap(filename)
    if width > 0 and height <= 0:
        return image.scaledToWidth(width, mode=Qt.TransformationMode.SmoothTransformation)
    if height > 0 and width <= 0:
        return image.scaledToHeight(height, mode=Qt.TransformationMode.SmoothTransformation)
    return image.scaled(width, height, mode=Qt.TransformationMode.SmoothTransformation)
