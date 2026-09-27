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
Widget plugin loader

Plugin layout (in "plugins" folder next to TinyPedal):
    plugins/<name>/setting.json   default options (merged with PLUGIN_BASE_DEFAULT)
    plugins/<name>/widget.py      Realtime class, inherits tinypedal.widget._base.Overlay

Plugin is registered as "plugin_<name>" widget. Plugins run as normal Python code,
only install plugins from trusted source.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
from types import MappingProxyType, ModuleType

logger = logging.getLogger(__name__)

PLUGIN_FOLDER = "plugins"
PLUGIN_PREFIX = "plugin_"
PLUGIN_BASE_DEFAULT = MappingProxyType({
    "enable": False,
    "update_interval": 50,
    "position_x": 100,
    "position_y": 100,
    "opacity": 0.9,
    "font_name": "Consolas",
    "font_size": 15,
    "font_weight": "Bold",
    "enable_auto_font_offset": True,
    "font_offset_vertical": 0,
    "bar_padding": 0.2,
    "bar_gap": 0,
})
_valid_name = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
PLUGIN_ERRORS: dict[str, str] = {}  # widget name: last loading error
ALLOWED_PACKAGE_FILES = (".py", ".json", ".png", ".svg", ".txt", ".md")


def discover_plugins(folder: str = PLUGIN_FOLDER) -> dict[str, str]:
    """Find plugin folders, returns widget name: plugin folder path"""
    plugins: dict[str, str] = {}
    if not os.path.isdir(folder):
        return plugins
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isdir(path):
            continue
        if not _valid_name.match(name):
            logger.warning("PLUGIN: invalid folder name %s (use lowercase letters, digits, _)", name)
            continue
        if os.path.exists(os.path.join(path, "widget.py")) and os.path.exists(os.path.join(path, "setting.json")):
            plugins[f"{PLUGIN_PREFIX}{name}"] = path
    return plugins


def load_plugin_defaults(folder: str = PLUGIN_FOLDER) -> dict[str, dict]:
    """Load plugin default settings, invalid plugin is skipped"""
    defaults: dict[str, dict] = {}
    for widget_name, path in discover_plugins(folder).items():
        try:
            with open(os.path.join(path, "setting.json"), encoding="utf-8") as file:
                setting = json.load(file)
            if not isinstance(setting, dict):
                raise ValueError("setting.json must be a JSON object")
        except (OSError, ValueError) as error:
            logger.error("PLUGIN: unable to load %s setting: %s", widget_name, error)
            continue
        defaults[widget_name] = {**PLUGIN_BASE_DEFAULT, **setting}
        logger.info("PLUGIN: found %s", widget_name)
    return defaults


def load_plugin_widget(package: str, widget_name: str, folder: str = PLUGIN_FOLDER) -> ModuleType:
    """Load plugin widget module as "<package>.<widget_name>", or error placeholder if failed"""
    module_name = f"{package}.{widget_name}"
    path = os.path.join(folder, widget_name[len(PLUGIN_PREFIX):], "widget.py")
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if not hasattr(module, "Realtime"):
            raise AttributeError("widget.py has no Realtime class")
        PLUGIN_ERRORS.pop(widget_name, None)
        return module
    except Exception as error:  # any error in plugin code must not stop app
        logger.error("PLUGIN: unable to load %s: %s", widget_name, error)
        PLUGIN_ERRORS[widget_name] = f"{type(error).__name__}: {error}"
        placeholder = error_placeholder(module_name, widget_name, str(error))
        sys.modules[module_name] = placeholder
        return placeholder


def error_placeholder(module_name: str, widget_name: str, message: str) -> ModuleType:
    """Placeholder widget module that shows plugin error"""
    from .widget._base import Overlay

    class Realtime(Overlay):
        """Plugin error"""

        def __init__(self, config, widget_name):
            super().__init__(config, widget_name)
            font = self.config_font(self.wcfg["font_name"], self.wcfg["font_size"], self.wcfg["font_weight"])
            self.setFont(font)
            font_m = self.get_font_metrics(font)
            layout = self.set_grid_layout()
            self.set_primary_layout(layout=layout)
            text = f"PLUGIN ERROR: {widget_name}"
            bar = self.set_rawtext(
                text=text, width=font_m.width * len(text) + 8, fixed_height=font_m.height,
                offset_y=font_m.voffset, fg_color="#FFFFFF", bg_color="#B03030",
            )
            bar.setToolTip(message)
            layout.addWidget(bar, 0, 0)

    placeholder = ModuleType(module_name)
    placeholder.Realtime = Realtime  # type: ignore[attr-defined]
    return placeholder


def install_plugin_package(zip_filename: str, folder: str = PLUGIN_FOLDER) -> str:
    """Install plugin from zip (one top folder with widget.py & setting.json), returns widget name

    Raises:
        ValueError: invalid package or plugin already exists.
        OSError: file error.
    """
    import zipfile

    with zipfile.ZipFile(zip_filename) as package:
        members = [info for info in package.infolist() if not info.is_dir()]
        tops = {info.filename.replace("\\", "/").split("/", 1)[0] for info in members}
        if len(tops) != 1:
            raise ValueError("package must contain a single plugin folder")
        name = tops.pop()
        if not _valid_name.match(name):
            raise ValueError(f"invalid plugin name: {name}")
        files = {info.filename.replace("\\", "/").split("/", 1)[-1]: info for info in members}
        if "widget.py" not in files or "setting.json" not in files:
            raise ValueError("widget.py or setting.json not found")
        target = os.path.join(folder, name)
        if os.path.exists(target):
            raise ValueError(f"plugin {name} already exists")
        for relative, info in files.items():
            parts = relative.split("/")
            if any(part in ("", ".", "..") for part in parts) or not relative.lower().endswith(ALLOWED_PACKAGE_FILES):
                continue  # skip unsafe or unexpected file
            if info.file_size > 10 * 1024 * 1024:
                continue
            path = os.path.join(target, *parts)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as file:
                file.write(package.read(info))
    logger.info("PLUGIN: installed %s", name)
    return f"{PLUGIN_PREFIX}{name}"
