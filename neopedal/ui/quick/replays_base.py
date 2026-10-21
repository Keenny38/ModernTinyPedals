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
Game Replays page: base of the mixins of GameReplaysBackend (replays_list, replays_folder, replays_playback,
replays_incidents, replays_standings, replays_map): signals of the page (named by properties of every mixin) &
page state & methods they share (declared for type checking)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal

if TYPE_CHECKING:
    import threading

    from PySide6.QtCore import Property, QTimer

    from ...game_rest import GameRequest
    from ...process.game_info import CarInfo, GameReplay, Incident, Standing
    from .._common import BaseDialog
    from .game_camera import Command
    from .game_pictures import LogoCache
    from .models import DictListModel
    from .page_backend import PageBackend
    from .replays_common import ReplayAction
    from .track_path import TrackPath

    _HostBase = PageBackend
else:
    _HostBase = object


class ReplaysBase(_HostBase):
    """Base of the mixins of GameReplaysBackend: signals of the page & page state & methods they use

    Signals are declared here (properties of every mixin name them). State is set by GameReplaysBackend.__init__,
    methods are defined by GameReplaysBackend & its mixins (at run time a plain class: the page is the only QObject).
    """

    statusChanged = Signal()
    updatedChanged = Signal()
    replaysChanged = Signal()
    filterChanged = Signal()
    selectionChanged = Signal()  # replay picked (every click: results page follows it), not incidents or cars
    checkedChanged = Signal()  # replays selected (count & size)
    selectedProtectedChanged = Signal()
    incidentSelectionChanged = Signal()
    incidentsChanged = Signal()  # counts, player, car followed by camera
    timelineEndChanged = Signal()
    carCountChanged = Signal()
    energyColumnChanged = Signal()
    classFilterChanged = Signal()
    selectedCarChanged = Signal()
    classesChanged = Signal()
    playbackChanged = Signal()
    replayTimeChanged = Signal()
    cameraChanged = Signal()
    hudChanged = Signal()
    lapsChanged = Signal()
    settingsChanged = Signal()
    filesChanged = Signal()
    copyProgressChanged = Signal()  # progress of copy alone (often), filesChanged when copy starts & ends
    trashProgressChanged = Signal()  # progress of recycle bin moves alone, filesChanged when they start & end
    noticeChanged = Signal()
    mapChanged = Signal()
    mapLiveChanged = Signal()
    revisionChanged = Signal()

    if TYPE_CHECKING:
        # Page state (set by GameReplaysBackend.__init__)
        _window: BaseDialog
        prefix: str
        replays: list[GameReplay]
        replays_answered: bool
        pending_watch: str
        pending_action: ReplayAction | None
        action: ReplayAction | None
        action_deadline: float
        action_generation: int
        state_generation: int
        action_after: float
        play_command: Command | None
        playing: str
        play_sent: Command | None
        results_links: dict[str, str]
        folder: str
        temp: list[str]
        protected: set[str]
        state: str
        last_session: bool
        incidents: tuple[Incident, ...]
        cars: dict[str, CarInfo]
        standings: list[Standing]
        class_list: list[dict]
        focus: int
        camera: tuple[str, str]
        trackside_choice: str
        hud: dict[str, bool]
        session_end: float
        session_name: str
        live_time: float
        lap_starts: dict[int, dict[int, float]]
        replay_time: float
        replay_rate: float
        time_received: float
        last_command: str
        rewatching: bool
        seconds_before: int
        session_filter: int
        search_words: list[str]
        sort: str
        incident_filter: int
        mine_only: bool
        driver_filter: str
        class_filter: str
        panel: int
        selected_replay: str
        checked: set[str]
        selected_incident: str
        selected_car: str
        copy_progress: float
        _folder_info: tuple[tuple, dict] | None
        checked_summary: str
        selected_protected: bool
        _counts: dict[str, int]
        _incident_view: tuple | None
        _incident_counts: tuple[tuple, dict[str, int]]
        _markers_from: tuple | None
        _last_incident: tuple[tuple, float]
        timeline_end: float
        car_count: int
        has_energy: bool
        _lap_view: tuple | None
        copy_kind: str
        copy_cancel: threading.Event
        trash_progress: float
        trash_kind: str
        trash_kept: int
        trash_cancel: threading.Event
        map_track: str | None
        map_center: list[tuple[float, float, float]]
        map_pit: list[tuple[float, float, float]]
        meters_per_pixel: float
        revision: int
        _shown: bool
        _replays_model: DictListModel
        _incidents_model: DictListModel
        _markers_model: DictListModel
        _chips_model: DictListModel
        _standings_model: DictListModel
        _map_model: DictListModel
        track_path: TrackPath | None
        _car_tracks: dict[int, tuple]
        _direction: float
        map_live: dict[str, list[float]]
        _live_timer: QTimer
        logos: LogoCache
        request_copy: GameRequest
        request_trash: GameRequest
        _timer: QTimer
        focusedDriver: Property

        # Methods of GameReplaysBackend & its mixins
        def ask_replays(self): ...
        def chosen_replays(self, key: str) -> list[GameReplay]: ...
        def focused_slot(self) -> int: ...
        def incident_counts(self) -> dict[str, int]: ...
        def notify(self, text: str, error: bool = False): ...
        def refresh_state(self): ...
        def replay_folder(self) -> str: ...
        def replay_of(self, key: str) -> GameReplay | None: ...
        def save_settings(self): ...
        def send(self, *commands: Command): ...
        def temp_size(self) -> str: ...
        def update_live_timer(self): ...
        def update_map_cars(self): ...
        def update_replays(self): ...
        def update_selected_protected(self): ...
        def update_standings(self): ...
