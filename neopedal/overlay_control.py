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
Overlay Control
"""

import logging
import sys
import threading
from collections.abc import Callable

from . import app_signal, overlay_signal, realtime_state
from .api_control import api
from .setting import cfg
from .template.setting_classes import SESSION_PRESET_KEYS, session_name
from .thread_guard import run_supervised, wait_stopped

logger = logging.getLogger(__name__)
UPDATE_INTERVAL = 0.2  # seconds between state reads while game data updates
FROZEN_WAIT = 1.0  # longest wait while game data frozen (game closed, menus), woken earlier on activity change


def stream_on_air() -> bool:
    """Stream overlay on air (see StreamOverlay.on_air): its module (http.server...) imported only once used,
    never imported means never started; module listed but still importing (main thread) has no instance yet:
    not started either"""
    module = sys.modules.get(f"{__package__}.stream_overlay")
    overlay = getattr(module, "streamoverlay", None)
    return overlay is not None and overlay.on_air()


class OverlayToggle:
    """Overlay state toggle

    Args:
        wake: wakes the overlay control thread (see OverlayControl.wake), None if none (tests).
    """

    __slots__ = ("_wake",)

    def __init__(self, wake: Callable[[], None] | None = None):
        self._wake = wake

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
        """Toggle hide state: control thread woken, hidden state read & signalled at once (it waits up to
        FROZEN_WAIT while game data is frozen)"""
        self.__toggle_option("auto_hide")
        if self._wake is not None:
            self._wake()

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
        "_wake",
        "_last_active_state",
        "_last_shown_state",
        "_last_hide_state",
    )

    def __init__(self):
        self.toggle = OverlayToggle(self.wake)
        self._thread: threading.Thread | None = None
        self._event = threading.Event()
        self._wake = threading.Event()  # activity change (realtime_state), toggle or stop

        self._last_active_state = None
        self._last_shown_state = None
        self._last_hide_state = None

    def wake(self):
        """Read state again now (auto hide toggled), instead of at the end of the current wait"""
        self._wake.set()

    def _stopped(self) -> bool:
        """Whether update thread stopped (or never started)"""
        return self._thread is None or not self._thread.is_alive()

    def enable(self):
        """Enable overlay control"""
        # A previous thread still stopping (event set) is replaced, it exits on its own event
        if self._stopped() or self._event.is_set():
            self._event = threading.Event()
            self._wake = threading.Event()
            self._thread = threading.Thread(
                target=self.__updating, args=(self._event, self._wake), daemon=True, name="Overlay control")
            self._thread.start()
            logger.info("ENABLED: overlay control")

    def disable(self, wait: bool = True):
        """Disable overlay control, wait (bounded) until stopped, else only signalled (see enable)"""
        self._event.set()
        self._wake.set()
        if wait:
            wait_stopped(self._stopped, "overlay control")

    def __updating(self, event: threading.Event, wake: threading.Event):
        """Run update loop"""
        realtime_state.subscribe(wake)
        try:
            run_supervised(lambda: self.__update_loop(event, wake), "overlay control", event)
        finally:
            realtime_state.unsubscribe(wake)

    def __update_loop(self, event: threading.Event, wake: threading.Event | None = None):
        """Update global state

        Game data frozen (game closed, menus) & overlays not shown: nothing to read until connector resumes
        (activity change notified), so state read every FROZEN_WAIT instead of every UPDATE_INTERVAL.

        Args:
            event: stop event.
            wake: activity change wake (subscribed to realtime_state), also set on stop.
        """
        if wake is None:  # not subscribed (tests): first frozen wait not held
            wake = threading.Event()
            wake.set()
        _event_wait = event.wait
        _wait_change = realtime_state.wait_change
        last_activity = None
        while True:
            if last_activity is not None and realtime_state.paused and not realtime_state.shown:
                _wait_change(FROZEN_WAIT, wake)
                if _event_wait(0):
                    break
            elif _event_wait(UPDATE_INTERVAL):
                break
            # Read state
            active = api.read.state.active()
            paused = api.read.state.paused()
            resets = api.read.state.resets()
            # Overlays shown & updated: driving, or spectating / replay streamed (overlays only, see on_air)
            shown = active or (not paused and api.read.vehicle.total_vehicles() > 0 and stream_on_air())
            hidden = cfg.overlay["auto_hide"] and not shown
            # Shown for stream only (garage, spectating): auto hide still applies on screen, sources keep them
            screen_hidden = cfg.overlay["auto_hide"] and shown and not active
            if active:
                session_type = api.read.session.session_type()
                in_pits = api.read.vehicle.in_pits() or api.read.vehicle.in_garage()
            else:
                session_type, in_pits = -1, False
            # Update state
            realtime_state.active = active
            realtime_state.shown = shown
            realtime_state.paused = paused
            realtime_state.resets = resets
            # Threads idle until activity changes (modules, RestAPI) woken
            activity = (active, paused, shown, resets)
            if last_activity != activity:
                last_activity = activity
                realtime_state.notify_change()
            # Auto hide state check
            if self._last_hide_state != (hidden, screen_hidden):
                self._last_hide_state = (hidden, screen_hidden)
                realtime_state.hidden = hidden
                realtime_state.screen_hidden = screen_hidden
                overlay_signal.hidden.emit(hidden)
            # Visibility context check (per widget "visibility_context" option)
            session_changed = realtime_state.session_type != session_type
            if session_changed or realtime_state.in_pits != in_pits:
                realtime_state.session_type = session_type
                realtime_state.in_pits = in_pits
                overlay_signal.context.emit()
            # Active state check
            entered = False
            if self._last_active_state != active:
                self._last_active_state = active
                entered = active
            # Auto load when player enters track, or session changes while driving (practice to qualifying)
            if (entered or (active and session_changed)) and cfg.application["enable_auto_load_preset"]:
                # Class preset of the session first, then track preset, then class preset (every session)
                if not self.__check_preset_class_session(session_type) and not self.__check_preset_track():
                    self.__check_preset_class()
            # Set overlay timer state
            if self._last_shown_state != shown:
                self._last_shown_state = shown
                overlay_signal.paused.emit(not shown)

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

    def __check_preset_class_session(self, session_type: int) -> bool:
        """Check primary preset from class & session (practice, qualify, race)"""
        session = session_name(session_type)
        if not session:
            return False
        class_name = api.read.vehicle.class_name()
        class_data = cfg.user.classes.get(class_name)
        if not isinstance(class_data, dict):
            return False
        preset_name = cfg.get_primary_preset_name(class_data.get(SESSION_PRESET_KEYS[session], ""))
        if preset_name == "":
            return False
        self.__auto_load_preset(f"{class_name} ({session})", preset_name)
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
