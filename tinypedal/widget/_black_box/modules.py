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
Black box widget, data module dependencies

Several readings come from data modules (Wheels, Fuel, Delta, Hybrid) instead of the game API.
When such a module is turned off, its data stops updating: the widget would show frozen or zero
values without telling why. This keeps track of which modules the enabled options need, which
of them are enabled, so readings of a disabled module are skipped and the widget says which
module is missing instead.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

# Module: (short name shown in widget, options that read its data)
MODULE_FEATURES: dict[str, tuple[str, tuple[str, ...]]] = {
    "module_wheels": ("Wheels", (
        "show_slip_warning", "show_wheel_camber", "show_tyre_slip_angle",
        "show_tyre_wear_per_lap", "show_tyre_wear_end_stint", "show_brake_wear", "show_wheel_locking",
        "show_stint_comparison", "show_tyre_status", "show_suspension",
    )),
    "module_fuel": ("Fuel", ("show_fuel_gauge", "show_energy_gauge", "show_tyre_wear_end_stint")),
    "module_delta": ("Delta", ("show_delta_best", "show_laptime")),
    "module_hybrid": ("Hybrid", ("show_battery_bar",)),
}


def required_modules(wcfg: Mapping) -> tuple[str, ...]:
    """Modules needed by enabled options, in MODULE_FEATURES order"""
    return tuple(
        name for name, (_, options) in MODULE_FEATURES.items()
        if any(wcfg.get(option) for option in options)
    )


class ModuleStatus:
    """Enabled state of required modules, refreshed from settings

    Reads the module "enable" setting rather than the running instance, so the state is known
    at once, including while a module is being started.
    """

    __slots__ = ("settings", "required", "enabled", "version")

    def __init__(self, settings: Mapping, required: tuple[str, ...]):
        self.settings = settings
        self.required = required
        self.enabled: frozenset[str] = frozenset()
        self.version = 0  # changes when a module is turned on or off
        self.refresh()

    def refresh(self) -> bool:
        """Read settings again, return True if a required module was turned on or off"""
        enabled = frozenset(name for name in self.required if self.is_enabled(name))
        if enabled == self.enabled:
            return False
        self.enabled = enabled
        self.version += 1
        return True

    def is_enabled(self, name: str) -> bool:
        module = self.settings.get(name)
        return bool(isinstance(module, Mapping) and module.get("enable", False))

    def ready(self, name: str) -> bool:
        """Module data available: enabled, or not required by any shown option"""
        return name in self.enabled or name not in self.required

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in self.required if name not in self.enabled)

    def missing_text(self) -> str:
        """Short notice, ex. "Wheels, Fuel module off", "" if nothing missing"""
        names = [MODULE_FEATURES[name][0] for name in self.missing]
        if not names:
            return ""
        return f"{', '.join(names)} module{'s' if len(names) > 1 else ''} off"


def enable_modules(names, settings, save) -> list[str]:
    """Turn on and start modules, return names actually started

    Used by enable_required_modules option: the same as turning the module on in the
    module list, so it is saved and stays on.
    """
    from ...module_control import mctrl  # imported here: module control imports every widget

    started = []
    for name in names:
        module = settings.get(name)
        if not isinstance(module, dict) or module.get("enable"):
            continue
        module["enable"] = True
        try:
            mctrl.start(name)
        except Exception:  # module failing to start must never take the widget down
            logger.exception("BLACK BOX: unable to start %s", name)
            continue
        started.append(name)
    if started:
        save()
        logger.info("BLACK BOX: enabled required module(s): %s", ", ".join(started))
    return started
