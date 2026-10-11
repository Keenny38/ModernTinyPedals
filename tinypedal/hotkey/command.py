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
Hotkey command function
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from functools import partial

from .. import app_signal, overlay_signal, realtime_state
from ..api_control import api
from ..const_file import ConfigType, FileExt
from ..module_control import mctrl, wctrl
from ..regex_pattern import CFG_DELTABEST_SOURCE, CHOICE_COMMON
from ..setting import cfg
from ..template.setting_module import MODULE_FILENAME
from ..template.setting_shortcuts import SHORTCUTS_PRESET
from ..template.setting_widget import WIDGET_FILENAME

logger = logging.getLogger(__name__)


def hotkey_module_toggle(module_name: str):
    """Command - module toggle"""
    mctrl.toggle(module_name)
    app_signal.refresh.emit(True)


def hotkey_widget_toggle(widget_name: str):
    """Command - widget toggle"""
    wctrl.toggle(widget_name)
    app_signal.refresh.emit(True)


def hotkey_overlay_visibility():
    """Command - overlay visibility"""
    realtime_state.hidden = not realtime_state.hidden
    overlay_signal.hidden.emit(realtime_state.hidden)


def hotkey_overlay_lock():
    """Command - overlay lock, unlocked: overlay edit mode (toolbar)"""
    cfg.overlay["fixed_position"] = not cfg.overlay["fixed_position"]
    cfg.save()
    overlay_signal.locked.emit(cfg.overlay["fixed_position"])
    from ..widget._edit_mode import follow_lock

    follow_lock(cfg.overlay["fixed_position"])


def hotkey_overlay_auto_hide():
    """Command - overlay auto hide"""
    cfg.overlay["auto_hide"] = not cfg.overlay["auto_hide"]
    cfg.save()


def hotkey_vr_compatibility():
    """Command - vr compatibility"""
    cfg.overlay["vr_compatibility"] = not cfg.overlay["vr_compatibility"]
    cfg.save()
    overlay_signal.iconify.emit(cfg.overlay["vr_compatibility"])


def hotkey_restart_api():
    """Command - restart api"""
    api.restart()
    app_signal.refresh.emit(True)


def hotkey_select_next_api():
    """Command - select next api"""
    api_name = api.name
    api_list = tuple(_api.NAME for _api in api.available)
    next_index = 0
    if api_name in api_list:
        next_index = api_list.index(api_name) + 1
        if next_index >= len(api_list):
            next_index = 0
    cfg.api_name = api_list[next_index]
    if cfg.telemetry["enable_api_selection_from_preset"]:
        save_type = ConfigType.SETTING
    else:
        save_type = ConfigType.CONFIG
    cfg.save(config_type=save_type)
    api.restart()
    app_signal.refresh.emit(True)


def hotkey_select_previous_api():
    """Command - select previous api"""
    api_name = api.name
    api_list = tuple(_api.NAME for _api in api.available)
    next_index = 0
    if api_name in api_list:
        next_index = api_list.index(api_name) - 1
        if next_index < 0:
            next_index = max(len(api_list) - 1, 0)
    cfg.api_name = api_list[next_index]
    if cfg.telemetry["enable_api_selection_from_preset"]:
        save_type = ConfigType.SETTING
    else:
        save_type = ConfigType.CONFIG
    cfg.save(config_type=save_type)
    api.restart()
    app_signal.refresh.emit(True)


def hotkey_load_preset(preset_key: str):
    """Command - load preset"""
    preset_name = cfg.user.shortcuts[preset_key]["preset"]
    if not preset_name:
        logger.error("USERDATA: preset not found, abort loading")
        return
    # Verify name (reserved names such as "brands" are not presets) & file
    filename = cfg.get_primary_preset_name(preset_name)
    if filename:
        cfg.set_next_to_load(filename)
        app_signal.reload.emit(True)
    else:
        logger.error("USERDATA: %s%s preset not found or invalid, abort loading", preset_name, FileExt.JSON)
        cfg.user.shortcuts[preset_key]["preset"] = ""
        cfg.save(config_type=ConfigType.SHORTCUTS)
        app_signal.refresh.emit(True)


def hotkey_reload_preset():
    """Command - reload preset"""
    app_signal.reload.emit(True)


def hotkey_load_next_preset():
    """Command - load next preset (in ascending order)"""
    preset_list = cfg.preset_files(by_date=False, reverse=False)
    loaded_preset = cfg.filename.setting[:-5]
    next_index = 0
    if loaded_preset in preset_list:
        next_index = preset_list.index(loaded_preset) + 1
        if next_index >= len(preset_list):
            next_index = 0
    cfg.set_next_to_load(f"{preset_list[next_index]}{FileExt.JSON}")
    app_signal.reload.emit(True)


