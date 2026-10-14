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
Broadcast Director graphics (QML: backend.graphics): state of the broadcast graphics (stream_director, browser source
/director) published about once a second, onboard & car positions of the track map ten times a second (local game:
shared memory) while a graphics source asks. On demand graphics (starting grid, event card, classification captured,
championship standings) shown one at a time by the operator or the director, message & countdown of the operator,
league branding, layout presets. Settings: page settings "graphics", "championship", "championship_class".
"""

from __future__ import annotations

import os
import time
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QTimer, Signal, Slot

from ...i18n import tr
from ...process import championship as champ
from ...process import director as dr
from ...process.game_info import Standing
from ...rank_info import ranks
from ...setting import cfg
from ...template.setting_status_colors import SAME_TIME
from .director_shared import (
    ACCENT,
    AUTO_EVENT_SECONDS,
    BANNER_KINDS,
    BANNER_PRIORITY,
    BANNERS_KEPT,
    BRAND_NAME_LENGTH,
    COUNTDOWN_LIMIT,
    GRAPHICS_CHOICES,
    GRAPHICS_DEFAULTS,
    GRAPHICS_LIMITS,
    KIND_TEXTS,
    KIND_TONES,
    LIVE_MS,
    MESSAGE_LENGTH,
    NEAR_GAP,
    ON_DEMAND,
    PUBLISH_DELAY_MS,
    REPLAY,
    SESSION_TEXTS,
    STORY_KINDS,
    TRAIN_MAX,
    TRAIN_MIN,
    DirectorPart,
    class_color,
    clock_text,
    delta_text,
    fold,
    graphics_setting,
    interval,
    interval_text,
    lap_text,
    load_championships,
    localized,
    read_qualifying_times,
    save_championships,
    seconds_text,
    sector_tone,
    short_name,
    speed_value,
    status_text,
    temperature_text,
)

if TYPE_CHECKING:
    from .director_backend import DirectorBackend


class BroadcastGraphics(DirectorPart):
    """Broadcast graphics of the page: settings, state published to the sources, on demand graphics"""

    graphicsChanged = Signal()
    onDemandChanged = Signal()
    championshipChanged = Signal()

    def __init__(self, page: DirectorBackend, settings: dict[str, Any]):
        super().__init__(page)
        self.settings = graphics_setting(settings.get("graphics"))
        self.on_demand = ""  # graphic shown by the operator (starting grid, event card...), "" if none
        self.captured: dict[str, Any] | None = None  # classification captured for the graphics
        self.championships = load_championships()
        index = settings.get("championship")
        self.championship_index = index if isinstance(index, int) and 0 <= index < len(self.championships) else 0
        cls = settings.get("championship_class")
        self.championship_class = cls if isinstance(cls, str) else ""
        self._publish_timer = QTimer(self)  # graphics setting changed again soon: sent once a while
        self._publish_timer.setSingleShot(True)
        self._publish_timer.setInterval(PUBLISH_DELAY_MS)
        self._publish_timer.timeout.connect(self.publish_settings)
        self._published: tuple[str, float] = ("", 0.0)  # graphics setting last sent at once, monotonic time
        self.auto_shown = ""  # on demand graphic shown by the director itself (hidden by it too)
        self._auto_done: set[str] = set()  # automatic graphics already shown this session
        self.message: dict[str, Any] | None = None  # message of the operator on the graphics
        self.countdown_end = 0.0  # time.time() the countdown of the operator ends, 0 if none
        self.countdown_label = ""
        self._sector_ends = [0.0, 0.0]  # meters: end of sectors 1 & 2 (furthest place seen in each)
        self._brand: tuple[float, tuple[str, list[str]]] = (0.0, ("", []))  # read time, logo & sponsors
        self._champ_view: tuple = ()  # what the championship graphic was made from
        self._champ_state: dict[str, Any] | None = None
        self._quali_times: tuple[tuple, dict[str, float]] = ((), {})  # qualifying results of the session
        self._index_of: dict[int, int] = {}  # shared memory vehicle index of each slot (live feed)
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_MS)
        self._live_timer.timeout.connect(self.publish_live)
        self._auto_timer = QTimer(self)  # event card shown at session start: hidden after a while
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.end_auto_event)
        self.cut_count = 0  # cars put on air: graphics show the driver card again
        self._links: dict[tuple[str, int], tuple[str, str]] = {}  # (vehicle, pictures version): logo & picture links

    def page_settings(self) -> dict[str, Any]:
        return {"graphics": self.settings, "championship": self.championship_index,
                "championship_class": self.championship_class}

    def release(self):
        """Page closed: last graphics setting change sent, timers stopped"""
        if self._publish_timer.isActive():
            self.publish_settings()
        self.stop()
        self._publish_timer.stop()

    def stop(self):
        """Director off or page closed: live feed & automatic event card stopped"""
        self._live_timer.stop()
        self._auto_timer.stop()

    def new_session(self):
        """Another session: captured classification & automatic graphics forgotten, event card shown if wanted"""
        self.captured = None
        self._sector_ends = [0.0, 0.0]
        self._auto_done.clear()
        if self.auto_shown and self.on_demand == self.auto_shown:
            self.on_demand = ""
            self.onDemandChanged.emit()
        self.auto_shown = ""
        if self.settings["autoEvent"]:
            self.show_auto("event")
            self._auto_timer.start(AUTO_EVENT_SECONDS * 1000)
        if self.on_demand == "results":
            self.on_demand = ""
            self.onDemandChanged.emit()

    def new_cut(self):
        """Another car on air: driver card shown again by the graphics"""
        self.cut_count += 1

    def picture_links(self, vehicle: str) -> tuple[str, str]:
        """Brand logo (for dark graphics) & car picture addresses on the stream server, "" if none"""
        from ...stream_overlay import picture_link
        from ...userfile.custom_image import brand_logo_file
        from ...userfile.game_images import images

        key = (vehicle, images.version)
        links = self._links.get(key)
        if links is None:
            logo = brand_logo_file(cfg.path.brand_logo, images.brand(vehicle, ""), False, vehicle) if vehicle else ""
            links = (picture_link(logo), picture_link(images.car_picture(vehicle)) if vehicle else "")
            if len(self._links) > 256:
                self._links.clear()
            self._links[key] = links
        return links

    def clock_state(self) -> dict[str, str] | None:
        """Session clock of graphics: time left when the session has a length, else time gone"""
        page = self.page
        if page.session_time < 0:
            return None
        start = page.session_key[2] if isinstance(page.session_key[2], (int, float)) else 0
        if page.session_info.phase < dr.GREEN_PHASE and start > page.session_time > 0:
            return {"text": clock_text(start - page.session_time), "label": tr("Start in")}
        if page.session_end > 0:
            return {"text": clock_text(max(page.session_end - page.session_time, 0.0)), "label": tr("Remaining")}
        return {"text": clock_text(page.session_time), "label": tr("Elapsed")}

    def graphics_state(self) -> dict[str, Any]:
        """What the broadcast graphics show now (texts in app language)"""
        from ...stream_director import labels

        page = self.page
        settings = self.settings
        on_air_slot, track_length = page.on_air_slot, page.track_length
        race = dr.is_race(page.session_key[1])
        grid = page.class_grid() if race else {}
        fronts, places = page.class_ahead(), page.places
        fastest = page.class_fastest()
        tower = []
        previous: Standing | None = None
        leader = page.standings[0] if page.standings else None
        class_leaders: dict[str, Standing] = {}
        for car in page.standings:
            class_leaders.setdefault(car.car_class, car)
            seconds, laps = interval(fronts[car.slot], car, track_length) \
                if car.slot in fronts else (-1.0, 0)
            tower.append({
                "pos": car.position, "classPos": places.get(car.slot, 0), "cls": car.car_class,
                "color": class_color(car.car_class), "number": car.number, "name": short_name(car.driver),
                "gap": interval_text(previous, car, track_length) if previous is not None else "",
                "gapClass": interval_text(fronts.get(car.slot), car, track_length),
                "close": laps == 0 and 0 <= seconds < NEAR_GAP, "pit": car.in_pit or car.garage,
                "state": tower_state(car),
                "air": car.slot == on_air_slot,
                "change": grid[car.slot] - places.get(car.slot, 0) if car.slot in grid else 0,
                # Last lap: shown a few seconds by the source when a new one comes (lap count changed)
                "lap": lap_text(car.last) if car.last > 0 else "", "lapId": car.laps,
                "lapTone": "fastest" if 0 < car.last <= fastest.get(car.car_class, 0.0) + SAME_TIME else "",
                "tyres": [letter for letter in dict.fromkeys(page.tyres.get(car.slot, ())) if letter],
                "pen": car.penalties,
                "gapLeader": interval_text(leader, car, track_length) if car is not leader else "",
                "gapClassLeader": interval_text(class_leaders[car.car_class], car, track_length)
                if car is not class_leaders[car.car_class] else "",
                "fastest": car.best > 0 and car.best <= fastest.get(car.car_class, 0.0) + SAME_TIME,
                "stops": car.pitstops,
            })
            previous = car
        on_air = None
        shown = page.by_slot.get(on_air_slot)
        if shown is not None:
            kind = page.on_air_kind
            on_air = self.card_state(shown, self.story_text(kind),
                                     KIND_TONES.get(kind, "") if kind in STORY_KINDS else "", grid)
        battle = None
        fight = next((item for item in page.watcher.battles.values()
                      if on_air_slot in (item.ahead, item.behind)), None)
        story = page.on_air_kind in (dr.BATTLE, dr.OVERTAKE, dr.LEAD)
        if fight is not None and story:
            ahead, behind = page.by_slot.get(fight.ahead), page.by_slot.get(fight.behind)
            if ahead is not None and behind is not None:
                trend = page.trend_text(fight, behind)
                battle = {
                    "title": f"{tr('Battle for P%1').replace('%1', str(fight.position))} · {fight.car_class}",
                    "color": class_color(fight.car_class), "gap": seconds_text(fight.gap), "trend": trend,
                    "trendClass": "closing" if fight.trend < -0.02 else "opening" if fight.trend > 0.02 else "",
                    "ahead": {"number": ahead.number, "name": short_name(ahead.driver), "team": ahead.team},
                    "behind": {"number": behind.number, "name": short_name(behind.driver), "team": behind.team},
                }
        events: list[dict[str, Any]] = []
        for event in reversed(page.events):
            if len(events) >= BANNERS_KEPT:
                break
            heavy = event.kind in (dr.CONTACT, dr.WALL) and page.watcher.severity.get(event.key, -1.0) >= dr.HEAVY
            if event.live and (event.kind in BANNER_KINDS or heavy):
                title, detail = page.event_texts(event)
                events.append({"id": event.key, "kind": page.kind_text(event), "title": title, "detail": detail,
                               "tone": KIND_TONES.get(event.kind, "accent"), "type": event.kind,
                               "priority": BANNER_PRIORITY.get(event.kind, 1) + (3 if heavy else 0),
                               # Source opened just now: banner of what just happened still shown
                               "fresh": 0 <= page.session_time - event.time < settings["bannerSeconds"]})
        events.reverse()
        flag = "" if page.session_info.yellow in ("NONE", "INVALID", "") else tr("Full course yellow")
        radar = None
        if shown is not None and settings["pitRadar"]:
            rows = self.pit_neighbours(shown)
            if rows:
                count = sum(1 for row in rows if not row["ahead"])
                radar = {"title": tr("Pit lane"), "rows": rows[:6],
                         "count": tr("%1 cars approaching").replace("%1", str(count)) if count else ""}
        on_demand = self.on_demand
        return {
            "pitRadar": radar,
            "live": page.can_command(), "graphics": settings, "cut": self.cut_count, "tower": tower,
            "onAir": on_air, "battle": battle, "events": events, "replay": page.instant or page.state == REPLAY,
            "train": self.train_state() if story and settings["train"] else None,
            "replayInfo": self.replay_info(grid) if settings["replayGraphics"] else None,
            "clock": self.clock_state(), "flag": flag,
            "weather": [text for text in self.weather_texts() if text != flag],
            "onboard": self.onboard_state() if settings["onboard"] else None,
            "quali": self.quali_state() if settings["quali"] and not race else None,
            "map": self.map_state() if settings["map"] else None,
            "grid": self.grid_state() if on_demand == "grid" else None,
            "event": self.event_state() if on_demand == "event" else None,
            "results": self.captured if on_demand == "results" else None,
            "champ": self.championship_state() if on_demand == "champ" else None,
            "message": self.message,
            "countdown": self.countdown_state(),
            "brand": self.brand_state(),
            "labels": labels(tr),
        }

    def card_state(self, car: Standing, story: str, tone: str, grid: dict[int, int]) -> dict[str, Any]:
        """Driver card of a car"""
        places = self.page.places
        logo, picture = self.picture_links(car.vehicle)
        gained = grid.get(car.slot, 0) - places.get(car.slot, 0) if car.slot in grid else 0
        name = car.driver.split("#", 1)[0].strip() or car.driver
        ranks.poll()
        known = ranks.team_ranks(name)  # player & team members only (game menu data)
        return {
            "number": car.number, "name": name,
            "team": car.team or car.vehicle, "cls": car.car_class, "color": class_color(car.car_class),
            "classPos": places.get(car.slot, 0), "logo": logo, "picture": picture,
            "stats": [[tr("Best"), lap_text(car.best) if car.best > 0 else ""],
                      [tr("Last"), lap_text(car.last) if car.last > 0 else ""],
                      [tr("Laps"), str(car.laps)],
                      [tr("Places"), f"{'+' if gained > 0 else ''}{gained}" if gained else ""],
                      ["DR", known.driver.short if known is not None and known.driver else ""],
                      ["SR", known.safety.short if known is not None and known.safety else ""]],
            "story": story, "storyTone": tone,
        }

    def weather_texts(self) -> list[str]:
        """Weather of the graphics, in the temperature unit of the graphics"""
        info, unit = self.page.session_info, self.settings["temperatureUnit"]
        return [text for text in (
            tr("Air %1").replace("%1", temperature_text(info.air, unit)) if info.air > -999 else "",
            tr("Track %1").replace("%1", temperature_text(info.track, unit)) if info.track > -999 else "",
            tr("Rain %1").replace("%1", f"{round(info.rain * 100)}%") if info.rain > 0.005 else "",
            tr("Wet %1").replace("%1", f"{round(info.wetness * 100)}%") if info.wetness > 0.005 else "",
        ) if text]

    def train_state(self) -> dict[str, Any] | None:
        """Battle train of the car on air: cars of its class following each other closely (3 to 6), None if not"""
        page = self.page
        car = page.by_slot.get(page.on_air_slot)
        if car is None or not dr.running(car):
            return None
        cars = [other for other in page.standings if other.car_class == car.car_class and dr.running(other)]
        limit = page.director.settings.battle_gap
        chain = [cars[0]] if cars else []
        trains = [chain]
        for ahead, behind in pairwise(cars):
            seconds, laps = interval(ahead, behind, page.track_length)
            if laps == 0 and 0 <= seconds <= limit:
                chain.append(behind)
            else:
                chain = [behind]
                trains.append(chain)
        train = next((item for item in trains if any(other.slot == car.slot for other in item)), [])
        if len(train) < TRAIN_MIN:
            return None
        index = next(position for position, other in enumerate(train) if other.slot == car.slot)
        start = min(max(index - TRAIN_MAX // 2, 0), max(len(train) - TRAIN_MAX, 0))
        train = train[start:start + TRAIN_MAX]
        first = page.places.get(train[0].slot, 0)
        return {
            "title": f"{tr('Battle for P%1').replace('%1', str(first))} · {car.car_class}",
            "color": class_color(car.car_class),
            "cars": [{"number": other.number, "name": short_name(other.driver), "color": class_color(other.car_class),
                      "classPos": page.places.get(other.slot, 0), "air": other.slot == car.slot,
                      "gap": interval_text(train[position - 1], other, page.track_length) if position else ""}
                     for position, other in enumerate(train)],
        }

    def replay_info(self, grid: dict[int, int]) -> dict[str, Any] | None:
        """Graphics of the instant replay shown: contact of two cars (both), other events (driver card)"""
        page = self.page
        event = page.instant_event
        if not page.instant or event is None:
            return None
        cars = [page.by_slot[slot] for slot in event.slots if slot in page.by_slot]
        if not cars:
            return None
        kind, tone = page.kind_text(event), KIND_TONES.get(event.kind, "accent")
        if event.kind == dr.CONTACT and len(cars) > 1:
            first, second = cars[0], cars[1]
            return {
                "mode": "duel", "kind": kind, "tone": tone, "center": tr("Replay").upper(),
                "ahead": {"number": first.number, "name": short_name(first.driver), "team": first.team},
                "behind": {"number": second.number, "name": short_name(second.driver), "team": second.team},
            }
        return {"mode": "driver", "kind": kind, "tone": tone, "car": self.card_state(cars[0], kind, tone, grid)}

    def onboard_state(self) -> dict[str, Any] | None:
        """Car of the onboard graphic (car on air): what does not change many times a second"""
        page = self.page
        car = page.by_slot.get(page.on_air_slot)
        if car is None:
            return None
        ahead = page.class_ahead().get(car.slot)
        gap = interval_text(ahead, car, page.track_length) if ahead is not None else ""
        return {"number": car.number, "name": short_name(car.driver), "color": class_color(car.car_class),
                "cls": car.car_class, "rpmMax": self.rpm_max(car.slot),
                "ahead": f"#{ahead.number} {gap}" if ahead is not None and gap else ""}

    def rpm_max(self, slot: int) -> float:
        """Highest engine rpm of a car (shared memory of the game on this computer), 9000 if unknown"""
        reader = self.reader()
        index = self.vehicle_index(slot)
        if reader is None or index < 0:
            return 9000.0
        try:
            value = float(reader.engine.rpm_max(index))
        except (AttributeError, IndexError, TypeError, ValueError):
            return 9000.0
        return value if value > 1000 else 9000.0

    def quali_state(self) -> dict[str, Any] | None:
        """Lap of the car on air outside races: lap time running, sectors, gap to pole of its class"""
        page = self.page
        car = page.by_slot.get(page.on_air_slot)
        if car is None:
            return None
        personal, class_best = page.best_sectors()
        bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
        current = dr.current_sectors(car)
        timed = [other for other in page.standings if other.car_class == car.car_class and other.best > 0]
        pole = min(timed, key=lambda other: other.best) if timed else None
        delta, improving = None, False
        if pole is not None and current[0] > 0:  # gap to pole lap at the last sector done
            done = car.current_sector2 if current[1] > 0 else car.current_sector1
            reference = pole.best_sector2 if current[1] > 0 else pole.best_sector1
            if reference > 0:
                delta = done - reference
            improving = all(value <= best + SAME_TIME for value, best in zip(current, bests) if value > 0 and best > 0)
        elif pole is not None and car.best > 0:
            delta = car.best - pole.best
        state = page.watcher.cars.get(car.slot)
        if car.in_pit or car.garage:
            status = tr("In Pits")
        elif state is not None and state.lap_pit:
            status = tr("Out lap")
        elif improving and car.best > 0:
            status = tr("Improving")
        else:
            status = ""
        running = not car.in_pit and not car.garage and car.into_lap >= 0
        return {
            "number": car.number, "name": short_name(car.driver), "color": class_color(car.car_class),
            "position": f"P{page.places.get(car.slot, 0)}", "running": running,
            "lapStart": car.lap_start, "now": page.session_time,
            "best": lap_text(car.best), "target": lap_text(pole.best) if pole is not None else "-",
            "targetLabel": tr("Pole"),
            "delta": delta_text(delta) if delta is not None else "",
            "deltaTone": "" if delta is None else "gain" if delta < 0 else "loss",
            "status": status,
            "sectors": [{"text": localized(f"{value:.3f}") if value > 0 else "-",
                         "tone": sector_tone(value, bests[index], class_bests[index])}
                        for index, value in enumerate(current)],
        }

    def map_state(self) -> dict[str, Any]:
        """Cars of the track map (positions of the answer, live feed moves them), yellow flag car"""
        from ...stream_director import track_outline

        page = self.page
        cars = {str(car.slot): [round(car.x, 1), round(car.y, 1), class_color(car.car_class), car.number,
                                car.slot == page.on_air_slot, car.in_pit]
                for car in page.standings if not car.garage}
        flagged = any(page.session_info.sector_flags) if page.session_info.sector_flags else False
        yellow = -1
        if flagged:
            event = next((event for event in reversed(page.events[-50:]) if event.kind == dr.YELLOW and event.slots
                          and page.session_time - event.time < 120), None)
            yellow = event.slots[0] if event is not None else -1
        flags = list(page.session_info.sector_flags or ())[:3]
        ends = self._sector_ends
        sectors = [round(end / page.track_length, 4) for end in ends] if (
            page.track_length > 0 and 0 < ends[0] < ends[1] < page.track_length) else []
        return {"track": track_outline.key, "yellow": yellow, "cars": cars, "sectors": sectors,
                "yellowSectors": flags + [False] * (3 - len(flags))}

    def note_sector_ends(self):
        """End of sectors 1 & 2 along the lap: furthest place a car was seen in each (track map sectors)"""
        page = self.page
        for car in page.standings:
            if car.sector in (1, 2) and 0 < car.distance < page.track_length and not car.in_pit:
                index = car.sector - 1
                if car.distance > self._sector_ends[index]:
                    self._sector_ends[index] = car.distance

    def set_track(self, points: Any):
        """Track outline of the session from the game (racing line & pit lane)"""
        from ...stream_director import track_outline
        from ...userfile.track_geometry import parse_points

        if not isinstance(points, list):
            return
        racing, pit = parse_points(points)
        if len(racing) < 3:
            return
        self.page.game.need_track = False
        track_outline.set(f"{self.page.session_key[0]}|{len(racing)}", [(x, y) for x, y, _ in racing],
                          [(x, y) for x, y, _ in pit])

    def qualifying_times(self) -> dict[str, float]:
        """Best lap of each driver in the last qualifying of this track (results files), read once a session in
        background (empty until read: grid made again then)"""
        key = self.page.session_key
        if self._quali_times[0] == key:
            return self._quali_times[1]
        self._quali_times = (key, {})
        track = fold(key[0])
        self.page.jobs.run("qualifying times", lambda: (key, read_qualifying_times(track)), self.qualifying_read,
                           key="quali")
        return {}

    def qualifying_read(self, result: tuple[tuple, dict[str, float]]):
        key, times = result
        if times and self._quali_times[0] == key:
            self._quali_times = (key, times)  # next graphics state shows them

    def grid_state(self) -> dict[str, Any]:
        """Starting grid: cars by qualifying place, qualifying lap, car picture"""
        times = self.qualifying_times()
        ordered = sorted(self.page.standings, key=lambda car: (car.grid <= 0, car.grid, car.position))
        cars = []
        for index, car in enumerate(ordered, 1):
            _, picture = self.picture_links(car.vehicle)
            best = times.get(car.driver, 0.0)
            cars.append({"pos": car.grid if car.grid > 0 else index, "number": car.number,
                         "name": short_name(car.driver), "team": car.team or car.vehicle, "cls": car.car_class,
                         "color": class_color(car.car_class), "time": lap_text(best) if best > 0 else "",
                         "picture": picture})
        return {"title": tr("Starting Grid"), "cars": cars}

    def event_state(self) -> dict[str, Any]:
        """Event card: track, session, conditions, forecast, schedule"""
        from ...stream_overlay import picture_link
        from ...userfile.game_images import images

        page = self.page
        track, session = page.session_key[:2]
        unit = self.settings["temperatureUnit"]
        kind = next((text for prefix, text in SESSION_TEXTS.items() if session.upper().startswith(prefix)), "")
        schedule = [[tr("Session"), tr(kind) if kind else session.title()]]
        start = page.session_key[2] if isinstance(page.session_key[2], (int, float)) else 0
        if page.session_end > 0:
            schedule.append([tr("Session length"), clock_text(page.session_end - max(start, 0.0))])
        clock = self.clock_state()
        if clock is not None:
            schedule.append([clock["label"], clock["text"]])
        schedule.append([tr("Cars"), str(len(page.standings))])
        classes = list(dict.fromkeys(car.car_class for car in page.standings if car.car_class))
        if len(classes) > 1:
            schedule.append([tr("Classes"), " · ".join(classes)])
        forecast = [{**node, "temperature": temperature_text(node.get("celsius", -1000.0), unit)
                     if node.get("celsius", -1000.0) > -999 else node.get("temperature", "")} for node in page.forecast]
        return {
            "track": track, "session": tr(kind) if kind else session.title(),
            "logo": picture_link(images.track_logo(track)) if track else "",
            "conditions": self.weather_texts(), "forecast": forecast, "schedule": schedule,
        }

    def results_state(self) -> dict[str, Any]:
        """Classification now (captured by the operator): every car, gap to leader, best lap, pit stops"""
        page = self.page
        leader = page.standings[0] if page.standings else None
        rows = []
        for car in page.standings:
            status, _ = status_text(car)
            if car.finish == "FSTAT_FINISHED" or car.in_pit or car.garage:
                status = "" if car.finish == "FSTAT_FINISHED" else status
            rows.append({
                "pos": car.position, "classPos": page.places.get(car.slot, 0), "cls": car.car_class,
                "color": class_color(car.car_class), "number": car.number, "name": short_name(car.driver),
                "team": car.team or car.vehicle, "laps": car.laps,
                "gap": tr("Leader") if car is leader else interval_text(leader, car, page.track_length),
                "best": lap_text(car.best), "pits": car.pitstops,
                "status": status if car.finish in ("FSTAT_DNF", "FSTAT_DQ") else "",
            })
        laps = leader.laps if leader is not None else 0
        clock = self.clock_state()
        parts = [tr("Lap %1").replace("%1", str(laps)) if laps else "", f"{clock['label']} {clock['text']}" if clock else ""]
        return {"title": tr("Classification"), "subtitle": " · ".join(part for part in parts if part), "rows": rows}

    def championship_state(self) -> dict[str, Any] | None:
        """Championship standings chosen (class chosen, or every driver), made again only when changed"""
        view = (self.championship_index, self.championship_class, id(self.championships),
                len(self.championships))
        if view != self._champ_view:
            self._champ_view = view
            self._champ_state = self.make_championship_state()
        return self._champ_state

    def make_championship_state(self) -> dict[str, Any] | None:
        if not 0 <= self.championship_index < len(self.championships):
            return None
        item = self.championships[self.championship_index]
        cls = self.championship_class if self.championship_class in champ.classes(item["rows"]) else ""
        rows = [{"pos": place, "name": row.name, "team": row.team, "cls": row.car_class,
                 "color": class_color(row.car_class) if row.car_class else "", "points": champ.points_text(row.points),
                 "medal": place if place <= 3 else 0}
                for place, row in champ.standings(item["rows"], cls)]
        return {"title": item["name"], "subtitle": cls, "rows": rows}

    # Live feed: onboard & car positions
    @staticmethod
    def reader() -> Any:
        """Game data of the app (shared memory), None if not readable"""
        from ...api_control import api

        return getattr(api, "read", None)

    def vehicle_index(self, slot: int) -> int:
        """Shared memory vehicle index of a car (slot), -1 if not there (game on another computer)"""
        if not self.page.game.local_game():
            return -1
        reader = self.reader()
        if reader is None:
            return -1
        index = self._index_of.get(slot, -1)
        try:
            if index >= 0 and reader.vehicle.slot_id(index) == slot:
                return index
            self._index_of = {reader.vehicle.slot_id(index): index for index in range(reader.vehicle.total_vehicles())}
        except (AttributeError, IndexError, TypeError, ValueError):
            self._index_of = {}
        return self._index_of.get(slot, -1)

    def live_wanted(self) -> bool:
        page = self.page
        return (page.is_open and page.is_enabled and page.can_command()
                and bool(self.settings["onboard"] or self.settings["map"]))

    def update_live_timer(self):
        """Live feed made while onboard or track map graphic is on (a source asks for it)"""
        if self.live_wanted():
            if not self._live_timer.isActive():
                self._live_timer.start()
        else:
            self._live_timer.stop()

    def publish_live(self):
        from ...stream_director import live_feed

        if not self.live_wanted():
            self._live_timer.stop()
            return
        if live_feed.watched():
            live_feed.publish(self.live_state())

    def live_state(self) -> dict[str, Any]:
        """Onboard of the car on air & positions of every car (shared memory of the game on this computer, else
        positions of the last answer)"""
        page = self.page
        reader = self.reader() if page.game.local_game() else None
        onboard = None
        car = page.by_slot.get(page.on_air_slot)
        if self.settings["onboard"] and car is not None:
            index = self.vehicle_index(car.slot)
            energy = dr.level(car)
            if reader is not None and index >= 0:
                try:
                    speed, unit = speed_value(float(reader.vehicle.speed(index)))
                    onboard = {"speed": round(speed, 1), "unit": unit, "gear": int(reader.engine.gear(index)),
                               "rpm": round(float(reader.engine.rpm(index))),
                               "rpmMax": round(float(reader.engine.rpm_max(index))),
                               "throttle": round(min(max(float(reader.inputs.throttle_raw(index)), 0.0), 1.0), 2),
                               "brake": round(min(max(float(reader.inputs.brake_raw(index)), 0.0), 1.0), 2),
                               "energy": round(energy, 3)}
                except (AttributeError, IndexError, TypeError, ValueError):
                    onboard = None
            if onboard is None:  # game on another computer: speed of the last answer only
                speed, unit = speed_value(car.speed)
                onboard = {"speed": round(speed, 1), "unit": unit, "gear": None, "rpm": 0, "rpmMax": 0, "throttle": 0,
                           "brake": 0, "energy": round(energy, 3)}
        cars: list[float] = []  # slot, x, y of each car (meters, flat: less to send five times a second)
        if self.settings["map"]:
            done = False
            if reader is not None:
                try:
                    for index in range(reader.vehicle.total_vehicles()):
                        x, _, z = reader.vehicle.position_xyz(index)
                        cars.extend((reader.vehicle.slot_id(index), round(x), round(-z)))
                    done = bool(cars)  # no vehicle in shared memory (other game data): last answer
                except (AttributeError, IndexError, TypeError, ValueError):
                    cars = []
            if not done:
                cars = [value for car in page.standings for value in (car.slot, round(car.x), round(car.y))]
        return {"onboard": onboard, "cars": cars}

    def pit_neighbours(self, car: Standing) -> list[dict[str, Any]]:
        """Cars near the car on air in the pit lane: number, name, color, distance text, alongside, ahead"""
        from ... import units

        page = self.page
        unit = units.set_unit_distance(cfg.units.get("distance_unit", "Meter"))
        symbol = units.set_symbol_distance(cfg.units.get("distance_unit", "Meter"))
        rows = []
        for neighbour in dr.pit_radar(car, page.standings, page.track_length, self.settings["pitRadarRange"]):
            other = page.by_slot[neighbour.slot]
            rows.append({
                "number": other.number, "name": short_name(other.driver), "color": class_color(other.car_class),
                "distance": f"{round(unit(abs(neighbour.distance)))} {symbol}", "alongside": neighbour.alongside,
                "ahead": neighbour.distance > 0,
            })
        return rows

    def story_text(self, kind: str) -> str:
        page = self.page
        on_air_slot = page.on_air_slot
        if kind == dr.BATTLE and on_air_slot in {slot for battle in page.watcher.battles.values()
                                                 for slot in (battle.ahead, battle.behind)}:
            fight = next(item for item in page.watcher.battles.values()
                         if on_air_slot in (item.ahead, item.behind))
            return tr("Battle for P%1").replace("%1", str(fight.position))
        return tr(KIND_TEXTS[kind]) if kind in STORY_KINDS else ""

    def publish_graphics(self, force: bool = False):
        """Graphics state to the browser source, only while a source shows it (or settings changed)"""
        from ...stream_director import director_feed

        self.update_live_timer()
        if self.page.is_enabled and (force or director_feed.watched()):
            director_feed.publish(self.graphics_state())

    # Settings
    @Property(dict, notify=graphicsChanged)
    def graphicsSettings(self) -> dict:
        return self.settings

    @Slot(str, "QVariant")
    def setGraphic(self, name: str, value: Any):
        """Graphics setting (see GRAPHICS_DEFAULTS): shown or not, numbers, choices"""
        default = GRAPHICS_DEFAULTS.get(name)
        if default is None:
            return
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int):
            low, high = GRAPHICS_LIMITS.get(name, (-1e9, 1e9))
            try:
                value = int(min(max(float(value), low), high))
            except (TypeError, ValueError):
                return
            if name in GRAPHICS_CHOICES and value not in GRAPHICS_CHOICES[name]:
                return
        elif name == "accent":
            value = str(value).strip()
            if not ACCENT.match(value):
                return
        elif name == "brandName":
            value = str(value).strip()[:BRAND_NAME_LENGTH]
        elif value not in GRAPHICS_CHOICES.get(name, ()):
            return
        if self.settings.get(name) == value:
            return
        self.settings = {**self.settings, name: value}
        self.page.save_settings()
        self.graphicsChanged.emit()
        self.publish_setting(name)

    def publish_setting(self, name: str):
        """Graphics sent at once, but at most every PUBLISH_DELAY_MS while the same setting keeps changing (number
        arrow held): the last value is sent once that time passed"""
        now = time.monotonic()
        if name == self._published[0] and now - self._published[1] < PUBLISH_DELAY_MS / 1000:
            if not self._publish_timer.isActive():
                self._publish_timer.start()
            return
        self._publish_timer.stop()
        self._published = (name, now)
        self.publish_graphics(force=True)

    def publish_settings(self):
        """Graphics settings changed meanwhile sent"""
        self._published = (self._published[0], time.monotonic())
        self.publish_graphics(force=True)

    @Slot()
    def checkGraphics(self):
        """Graphics panel opened: source address made again (stream overlays turned on or off meanwhile)"""
        self.graphicsChanged.emit()

    @Slot()
    def showDriverCard(self):
        """Driver card of the car on air shown again now"""
        self.cut_count += 1
        self.publish_graphics(force=True)

    @Property(str, notify=graphicsChanged)
    def graphicsUrl(self) -> str:
        """Address of the graphics browser source, "" while stream overlays are off"""
        return self.graphics_url()

    @staticmethod
    def graphics_url() -> str:
        from ...stream_overlay import streamoverlay

        return streamoverlay.url("/director") if streamoverlay.running else ""

    @Slot()
    def copyGraphicsUrl(self):
        from PySide6.QtGui import QGuiApplication

        url = self.graphics_url()
        if url:
            QGuiApplication.clipboard().setText(url)
            self.page.notify(tr("Address copied: add it as a browser source (1920 x 1080)"))

    @Slot()
    def openStreamOverlays(self):
        """Stream Overlays page (turn the server on, sources)"""
        from PySide6.QtWidgets import QWidget

        from ..tools_view import open_tool

        parent = self.page.parent()
        open_tool("stream_overlay_view.StreamOverlaysView", parent.window() if isinstance(parent, QWidget) else None)

    # On demand graphics: starting grid, event card, classification, championship
    @Property(str, notify=onDemandChanged)
    def onDemand(self) -> str:
        return self.on_demand

    @Slot(str)
    def showOnDemand(self, name: str):
        """Graphic shown by the operator (the same name again: hidden), one at a time"""
        if name not in ON_DEMAND:
            name = ""
        name = "" if name == self.on_demand else name
        self.auto_shown = ""  # operator takes over
        if name == "results" and self.captured is None:
            self.captured = self.results_state()
        self.on_demand = name
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Property(str, notify=onDemandChanged)
    def captureText(self) -> str:
        """When the classification shown was captured, "" if none"""
        return self.captured["subtitle"] if self.captured is not None else ""

    @Slot()
    def captureResults(self):
        """Classification now captured & shown (stays as it is until captured again)"""
        self.captured = self.results_state()
        self.on_demand = "results"
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def clearResults(self):
        self.captured = None
        if self.on_demand == "results":
            self.on_demand = ""
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Property(list, notify=championshipChanged)
    def championshipNames(self) -> list[str]:
        return [item["name"] for item in self.championships]

    @Property(int, notify=championshipChanged)
    def championshipIndex(self) -> int:
        return self.championship_index if self.championships else -1

    @Property(list, notify=championshipChanged)
    def championshipClasses(self) -> list[str]:
        if not 0 <= self.championship_index < len(self.championships):
            return []
        return champ.classes(self.championships[self.championship_index]["rows"])

    @Property(str, notify=championshipChanged)
    def championshipClass(self) -> str:
        return self.championship_class

    @Slot()
    def importChampionship(self):
        """Championship standings from a CSV file (driver, points, team, class...): added, or replacing the one of
        the same name"""
        from PySide6.QtWidgets import QFileDialog, QWidget

        parent = self.page.parent()
        path, _ = QFileDialog.getOpenFileName(parent if isinstance(parent, QWidget) else None,
                                              tr("Import Championship"), "", "CSV (*.csv *.txt)")
        if path:
            self.import_championship(path)

    def import_championship(self, path: str) -> bool:
        try:
            with open(path, "rb") as file:
                data = file.read(2_000_000)
        except OSError as error:
            self.page.notify(f"{tr('Championship not imported')}: {error}", True)
            return False
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", "replace")
        rows = champ.parse_championship(text)
        if not rows:
            self.page.notify(tr("No driver with points found in this file"), True)
            return False
        name = os.path.splitext(os.path.basename(path))[0]
        items = [item for item in self.championships if item["name"] != name]
        items.append({"name": name, "rows": rows})
        self.championships = items
        self.championship_index = len(items) - 1
        self.championship_class = ""
        self.store_championships()
        self.page.notify(tr("%1 drivers imported").replace("%1", str(len(rows))))
        return True

    def store_championships(self):
        try:
            save_championships(self.championships)
        except OSError as error:
            self.page.notify(f"{tr('Championship not imported')}: {error}", True)
        self.page.save_settings()
        self.championshipChanged.emit()
        if self.on_demand == "champ":
            self.publish_graphics(force=True)

    @Slot()
    def removeChampionship(self):
        if 0 <= self.championship_index < len(self.championships):
            del self.championships[self.championship_index]
            self.championship_index = max(min(self.championship_index, len(self.championships) - 1), 0)
            if not self.championships and self.on_demand == "champ":
                self.on_demand = ""
                self.onDemandChanged.emit()
            self.store_championships()

    @Slot(int)
    def setChampionship(self, index: int):
        if 0 <= index < len(self.championships) and index != self.championship_index:
            self.championship_index = index
            self.championship_class = ""
            self.store_championships()

    @Slot(str)
    def setChampionshipClass(self, name: str):
        if name != self.championship_class:
            self.championship_class = name
            self.store_championships()

    # Layout editor of the graphics (browser)
    @Slot()
    def editGraphicsLayout(self):
        """Layout editor of the graphics opened in the browser (sample data, drag to move, wheel to resize)"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ...stream_overlay import streamoverlay

        if streamoverlay.running:
            QDesktopServices.openUrl(QUrl(streamoverlay.url("/director", "edit=1")))

    @Slot()
    def resetGraphicsLayout(self):
        """Every graphic back to its place & size"""
        from ...stream_director import director_feed, director_layout

        director_layout.set("", {})
        director_feed.bump()
        self.page.notify(tr("Graphics back to their places"))

    # Graphics shown by the director itself: starting grid before the start, event card, classification at the end
    def auto_graphics(self, new_events: list[dr.Event]):
        page = self.page
        race = dr.is_race(page.session_key[1])
        phase = page.session_info.phase
        settings = self.settings
        if race and settings["autoGrid"] and phase in dr.START_PHASES and "grid" not in self._auto_done:
            self._auto_done.add("grid")
            self.show_auto("grid")
        elif self.auto_shown == "grid" and phase >= dr.GREEN_PHASE:  # race started
            self.hide_auto("grid")
        if (race and settings["autoResults"] and "results" not in self._auto_done
                and any(event.kind == dr.WINNER and event.live for event in new_events)):
            self._auto_done.add("results")
            self.captured = self.results_state()
            self.show_auto("results")
        elif self.auto_shown == "results":  # cars still finishing: classification kept up to date
            self.captured = self.results_state()

    def show_auto(self, name: str):
        """On demand graphic shown by the director, unless the operator shows another one"""
        if self.on_demand and self.on_demand != self.auto_shown:
            return
        self.on_demand = self.auto_shown = name
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    def hide_auto(self, name: str):
        if self.on_demand == name and self.auto_shown == name:
            self.on_demand = ""
            self.onDemandChanged.emit()
            self.publish_graphics(force=True)
        if self.auto_shown == name:
            self.auto_shown = ""

    def end_auto_event(self):
        self.hide_auto("event")

    # Message of the operator & countdown
    @Property(str, notify=onDemandChanged)
    def messageText(self) -> str:
        return self.message["text"] if self.message is not None else ""

    @Slot(str, str)
    def showMessage(self, title: str, text: str):
        """Message on the graphics (lower third) until hidden: title (race control, commentators...) & text"""
        text = " ".join(text.split())[:MESSAGE_LENGTH]
        if not text:
            self.hideMessage()
            return
        count = self.message["id"] + 1 if self.message is not None else 1
        self.message = {"id": count, "title": " ".join(title.split())[:40], "text": text}
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def hideMessage(self):
        self.message = None
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    def countdown_state(self) -> dict[str, Any] | None:
        if self.countdown_end <= time.time():
            return None
        return {"label": self.countdown_label or tr("Race starts in"), "endsAt": round(self.countdown_end * 1000)}

    @Property(bool, notify=onDemandChanged)
    def countdownRunning(self) -> bool:
        return self.countdown_end > time.time()

    @Slot(float, str)
    def startCountdown(self, minutes: float, label: str):
        """Countdown on the graphics until a time (minutes from now), with a text"""
        seconds = min(max(float(minutes) * 60, 1.0), COUNTDOWN_LIMIT)
        self.countdown_end = time.time() + seconds
        self.countdown_label = " ".join(label.split())[:60]
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def stopCountdown(self):
        self.countdown_end = 0.0
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    # League branding: name, logo, sponsors pictures (config folder)
    def brand_state(self) -> dict[str, Any]:
        from ...stream_director import brand_pictures

        now = time.monotonic()
        if now - self._brand[0] > 5:  # folder looked at again every few seconds (pictures added)
            self._brand = (now, brand_pictures())
        logo, sponsors = self._brand[1]
        return {"name": self.settings["brandName"], "logo": logo, "sponsors": sponsors}

    @Slot()
    def chooseLogo(self):
        """League logo picked (PNG, JPG, WEBP, SVG): copied to the branding folder"""
        from PySide6.QtWidgets import QFileDialog, QWidget

        parent = self.page.parent()
        path, _ = QFileDialog.getOpenFileName(parent if isinstance(parent, QWidget) else None, tr("League logo"), "",
                                              "Images (*.png *.jpg *.jpeg *.webp *.svg)")
        if path:
            self.set_logo(path)

    def set_logo(self, path: str) -> bool:
        import shutil

        from ...stream_director import BRAND_TYPES, brand_folder

        extension = os.path.splitext(path)[1].lower().lstrip(".")
        if extension not in BRAND_TYPES:
            self.page.notify(tr("Choose a PNG, JPG, WEBP or SVG picture"), True)
            return False
        folder = brand_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            self.remove_logo_files()
            shutil.copyfile(path, os.path.join(folder, f"logo.{extension}"))
        except OSError as error:
            self.page.notify(f"{tr('Logo not saved')}: {error}", True)
            return False
        self._brand = (0.0, self._brand[1])
        self.publish_graphics(force=True)
        return True

    @staticmethod
    def remove_logo_files():
        from ...stream_director import brand_folder

        folder = brand_folder()
        try:
            for entry in os.scandir(folder):
                if entry.is_file() and entry.name.lower().startswith("logo."):
                    os.remove(entry.path)
        except OSError:
            pass

    @Slot()
    def clearLogo(self):
        self.remove_logo_files()
        self._brand = (0.0, self._brand[1])
        self.publish_graphics(force=True)

    @Slot()
    def openSponsorsFolder(self):
        """Folder of sponsors pictures (shown in turn, file name order)"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ...stream_director import brand_folder

        folder = os.path.join(brand_folder(), "sponsors")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self._brand = (0.0, self._brand[1])

    # Layout presets & sources with some graphics only
    @Property(list, constant=True)
    def layoutPresets(self) -> list[dict]:
        from ...stream_director import LAYOUT_PRESETS, labels

        names = labels(tr)["presets"]
        return [{"key": key, "name": names[key]} for key in LAYOUT_PRESETS]

    @Property(str, notify=graphicsChanged)
    def layoutPreset(self) -> str:
        from ...stream_director import director_layout

        return director_layout.active()

    @Slot(str)
    def setLayoutPreset(self, key: str):
        """Layout preset used by the graphics sources (those without their own preset)"""
        from ...stream_director import director_feed, director_layout

        if director_layout.set_active(key):
            director_feed.bump()
            self.graphicsChanged.emit()

    @Slot()
    def nextLayoutPreset(self):
        from ...stream_director import LAYOUT_PRESETS, director_layout, labels

        presets = list(LAYOUT_PRESETS)
        key = presets[(presets.index(director_layout.active()) + 1) % len(presets)]
        self.setLayoutPreset(key)
        self.page.notify(tr("Layout: %1").replace("%1", labels(tr)["presets"][key]))

    @Property(list, constant=True)
    def graphicNames(self) -> list[dict]:
        """Every graphic of the source: id & name (sources with some graphics only)"""
        from ...stream_director import GRAPHIC_IDS, labels

        names = labels(tr)["names"]
        return [{"key": key, "name": names[key]} for key in GRAPHIC_IDS]

    @Slot("QVariantList", str)
    def copyPartialUrl(self, ids: list, preset: str):
        """Address of a graphics source with some graphics only (another OBS scene or source), its own layout
        preset if given"""
        from PySide6.QtGui import QGuiApplication

        from ...stream_director import GRAPHIC_IDS, LAYOUT_PRESETS
        from ...stream_overlay import streamoverlay

        chosen = [str(key) for key in ids if key in GRAPHIC_IDS]
        if not streamoverlay.running or not chosen:
            return
        query = f"only={','.join(chosen)}"
        if preset in LAYOUT_PRESETS and preset:
            query += f"&preset={preset}"
        QGuiApplication.clipboard().setText(streamoverlay.url("/director", query))
        self.page.notify(tr("Address copied: add it as a browser source (1920 x 1080)"))


def tower_state(car: Standing) -> str:
    """Status shown in place of the gap on the stream tower, colored as everywhere (status_text tones):
    dq & dnf (loss), garage (dim), pit (warning), "" on track or finished (gap kept)"""
    if car.finish == "FSTAT_DQ":
        return "dq"
    if car.finish == "FSTAT_DNF":
        return "dnf"
    if car.garage:
        return "garage"
    if car.in_pit:
        return "pit"
    return ""
