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
Loader function

Important: DO NOT call those functions in non-main thread.

Safe mode (see safe_mode): overlays (widgets & VR overlay) not started at start and reload,
a widget can still be turned on by hand; restart starts normally.
"""

import gc
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from time import monotonic
from typing import Any

from . import realtime_state, safe_mode
from .api_control import api
from .const_app import EXECUTABLE, RESTART_ENVIRONMENT
from .const_file import FileExt
from .hotkey_control import kctrl
from .lazy_service import LazyService, cmdserver, imported, streamoverlay, update_checker, webdashboard  # noqa: F401
from .module.module_recorder import wait_lap_saver
from .module_control import event_loop_running, mctrl, wctrl
from .overlay_control import octrl
from .replay import replay
from .setting import cfg
from .userfile.data_saver import wait_data_saver
from .vr_overlay import vroverlay

logger = logging.getLogger(__name__)

# Settings changed in memory & saved later by their owner (car followed by the Director): written before preset
# reload, restart & quit, else lost (preset file loaded again) or written late, see write_pending
_pending_writers: list[Callable[[], object]] = []
LAP_SAVER_TIMEOUT = 10.0  # seconds to wait for lap files being written before restart
REPLAY_CLOSE_TIMEOUT = 10.0  # seconds to wait more for a replay recording still closing (quit, restart)
# Objects of a started app (window, overlays, settings) moved out of garbage collection: full collections scan
# only objects made since, shorter pauses while driving. Done once start finished, again after each reload.
_gc_frozen = False
_gc_collect_due = False  # full collection of objects parked by reload (or page closed) waiting for idle moment
_gc_last_collect = 0.0  # monotonic time of last full collection of frozen objects
IDLE_COLLECT_MS = 10 * 60 * 1000  # full collection asked this often while not driving (garbage of closed pages)
_idle_collect_timer: Any = None  # QTimer asking periodic full collection, once start finished
RELOAD_POLL_MS = 10  # reload: interval checking whether modules stopped
SAVE_TIMEOUT = 10.0  # reload: seconds waiting for settings saving before loading preset (as cfg.flush)


def int_signal_handler(sign, frame):
    """Quit by keyboard interrupt (Ctrl+C in console)

    Main window quits as by its Quit menu (pages closed, QML unloaded before backends, window state
    saved). Closing here then exiting left QML pages bound to deleted backends ("of null" errors).
    """
    from PySide6.QtCore import SIGNAL

    from . import app_signal

    if app_signal.receivers(SIGNAL("quitapp(bool)")) > 0:
        app_signal.quitapp.emit(True)
        return
    close()
    sys.exit()


def start():
    """Start api, modules, widgets, etc. Call once per launch."""
    logger.info("STARTING............")
    signal.signal(signal.SIGINT, int_signal_handler)
    # 1 load user preset
    cfg.set_next_to_load(f"{cfg.preset_files()[0]}{FileExt.JSON}")
    cfg.load_user()
    sync_screen_layout()
    cfg.save_loaded()  # preset written only if missing, repaired or migrated (unchanged file left alone)
    # 2 start api
    api.connect()
    api.start()
    # 3 start modules
    mctrl.start()
    # 4 start widgets
    if not safe_mode.state.enabled:
        wctrl.start()
    # 5 start main window
    from .ui.app import AppWindow
    window = AppWindow()
    # Finalize loading after main GUI fully loaded
    logger.info("FINALIZING............")
    # 1 Enable overlay control
    octrl.enable()
    # 2 Enable hotkey control
    kctrl.enable()
    # 3 Enable remote control & VR overlay
    enable_servers()
    if not safe_mode.state.enabled:
        vroverlay().enable()
        enable_stream_overlay()
    else:
        vroverlay().disable()  # OpenXR layer left registered (0.22.3) removed in safe mode too
    # 4 Check for updates
    if cfg.application["check_for_updates_on_startup"]:
        update_checker.check(False)
    # 5 Start finished once window & overlays are up for a while (startup marker removed)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(safe_mode.SETTLE_MS, finish_start)
    if safe_mode.state.enabled:
        QTimer.singleShot(0, lambda: show_safe_mode_notice(window))


def finish_start():
    """Start finished (main window & overlays up): next start is a normal one"""
    safe_mode.clear_marker(cfg.path.config)
    logger.info("STARTED: startup marker removed")
    freeze_collected()
    start_idle_collect_timer()


def freeze_collected():
    """Objects alive now never scanned again by garbage collection (see _gc_frozen)"""
    global _gc_frozen, _gc_last_collect
    _gc_frozen = True
    gc.collect()
    gc.freeze()
    _gc_last_collect = monotonic()


def start_idle_collect_timer():
    """Full collection asked every IDLE_COLLECT_MS while not driving (see request_idle_collect)"""
    global _idle_collect_timer
    if _idle_collect_timer is not None:
        return
    from PySide6.QtCore import QTimer

    _idle_collect_timer = QTimer()
    _idle_collect_timer.timeout.connect(periodic_idle_collect)
    _idle_collect_timer.start(IDLE_COLLECT_MS)


def periodic_idle_collect():
    """Full collection if none for IDLE_COLLECT_MS & not driving (never waits for driving to end)"""
    if realtime_state.active or monotonic() - _gc_last_collect < IDLE_COLLECT_MS / 1000 * 0.9:
        return
    request_idle_collect()


def request_idle_collect():
    """Frozen objects collected at next idle moment (not driving): garbage of closed page or tool, made of
    objects frozen with the app (unfreeze, full collection, freeze again). Several requests: one collection."""
    global _gc_collect_due
    if not _gc_frozen or _gc_collect_due:
        return
    _gc_collect_due = True
    from PySide6.QtCore import QTimer

    QTimer.singleShot(safe_mode.SETTLE_MS, collect_parked_idle)


def park_collected():
    """After reload: objects made since frozen too, without collecting (no pause, auto-load reloads on track)

    Garbage of replaced overlays & modules is parked with them, collected by one full collection at next idle
    moment (not driving), see collect_parked_idle.
    """
    if not _gc_frozen:
        return
    gc.freeze()
    request_idle_collect()


def collect_parked_idle():
    """Full collection of objects parked by reload (or of closed pages), once not driving (pauses GUI & modules)"""
    global _gc_collect_due
    if realtime_state.active:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(safe_mode.SETTLE_MS, collect_parked_idle)
        return
    _gc_collect_due = False
    if unfreeze_collected():
        freeze_collected()


def unfreeze_collected() -> bool:
    """Frozen objects back to garbage collection (overlays & modules about to be replaced), True if were frozen"""
    global _gc_frozen
    if not _gc_frozen:
        return False
    _gc_frozen = False
    gc.unfreeze()
    return True


def show_safe_mode_notice(window):
    """Safe mode: shown in window title, notice offering to restart normally"""
    import shiboken6
    from PySide6.QtWidgets import QMessageBox

    from .i18n import tr

    if window is not None and not shiboken6.isValid(window):
        window = None
    if window is not None:
        window.setWindowTitle(f"{window.windowTitle()} - {tr('Safe Mode')}")
    box = QMessageBox(window if window is not None and window.isVisible() else None)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("Safe Mode"))
    box.setText(tr("Safe mode: plugins are not loaded and overlays are not started.\n\n"
                   "Fix the settings that stopped NeoPedal from starting, "
                   "then restart normally."))
    button_restart = box.addButton(tr("Restart Normally"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is not button_restart:
        return
    restart_app = getattr(window, "restart_app", None)
    if callable(restart_app):
        restart_app()  # open pages may ask to save first
    else:
        restart()


def on_pending_write(writer: Callable[[], object]):
    """Writer called before reload, restart & quit: queues its unsaved settings (cfg.save), registered once"""
    if writer not in _pending_writers:
        _pending_writers.append(writer)


def write_pending():
    """Unsaved settings of every writer queued for saving now (see on_pending_write)"""
    for writer in tuple(_pending_writers):
        try:
            writer()
        except Exception:  # one writer failing never stops reload or quit
            logger.exception("USERDATA: pending setting write failed")


def close():
    """Close api, modules, widgets. Call before quit APP."""
    logger.info("CLOSING............")
    write_pending()
    # 0 reload in progress never finished (modules still stopping waited below)
    cancel_reload()
    # 1 unload modules (recorder module saves last lap); their queued data saves (delta, fuel, sectors,
    # consumption) written before the process ends (each module already waits for its own, safety net)
    unload_modules()
    if not wait_data_saver(LAP_SAVER_TIMEOUT):
        logger.warning("CLOSING: data saving not finished")
    # 2 finish replay recording (manual recording is not stopped by recorder module)
    replay.stop_recording()
    if not replay.wait_closed(REPLAY_CLOSE_TIMEOUT):  # slow drive: never cut by the process end
        logger.warning("CLOSING: replay recording not closed")
    # 3 stop & close api
    api.stop()
    api.close()
    logger.info("API: closed")
    # 4 quitting or restarting before start finished is no crash
    safe_mode.clear_marker(cfg.path.config)
    # 5 settings saved by stopped modules (track info, brands, brakes) written before the process ends:
    # quit never waited for the saving thread (restart does, see restart)
    cfg.flush()


def restart():
    """Restart APP"""
    logger.info("RESTARTING............")
    # 0 must close first
    close()
    # 1 wait unfinished saving (settings, recorded laps: process exits without waiting threads)
    cfg.flush()
    if not wait_lap_saver(LAP_SAVER_TIMEOUT):
        logger.warning("RESTARTING: lap saving not finished")
    if not wait_data_saver(LAP_SAVER_TIMEOUT):
        logger.warning("RESTARTING: data saving not finished")
    # 2 set restart env for skipping single instance check
    os.environ[RESTART_ENVIRONMENT] = "TRUE"
    command = restart_command()
    try:
        if sys.platform == "win32":
            # os.execl does not quote arguments on Windows, which breaks path with spaces
            subprocess.Popen(command, close_fds=True)
            logging.shutdown()
            os._exit(0)
        logging.shutdown()  # flush log files, execv replaces process without cleanup
        os.execv(command[0], command)
    except OSError as error:
        # exe moved or blocked: keep running, reload what close() unloaded
        logger.error("RESTARTING: failed, %s", error)
        os.environ.pop(RESTART_ENVIRONMENT, None)
        api.connect()
        api.start()
        load_modules()


def restart_command() -> list[str]:
    """Command line to relaunch APP, normal start (safe mode flag left out)"""
    arguments = safe_mode.restart_arguments(sys.argv)
    if getattr(sys, "frozen", False) or os.path.basename(sys.executable).lower() == EXECUTABLE:  # if run as exe
        return [sys.executable, *arguments[1:]]
    return [sys.executable, *arguments]  # if run as script


class ReloadState:
    """Reload in progress: modules stopping polled by timer (GUI & overlays kept running)"""

    __slots__ = ("running", "preset", "serial", "queued", "callbacks", "save_deadline")

    def __init__(self):
        self.running = False
        self.preset = False  # reload preset file once modules stopped
        self.serial = 0  # changed once finished or cancelled: poll timer of that reload does nothing
        self.queued: bool | None = None  # reload asked while running (its reload_preset), None if not asked
        self.callbacks: list[Callable[[], object]] = []  # run once no reload left
        self.save_deadline = 0.0  # monotonic time waiting for saving gives up, 0 until saving seen


_reload = ReloadState()


def reloading() -> bool:
    """Whether a reload is in progress (modules stopping)"""
    return _reload.running


def after_reload(callback: Callable[[], object]):
    """Run callback once reload finished (reload asked meanwhile too), at once if none in progress

    For callers acting on reloaded preset or started overlays (pages refreshed...).
    """
    if _reload.running:
        _reload.callbacks.append(callback)
    else:
        callback()


def cancel_reload():
    """Reload in progress dropped (quit, restart): nothing started again, callbacks never run"""
    state = _reload
    state.serial += 1
    state.running = False
    state.queued = None
    state.callbacks.clear()


def reload(reload_preset: bool = False, wait: bool | None = None):
    """Reload preset, api, modules, widgets

    Modules are signalled to stop, then polled from a timer: GUI & event loop keep running while a module
    finishes its stop work (lap saving, replay closed), up to its stop timeout. Steps after (preset loaded,
    api, modules & widgets started) run once all stopped. Reload asked meanwhile runs once after, with
    preset reloaded if any asked so. See after_reload to act once finished.

    Args:
        reload_preset:
            Whether to reload preset file.
            Should only done if changed global setting,
            or reloading from preset tab,
            or auto-loading preset.
        wait: finished before returning (GUI paused while modules stop). Default: only if no event loop runs.
    """
    if wait is None:
        wait = not event_loop_running()
    state = _reload
    if state.running:
        state.queued = reload_preset or bool(state.queued)
        if wait:
            complete_reload(wait=True)
        else:
            logger.info("RELOADING: queued after reload in progress")
        return
    logger.info("RELOADING............")
    write_pending()  # settings saved later by their owner written before preset file loaded again
    # 1 unload modules (servers kept listening: browser sources, dashboard, stream clients stay connected)
    if wait:
        cfg.flush()  # 0 wait unfinished saving
        unload_modules(keep_servers=True)
        finish_reload(reload_preset)
        return
    if cfg.is_saving:  # 0 unfinished saving written now, waited by poll_reload (GUI never blocked)
        cfg.save(next_task=True)
    state.running = True
    state.preset = reload_preset
    state.serial += 1
    state.save_deadline = 0.0
    try:
        unload_modules(keep_servers=True, wait=False)
    except BaseException:
        cancel_reload()
        raise
    poll_reload(state.serial)


def poll_reload(serial: int):
    """Continue reload once modules stopped (or gave up after stop timeout, logged), else check again later

    Preset reloaded: saving (data saved by stopped modules, track info) then finished first (or gave up
    after SAVE_TIMEOUT, logged), never lost by loading older file. Polled, GUI never waits for files.
    """
    state = _reload
    if serial != state.serial:
        return  # finished or cancelled
    stopping = wctrl.stopping() | mctrl.stopping()  # both checked: each logs its own timeouts
    if stopping or (state.preset and saving_pending(state)):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(RELOAD_POLL_MS, lambda: poll_reload(serial))
        return
    complete_reload()


def saving_pending(state: ReloadState) -> bool:
    """Whether settings saving is still running (written at once), False once finished or gave up"""
    if not cfg.is_saving:
        return False
    now = monotonic()
    if not state.save_deadline:
        state.save_deadline = now + SAVE_TIMEOUT
        cfg.save(next_task=True)  # data saved by stopping modules written now
    elif now >= state.save_deadline:
        logger.error("USERDATA: saving not finished after %ss, continue anyway", SAVE_TIMEOUT)
        return False
    return True


def complete_reload(wait: bool = False):
    """Finish reload in progress (modules still stopping waited), then reload asked meanwhile, then callbacks"""
    state = _reload
    state.serial += 1
    wctrl.wait_stopping()
    mctrl.wait_stopping()
    failed = False
    try:
        finish_reload(state.preset, flush=wait)
    except Exception:
        logger.exception("RELOADING: failed")
        failed = True
    finally:
        state.running = False
        queued, state.queued = state.queued, None
    if failed:
        state.callbacks.clear()  # never run after a later unrelated reload
    if queued is not None:  # asked meanwhile: tried again even after failure
        reload(queued, wait)
        if state.running:
            return  # callbacks run once queued reload finished
    callbacks = state.callbacks[:]
    state.callbacks.clear()
    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.exception("RELOADING: error after reload")


def finish_reload(reload_preset: bool, flush: bool = True):
    """Reload steps once modules stopped

    Args:
        reload_preset: reload preset file.
        flush: wait unfinished saving before loading preset, done already (polled) by asynchronous reload.
    """
    # 2 reload user preset from file
    if reload_preset:
        if flush:
            cfg.flush()  # data saved by stopped modules (track info) written first, never lost by loading older file
        cfg.load_user()
        # Save new changes in case preset was edited externally; an unchanged preset is not rewritten, only
        # its modified time is set: the preset loaded last is the most recent one, loaded at next start
        cfg.save(0)
    # 3 widget positions of current screen setup
    sync_screen_layout()
    # 4 restart api
    api.restart()
    # 5 load modules
    load_modules()
    # 6 new objects out of garbage collection, replaced ones collected once idle
    park_collected()


def sync_screen_layout():
    """Restore widget positions saved for current screen setup (single, triple screen...)"""
    if not cfg.application["enable_layout_per_screen_setup"]:
        return
    from .template.setting_widget import WIDGET_FILENAME
    from .userfile.layout_profile import profile_filename, screen_key, sync_layout

    filename = profile_filename(cfg.path.settings, cfg.filename.setting)
    if sync_layout(cfg.user.setting, WIDGET_FILENAME, filename, screen_key()):
        cfg.save(0)


def load_modules():
    """Load modules, widgets (overlays kept off in safe mode)"""
    octrl.enable()  # 1 overlay control
    mctrl.start()  # 2 module
    if not safe_mode.state.enabled:
        wctrl.start()  # 3 widget
    kctrl.enable()  # 4 hotkey
    enable_servers()  # 5 remote control & web dashboard
    if not safe_mode.state.enabled:
        vroverlay().enable()  # 6 vr overlay
        enable_stream_overlay()  # 7 stream overlay
    elif imported(streamoverlay) and streamoverlay.running:  # 7 started from stream page: capture resumed
        streamoverlay.enable()


def enable_servers():
    """Start remote control & web dashboard if on in setting, stop them if off (module imported only if on)"""
    config = cfg.user.config
    if config["remote_control"]["enable_remote_control"] or imported(cmdserver):
        cmdserver.enable()
    if config["web_dashboard"]["enable_web_dashboard"] or imported(webdashboard):
        webdashboard.enable()


def enable_stream_overlay():
    """Start stream overlay if on in setting, stop it if off (module imported only if on)"""
    if cfg.user.config["stream_overlay"]["enable_stream_overlay"] or imported(streamoverlay):
        streamoverlay.enable()


def unload_modules(keep_servers: bool = False, wait: bool = True):
    """Unload modules, widgets

    Args:
        keep_servers: keep stream overlay, remote control & web dashboard servers listening (reload), only
            stream overlay capture stopped. load_modules then applies their setting: server stopped, or
            listening again only if its address changed. A server stopped then started again can find its
            port still held by its closed connections (Windows), and its clients would be disconnected.
        wait: wait until modules & widgets stopped, else only signalled (see ModuleControl.stop_all).
    """
    vroverlay().disable()  # 0 vr overlay
    if keep_servers:
        if imported(streamoverlay):
            streamoverlay.suspend()  # 0 stream overlay capture, started again by load_modules
    else:  # never started if not imported
        for server in (streamoverlay, cmdserver, webdashboard):  # 0 stream overlay, remote control, web dashboard
            if imported(server):
                server.disable()
    kctrl.disable()  # 1 hotkey
    if wait:
        wctrl.close()  # 2 widget
        mctrl.close()  # 3 module
    else:
        wctrl.stop_all()  # 2 widget
        mctrl.stop_all()  # 3 module
    octrl.disable(wait)  # 4 overlay control