def hotkey_load_previous_preset():
    """Command - load previous preset (in ascending order)"""
    preset_list = cfg.preset_files(by_date=False, reverse=False)
    loaded_preset = cfg.filename.setting[:-5]
    next_index = 0
    if loaded_preset in preset_list:
        next_index = preset_list.index(loaded_preset) - 1
        if next_index < 0:
            next_index = max(len(preset_list) - 1, 0)
    cfg.set_next_to_load(f"{preset_list[next_index]}{FileExt.JSON}")
    app_signal.reload.emit(True)


def hotkey_spectate_mode():
    """Command - spectate mode"""
    cfg.api["enable_player_index_override"] = not cfg.api["enable_player_index_override"]
    cfg.save()
    api.setup()  # override applied at once, as from the Spectate page
    app_signal.refresh.emit(True)


def spectate_place(offset: int):
    """Spectate driver at next (1) or previous (-1) overall place, wraps around

    Spectated driver is saved as slot id (api player_index), not as vehicle index: indexes
    shift when a car leaves the session.
    """
    if not cfg.api["enable_player_index_override"]:
        return
    total_vehicles = api.read.vehicle.total_vehicles()
    if total_vehicles < 1:
        return
    place = api.read.vehicle.place() + offset
    if place > total_vehicles:
        place = 1  # back to leader
    elif place < 1:
        place = total_vehicles
    for vehicle_index in range(total_vehicles):
        if api.read.vehicle.place(vehicle_index) == place:
            cfg.api["player_index"] = api.read.vehicle.slot_id(vehicle_index)
            api.setup()
            cfg.save()
            app_signal.refresh.emit(True)  # Spectate page follows
            return


def hotkey_spectate_next_driver():
    """Command - spectate next driver (overall position)"""
    spectate_place(1)


def hotkey_spectate_previous_driver():
    """Command - spectate previous driver (overall position)"""
    spectate_place(-1)


def open_director():
    """Director of the Broadcast Director page if open (its module is imported only by the page)"""
    module = sys.modules.get("tinypedal.ui.quick.director_backend")
    return module.active_director() if module is not None else None


def director_step(offset: int):
    """Car on air: next (1) or previous (-1) by place; page closed: game camera on next or previous car"""
    director = open_director()
    if director is not None:
        director.stepCar(offset)
        return
    from ..ui.game_rest import game_command

    resource = "/rest/watch/focusForward" if offset > 0 else "/rest/watch/focusBackward"
    threading.Thread(target=game_command, args=("PUT", resource), daemon=True, name="Game camera").start()


def hotkey_director_next_car():
    """Command - Broadcast Director: next car on air"""
    director_step(1)


def hotkey_director_previous_car():
    """Command - Broadcast Director: previous car on air"""
    director_step(-1)


def hotkey_director_auto():
    """Command - Broadcast Director: automatic cuts on or off (page open)"""
    director = open_director()
    if director is not None:
        director.toggleAuto()


def hotkey_director_lock():
    """Command - Broadcast Director: keep the car on air (director does not cut) or let go (page open)"""
    director = open_director()
    if director is not None:
        director.toggleLock()


def hotkey_director_take_best():
    """Command - Broadcast Director: cut to the best suggestion (page open)"""
    director = open_director()
    if director is not None:
        director.takeBest()


def hotkey_director_starting_grid():
    """Command - Broadcast Director: starting grid on the graphics, or hidden (page open)"""
    director = open_director()
    if director is not None:
        director.showOnDemand("grid")


def hotkey_director_event_card():
    """Command - Broadcast Director: event card on the graphics, or hidden (page open)"""
    director = open_director()
    if director is not None:
        director.showOnDemand("event")


def hotkey_director_classification():
    """Command - Broadcast Director: classification captured & shown, or hidden when shown (page open)"""
    director = open_director()
    if director is not None:
        if director.onDemand == "results":
            director.showOnDemand("results")
        else:
            director.captureResults()


def hotkey_director_championship():
    """Command - Broadcast Director: championship standings on the graphics, or hidden (page open)"""
    director = open_director()
    if director is not None:
        director.showOnDemand("champ")


def hotkey_director_hide_graphics():
    """Command - Broadcast Director: every graphic hidden, or shown again (page open)"""
    director = open_director()
    if director is not None:
        director.setGraphic("hidden", not director.graphicsSettings["hidden"])


