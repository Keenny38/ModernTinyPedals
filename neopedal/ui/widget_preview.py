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
Widget drawn with edited (unsaved) options on simulated race data, for pictures of Overlays,
Overlay Options & setup wizard pages (see demo_data: real game data never shown, nor changed)

Pictures are kept by inputs (render_image): a page drawing an overlay with the same options, style,
shared setting & scale as any page before gets the same picture, nothing drawn. Shared inputs (global
config, style files...) are read again only after a setting refresh, when a picture is next asked.
Once no page shows pictures for a while (window hidden while racing), kept pictures & the simulated
session are released.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import weakref
from collections import OrderedDict
from collections.abc import Mapping
from importlib import import_module
from typing import Any

from PySide6.QtCore import QObject, QRect, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication, QImage, QPixmap

from ..setting import Setting

logger = logging.getLogger(__name__)

CACHE_BUDGET = 64 << 20  # bytes of pictures kept for reuse while pages show pictures
IDLE_DELAY_MS = 3000  # no page showing pictures that long: kept pictures & simulated session released
DUMP_ATTEMPTS = 5
NOT_DRAWN = frozenset(("enable", "position_x", "position_y"))  # widget options never changing its picture


class _PreviewUser:
    """User presets, with edited (unsaved) widget setting and preview scale"""

    def __init__(self, user, widget_name: str, widget_setting: dict, scale: float = 1.0):
        self._user = user
        self.setting = {**user.setting, widget_name: widget_setting}
        if scale != 1:  # drawn bigger as global overlay scale does: sharp text & lines
            style = user.config["overlay_style"]
            scaled = {**style, "overlay_scale": style.get("overlay_scale", 1.0) * scale}
            self.config = {**user.config, "overlay_style": scaled}

    def __getattr__(self, name):
        return getattr(self._user, name)


class PreviewSetting:
    """Setting proxy for preview: reads edited values, never saves"""

    def __init__(self, config: Setting, widget_name: str, widget_setting: dict, scale: float = 1.0):
        self._cfg = config
        self.user = _PreviewUser(config.user, widget_name, widget_setting, scale)

    def __getattr__(self, name):
        return getattr(self._cfg, name)

    def save(self, *args, **kwargs):
        """Never save preview setting"""


def render_widget(config: Setting, widget_name: str, widget_setting: dict, scale: float = 1.0) -> QPixmap:
    """Render widget with edited setting to pixmap, on simulated race data

    Args:
        config: setting (preset of user, or style proxy).
        widget_name: widget name.
        widget_setting: widget options drawn.
        scale: size multiplier (zoom), applied as global overlay scale (limited to its range).
    """
    return _with_preview_widget(config, widget_name, widget_setting, scale, lambda widget: widget.grab())


def widget_part_rects(config: Setting, widget_name: str, widget_setting: dict,
                      scale: float = 1.0) -> tuple[QSize, dict[str, QRect]] | None:
    """Size & rects of the parts of widget as drawn in its picture (black box regions), None if it has none"""
    from ..widget._painter import OverlayStyle

    def part_rects(widget):
        rects = getattr(widget, "part_rects", None)
        return None if rects is None else (widget.size(), dict(rects()))

    shared = OverlayStyle.corner_scale, OverlayStyle.depth_effects  # set by widget: running overlays keep theirs
    try:
        return _with_preview_widget(config, widget_name, widget_setting, scale, part_rects)
    finally:
        OverlayStyle.corner_scale, OverlayStyle.depth_effects = shared


def _with_preview_widget(config: Setting, widget_name: str, widget_setting: dict, scale: float, use):
    """use(widget) with widget built on simulated race data, deleted after"""
    from ..demo_data import SAMPLE_WIDGETS, demo_globals, demo_session, update_widget
    from ..widget._modern import modern_module, uses_modern_design

    preview_config = PreviewSetting(config, widget_name, widget_setting, scale)
    if uses_modern_design(preview_config, widget_name):
        module = modern_module(widget_name)  # classic widget code not loaded
    else:
        module = import_module(f"neopedal.widget.{widget_name}")
    session = demo_session(config.user.setting["standings"])
    with demo_globals(session) as patch_loaded:
        widget = module.Realtime(preview_config, widget_name)
        try:
            patch_loaded()  # modules imported by widget
            show_sample = getattr(widget, "show_sample", None)
            if show_sample is not None:  # driver lists: sample race made with edited list options
                show_sample()
            elif widget_name not in SAMPLE_WIDGETS:
                update_widget(widget, widget_name, session)
            widget.adjustSize()
            return use(widget)
        finally:
            widget.deleteLater()


