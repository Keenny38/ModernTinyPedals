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
Race calculator page: page tabs & base of the mixins of RaceBackend (page state & methods they share,
declared for type checking)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from contextlib import contextmanager
    from typing import Any

    from PySide6.QtCore import QTimer, SignalInstance

    from ...fuel_strategy import RaceState, Strategy, StrategyInput
    from ...game_rest import GameRequest
    from ...module_info import ConsumptionDataSet
    from ...process.team_usage import StintUsage
    from ...race_live import RivalTracker, StopCounter
    from ...race_live_data import GarageData, LiveValue
    from .background import BackgroundJobs
    from .models import DictListModel
    from .race_backend import RaceHost
    from .race_tyres import TyrePlan

TABS = ("fuel", "tyres", "team", "live")


class RaceBase:
    """Base of the mixins of RaceBackend (race_files, race_history, race_team_plan, race_tyre_tab, race_live_tab): page state &
    methods they use

    Declared for type checking only: state is set by RaceBackend.__init__, methods are defined by RaceBackend & its
    mixins (at run time a plain class: the page is the only QObject).
    """

    if TYPE_CHECKING:
        # Page state (set by RaceBackend.__init__ & its mixins)
        _apply_garage: bool
        _autosave_timer: QTimer
        _combo_loaded: str
        _dry_plan: tuple[StrategyInput | None, int]
        _garage_timer: QTimer
        _history_anchor: int
        _history_cache: dict[int, tuple[ConsumptionDataSet, dict]]
        _history_cursor: int
        _history_view: dict
        _live_parts: dict
        _live_rows: list[dict]
        _live_signature: tuple
        _plan_file_data: dict
        _plan_file_timer: QTimer
        _race_dismissed: bool
        _race_key: tuple | None
        _race_running: bool
        _recent: dict[str, list[str]]
        _recent_serial: int
        _rivals: dict
        _shown_combo: str
        _team_info: dict
        _team_timer: QTimer
        active: bool
        fill_source: str
        fuel_unit: str
        garage: GarageData
        garage_request: GameRequest
        garage_time: str
        headerChanged: SignalInstance
        history_added: str
        history_data: list[ConsumptionDataSet]
        history_file: tuple[str, str, str]
        history_model: DictListModel
        history_selection: set[int]
        history_serials: list[int]
        historyChanged: SignalInstance
        historySelectionChanged: SignalInstance
        historyViewChanged: SignalInstance
        host: RaceHost
        is_gallon: bool
        jobs: BackgroundJobs
        live_model: DictListModel
        live_source: bool
        live_status: str
        live_tip: str
        live_values: list[LiveValue]
        liveChanged: SignalInstance
        liveDataChanged: SignalInstance
        measured_index: int
        notesChanged: SignalInstance
        pit_menu_available: bool
        plan_setup: StrategyInput
        race_setup: StrategyInput
        race_state: RaceState | None
        race_strategy: Strategy
        race_tyre_changes: list[int]
        recentChanged: SignalInstance
        rival_tracker: RivalTracker
        rivalsChanged: SignalInstance
        save_failed: set[str]
        sections: dict
        sort_ascending: bool
        sort_column: int
        source_name: str
        stop_counter: StopCounter
        strategy: Strategy
        symbol_fuel: str
        tab: int
        team_capacity: float
        team_model: DictListModel
        team_request: GameRequest
        team_selection: set[int]
        team_status: str
        team_stints: list[StintUsage]
        teamChanged: SignalInstance
        teamInfoChanged: SignalInstance
        teamSelectionChanged: SignalInstance
        teamStatusChanged: SignalInstance
        tyre_request: GameRequest
        tyres: TyrePlan
        tyresChanged: SignalInstance
        undoChanged: SignalInstance
        unit_fuel: Callable[..., Any]
        values: dict

        # Methods of RaceBackend & its mixins
        def apply_live(self, keys: set[str] | None = None, followed: bool = False, filled: bool = False) -> int: ...
        def autosave_tyres(self): ...
        @contextmanager
        def batch(self) -> Iterator[None]: ...
        def fill_in_data(self, dataset: Sequence[ConsumptionDataSet], race_length: tuple[str, int] | None = None,
                         live: bool = True, skip: frozenset[str] | set[str] = frozenset()): ...
        def forget_recent(self, kind: str, filename_full: str): ...
        @property
        def game_data(self) -> bool: ...
        def game_data_refused(self) -> bool: ...
        def input_values(self) -> dict: ...
        def driver_label(self, number: int) -> str: ...
        def driver_short(self, number: int) -> str: ...
        def keep_team_names(self): ...
        def publish(self, name: str, value): ...
        def open_tyre_plan_file(self, filename_full: str) -> bool: ...
        def publish_live_data(self, values: list[LiveValue] | None = None): ...
        def refresh_garage(self, apply: bool = False): ...
        def refresh_history(self, dataset: Sequence[ConsumptionDataSet]): ...
        def remember_recent(self, kind: str, filename_full: str): ...
        def save_failure(self, kind: str, text: str): ...
        def save_success(self, kind: str): ...
        def set_fill_source(self, text: str): ...
        def set_measured_compound(self, index: int): ...
        def set_option(self, name: str, value) -> bool: ...
        def set_race_state(self, state: RaceState | None): ...
        def update_pit_menu_available(self): ...
        def setGameData(self, enabled: bool): ...
        def set_values(self, values: dict): ...
        def setInput(self, key: str, value: Any) -> Any: ...
        def strategy_input(self) -> StrategyInput: ...
        def time_text(self, seconds: float) -> str: ...
        def tyre_plan_changed(self, user_edit: bool = True): ...
        @staticmethod
        def unfollowed_live() -> set[str]: ...
        def update_input(self): ...
        def update_race_proposal(self): ...
