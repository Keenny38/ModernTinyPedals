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

Plugin layout (in "plugins" folder next to Modern Tiny Pedals):
    plugins/<name>/setting.json   default options (merged with PLUGIN_BASE_DEFAULT)
    plugins/<name>/widget.py      Realtime class, inherits tinypedal.widget._base.Overlay

Plugin is registered as "plugin_<name>" widget. Plugins run as normal Python code,
only install plugins from trusted source.

Plugin code is only executed after user trusted it (Plugin Manager, or install from zip).
Trust is bound to SHA-256 digest of all Python files in plugin folder, so any code change
requires trusting again. Digests are stored in config folder, plugins shipped with TinyPedal
are trusted by digest listed in BUNDLED_PLUGINS.

Widget code runs from the very bytes checked against trusted digest (never from compiled
bytecode, which is not covered by digest): compiled files in plugin folder are removed before
loading, and none is written while loading.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from contextlib import suppress
from types import MappingProxyType, ModuleType
from typing import Any

from . import safe_mode
from .validator import is_finite_number

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
BYTECODE_FILES = (".pyc", ".pyo")
WINDOWS_DEVICE_NAMES = frozenset((
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{index}" for index in range(10)), *(f"LPT{index}" for index in range(10)),
))
TRUST_FILE = "plugin_trust.json"
UNTRUSTED_ERROR = "Not trusted: review plugin code, then trust it in Plugin Manager"
SAFE_MODE_ERROR = "Safe mode: plugin not loaded, restart Modern Tiny Pedals to load it"
# Plugins shipped with TinyPedal: widget name: plugin digest (none since example speed plugin was removed)
BUNDLED_PLUGINS: MappingProxyType[str, str] = MappingProxyType({})


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
        defaults[widget_name] = {**PLUGIN_BASE_DEFAULT, **valid_plugin_setting(widget_name, setting)}
        logger.info("PLUGIN: found %s", widget_name)
    return defaults


def is_valid_option_value(value: Any, default: Any = None) -> bool:
    """Is valid plugin option value: same type as base option default, else number (finite),
    bool, string or list of them"""
    if default is not None:  # base option
        if isinstance(default, bool):
            return isinstance(value, bool)
        if isinstance(default, int):
            return isinstance(value, int) and not isinstance(value, bool)
        if isinstance(default, float):
            return is_finite_number(value)
        return isinstance(value, type(default))
    if isinstance(value, list):
        return all(not isinstance(item, list) and is_valid_option_value(item) for item in value)
    return isinstance(value, (bool, str)) or is_finite_number(value)


def valid_plugin_setting(widget_name: str, setting: dict) -> dict:
    """Plugin options with valid value type only (invalid option: base default used, or left out),
    so a wrong value in setting.json never stops widget or app from starting"""
    valid = {}
    for key, value in setting.items():
        if is_valid_option_value(value, PLUGIN_BASE_DEFAULT.get(key)):
            valid[key] = value
        else:
            logger.warning("PLUGIN: %s option %s has invalid value %r, ignored", widget_name, key, value)
    return valid


def plugin_path(widget_name: str, folder: str = PLUGIN_FOLDER) -> str:
    """Plugin folder path from widget name"""
    return os.path.join(folder, widget_name[len(PLUGIN_PREFIX):])


def plugin_code_files(path: str) -> list[str]:
    """Relative path of all Python files in plugin folder, sorted"""
    code_files = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                code_files.append(os.path.relpath(os.path.join(root, name), path).replace("\\", "/"))
    return code_files


def plugin_sources(path: str) -> dict[str, bytes]:
    """Content of all Python files in plugin folder, relative path: content"""
    sources = {}
    for relative in plugin_code_files(path):
        with open(os.path.join(path, relative), "rb") as file:
            sources[relative] = file.read()
    return sources