# Pictures kept by inputs
def dump(value: Any) -> str:
    """Stable text of setting value (sorted keys), read again if changed meanwhile by a module thread
    (brands, tracks...)"""
    for _ in range(DUMP_ATTEMPTS):
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)
        except (TypeError, ValueError, RecursionError):  # keys not sortable, cycles
            return _repr(value)
        except RuntimeError:  # dict changed size while read
            continue
    if isinstance(value, dict):
        from ..setting import snapshot_dict

        value = snapshot_dict(value)
    return _repr(value)


def _repr(value: Any) -> str:
    try:
        return repr(value)
    except RuntimeError:  # still changing: never equal, drawn again
        return f"<changing {id(value)} {os.urandom(4).hex()}>"


def digest(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=16).hexdigest()


def setting_text(widget_setting: Mapping) -> str:
    """Text of widget options drawn (state & position left out)"""
    return dump({key: value for key, value in tuple(widget_setting.items()) if key not in NOT_DRAWN})


def _folder_state(folder: str) -> list:
    """Files of folder with size & time (own brand logos)"""
    try:
        with os.scandir(folder) as entries:
            return sorted((entry.name, entry.stat().st_size, entry.stat().st_mtime_ns) for entry in entries)
    except OSError:
        return []


_shared: list[tuple[tuple, str]] = []  # (setting objects & folder, digest of shared inputs), empty until read again


def inputs_changed(*_):
    """Setting refreshed (preset, config, style files...): shared inputs read again when next needed"""
    _shared.clear()


def shared_inputs() -> str:
    """Digest of everything pictures read besides own options, overlay style & scale: global config (themes,
    design, compatibility...), settings other than overlays (units, modules; not game API: never drawn, spectate
    switched often), style files (classes, brands, heatmaps...), paths & own logos, preset. Read once per setting
    refresh (or setting objects replaced)."""
    from ..setting import cfg

    user = cfg.user
    objects = (id(user), id(user.setting), id(user.config), cfg.path.settings)
    if not _shared or _shared[0][0] != objects:
        _hook_refresh()
        _shared[:] = [(objects, _read_shared())]
    return _shared[0][1]


def _read_shared() -> str:
    from ..module_control import wctrl
    from ..setting import cfg
    from ..template.setting_api import API_DEFAULT

    overlays = set(wctrl.names)
    user = cfg.user
    settings: dict = {}
    for _ in range(DUMP_ATTEMPTS):
        try:
            settings = {key: value for key, value in user.setting.items() if key not in overlays and key not in API_DEFAULT}
            break
        except RuntimeError:  # preset loading meanwhile
            continue
    parts = [
        dump(user.config),
        dump(settings),
        *(dump(getattr(user, name, None)) for name in ("brakes", "brands", "classes", "compounds", "heatmap", "tracks")),
        dump({name: getattr(cfg.path, name, None) for name in getattr(cfg.path, "__slots__", None) or vars(cfg.path)}),
        dump(_folder_state(cfg.path.brand_logo) if cfg.path.brand_logo else []),
        str(cfg.filename.setting),
    ]
    return digest("\x00".join(parts))


class _RefreshHook(QObject):
    """Shared inputs read again after every setting refresh"""

    @Slot(bool)
    def changed(self, *_):
        inputs_changed()


_hook: list[_RefreshHook] = []


def _hook_refresh():
    """Connected once (again if app signals were all disconnected)"""
    from .. import app_signal

    if not _hook:
        _hook.append(_RefreshHook())
    app_signal.refresh.connect(_hook[0].changed, Qt.ConnectionType.UniqueConnection)


def pixel_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0


