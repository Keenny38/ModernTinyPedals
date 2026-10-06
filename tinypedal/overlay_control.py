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
Overlay Control
"""

import logging
import threading

from . import app_signal, overlay_signal, realtime_state
from .api_control import api
from .setting import cfg
from .thread_guard import run_supervised, wait_stopped

logger = logging.getLogger(__name__)


class OverlayToggle:
    """Overlay state toggle"""

    __slots__ = ()

    def vr(self):
        """Toggle VR state"""
        self.__toggle_option("vr_compatibility")
        overlay_signal.iconify.emit(cfg.overlay["vr_compatibility"])

    def lock(self):
        """Toggle lock state, unlocked: overlay edit mode (toolbar), see widget._edit_mode"""
        self.__toggle_option("fixed_position")
        overlay_signal.locked.emit(cfg.overlay["fixed_position"])
        from .widget._edit_mode import follow_lock

        follow_lock(cfg.overlay["fixed_position"])

    def hide(self):
        """Toggle hide state"""
        self.__toggle_option("auto_hide")

    def grid(self):
        """Toggle grid move state"""
        self.__toggle_option("enable_grid_move")

    @staticmethod
    def __toggle_option(option_name: str):
        """Toggle option"""
        cfg.overlay[option_name] = not cfg.overlay[option_name]
        cfg.save()


class OverlayControl:
    """Overlay control"""

    __slots__ = (
        "toggle",
        "_thread",
        "_event",
        "_last_active_state",
        "_last_hide_state",
    )

    def __init__(self):
        self.toggle = OverlayToggle()
        self._thread: threading.Thread | None = None
        self._event = threading.Event()

        self._last_active_state = None
        self._last_hide_state = None

    def _stopped(self) -> bool:
        """Whether update thread stopped (or never started)"""
        return self._thread is None or not self._thread.is_alive()

    def enable(self):
        """Enable overlay control"""
        # A previous thread still stopping (event set) is replaced, it exits on its own event
        if self._stopped() or self._event.is_set():
            self._event = threading.Event()
            self._thread = threading.Thread(
                target=self.__updating, args=(self._event,), daemon=True, name="Overlay control")
            self._thread.start()
            logger.info("ENABLED: overlay control")

    def disable(self):
        """Disable overlay control, wait (bounded) until stopped"""
        self._event.set()
        wait_stopped(self._stopped, "overlay control")

    def __updating(self, event: threading.Event):
        """Run update loop"""
        run_supervised(lambda: self.__update_loop(event), "overlay control", event)

    def __update_loop(self, event: threading.Event):
        """Update global state"""
        _event_wait = event.wait
        while not _event_wait(0.2):
            # Read state
            active = api.read.state.active()
            paused = api.read.state.paused()
            resets = api.read.state.resets()
            hidden = cfg.overlay["auto_hide"] and not active
            if active:
                session_type = api.read.session.session_type()
                in_pits = api.read.vehicle.in_pits() or api.read.vehicle.in_garage()
            else:
                session_type, in_pits = -1, False
            # Update state
            realtime_state.active = active
            realtime_state.paused = paused
            realtime_state.resets = resets
            # Auto hide state check
            if self._last_hide_state != hidden:
                self._last_hide_state = hidden
                realtime_state.hidden = hidden
                overlay_signal.hidden.emit(hidden)
            # Visibility context check (per widget "visibility_context" option)
            if realtime_state.session_type != session_type or realtime_state.in_pits != in_pits:
                realtime_state.session_type = session_type
                realtime_state.in_pits = in_pits
                overlay_signal.context.emit()
            # Active state check
            if self._last_active_state != active:
                self._last_active_state = active
                # Update auto load state only once when player enters track
                if active and cfg.application["enable_auto_load_preset"]:
                    # Track primary preset takes priority over class primary preset
                    if not self.__check_preset_track():
                        self.__check_preset_class()
                # Set overlay timer state
                overlay_signal.paused.emit(not active)

        logger.info("DISABLED: overlay control")

    def __check_preset_track(self) -> bool:
        """Check primary preset from track"""
        track_name = api.read.session.track_name()
        track_data = cfg.user.tracks.get(track_name)
        if not track_data or not track_data.get("preset", ""):
            return False
        preset_name = cfg.get_primary_preset_name(track_data["preset"])
        if preset_name == "":
            return False
        self.__auto_load_preset(track_name, preset_name)
        return True

    def __check_preset_class(self) -> bool:
        """Check primary preset from class"""
        class_name = api.read.vehicle.class_name()
        class_data = cfg.user.classes.get(class_name)
        if class_data is None:
            return False
        class_preset_name = class_data["preset"]
        if class_preset_name == "":
            return False
        preset_name = cfg.get_primary_preset_name(class_preset_name)
        self.__auto_load_preset(class_name, preset_name)
        return True

    def __auto_load_preset(self, target_name, preset_name):
        """Auto load primary preset"""
        logger.info("AUTOLOADING: %s detected, attempt loading %s (primary preset)", target_name, preset_name)
        # Abort if preset file does not exist
        if preset_name == "":
            logger.info("AUTOLOADING: %s (primary preset) not found, abort auto loading", preset_name)
            return
        # Check if already loaded
        if cfg.is_loaded(preset_name):
            logger.info("AUTOLOADING: %s (primary preset) already loaded", preset_name)
            return
        # Update preset name & signal reload
        cfg.set_next_to_load(preset_name)
        app_signal.reload.emit(False)


octrl = OverlayControl()