def hotkey_director_next_layout():
    """Command - Broadcast Director: next layout preset of the graphics (page open)"""
    director = open_director()
    if director is not None:
        director.nextLayoutPreset()


def hotkey_pace_notes_playback():
    """Command - pace notes playback"""
    cfg.user.setting["pace_notes_playback"]["enable"] = not cfg.user.setting["pace_notes_playback"]["enable"]
    cfg.save()
    app_signal.refresh.emit(True)


def hotkey_show_main_window():
    """Command - show main window in front of the game, also hidden in tray or minimized"""
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        bring_to_front = getattr(widget, "bring_to_front", None)
        if callable(bring_to_front):
            bring_to_front()
            return


def hotkey_restart_application():
    """Command - restart application, through main window if any (open pages reopened)"""
    from PySide6.QtWidgets import QApplication

    from .. import loader  # local import, loader imports hotkey control (circular)

    for widget in QApplication.topLevelWidgets():
        restart_app = getattr(widget, "restart_app", None)
        if callable(restart_app):
            restart_app()
            return
    loader.restart()


def hotkey_quit_application():
    """Command - quit application"""
    app_signal.quitapp.emit(True)


def hotkey_cycle_deltabest_source():
    """Command - cycle deltabest source"""
    deltabest_options = cfg.user.setting["deltabest"]
    current_source = deltabest_options["deltabest_source"]
    available_sources = CHOICE_COMMON[CFG_DELTABEST_SOURCE]
    next_source = available_sources[0]
    break_next = False
    for name_source in available_sources:
        if name_source == current_source:
            break_next = True
            continue
        if break_next:
            next_source = name_source
            break
    deltabest_options["deltabest_source"] = next_source
    wctrl.reload("deltabest")
    cfg.save()


def hotkey_black_box_next_incident():
    """Command - Black box: show next older incident in the incident recorder"""
    from ..widget._black_box.recorder import request_next_incident

    request_next_incident()


def hotkey_black_box_open_incident_folder():
    """Command - Black box: open the folder incidents are saved in"""
    from ..widget._black_box.recorder import open_folder

    open_folder(os.path.join(cfg.path.config, "blackbox"))


# Define command list:
# 0 hotkey name, 1 hotkey function
COMMANDS_GENERAL = (
    ("overlay_visibility", hotkey_overlay_visibility),
    ("overlay_lock", hotkey_overlay_lock),
    ("overlay_auto_hide", hotkey_overlay_auto_hide),
    ("vr_compatibility", hotkey_vr_compatibility),
    ("restart_api", hotkey_restart_api),
    ("select_next_api", hotkey_select_next_api),
    ("select_previous_api", hotkey_select_previous_api),
    ("reload_preset", hotkey_reload_preset),
    ("load_next_preset", hotkey_load_next_preset),
    ("load_previous_preset", hotkey_load_previous_preset),
    ("spectate_mode", hotkey_spectate_mode),
    ("spectate_next_driver", hotkey_spectate_next_driver),
    ("spectate_previous_driver", hotkey_spectate_previous_driver),
    ("director_next_car", hotkey_director_next_car),
    ("director_previous_car", hotkey_director_previous_car),
    ("director_auto", hotkey_director_auto),
    ("director_take_best", hotkey_director_take_best),
    ("director_lock", hotkey_director_lock),
    ("director_starting_grid", hotkey_director_starting_grid),
    ("director_event_card", hotkey_director_event_card),
    ("director_classification", hotkey_director_classification),
    ("director_championship", hotkey_director_championship),
    ("director_hide_graphics", hotkey_director_hide_graphics),
    ("director_next_layout", hotkey_director_next_layout),
    ("pace_notes_playback", hotkey_pace_notes_playback),
    ("cycle_deltabest_source", hotkey_cycle_deltabest_source),
    ("black_box_next_incident", hotkey_black_box_next_incident),
    ("black_box_open_incident_folder", hotkey_black_box_open_incident_folder),
    ("show_main_window", hotkey_show_main_window),
    ("restart_application", hotkey_restart_application),
    ("quit_application", hotkey_quit_application),
)
COMMANDS_PRESET = tuple(
    (preset_key, partial(hotkey_load_preset, preset_key))
    for preset_key in SHORTCUTS_PRESET
)
COMMANDS_MODULE = tuple(
    (hotkey_name, partial(hotkey_module_toggle, hotkey_name))
    for hotkey_name in MODULE_FILENAME
)
COMMANDS_WIDGET = tuple(
    (f"widget_{hotkey_name}", partial(hotkey_widget_toggle, hotkey_name))
    for hotkey_name in WIDGET_FILENAME
)
