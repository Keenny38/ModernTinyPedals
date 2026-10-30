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
Lap viewer lap loading (mixin of LapViewerBackend): official circuit from game REST API, track limits
guessed in background (cached), shown laps read & prepared in background, laps of other circuits, loaded laps
released while page is hidden
"""

from __future__ import annotations

import html
import json
import logging
import os
import threading

from PySide6.QtCore import (
    Slot,
)

from ...const_api import API_LMU_CONFIG
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile import track_geometry, write_json
from ...userfile.circuit_match import same_imported_circuit
from ...userfile.lap_cache import (
    load_cached_lap,
)
from ...userfile.lap_geometry import (
    Yielder,
)
from ...userfile.lap_library import track_of_folder
from ...userfile.lap_offset import is_recorded
from ...userfile.telemetry_lap import (
    LapData,
    forget_increasing,
    is_valid_name,
    lap_timestamp_of,
    median_sector_bounds,
    same_circuit,
)
from .. import lap_viewer
from ..lap_viewer import (
    CHANNEL_MAP,
    LapEntry,
    PlotLap,
    lap_color,
    lap_label,
)
from . import lap_map
from .formatting import day_month
from .lap_base import (
    BackendBase,
    keys_match,
)
from .lap_map_view import (
    prepare_placements,
)
from .lap_panels import CHART_RETRIES
from .lines import (
    VertexStore,
    Vertices,
)
from .trace_data import TraceData, align_laps

logger = logging.getLogger(__name__)

LIMITS_FOLDER = ".track_limits"  # track limits cache, in telemetry folder (hidden: not a track)
LIMITS_LAPS = 40  # newest clean laps used to guess track limits


def read_limits_cache(cache: str, names: list[str], base_key: str) -> tuple | None:
    """Track limits, source & sector bounds saved for these laps, base line & algorithm (thread job), None if not
    saved for them (computed again)"""
    try:
        with open(cache, encoding="utf-8") as file:
            saved = json.load(file)
        if not (isinstance(saved, dict) and saved.get("laps") == names and "sectors" in saved  # damaged: not a dict
                and saved.get("base", "lap") == base_key
                and saved.get("version") == lap_map.LIMITS_VERSION):  # older algorithm: computed again
            return None
        limits = None
        if saved.get("left"):
            limits = lap_map.TrackLimits(*(
                lap_map.MapLine([p[0] for p in saved[side]], [p[1] for p in saved[side]], [p[2] for p in saved[side]])
                for side in ("left", "right")))
        return limits, str(saved.get("source", "estimated")), [float(value) for value in saved["sectors"]][:2]
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        return None


def circuit_name(info: dict, path: str) -> str:
    """Track name telling circuits apart: game track name of lap recorded by app, track of track folder
    ("<track> - <class>") of lap without lap info, empty if unknown (imported log: venue name, not game name)"""
    if "combo" in info:
        return str(info.get("track", ""))
    if not (info.get("track") or info.get("track_length")):
        return track_of_folder(path)
    return ""


class LapLoading(BackendBase):
    """Official circuit, track limits & lap loading of lap viewer page"""

    # Official circuit: circuit path (game driving line) & pit lane from game REST API (saved), base of lap placement
    def track_title(self, track: str) -> str:
        """Game track name of track folder (lap info), else folder name without class"""
        for entry in self.entries:
            if entry.info.get("track"):
                return str(entry.info["track"])
        return track.rsplit(" - ", 1)[0]

    def start_geometry(self, track: str):
        """Official circuit of track: saved file, else asked to game in background (once per session)

        Saved circuit checked in background: dropped if best lap no longer lies along it (another layout), fetched
        again if game has another version of its layout (or file saved without version).
        """
        if track == self._geometry_track:
            return
        self._geometry_track = track
        saved = self._geometry = track_geometry.load_geometry(self.folder, track) if track else None
        setting = cfg.user.setting.get(API_LMU_CONFIG, {}) if hasattr(cfg.user, "setting") else {}
        ask = bool(track) and track not in self._geometry_tried and bool(setting.get("enable_restapi_access", True))
        clean = [entry for entry in self.entries if entry.file.valid and entry.info.get("kind", "lap") == "lap"]
        if not clean or (saved is None and not ask):
            return
        if ask:
            self._geometry_tried.add(track)
        best = min(clean, key=lambda entry: entry.file.lap_time or float("inf"))
        host, port = str(setting.get("url_host", "localhost")), int(setting.get("url_port", 6397))
        title, folder = self.track_title(track), self.folder

        def best_positions() -> tuple[list[tuple[float, float]], float]:
            """Positions & track length of best lap (empty if unreadable)"""
            try:
                lap = load_cached_lap(folder, best.file.path)
            except (OSError, ValueError):
                return [], 0.0
            found = lap_map.map_line(lap)
            positions = list(zip(found.xs, found.ys)) if found is not None else []
            return positions, float(best.info.get("track_length") or (lap.distance[-1] if len(lap) else 0.0))

        def fetching() -> tuple:
            """(circuit to use) : saved one if still right, else from game, None if none"""
            positions, length = best_positions() if saved is not None else ([], 0.0)
            fitting = saved is not None and track_geometry.fits(saved, positions)
            tracks = track_geometry.rest_get(host, port, "/rest/race/track") if ask else None
            if not isinstance(tracks, list):  # game not running (lap file read only if game answers)
                return (saved if fitting else None,)
            if fitting and saved is not None and saved.name in track_geometry.layout_names(tracks, saved.layout):
                return (saved,)  # current game version
            if saved is None:
                positions, length = best_positions()
            found = track_geometry.fetch_geometry(host, port, title, positions, length, tracks)
            return (found if found is not None else saved if fitting else None,)

        def fetched(result):
            if not isinstance(result, tuple) or result[0] is saved:  # job failed or saved circuit still right
                return
            geometry = result[0]
            if geometry is not None:
                track_geometry.save_geometry(self.folder, track, geometry)  # kept even if another track is shown
            if track != self._track:
                return
            before = self.base_key()
            self._geometry = geometry
            if self.base_key() == before:  # same circuit
                return
            self._limits_track = ""  # placement measured from another base line: track limits again
            self.start_limits(track)
            self.place_laps()  # placement on map measured in background, charts & map built again then
            if geometry is not None:
                self.set_status(tr("Official circuit map received from game"))
            else:
                logger.info("LAP VIEWER: saved official circuit of %s does not fit recorded laps", track)

        self.run_job("official circuit", fetching, fetched)

    def official_base(self, length: float = 0.0) -> lap_map.MapLine | None:
        """Official circuit path (game driving line, not track center) from start line, distances scaled to lap length,
        None if unknown"""
        geometry = self._geometry
        if geometry is None:
            return None
        key = (geometry, length or geometry.length)
        if self._official_line and keys_match(self._official_line[0], key):
            return self._official_line[1]
        line = lap_map.geometry_line(geometry.center, geometry.start, length or geometry.length)
        self._official_line = (key, line)
        return line

    def base_key(self) -> str:
        """What lap placement is measured from (saved track limits & lap placements valid only for the same): official
        circuit layout, game version, points & start line (nearest points of laps change with them), else lap line"""
        geometry = self._geometry
        if geometry is None:
            return "lap"
        start = "{:.1f},{:.1f}".format(*geometry.start) if geometry.start else "-"
        return f"official|{geometry.layout}|{geometry.name}|{len(geometry.center)}|{start}"

    # Track limits: guessed in background from every clean lap of the track, cached in telemetry folder
    def limits_cache_path(self, track: str) -> str:
        return os.path.join(self.folder, LIMITS_FOLDER, f"{track}.json")

    def limits_parts_folder(self, track: str) -> str:
        """Per lap placement around base line (track limits): only new laps computed when laps change"""
        return os.path.join(self.folder, LIMITS_FOLDER, f"{track}.laps")

    def start_limits(self, track: str):
        """Track limits of track: from cache file if laps did not change (read in a thread), else computed in worker
        process"""
        if track == self._limits_track and (self._limits is not None or self._limits_job is not None
                                            or self._limits_reading):
            return
        self._limits_track = track
        self._limits = None
        self._limits_source = ""
        self._track_sectors = []
        self._limits_reading = False
        self._limits_token += 1  # cache read for a former call ignored
        clean = [entry for entry in self.entries
                 if entry.file.valid and entry.info.get("kind", "lap") not in ("out", "in")][:LIMITS_LAPS]
        if not track or len(clean) < lap_map.LIMITS_MIN_LAPS:
            return
        names = sorted(entry.file.filename for entry in clean)
        cache = self.limits_cache_path(track)
        base_key = self.base_key()
        best = min(clean, key=lambda entry: entry.file.lap_time or float("inf"))
        paths = [best.file.path] + [entry.file.path for entry in clean if entry is not best]
        official = self.official_base(float(best.info.get("track_length") or 0.0))
        args = (self.folder, self.limits_parts_folder(track), os.path.join(self.folder, track), paths, official,
                base_key)
        job = {"track": track, "names": names, "cache": cache, "base": base_key, "args": args}
        token = self._limits_token

        def read(found):
            if token != self._limits_token:
                return  # another track (or base line) since
            self._limits_reading = False
            if found is None:  # laps, base line or algorithm changed: computed again
                self.start_limits_job(job)
                return
            self._limits, self._limits_source, self._track_sectors = found
            if self.data.laps and self._loader is None:  # laps loading: placed with these once loaded
                self.apply_track_sectors()
                self.place_laps()
            self.mapChanged.emit()

        self._limits_reading = True
        self.run_job("track limits cache", lambda: read_limits_cache(cache, names, base_key), read)

    def save_limits(self, job: dict, limits: lap_map.TrackLimits | None):
        """Track limits saved in cache file (used while laps of track stay the same), written in background"""
        saved: dict = {"laps": job["names"], "source": self._limits_source, "sectors": list(self._track_sectors),
                       "base": job["base"], "version": lap_map.LIMITS_VERSION}
        target = job["cache"]

        def saving():
            if limits is not None:
                for side, line in (("left", limits.left), ("right", limits.right)):
                    saved[side] = [[round(d, 2), round(x, 2), round(y, 2)]
                                   for d, x, y in zip(line.distances, line.xs, line.ys)]
            try:  # written whole (temporary file renamed): never read half written
                os.makedirs(os.path.dirname(target), exist_ok=True)
                write_json(target, saved, raise_error=True)
            except OSError as error:
                logger.warning("LAP VIEWER: unable to save track limits: %s", error)

        self.run_job("track limits cache", saving, lambda _: None)

    def apply_track_sectors(self):
        """Sector lines: median of every lap of track (game sector times), else of laps shown"""
        bounds = self._track_sectors or median_sector_bounds([lap.data for lap in self.data.laps])
        if len(bounds) == 2:
            self.data.set_sector_lines(bounds)

    # Lap loading
    def read_lap(self, path: str) -> LapData | None:
        if not path:
            return None
        if path in self._lap_cache:
            self._lap_cache[path] = self._lap_cache.pop(path)  # most recently used last
            return self._lap_cache[path]
        try:
            lap = self.load_lap_file(path)
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to load %s: %s", path, error)
            self.set_status(trm(f"Unable to load lap: {error}"))
            lap = None
        except Exception as error:  # unexpected: lap flagged unreadable, page goes on
            logger.exception("LAP VIEWER: unable to load %s", path)
            self.set_status(trm(f"Unable to load lap: {error}"))
            lap = None
        self.store_lap(path, lap)
        return lap

    def store_lap(self, path: str, lap: LapData | None):
        """Keep loaded lap, oldest laps forgotten over cache size (a lap takes several MB in memory)"""
        self._lap_cache[path] = lap
        try:
            self._cache_mtime[path] = os.path.getmtime(path)
        except OSError:
            self._cache_mtime.pop(path, None)
        limit = max(lap_viewer.LAP_CACHE_SIZE, len(self.checked) + 2)  # shown laps, main & anchor laps
        while len(self._lap_cache) > limit:
            oldest = next(iter(self._lap_cache))
            self._lap_cache.pop(oldest)
            self._cache_mtime.pop(oldest, None)

    def load_in_background(self, paths: list[str]):
        """Read laps in a thread, charts updated once all are loaded (page stays responsive), shape checks &
        alignments of laps about to be shown measured there too (see prepare_laps)"""
        if self._loader is not None:
            return  # current selection shown once loaded (check_background_load)
        plan, self._load_plan = self._load_plan, None
        results: dict[str, LapData | None] = {}
        prepared: list[tuple[dict, dict]] = []
        charts: list[tuple[TraceData, dict[str, Vertices], dict]] = []
        cached = {path: self._lap_cache.get(path) for path in (plan[0] + list(plan[1:3]) if plan else ())}
        checks, aligned = dict(self._shape_checks), self.data.aligned_snapshot()
        chart = self.chart_plan() if plan is not None else None

        def loading():
            for path in paths:
                try:
                    results[path] = self.load_lap_file(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    results[path] = None
                except Exception:  # any other failure: lap flagged unreadable, never loaded again in a loop
                    logger.exception("LAP VIEWER: unable to load %s", path)
                    results[path] = None
            if plan is not None:
                try:
                    prepared.append(self.prepare_laps(plan, {**cached, **results}, checks, aligned))
                except Exception:  # measured again when shown
                    logger.exception("LAP VIEWER: unable to compare laps")
            if plan is not None and chart is not None and prepared:
                try:
                    charts.append(self.prepare_chart(chart, plan, {**cached, **results}, prepared[0], checks))
                except Exception:  # built again when shown
                    logger.exception("LAP VIEWER: unable to prepare charts")

        self._prepared_laps = prepared
        self._prepared_charts = charts
        self._preparing = plan[:4] if plan is not None else None
        self._loaded = results
        self._loaded_paths = set(paths)
        self._load_total = len(paths)
        self._load_message = self._status
        self._loader = threading.Thread(target=loading, daemon=True, name="Lap viewer loading")
        self._loader.start()
        self._load_timer.start()
        if paths:
            self.set_status(trm(f"Loading {len(paths)} lap{'s' if len(paths) > 1 else ''}…"), False)
        else:  # laps loaded: imported laps compared in background
            self.set_status(tr("Reading laps…"), False)

    @Slot()
    def check_background_load(self):
        """Background loading progress, once finished: laps kept, charts updated"""
        if self._loader is None:
            return
        if self._loader.is_alive():
            if self._load_total > 1:
                self.set_status(trm(f"Loading laps: {len(self._loaded)}/{self._load_total}"), False)
            return
        self._load_timer.stop()
        self._loader = None
        for path in self._loaded_paths - self._loaded.keys():  # loading stopped before it: unreadable
            self._loaded[path] = None
        failed = [path for path, lap in self._loaded.items() if lap is None]
        for path, lap in self._loaded.items():
            self.store_lap(path, lap)
        self._failed.update(failed)  # not read again by load_laps below (read again once checked again, refresh)
        self._loaded = {}
        prepared, self._prepared_laps = self._prepared_laps, []
        for checks, aligned in prepared:  # used by load_laps below if laps are still the same
            self._prepared_checks.update(checks)  # laps found on another circuit told by drop_other_shapes
            self.data.keep_aligned(aligned)
            self._prepared = self._preparing
        charts, self._prepared_charts = self._prepared_charts, []
        self._prepared_chart = charts[0] if charts else None  # adopted by load_laps below if laps are the same
        if failed:
            self.set_status(trm(f"Unable to load lap: {html.escape(os.path.basename(failed[0]))}"))
        else:  # message shown before loading (new lap) shown again
            self.set_status(self._load_message)
        if self._pending_delete:  # deleted while loading: laps list & charts updated by deletion if any lap moved
            paths, self._pending_delete = self._pending_delete, []
            if self.apply_delete(paths, pending=True):
                return
        self.load_laps()

    def is_loading(self) -> bool:
        """Laps or lap infos loading, charts built, importing or exporting in background"""
        return (self._loader is not None or self._exports.exporting() or self._exports.importing() or self.reading_infos()
                or bool(self._chart_afters) or self._placing > 0 or self.map_pending() or self._limits_reading
                or self._file_actions > 0)

    def map_pending(self) -> bool:
        """Track map built, its shapes sized for map scale being built in background (shown once ready)"""
        return bool(self._map) and not self._band_cache and any(
            generation == self._band_generation for generation, _ in self._prefetching)

    def reading_infos(self) -> bool:
        """Lap infos of a track (track shown once read) or of new lap files being read in background"""
        return bool(self._infos_track) or self._infos_reading

    def assign_colors(self, ordered: list[str]) -> dict[str, int]:
        """Color index of each shown lap: kept while lap stays shown, lowest free index for new laps"""
        slots = {path: slot for path, slot in self._color_slots.items() if path in ordered}
        used = set(slots.values())
        for path in ordered:
            if path not in slots:
                slot = next(index for index in range(len(ordered) + len(used) + 1) if index not in used)
                slots[path] = slot
                used.add(slot)
        self._color_slots = slots
        return slots

    def load_laps(self):
        paths = self.ordered_checked()
        track_paths = {entry.file.path for entry in self.entries}
        if paths and self.reference_key not in paths:  # lap of current track first (added laps listed on top)
            self.reference_key = next((path for path in paths if path in track_paths), paths[0])
        paths = self.drop_other_circuits(paths)
        if paths and self.reference_key not in paths:  # reference lap of another circuit than shown track
            self.reference_key = next((path for path in paths if path in track_paths), paths[0])
        ordered = sorted(paths, key=lambda path: path != self.reference_key)  # reference first
        for path in ordered:  # unreadable lap checked again: read again (file may be readable now, antivirus lock)
            if path not in self._failed and path in self._lap_cache and self._lap_cache[path] is None:
                del self._lap_cache[path]
        main_path = self.main_circuit()[1]
        anchor_path = self.track_anchor(ordered)
        needed = [*ordered, *(path for path in (main_path, anchor_path) if path and path not in ordered)]
        missing = [path for path in needed if path not in self._lap_cache]
        prepared = self._prepared == (ordered, main_path, anchor_path, self.reference_key)  # else picked meanwhile
        self._prepared = None
        # Charts prepared by loading thread on trace data changed meanwhile (settings, placement): prepared again
        stale = (prepared and self._prepared_chart is not None and self._load_retries < CHART_RETRIES
                 and self._prepared_chart[0].snapshot_of != self.data.version)
        if stale:
            self._prepared_chart = None
        if (self._loader is not None or len(missing) >= lap_viewer.BACKGROUND_LOAD_COUNT
                or (not prepared and self.needs_preparing(ordered, main_path, anchor_path))
                or ((not prepared or stale) and self.load_work(ordered) >= lap_viewer.BACKGROUND_CHART_SAMPLES)):
            self._load_retries = self._load_retries + 1 if stale else 0
            self.update_list_state(self.data.laps)
            stamps = {path: self.shape_stamps(main_path, path) for path in ordered}
            self._load_plan = (ordered, main_path, anchor_path, self.reference_key, stamps)
            self.load_in_background(missing)
            return
        self._load_retries = 0
        prepared_chart, self._prepared_chart = self._prepared_chart, None
        entries = {entry.file.path: entry for entry in self.all_entries()}
        loaded = self.drop_other_shapes([(path, self.read_lap(path)) for path in ordered])
        if self._pending_switch is not None:  # laps just added all driven on another circuit: shown instead
            switch, self._pending_switch = self._pending_switch, None
            self.switch_circuit(*switch)
            return
        paths = [path for path in paths if path in self.checked]
        self._failed = {path for path, lap_data in loaded if lap_data is None}
        if self.reference_key in self._failed:  # first lap read is reference (star, compared laps, exports, saved)
            self.reference_key = next((path for path, lap_data in loaded if lap_data is not None), self.reference_key)
        self.save_selection(paths)
        slots = self.assign_colors([path for path, lap_data in loaded if lap_data is not None])
        laps = [
            PlotLap(path, self.entry_label(entries.get(path), path), lap_data, lap_color(slots[path]),
                    self.is_clean(entries.get(path), path, lap_data))
            for path, lap_data in loaded if lap_data is not None
        ]
        self.build_labels(laps)
        anchor_data = self.read_lap(anchor_path) if anchor_path and anchor_path in self._lap_cache else None
        anchor = (anchor_path, anchor_data) if anchor_data is not None else None
        placed = True
        if prepared_chart is not None and self.data.adopt_laps(prepared_chart[0], laps, self.reference_key, anchor):
            for key, vertices in prepared_chart[1].items():  # series built by loading thread
                if not VertexStore.has(key):
                    VertexStore.set(key, vertices)
            self.keep_placements(prepared_chart[2])  # lap placement on map measured there too
            placed = self.placements_current(prepared_chart[2])
        else:
            self.data.set_laps(laps, self.reference_key, anchor)
        self.apply_track_sectors()
        self.update_list_state(laps)
        self._warning = self.laps_warning(laps)
        if placed:
            self.rebuild_chart()  # chart zoom shown again once built (laps released while page was hidden)
        else:  # track limits or official circuit received meanwhile: placement measured again in background first
            self.place_laps()

    def load_work(self, ordered: list[str]) -> int:
        """Samples of chart series showing laps (all loaded) computes (estimate): every series of laps not shown yet,
        of every lap if reference lap changes (delta, scale)"""
        reference = self.data.reference
        same = reference is not None and bool(ordered) and reference.key == ordered[0]
        shown = {lap.key for lap in self.data.laps}
        series = self.series_count() + 1  # delta measured too
        return sum(len(lap_data) * series for path in ordered for lap_data in (self._lap_cache.get(path),)
                   if lap_data is not None and (not same or path not in shown))

    def series_count(self) -> int:
        """Series drawn for each lap (combined panels: one per part)"""
        return sum(len(channel.parts) or 1 for column in self.visible
                   for channel in (CHANNEL_MAP.get(column),) if channel is not None)

    def drop_other_circuits(self, paths: list[str]) -> list[str]:
        """Checked laps driven on another circuit than main lap unchecked (told in status line): never drawn
        nor compared with it (added lap of another track, laps kept checked when track changes)"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        main = self.main_circuit()
        others = [path for path in paths if self.other_circuit(main, infos.get(path, {}), path)]
        if not others:
            return paths
        self.checked.difference_update(others)
        self.set_status(trm(f"Laps from another circuit, not compared with reference lap: "
                            f"{', '.join(self.circuit_names(others, infos))}"))
        return [path for path in paths if path not in others]

    def main_circuit(self) -> tuple[dict, str]:
        """Lap info & path of main lap, every shown lap must be driven on its circuit: reference lap if a lap of shown
        track, else newest lap of track, else reference lap (only added laps)"""
        entries = {entry.file.path: entry for entry in self.entries}
        entry = entries.get(self.reference_key) or (self.entries[0] if self.entries else None)
        if entry is not None:
            return entry.info, entry.file.path
        infos = {entry.file.path: entry.info for entry in self.external}
        key = self.reference_key
        if self._added_batch is not None and key in self._added_batch[0]:  # laps just added not checked yet:
            # shown lap added before is main lap
            key = next((entry.file.path for entry in self.external
                        if entry.file.path in self.checked and entry.file.path not in self._added_batch[0]), key)
        return infos.get(key, {}), key

    def other_circuit(self, main: tuple[dict, str], info: dict, path: str) -> bool:
        """Whether lap (lap info & path) was driven on another circuit than main lap: game track name & length (see
        same_circuit), else track of track folder ("<track> - <class>") of laps without lap info, imported lap found
        on another circuit from its telemetry once loaded (see drop_other_shapes)"""
        main_info, main_path = main
        if path == main_path:
            return False
        if not same_circuit(LapData("", {}, main_info), LapData("", {}, info)):
            return True
        names = [circuit_name(main_info, main_path), circuit_name(info, path)]
        if all(names) and names[0].casefold() != names[1].casefold():
            return True
        checked = self._shape_checks.get((main_path, path))
        return checked is not None and checked[1] is False and checked[0] == self.shape_stamps(main_path, path)

    def lap_stamp(self, path: str) -> float:
        """File time of lap (loaded lap: time of file read), -1 if no file"""
        stamp = self._cache_mtime.get(path)
        if stamp is not None:
            return stamp
        try:
            return os.path.getmtime(path)
        except OSError:
            return -1.0

    def shape_stamps(self, main_path: str, path: str) -> tuple[float, float]:
        """File stamps of main lap & lap a shape check is valid for (see drop_other_shapes)"""
        return self.lap_stamp(main_path), self.lap_stamp(path)

    @staticmethod
    def shape_check(main: LapData, lap_data: LapData, path: str) -> bool | None:
        """Whether lap was driven on circuit of main lap from telemetry (see same_imported_circuit), None if unknown
        or if its telemetry cannot be compared (damaged log: logged, lap kept)"""
        if is_recorded(main) and is_recorded(lap_data):
            return None
        try:
            return same_imported_circuit(main, lap_data)
        except Exception:  # unexpected values in an imported log: lap kept, page never stuck
            logger.exception("LAP VIEWER: unable to compare circuit of %s", path)
            return None

    @classmethod
    def prepare_laps(cls, plan: tuple, laps: dict[str, LapData | None],
                     checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]],
                     aligned: dict) -> tuple[dict, dict]:
        """Shape checks & alignments of laps about to be shown measured in background thread (slow on a long track:
        page stays responsive), same as drop_other_shapes & TraceData.set_laps then find them done: new shape checks
        & aligned laps (see align_laps)

        plan: shown lap paths (reference first), main lap path, anchor lap path, reference lap path, file stamps of
        each shown lap shape check (see shape_stamps). Never touches page state (thread).
        """
        ordered, main_path, anchor_path, reference_key, stamps = plan
        main = laps.get(main_path)
        found = {}
        others = set()
        for path in ordered:
            lap_data = laps.get(path)
            if main is None or lap_data is None or path == main_path:
                continue
            checked = checks.get((main_path, path))
            if checked is None or checked[0] != stamps[path]:
                checked = found[(main_path, path)] = (stamps[path], cls.shape_check(main, lap_data, path))
            if checked[1] is False:
                others.add(path)
        shown = [(path, lap_data) for path in ordered if path not in others
                 for lap_data in (laps.get(path),) if lap_data is not None]
        anchor_data = laps.get(anchor_path) if anchor_path else None
        anchor = (anchor_path, anchor_data) if anchor_data is not None else None
        return found, align_laps(shown, reference_key, anchor, aligned)[0]

    def chart_plan(self) -> tuple:
        """What loading thread needs to prepare charts of laps about to be shown (see prepare_chart), read on page
        thread: trace data snapshot, lap list entries, visible channels, envelope shown, lap color placeholder"""
        placing = (self._limits, self._geometry, self._official_line, dict(self._line_cache))  # see prepare_placements
        return (self.data.snapshot(), {entry.file.path: entry for entry in self.all_entries()}, list(self.visible),
                self._envelope, lap_color(0), placing, self._dashboard.columns())

    def prepare_chart(self, chart: tuple, plan: tuple, laps: dict[str, LapData | None], prepared: tuple[dict, dict],
                      checks: dict) -> tuple[TraceData, dict[str, Vertices], dict]:
        """Laps about to be shown set on a trace data snapshot & vertices of their chart series built (loading
        thread, see prepare_laps): adopted by load_laps if the same laps are shown, never touches page state

        checks: shape checks known when loading started (copy), prepared: new shape checks & aligned laps.
        """
        data, entries, visible, envelope, color, placing, dashboard = chart
        ordered, main_path, anchor_path, reference_key, _ = plan
        found = {**checks, **prepared[0]}
        shown = [
            PlotLap(path, "", lap_data, color, self.is_clean(entries.get(path), path, lap_data))
            for path in ordered for lap_data in (laps.get(path),) if lap_data is not None
            and (path == main_path or (found.get((main_path, path)) or ((), None))[1] is not False)
        ]
        anchor_data = laps.get(anchor_path) if anchor_path else None
        data.keep_aligned(prepared[1])
        data.prepare_laps(shown, reference_key, (anchor_path, anchor_data) if anchor_data is not None else None)
        vertices = self.chart_vertices(data, visible, envelope)
        data.warm(dashboard, Yielder())  # simple view values read at cursor
        return data, vertices, prepare_placements(data.laps, data.reference, *placing)

    def needs_preparing(self, ordered: list[str], main_path: str, anchor_path: str) -> bool:
        """Whether showing laps (all loaded) measures shape checks or lap offsets of imported laps long enough to
        freeze the page (long track, many laps): done in background first (see prepare_laps)"""
        cache = self._lap_cache
        main = cache.get(main_path)
        shown = []
        work = 0
        for path in ordered:
            lap_data = cache.get(path)
            if lap_data is None:
                continue
            if main is not None and path != main_path and not (is_recorded(main) and is_recorded(lap_data)):
                checked = self._shape_checks.get((main_path, path))
                if checked is None or checked[0] != self.shape_stamps(main_path, path):
                    work += len(lap_data)
                elif checked[1] is False:
                    continue
            shown.append((path, lap_data))
        anchor_data = cache.get(anchor_path) if anchor_path else None
        anchor = (anchor_path, anchor_data) if anchor_data is not None else None
        work += self.data.alignment_work(shown, self.reference_key, anchor)
        return work >= lap_viewer.BACKGROUND_PREPARE_SAMPLES

    def track_anchor(self, paths: list[str]) -> str:
        """Lap recorded by the app an imported reference lap is aligned on when no shown lap was recorded by the app
        (see TraceData.aligned_laps): main lap, else newest lap of track recorded by the app, empty if not needed"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        if "combo" in infos.get(self.reference_key, {"combo": ""}) or any(
                "combo" in infos.get(path, {}) for path in paths):
            return ""
        main_path = self.main_circuit()[1]
        candidates = [main_path, *(entry.file.path for entry in self.entries)]
        return next((path for path in candidates if path != self.reference_key and path not in self._failed
                     and "combo" in infos.get(path, {})), "")

    def drop_other_shapes(self, loaded: list[tuple[str, LapData | None]]) -> list[tuple[str, LapData | None]]:
        """Loaded laps without imported laps found driven on another circuit than main lap from their telemetry
        (driven line, else speed trace, see same_imported_circuit): added laps no longer listed, laps of track
        unchecked (told in status line like laps of another circuit)"""
        main_path = self.main_circuit()[1]
        batch, self._added_batch = self._added_batch, None
        main = dict(loaded).get(main_path) or self.read_lap(main_path)
        if main is None:
            return loaded
        checks = {key: value for key, value in self._shape_checks.items() if key[0] == main_path}
        prepared, self._prepared_checks = self._prepared_checks, {}
        others = []
        for path, lap_data in loaded:
            if lap_data is None or path == main_path:
                continue
            stamps = self.shape_stamps(main_path, path)
            found = checks.get((main_path, path))
            if found is None or found[0] != stamps:  # measured in background unless few samples (see prepare_laps)
                found = prepared.get((main_path, path))
                if found is None or found[0] != stamps:
                    found = (stamps, self.shape_check(main, lap_data, path))
                checks[(main_path, path)] = found
            if found[1] is False:
                others.append(path)
        self._shape_checks = checks
        if not others:
            return loaded
        if batch is not None:  # every lap just added & shown driven on another circuit: viewer switches to it
            opened = {path for path, lap_data in loaded if path in batch[1] and lap_data is not None}
            if opened and opened <= set(others):
                lead = batch[2] or next(path for path in batch[1] if path in opened)
                self._pending_switch = (batch[0], batch[1], lead)
                return loaded
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        names = ", ".join(self.circuit_names(others, infos))
        self.checked.difference_update(others)
        added = {entry.file.path for entry in self.external} & set(others)
        if added:  # never listed, like laps of another circuit added (see add_external)
            self.external = [entry for entry in self.external if entry.file.path not in added]
            self.fill_list()
            self.set_status(trm(f"Laps from another circuit, not added: {names}"))
        else:
            self.set_status(trm(f"Laps from another circuit, not compared with reference lap: {names}"))
        kept = [(path, lap_data) for path, lap_data in loaded if path not in others]
        if self.reference_key in others:
            self.reference_key = next((path for path, lap_data in kept if lap_data is not None), main_path)
        return kept

    @staticmethod
    def circuit_names(paths: list[str], infos: dict[str, dict]) -> list[str]:
        """Track names of laps (lap info, else track folder), each once"""
        return sorted({str(infos.get(path, {}).get("track") or track_of_folder(path)
                           or os.path.basename(os.path.dirname(path))) for path in paths})

    @staticmethod
    def laps_warning(laps: list[PlotLap]) -> str:
        """Shown laps not alike: driven with different vehicles"""
        vehicles = sorted({str(lap.data.meta.get("vehicle")) for lap in laps if lap.data.meta.get("vehicle")})
        return trm(f"Laps from different vehicles: {', '.join(vehicles)}") if len(vehicles) > 1 else ""

    @staticmethod
    def is_clean(entry: LapEntry | None, path: str, lap: LapData) -> bool:
        """Valid lap, not out or in lap: may count in ideal lap & mini-sectors"""
        info = entry.info if entry is not None else lap.meta
        return is_valid_name(os.path.basename(path)) and info.get("kind", "lap") == "lap"

    @staticmethod
    def entry_label(entry: LapEntry | None, path: str) -> str:
        """Lap name in legend: "Lap 12 · 1:11.525 · Race 03/10", or "log: Lap 3 · 2:18.200" """
        label = lap_label(os.path.basename(path))
        if entry is None or entry.external:
            return f"{os.path.basename(os.path.dirname(path))}: {label}"
        session = str(entry.info.get("session", ""))
        timestamp = lap_timestamp_of(entry.file.filename)
        date = day_month(timestamp)
        where = " ".join(filter(None, [tr(session) if session else "", date]))
        return f"{label} · {where}" if where else label

    def update_list_state(self, laps: list[PlotLap]):
        """Check marks, lap colors, reference, errors & other circuit hints in lap list (in place: list keeps scroll
        position)"""
        colors = {lap.key: lap.color.name() for lap in laps}
        hint = self.circuit_hints()  # reference may have changed
        self.lap_model.update_rows(lambda row: {
            "checked": row["path"] in self.checked,
            "reference": bool(row["path"]) and row["path"] == self.reference_key,
            "color": colors.get(row["path"], ""),
            "error": row["path"] in self._failed and row["path"] in self.checked,
            **hint(row),
        })

    # Memory release while page is in background (see LapViewerBackend.page_hidden)
    @Slot()
    def release_laps(self):
        """Free memory of loaded laps (several MB each) while page is hidden, see page_shown"""
        if self._window.isVisible() or self._released:
            return
        if self._loader is not None:  # released once loading is done
            self._release_timer.start()
            return
        self._released_view = self._chart_view
        self._prepared_chart = None
        self._lap_cache.clear()
        self._cache_mtime.clear()
        self.data.set_laps([])
        self.clear_lap_caches()
        forget_increasing()
        self.rebuild_chart()
        self._released = True
        logger.info("LAP VIEWER: loaded laps released while hidden")

    def clear_lap_caches(self):
        """Forget results kept per loaded lap (they keep lap data in memory)"""
        for cache in (self._line_cache, self._lap_offsets, self._events, self._grids,
                      self._zones, self._placements, self._g_laps, self._g_drawn,
                      self._normals, self._turned, self._lap_shapes):
            cache.clear()
        self._corner_table.forget()
        self._map_marks.forget()
        self._map_pointer.forget()
        self._color_lines = ()
        self._colored_steps = {}
        self._line_offsets = {}
        self._edges_cache = ()
        self._edge_normals = ()
        self._g_points = []
        self._shape_checks.clear()