def preview_key(
    config: Setting, widget_name: str, widget_setting: Mapping, scale: float = 1.0, max_size: QSize | None = None,
) -> tuple:
    """Inputs of a picture: same key, same picture (see render_image)"""
    from ..i18n import current_language
    from ..userfile.game_images import images

    user = config.user
    text = "\x00".join((
        shared_inputs(),
        dump(user.config.get("overlay_style")),  # style proxies (setup wizard, zoom) change it
        setting_text(widget_setting),
        # Simulated session made with saved standings options, read by standings only
        dump(user.setting.get("standings")) if widget_name == "standings" else "",
        current_language(),
        repr(pixel_ratio()),
        repr(images.version),  # game logos fetched
    ))
    size = None if max_size is None else (max_size.width(), max_size.height())
    return widget_name, float(scale), size, digest(text)


class PictureCache:
    """Pictures by key, least recently used dropped beyond budget (bytes)"""

    def __init__(self, budget: int = CACHE_BUDGET):
        self.budget = budget
        self._items: OrderedDict[tuple, QImage | None] = OrderedDict()
        self._bytes = 0

    def get(self, key: tuple) -> tuple[bool, QImage | None]:
        """(found, picture), picture None if overlay cannot be drawn"""
        if key not in self._items:
            return False, None
        self._items.move_to_end(key)
        return True, self._items[key]

    def put(self, key: tuple, image: QImage | None):
        self._drop(key)
        self._items[key] = image
        self._bytes += _size(image)
        while self._bytes > self.budget and len(self._items) > 1:
            self._drop(next(iter(self._items)))

    def _drop(self, key: tuple):
        image = self._items.pop(key, None)
        self._bytes -= _size(image)

    def clear(self):
        self._items.clear()
        self._bytes = 0

    @property
    def size(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)


def _size(image: QImage | None) -> int:
    return 0 if image is None else image.sizeInBytes()


CACHE = PictureCache()


def render_image(
    config: Setting, widget_name: str, widget_setting: Mapping, scale: float = 1.0, max_size: QSize | None = None,
) -> QImage | None:
    """Widget picture (render_widget) scaled down to fit max_size (logical pixels) if set, None if empty; picture
    of same inputs reused (any page, any max size). Errors raised (not kept)."""
    key = preview_key(config, widget_name, widget_setting, scale)
    fitted_key = None if max_size is None else (*key[:2], (max_size.width(), max_size.height()), key[3])
    if fitted_key is not None:
        found, image = CACHE.get(fitted_key)
        if found:
            return image
    found, image = CACHE.get(key)
    if not found:
        image = _draw(config, widget_name, widget_setting, scale)
        CACHE.put(key, image)
    if image is None or fitted_key is None:
        return image
    fitted = fit(image, max_size)  # type: ignore[arg-type]
    if fitted is not image:  # bigger overlay: scaled down picture kept too
        CACHE.put(fitted_key, fitted)
    return fitted


def _draw(config: Setting, widget_name: str, widget_setting: Mapping, scale: float) -> QImage | None:
    from ..widget._painter import OverlayStyle

    shared = OverlayStyle.corner_scale, OverlayStyle.depth_effects  # set by widget: running overlays keep theirs
    try:
        pixmap = render_widget(config, widget_name, dict(widget_setting), scale)
    finally:
        OverlayStyle.corner_scale, OverlayStyle.depth_effects = shared
    return None if pixmap.isNull() else pixmap.toImage()


def fit(image: QImage, max_size: QSize) -> QImage:
    """Picture scaled down to fit max size (logical pixels), as is if it fits"""
    ratio = image.devicePixelRatio() or 1
    limit = max_size * ratio
    if image.width() <= limit.width() and image.height() <= limit.height():
        return image
    scaled = image.scaled(limit, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(ratio)
    return scaled


# Pages showing pictures
_showing: weakref.WeakSet = weakref.WeakSet()


def set_showing(owner: object, showing: bool):
    """Page (owner) shows pictures or not: once none does for a while, kept pictures & simulated session
    released (racing with window hidden)"""
    if showing:
        _showing.add(owner)
    else:
        _showing.discard(owner)
        if not _showing:
            QTimer.singleShot(IDLE_DELAY_MS, release_idle)


def release_idle() -> bool:
    """Release kept pictures & simulated session if no page shows pictures, True if released"""
    if _showing:
        return False
    from ..demo_data import release_session

    CACHE.clear()
    release_session()
    return True
