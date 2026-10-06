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

import contextlib
import hashlib
import os
import re
import threading
from array import array

from PySide6.QtCore import QRect, QSize, Qt
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
_tinted_lock = threading.Lock()  # logo_for_background runs on GUI & stream server threads
_own_logos: dict[str, tuple[float, dict[str, str]]] = {}  # folder -> folder time, normalized name -> file
_NOT_WORD = re.compile(r"[^a-z0-9]+")
_DRAWN = bytes(value > DRAWN_ALPHA for value in range(256))  # alpha -> 1 if drawn


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


def logo_for_background(path: str, light_background: bool) -> str:
    """Logo file readable on background: copy without transparent margins, parts too close to background
    recolored (white logo on light background, black logo on dark one), made once in game image folder;
    else logo file itself (no margins, readable)"""
    if not path:
        return ""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return path
    key = (path, light_background, stamp)
    found = _tinted.get(key)
    if found is not None and (found == path or os.path.isfile(found)):
        return found
    with _tinted_lock:  # one thread makes a copy, others wait & reuse it
        found = _tinted.get(key)
        if found is not None and (found == path or os.path.isfile(found)):
            return found
        found = _tinted[key] = _make_logo_for_background(path, light_background, stamp)
    return found


def _make_logo_for_background(path: str, light_background: bool, stamp: float) -> str:
    """Readable copy of logo made in game image folder if needed (see logo_for_background), under lock"""
    from .game_images import images

    digest = hashlib.sha1(f"{os.path.abspath(path)}|{stamp}|{TINT_VERSION}".encode()).hexdigest()[:16]
    target = os.path.join(images.folder, TINTED_FOLDER, f"{'on_light' if light_background else 'on_dark'}_{digest}.png")
    if os.path.isfile(target):
        return target
    whole = read_picture(path, TINT_HEIGHT * 4, TINT_HEIGHT)
    recolor = is_light_logo(whole) if light_background else is_dark_logo(whole)
    if not recolor and not has_margins(whole):
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