def sources_digest(sources: dict[str, bytes]) -> str:
    """SHA-256 digest of plugin Python files (relative path & content, line ending neutral)"""
    digest = hashlib.sha256()
    for relative, content in sources.items():
        digest.update(relative.encode("utf-8") + b"\0" + content.replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def plugin_digest(path: str) -> str:
    """SHA-256 digest of all Python files in plugin folder (relative path & content, line ending neutral)"""
    return sources_digest(plugin_sources(path))


def remove_bytecode(path: str) -> None:
    """Remove compiled Python files (not covered by trusted digest) from plugin folder

    Raises:
        OSError: unable to remove a compiled file.
    """
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            if name.lower().endswith(BYTECODE_FILES):
                os.remove(os.path.join(root, name))
                logger.info("PLUGIN: removed compiled file %s", os.path.join(root, name))
        for name in dirs:
            if name == "__pycache__":
                with suppress(OSError):  # other files left, not code
                    os.rmdir(os.path.join(root, name))


def trust_filename() -> str:
    """Trusted plugin digest file (config folder)"""
    from .setting import cfg  # late import, setting imports plugin defaults

    return f"{cfg.path.config}{TRUST_FILE}"


def load_trusted() -> dict[str, str]:
    """Load trusted plugin digests, empty if missing or invalid"""
    try:
        with open(trust_filename(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name): str(digest) for name, digest in data.items()}


def is_trusted(widget_name: str, folder: str = PLUGIN_FOLDER) -> bool:
    """Check if plugin code matches trusted digest"""
    return is_trusted_digest(widget_name, plugin_digest(plugin_path(widget_name, folder)))


def is_trusted_digest(widget_name: str, digest: str) -> bool:
    """Check if plugin code digest is trusted"""
    return digest in (BUNDLED_PLUGINS.get(widget_name), load_trusted().get(widget_name))


def trust_plugin(widget_name: str, folder: str = PLUGIN_FOLDER) -> str:
    """Trust current plugin code, returns digest

    Raises:
        OSError: unable to save trust file.
    """
    digest = plugin_digest(plugin_path(widget_name, folder))
    trusted = load_trusted()
    trusted[widget_name] = digest
    filename = trust_filename()
    temp_filename = f"{filename}.tmp"
    with open(temp_filename, "w", encoding="utf-8") as file:
        json.dump(trusted, file, indent=4, sort_keys=True)
    os.replace(temp_filename, filename)
    logger.info("PLUGIN: trusted %s (%s)", widget_name, digest[:12])
    return digest


def load_plugin_widget(package: str, widget_name: str, folder: str = PLUGIN_FOLDER) -> ModuleType:
    """Load plugin widget module as "<package>.<widget_name>", or error placeholder if failed

    Code is read once: digest checked & code run from the same bytes (never from bytecode).
    Safe mode: no plugin code run at all.
    """
    module_name = f"{package}.{widget_name}"
    if safe_mode.state.enabled:
        logger.warning("PLUGIN: %s not loaded (safe mode)", widget_name)
        PLUGIN_ERRORS[widget_name] = SAFE_MODE_ERROR
        placeholder = error_placeholder(module_name, widget_name, SAFE_MODE_ERROR)
        sys.modules[module_name] = placeholder
        return placeholder
    plugin_folder = plugin_path(widget_name, folder)
    path = os.path.join(plugin_folder, "widget.py")
    sources: dict[str, bytes] = {}
    try:
        remove_bytecode(plugin_folder)
        sources = plugin_sources(plugin_folder)
        trusted = is_trusted_digest(widget_name, sources_digest(sources))
    except OSError as error:
        trusted = False
        logger.error("PLUGIN: unable to read %s code: %s", widget_name, error)
    if not trusted:
        logger.warning("PLUGIN: %s not trusted, code not loaded", widget_name)
        PLUGIN_ERRORS[widget_name] = UNTRUSTED_ERROR
        placeholder = error_placeholder(module_name, widget_name, UNTRUSTED_ERROR)
        sys.modules[module_name] = placeholder
        return placeholder
    write_bytecode = sys.dont_write_bytecode
    try:
        source = sources.get("widget.py")
        if source is None:
            raise ImportError(f"cannot load {path}")
        code = compile(source, path, "exec", dont_inherit=True)
        module = ModuleType(module_name)
        module.__file__ = path
        module.__package__ = package
        sys.modules[module_name] = module
        sys.dont_write_bytecode = True  # modules imported by plugin: no compiled file in plugin folder
        exec(code, module.__dict__)  # trusted plugin code
        if not hasattr(module, "Realtime"):
            raise AttributeError("widget.py has no Realtime class")
        PLUGIN_ERRORS.pop(widget_name, None)
        return module
    except Exception as error:  # any error in plugin code must not stop app
        logger.error("PLUGIN: unable to load %s: %s", widget_name, error)
        logger.debug("PLUGIN: %s traceback", widget_name, exc_info=True)
        PLUGIN_ERRORS[widget_name] = f"{type(error).__name__}: {error}"
        placeholder = error_placeholder(module_name, widget_name, str(error))
        sys.modules[module_name] = placeholder
        return placeholder
    finally:
        sys.dont_write_bytecode = write_bytecode


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
        real_target = os.path.realpath(target)
        for relative, info in files.items():
            parts = relative.split("/")
            if not is_safe_package_path(parts) or not relative.lower().endswith(ALLOWED_PACKAGE_FILES):
                continue  # skip unsafe or unexpected file
            if info.file_size > 10 * 1024 * 1024:
                continue
            path = os.path.join(target, *parts)
            if not is_inside_folder(path, real_target):
                continue  # outside plugin folder
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as file:
                file.write(package.read(info))
    logger.info("PLUGIN: installed %s", name)
    return f"{PLUGIN_PREFIX}{name}"


def is_inside_folder(path: str, real_folder: str) -> bool:
    """Check if path (links resolved) is inside folder (real path)"""
    try:
        return os.path.commonpath([os.path.realpath(path), real_folder]) == real_folder
    except ValueError:  # other drive
        return False


def is_safe_package_path(parts: list[str]) -> bool:
    """Check if path parts of package file stay inside plugin folder

    Not allowed: empty, relative (. ..), absolute or drive part ("C:", "D:pwn.py"), Windows device
    name, and compiled Python cache (not covered by trusted digest).
    """
    for part in parts:
        if part in ("", ".", "..", "__pycache__") or ":" in part or "\\" in part or "\0" in part:
            return False
        if os.path.isabs(part) or os.path.splitdrive(part)[0]:
            return False
        if part.split(".", 1)[0].strip().upper() in WINDOWS_DEVICE_NAMES or part.endswith((" ", ".")):
            return False
    return True
