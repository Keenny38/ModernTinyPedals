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
Broadcast director: race events of every car & shots for the game camera

RaceWatcher reads watch standings & contacts of the game (LMU Rest API, live session or replay, about once
a second) and tells what happened since last time: battles, overtakes, lead changes, contacts, stopped cars,
pit stops, fastest laps, finishes, retirements, penalties. Director scores what is worth showing and decides
when to cut to another car & camera (shortest and longest shot, urgent events, cars not shown again too soon,
operator cuts held a while). No Qt: fed by ui/quick/director_backend.py, tested alone.

Times: session time (seconds, replay time in a replay) for race events, a monotonic clock (seconds) for shots:
a shot lasts on screen, whatever the replay speed.
"""

from __future__ import annotations

from array import array
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from typing import NamedTuple

from .game_info import IMMOVABLE, Contact, SessionState, Standing, merge_contacts

# Event kinds
BATTLE = "battle"
OVERTAKE = "overtake"
LEAD = "lead"
CONTACT = "contact"
WALL = "wall"
STOPPED = "stopped"
PIT_IN = "pit_in"
PIT_OUT = "pit_out"
FASTEST = "fastest"
FINISH = "finish"
WINNER = "winner"
RETIRED = "retired"
PENALTY = "penalty"
SLOW = "slow"  # car much slower than usual at that place of the track
YELLOW = "yellow"  # yellow flag in a sector
FCY = "fcy"  # full course yellow (safety car)
GREEN = "green"  # race goes on after a full course yellow
START = "start"  # race start: leader followed
ROAM = "roam"  # nothing happening: cars shown in turn
MANUAL = "manual"  # shot chosen by operator

# Base priority of events (0 to 100) & how long (seconds of session time) an event is worth showing
PRIORITY = {
    WINNER: 95, CONTACT: 90, LEAD: 85, STOPPED: 80, SLOW: 75, START: 75, OVERTAKE: 70, YELLOW: 70, WALL: 60,
    FINISH: 60, BATTLE: 55, RETIRED: 50, FCY: 50, GREEN: 50, FASTEST: 45, PIT_IN: 35, PIT_OUT: 30, PENALTY: 25,
    ROAM: 10, MANUAL: 0,
}
LIFETIME = {
    WINNER: 20.0, CONTACT: 15.0, LEAD: 12.0, STOPPED: 30.0, OVERTAKE: 10.0, WALL: 12.0, RETIRED: 15.0,
    FASTEST: 8.0, FINISH: 10.0, PIT_IN: 25.0, PIT_OUT: 12.0, PENALTY: 8.0, SLOW: 20.0, YELLOW: 20.0,
}
QUALIFY_FASTEST = 80  # new fastest lap of a class outside races (provisional pole)
URGENT = frozenset((CONTACT, STOPPED, SLOW, LEAD, WINNER))  # may cut a shot shorter than the shortest shot
# Game cameras of each kind of shot, used in turn (keys of game camera menu, see ui/quick/game_camera)
CAMERA_PLAN = {
    BATTLE: ("TRACKSIDE0", "SWINGMAN", "ONBOARD00", "TVCOCKPIT"),
    OVERTAKE: ("TRACKSIDE0", "SWINGMAN"),
    LEAD: ("TRACKSIDE0", "SWINGMAN"),
    CONTACT: ("TRACKSIDE0",),
    WALL: ("TRACKSIDE0",),
    STOPPED: ("TRACKSIDE0",),
    RETIRED: ("TRACKSIDE0",),
    PIT_IN: ("TRACKSIDE0",),
    PIT_OUT: ("TRACKSIDE0", "SWINGMAN"),
    FASTEST: ("ONBOARD00", "TVCOCKPIT", "COCKPIT"),
    FINISH: ("TRACKSIDE0",),
    WINNER: ("TRACKSIDE0",),
    PENALTY: ("SWINGMAN",),
    SLOW: ("TRACKSIDE0",),
    YELLOW: ("TRACKSIDE0",),
    START: ("TRACKSIDE0", "SWINGMAN"),
    ROAM: ("TRACKSIDE0", "SWINGMAN", "ONBOARD00", "TVCOCKPIT", "NOSECAM"),
}
CAMERA_STYLES = ("mixed", "trackside", "onboard", "keep")  # keep: car changes, camera left as it is
STYLE_CAMERAS = {"trackside": ("TRACKSIDE0",), "onboard": ("ONBOARD00", "TVCOCKPIT", "ONBOARD02", "SWINGMAN")}

SETTLE = 1.0  # seconds: a new place counts once seen this long (cars side by side swap places)
JUMP = 20.0  # seconds: session time moved further (replay seek, other session): watched again from there
STOP_SPEED = 3.0  # m/s: car stands still
STOP_TIME = 3.0  # seconds standing still on track: stopped car
MOVE_AGAIN = 10.0  # m/s: stopped car moving again (can stop again)
MIN_SPEED = 15.0  # m/s: slower car still takes at least this long to reach the car ahead (gap of a slow car)
HALTED_SHARE = 0.34  # this share of cars stopped at once: race halted (grid, red flag), no stopped car events
CONTACT_LIVE = 10.0  # seconds: contact listed this long after it happened is still news
BATTLE_END_MARGIN = 0.3  # seconds over battle gap before a battle ends (no flicker on the threshold)
TREND_SMOOTHING = 0.3  # weight of new gap change rate
FEED_LIMIT = 300  # events kept
ROAM_LENGTH = 2.0  # roaming shots (nothing happening) last this many shortest shots
SPEED_BIN = 50.0  # meters: usual speed of cars kept for each part of the lap this long
SPEED_SAMPLES = 8  # speeds seen in a part of the lap before its usual speed is trusted
SPEED_SMOOTHING = 0.1  # weight of a new speed in the usual speed of a part of the lap
SLOW_SHARE = 0.45  # under this share of the usual speed at that place: slow car
RECOVERED_SHARE = 0.7  # back over this share: slow car going again (can be slow again)
SLOW_TIME = 3.0  # seconds slow before told
LAP_LIMIT = 500  # laps kept for each car
SPEED_HISTORY = 12.0  # seconds of speeds kept for each car (contact severity)
BEFORE_CONTACT = 3.0  # seconds: speed before a contact, highest of this long before it
AFTER_CONTACT = 5.0  # seconds: speed after a contact, lowest of this long after it
HEAVY, LIGHT = 0.4, 0.12  # speed lost: heavy contact over, light contact under (fraction of speed before)
MOVING = 15.0  # m/s: speed before a contact needed to measure its severity
SEEN_SHARE = 0.5  # interest kept by an event already shown
IMMINENT_GAP = 0.35  # seconds: battle this close & closing fast, overtake coming
IMMINENT_TREND = -0.04  # gap change (seconds per second)
IMMINENT_BONUS = 4.0  # first among battles, still below a fresh contact
OVERTAKE_CAMERA = "TVCOCKPIT"  # bonnet camera of the car behind: the car ahead in view
CLIMB_PLACES = 3  # class places gained since the start: comeback worth following
CLIMB_BONUS = 1.5  # interest by place gained
GREEN_PHASE = 5  # game phase of a green race (formation 3, countdown 4, full course yellow 6, stopped 7, over 8)
START_PHASES = frozenset((3, 4))


class Event(NamedTuple):
    """Something that happened to one or two cars"""

    key: str  # unique
    kind: str
    time: float  # session time (seconds)
    slots: tuple[int, ...]  # cars, first one shown
    drivers: tuple[str, ...]
    car_class: str
    position: int = 0  # class place (overtake, lead, battle, finish), 0 if none
    value: float = 0.0  # gap, lap time, pit lane time (seconds), penalties, sector... 0 if none
    live: bool = True  # False: happened before the page watched (history only, never shown on camera)
    extra: float = 0.0  # pit exit: seconds stopped in pit box


class Battle(NamedTuple):
    """Two cars of a class less than the battle gap apart, same lap"""

    ahead: int  # slot
    behind: int
    car_class: str
    position: int  # class place of car ahead
    gap: float  # seconds
    trend: float  # gap change, seconds per second (negative: closing)
    since: float  # session time battle started


class PitStop(NamedTuple):
    """Visit of a car to the pit lane"""

    lap: int  # lap of pit entry
    time: float  # session time of pit entry
    duration: float  # seconds in pit lane, 0 while still there
    stopped: float = 0.0  # seconds stopped in pit box


class LapRecord(NamedTuple):
    """Lap of a car seen by the watcher"""

    lap: int  # lap number
    time: float  # lap time (seconds), 0 if none
    sectors: tuple[float, float, float]  # sector times (seconds), -1 if unknown
    pit: bool  # lap with a visit to the pit lane
    energy: float  # virtual energy (else fuel) used (fraction), -1 if unknown (hidden, refilled)
    position: int  # class place at lap end


class LapHistory:
    """Laps of a car seen by the watcher, oldest first, at most LAP_LIMIT (packed: about 50 bytes a lap), read as
    LapRecord"""

    __slots__ = ("_lap", "_time", "_sectors", "_pit", "_energy", "_position")

    def __init__(self) -> None:
        self._lap = array("i")
        self._time = array("d")
        self._sectors = array("d")  # 3 per lap
        self._pit = bytearray()
        self._energy = array("d")
        self._position = array("i")

    def __len__(self) -> int:
        return len(self._lap)

    def __getitem__(self, index: int) -> LapRecord:
        count = len(self._lap)
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError("lap index out of range")
        sectors = self._sectors
        return LapRecord(self._lap[index], self._time[index],
                         (sectors[index * 3], sectors[index * 3 + 1], sectors[index * 3 + 2]),
                         bool(self._pit[index]), self._energy[index], self._position[index])

    def __iter__(self) -> Iterator[LapRecord]:
        return (self[index] for index in range(len(self._lap)))

    def __reversed__(self) -> Iterator[LapRecord]:
        return (self[index] for index in range(len(self._lap) - 1, -1, -1))

    def append(self, record: LapRecord) -> None:
        self._lap.append(record.lap)
        self._time.append(record.time)
        self._sectors.extend(record.sectors)
        self._pit.append(1 if record.pit else 0)
        self._energy.append(record.energy)
        self._position.append(record.position)
        if len(self._lap) > LAP_LIMIT:
            for column in (self._lap, self._time, self._pit, self._energy, self._position):
                del column[0]
            del self._sectors[:3]


class CarState:
    """What the watcher remembers of a car between answers"""

    __slots__ = ("in_pit", "pit_since", "finish", "penalties", "best", "still_since", "stopped",
                 "place", "pending", "pending_since", "stint_lap", "slow_since", "slow", "box_since", "box_time",
                 "laps", "lap_pit", "lap_energy", "stopped_at", "speeds")

    def __init__(self, car: Standing, place: int, now: float):
        self.in_pit = car.in_pit
        self.pit_since = now if car.in_pit else -1.0
        self.finish = car.finish
        self.penalties = car.penalties
        self.best = car.best
        self.still_since = -1.0  # session time car stopped moving, -1 if moving
        self.stopped = False  # stopped car told (once until it moves again)
        self.stopped_at = -1e9  # session time stopped car was told (same incident not told as slow car after)
        self.speeds: deque[tuple[float, float]] = deque()  # (session time, speed) of last seconds
        self.place = place  # class place settled
        self.pending = place  # class place seen, not settled yet
        self.pending_since = now
        # Laps completed at last pit exit: from the start if the car never stopped, else unknown until seen
        self.stint_lap = 0 if car.pitstops <= 0 and not car.in_pit else -1
        self.slow_since = -1.0  # session time car got slow, -1 if not
        self.slow = False  # slow car told (once until it goes again)
        self.box_since = now if car.pit_state == "STOPPED" else -1.0  # session time stopped in pit box
        self.box_time = 0.0  # seconds stopped in pit box during this visit to the pit lane
        self.laps = car.laps  # laps completed seen
        self.lap_pit = car.in_pit  # lap with a visit to the pit lane
        self.lap_energy = level(car)  # energy (else fuel) at lap start, -1 if unknown


def is_race(session: str) -> bool:
    """Race session (RACE1...): battles, overtakes, pit stops, stopped cars"""
    return session.upper().startswith("RACE")


def class_places(cars: list[Standing]) -> dict[int, int]:
    """Class place of each car (slot): standings are by overall place"""
    counts: dict[str, int] = {}
    places = {}
    for car in sorted(cars, key=lambda item: (item.position <= 0, item.position)):
        counts[car.car_class] = counts.get(car.car_class, 0) + 1
        places[car.slot] = counts[car.car_class]
    return places


def track_gap(ahead: Standing, behind: Standing, track_length: float) -> float:
    """Seconds the car behind needs to reach where the car ahead is on track, -1 if not right behind it
    (a lap or more apart, or ahead of it): game gives no time gap to cars laps behind the leader"""
    if track_length <= 0:  # no track length: game gaps, same lap only
        if ahead.laps_behind != behind.laps_behind or behind.gap <= 0:
            return -1.0
        return behind.gap - ahead.gap
    distance = (ahead.laps - behind.laps) * track_length + ahead.distance - behind.distance
    if not 0 <= distance < track_length * 0.5:
        return -1.0
    return distance / max(behind.speed, MIN_SPEED)


def level(car: Standing) -> float:
    """Virtual energy left (else fuel), -1 if hidden"""
    return car.energy if car.energy >= 0 else car.fuel


def last_sectors(car: Standing) -> tuple[float, float, float]:
    """Sector times of last lap (game gives sector 2 with sector 1 in it), -1 if unknown"""
    first, second = car.last_sector1, car.last_sector2
    sector1 = first if first > 0 else -1.0
    sector2 = second - first if first > 0 and second > first else -1.0
    sector3 = car.last - second if second > 0 and car.last > second else -1.0
    return sector1, sector2, sector3


def current_sectors(car: Standing) -> tuple[float, float, float]:
    """Sector times of current lap done so far (sector 3 never: lap not over), -1 if not done"""
    first, second = car.current_sector1, car.current_sector2
    sector1 = first if first > 0 and car.sector >= 2 else -1.0
    sector2 = second - first if sector1 > 0 and second > first and car.sector >= 3 else -1.0
    return sector1, sector2, -1.0


ALONGSIDE = 6.0  # meters: car alongside in the pit lane
PIT_REACH = 150.0  # meters: cars of the pit lane this close shown by the pit radar


class PitNeighbour(NamedTuple):
    """Car near another one in the pit lane"""

    slot: int
    distance: float  # meters along the lap, positive ahead, negative behind
    alongside: bool


def pit_radar(car: Standing, cars: list[Standing], track_length: float,
              reach: float = PIT_REACH) -> list[PitNeighbour]:
    """Cars in the pit lane near a car in the pit lane (closest first), empty if it is not there"""
    if not car.in_pit or car.garage or track_length <= 0:
        return []
    half = track_length / 2
    result = []
    for other in cars:
        if other.slot == car.slot or not other.in_pit or other.garage:
            continue
        distance = (other.distance - car.distance + half) % track_length - half
        if abs(distance) <= reach:
            result.append(PitNeighbour(other.slot, distance, abs(distance) < ALONGSIDE))
    result.sort(key=lambda neighbour: abs(neighbour.distance))
    return result


def running(car: Standing) -> bool:
    """Car racing on track: not in pit lane or garage, not finished or out"""
    return not car.in_pit and not car.garage and car.finish == "FSTAT_NONE"


class RaceWatcher:
    """Race events of every car, from game answers one after another"""

    def __init__(self, battle_gap: float = 1.0):
        self.battle_gap = battle_gap
        self.reset()

    def reset(self) -> None:
        """Another session, or session time jumped: watched again from next answer, nothing told"""
        self.now = -1.0
        self.cars: dict[int, CarState] = {}
        self.class_best: dict[str, float] = {}
        self.battles: dict[tuple[int, int], Battle] = {}
        self.seen_incidents: set[tuple[float, str, str]] = set()
        self.pit_stops: dict[int, list[PitStop]] = {}
        self.finished_classes: set[str] = set()
        self.track_length = 0.0
        self.laps: dict[int, LapHistory] = {}
        self.sector_best: dict[int, list[float]] = {}  # slot: best time of each sector (laps seen, best lap)
        self.contacts_seen: tuple[Contact, ...] | None = None  # contacts list last merged
        self.contacts_ahead = False  # incidents of that list not happened yet (replay): merged again
        self.severity: dict[str, float] = {}  # contact event key: speed lost (0 to 1), measured as it comes
        self.severity_version = 0  # severities changed
        self.measuring: list[Event] = []  # contacts still being measured
        self.usual_speed: dict[int, tuple[float, int]] = {}  # part of the lap: usual speed (m/s), samples
        self.session = SessionState()

    def update(self, cars: list[Standing], contacts: tuple[Contact, ...], now: float, session: str,
               track_length: float = 0.0, info: SessionState | None = None) -> list[Event]:
        """Events since last answer, oldest first. First answer (or after a jump): contacts already listed
        come back as history (live False), nothing else is told"""
        if now < 0:
            return []
        jumped = self.now >= 0 and (now < self.now - 1.0 or now > self.now + JUMP)
        if jumped:
            stops, known, laps, speeds, sectors = (self.pit_stops, self.seen_incidents, self.laps, self.usual_speed,
                                                   self.sector_best)
            self.reset()
            self.pit_stops = stops  # stops & laps seen stay true (replay seek), incidents not told twice
            self.seen_incidents = known
            self.laps = laps
            self.usual_speed = speeds
            self.sector_best = sectors
        first = self.now < 0
        self.track_length = track_length
        previous_time, self.now = self.now, now
        race = is_race(session)
        places = class_places(cars)
        by_slot = {car.slot: car for car in cars}
        events = self.contact_events(contacts, cars, now, first)
        session_state = info if info is not None else SessionState()
        green = session_state.phase in (-1, GREEN_PHASE) and session_state.yellow in ("NONE", "INVALID", "")
        if not first:
            events.extend(self.flag_events(session_state, cars, now, race))
        self.session = session_state
        self.learn_speeds(cars)
        if first:
            for car in cars:
                self.cars[car.slot] = CarState(car, places[car.slot], now)
                self.note_best(car)
                if car.finish == "FSTAT_FINISHED":
                    self.finished_classes.add(car.car_class)
            self.update_battles(cars, places, now, 0.0, race)
            return events
        elapsed = max(now - previous_time, 0.0)
        self.keep_speeds(cars, now)
        stopped_now = 0
        for car in cars:
            state = self.cars.get(car.slot)
            if state is None:  # joined the session
                self.cars[car.slot] = CarState(car, places[car.slot], now)
                self.note_best(car)
                continue
            events.extend(self.car_events(car, state, places[car.slot], by_slot, now, race))
            if state.still_since >= 0 and now - state.still_since >= STOP_TIME:
                stopped_now += 1
        # Cars standing still: many at once is a halted race (grid, red flag), not news
        halted = stopped_now >= max(2, len(cars) * HALTED_SHARE)
        for car in cars:
            state = self.cars[car.slot]
            if (race and not halted and not state.stopped and state.still_since >= 0
                    and now - state.still_since >= STOP_TIME and car.laps >= 1 and running(car)):
                state.stopped = True
                state.stopped_at = now
                events.append(self.event(STOPPED, state.still_since, (car,)))
            self.check_slow(car, state, now, race and green and not halted, events)
        for slot in set(self.cars) - set(by_slot):  # left the session
            del self.cars[slot]
        events.extend(self.update_battles(cars, places, now, elapsed, race))
        events.sort(key=lambda event: event.time)
        self.measuring.extend(event for event in events if event.kind in (CONTACT, WALL) and event.live)
        self.measure_contacts(events, now)
        return events

    # Contact severity
    def keep_speeds(self, cars: list[Standing], now: float) -> None:
        for car in cars:
            state = self.cars.get(car.slot)
            if state is None:
                continue
            state.speeds.append((now, car.speed))
            while state.speeds and now - state.speeds[0][0] > SPEED_HISTORY:
                state.speeds.popleft()

    def measure_contacts(self, events: list[Event], now: float) -> None:
        """Speed lost by the cars of recent contacts: highest speed before, lowest after (a car that stops
        or crawls after a contact: heavy)"""
        followed = {slot for event in events if event.kind in (STOPPED, SLOW) for slot in event.slots}
        measuring = []
        for event in self.measuring:
            lost = -1.0
            for slot in event.slots:
                state = self.cars.get(slot)
                if state is None:
                    continue
                before = [speed for time, speed in state.speeds if event.time - BEFORE_CONTACT <= time <= event.time]
                after = [speed for time, speed in state.speeds if event.time < time <= event.time + AFTER_CONTACT]
                if slot in followed:
                    lost = 1.0
                elif before and after and max(before) >= MOVING:
                    lost = max(lost, 1.0 - min(after) / max(before))
            if lost >= 0 and self.severity.get(event.key) != round(lost, 2):
                self.severity[event.key] = round(min(max(lost, 0.0), 1.0), 2)
                self.severity_version += 1
                if len(self.severity) > FEED_LIMIT:  # contacts of the feed only (oldest measured first)
                    del self.severity[next(iter(self.severity))]
            if now - event.time < AFTER_CONTACT + 1.0:
                measuring.append(event)
        self.measuring = measuring

    # Each car
    def car_events(self, car: Standing, state: CarState, place: int, by_slot: dict[int, Standing], now: float,
                   race: bool) -> list[Event]:
        events: list[Event] = []
        # Laps
        if car.laps > state.laps:
            self.record_lap(car, state, place)
        if car.in_pit:
            state.lap_pit = True
        # Pit box: stationary time of the visit
        if car.pit_state == "STOPPED":
            if state.box_since < 0:
                state.box_since = now
        elif state.box_since >= 0:
            state.box_time += now - state.box_since
            state.box_since = -1.0
        # Pit lane
        if car.in_pit and not state.in_pit:
            state.pit_since = now
            state.box_time = 0.0
            if race and not car.garage:
                events.append(self.event(PIT_IN, now, (car,), place))
                self.pit_stops.setdefault(car.slot, []).append(PitStop(car.laps + 1, now, 0.0))
        elif state.in_pit and not car.in_pit:
            duration = now - state.pit_since if state.pit_since >= 0 else 0.0
            if state.box_since >= 0:
                state.box_time += now - state.box_since
                state.box_since = -1.0
            stops = self.pit_stops.get(car.slot)
            if stops and stops[-1].duration <= 0:
                stops[-1] = stops[-1]._replace(duration=duration, stopped=state.box_time)
            state.stint_lap = car.laps
            if race and stops:
                events.append(self.event(PIT_OUT, now, (car,), place, duration)._replace(extra=state.box_time))
            state.pit_since = -1.0
        state.in_pit = car.in_pit
        # Finish, retirement
        if car.finish != state.finish:
            if car.finish == "FSTAT_FINISHED":
                kind = WINNER if car.car_class not in self.finished_classes else FINISH
                self.finished_classes.add(car.car_class)
                events.append(self.event(kind, now, (car,), place))
            elif car.finish in ("FSTAT_DNF", "FSTAT_DQ"):
                events.append(self.event(RETIRED, now, (car,), place, 1.0 if car.finish == "FSTAT_DQ" else 0.0))
            state.finish = car.finish
        # Penalties
        if car.penalties > state.penalties:
            events.append(self.event(PENALTY, now, (car,), place, float(car.penalties)))
        state.penalties = car.penalties
        # Fastest lap of class
        if car.best > 0 and (state.best <= 0 or car.best < state.best - 0.0005):
            best = self.class_best.get(car.car_class, 0.0)
            if best > 0 and car.best < best - 0.0005:
                events.append(self.event(FASTEST, now, (car,), place, car.best))
            self.note_best(car)
        state.best = car.best
        # Standing still on track
        if car.speed < STOP_SPEED and running(car):
            if state.still_since < 0:
                state.still_since = now
        else:
            state.still_since = -1.0
            if car.speed >= MOVE_AGAIN or not running(car):
                state.stopped = False
        # Class place: settled once seen SETTLE seconds (side by side cars swap places)
        if place != state.pending:
            state.pending, state.pending_since = place, now
        elif place != state.place and now - state.pending_since >= SETTLE:
            old, state.place = state.place, place
            if race and place < old and running(car):
                passed = self.passed_car(car, place, old, by_slot)
                if passed is not None:
                    events.append(self.event(LEAD if place == 1 else OVERTAKE, now, (car, passed), place))
        return events

    def record_lap(self, car: Standing, state: CarState, place: int) -> None:
        """Lap just completed: time, sectors, pit lane visit, energy used"""
        energy = level(car)
        used = state.lap_energy - energy if state.lap_energy >= 0 and 0 <= energy <= state.lap_energy else -1.0
        if car.laps == state.laps + 1:  # one lap (several at once: replay seek, joined late)
            laps = self.laps.get(car.slot)
            if laps is None:
                laps = self.laps[car.slot] = LapHistory()
            record = LapRecord(car.laps, car.last, last_sectors(car), state.lap_pit, used, place)
            laps.append(record)
            self.note_sectors(car.slot, record.sectors)
        state.laps = car.laps
        state.lap_pit = car.in_pit
        state.lap_energy = energy

    # Slow cars
    def learn_speeds(self, cars: list[Standing]) -> None:
        """Usual speed of each part of the lap, from every car running there"""
        if self.track_length <= 0:
            return
        for car in cars:
            if running(car) and car.speed > STOP_SPEED:
                part = int(car.distance // SPEED_BIN)
                usual, samples = self.usual_speed.get(part, (car.speed, 0))
                # Faster cars weigh more: the usual speed is the speed of a car going well there
                weight = SPEED_SMOOTHING * (2.0 if car.speed > usual else 0.5)
                self.usual_speed[part] = (usual + (car.speed - usual) * weight, samples + 1)

    def usual_speed_at(self, car: Standing) -> float:
        """Usual speed where the car is (m/s), 0 if not known yet"""
        usual, samples = self.usual_speed.get(int(car.distance // SPEED_BIN), (0.0, 0))
        return usual if samples >= SPEED_SAMPLES else 0.0

    def check_slow(self, car: Standing, state: CarState, now: float, watched: bool, events: list[Event]) -> None:
        """Car going much slower than usual at that place of the track (not stopped: told apart)"""
        usual = self.usual_speed_at(car)
        if not watched or usual <= 0 or not running(car) or car.laps < 1:
            state.slow_since = -1.0
            if not running(car):
                state.slow = False
            return
        if car.speed >= usual * RECOVERED_SHARE:
            state.slow_since = -1.0
            state.slow = False
        elif STOP_SPEED <= car.speed < usual * SLOW_SHARE:
            if state.slow_since < 0:
                state.slow_since = now
            elif (not state.slow and not state.stopped and now - state.slow_since >= SLOW_TIME
                  and now - state.stopped_at > LIFETIME[STOPPED]):
                state.slow = True
                events.append(self.event(SLOW, state.slow_since, (car,), value=car.speed))

    # Flags
    def flag_events(self, session: SessionState, cars: list[Standing], now: float, race: bool) -> list[Event]:
        """Full course yellow start & end, yellow flag in a sector (slowest car of that sector shown)"""
        events = []
        before, after = self.session.yellow in ("NONE", "INVALID", ""), session.yellow in ("NONE", "INVALID", "")
        if before and not after:
            events.append(Event(f"{FCY}|{now:.1f}", FCY, now, (), (), "", live=race))
        elif after and not before and self.session.phase in (GREEN_PHASE, 6) and session.phase == GREEN_PHASE:
            events.append(Event(f"{GREEN}|{now:.1f}", GREEN, now, (), (), "", live=race))
        for sector, yellow in enumerate(session.sector_flags, 1):
            was = len(self.session.sector_flags) >= sector and self.session.sector_flags[sector - 1]
            if yellow and not was:
                suspects = [car for car in cars if running(car) and car.sector == sector]
                slowest = min(suspects, key=lambda car: car.speed / max(self.usual_speed_at(car), car.speed, 1.0),
                              default=None)
                if slowest is not None and slowest.speed < max(self.usual_speed_at(slowest), 1.0) * RECOVERED_SHARE:
                    events.append(self.event(YELLOW, now, (slowest,), value=float(sector)))
                else:
                    events.append(Event(f"{YELLOW}|{now:.1f}|s{sector}", YELLOW, now, (), (), "",
                                        value=float(sector)))
        return events

    # Laps & sectors
    def note_sectors(self, slot: int, sectors: tuple[float, float, float]) -> None:
        """Sector times of a lap of a car: its best sectors kept"""
        best = self.sector_best.setdefault(slot, [-1.0, -1.0, -1.0])
        for index, value in enumerate(sectors):
            if value > 0 and (best[index] <= 0 or value < best[index]):
                best[index] = value

    def best_sectors(self, cars: list[Standing]) -> tuple[dict[int, list[float]], dict[str, list[float]]]:
        """Best time of each sector of every car (laps seen & sectors of its best lap) and of every class,
        -1 if none: kept as laps come, so asking each second costs little"""
        classes: dict[str, list[float]] = {}
        for car in cars:
            first, second = car.best_sector1, car.best_sector2
            if first > 0:  # sectors of best lap (game): new best lap brings them
                self.note_sectors(car.slot, (first, second - first if second > first else -1.0,
                                             car.best - second if second > 0 and car.best > second else -1.0))
            best = self.sector_best.get(car.slot)
            if best is None:
                continue
            class_best = classes.setdefault(car.car_class, [-1.0, -1.0, -1.0])
            for index, value in enumerate(best):
                if value > 0 and (class_best[index] <= 0 or value < class_best[index]):
                    class_best[index] = value
        return self.sector_best, classes

    def energy_average(self, slot: int, count: int) -> float:
        """Energy (else fuel) used per lap over the last laps of the stint (no pit lap), -1 if not enough laps"""
        used = []
        for record in reversed(self.laps.get(slot, ())):
            if record.pit:
                break
            if record.energy >= 0:
                used.append(record.energy)
            if len(used) == count:
                break
        return sum(used) / count if len(used) == count else -1.0

    def passed_car(self, car: Standing, place: int, old: int, by_slot: dict[int, Standing]) -> Standing | None:
        """Car of same class passed on track (one place behind now, ahead before), None if it lost its place
        in the pits or by stopping (no overtake then)"""
        for slot, state in self.cars.items():
            other = by_slot.get(slot)
            if other is None or slot == car.slot or other.car_class != car.car_class:
                continue
            if state.pending == place + 1 and state.place < old:
                if not running(other) or state.still_since >= 0:
                    return None
                return other
        return None

    def note_best(self, car: Standing) -> None:
        if car.best > 0:
            best = self.class_best.get(car.car_class, 0.0)
            if best <= 0 or car.best < best:
                self.class_best[car.car_class] = car.best

    # Contacts
    def contact_events(self, contacts: tuple[Contact, ...], cars: list[Standing], now: float,
                       first: bool) -> list[Event]:
        """Contacts not told yet: news if recent, history if listed before the page watched (or long ago)"""
        events: list[Event] = []
        if not first and contacts == self.contacts_seen and not self.contacts_ahead:
            return events  # long races list hundreds of contacts: merged again only when the list changes
        self.contacts_seen, self.contacts_ahead = contacts, False
        slots = {car.driver: car for car in cars}
        listed: set[tuple[float, str, str]] = set()
        for incident in merge_contacts(contacts):
            key = (incident.time, incident.driver, incident.other)
            listed.add(key)
            if key in self.seen_incidents:
                continue
            if incident.time > now + 1.0:  # replay: not happened yet
                self.contacts_ahead = True
                continue
            self.seen_incidents.add(key)
            driver = slots.get(incident.driver)
            other = slots.get(incident.other) if incident.other != IMMOVABLE else None
            wall = incident.other == IMMOVABLE
            live = not first and now - incident.time <= CONTACT_LIVE
            events.append(Event(
                key=f"{WALL if wall else CONTACT}|{incident.time:.1f}|{incident.driver}|{incident.other}",
                kind=WALL if wall else CONTACT,
                time=incident.time,
                slots=tuple(car.slot for car in (driver, other) if car is not None),
                drivers=(incident.driver,) if wall else (incident.driver, incident.other),
                car_class=driver.car_class if driver is not None else "",
                value=float(incident.contacts),
                live=live and driver is not None,
            ))
        if listed and len(self.seen_incidents) > 2 * len(listed) + 100:  # game list cut: gone ones never listed again
            self.seen_incidents &= listed
        return events

    # Battles
    def update_battles(self, cars: list[Standing], places: dict[int, int], now: float, elapsed: float,
                       race: bool) -> list[Event]:
        """Battles of each class (races only), new ones told"""
        if not race:
            self.battles.clear()
            return []
        by_class: dict[str, list[Standing]] = {}
        for car in cars:
            if car.position > 0:
                by_class.setdefault(car.car_class, []).append(car)
        battles: dict[tuple[int, int], Battle] = {}
        events = []
        for class_cars in by_class.values():
            class_cars.sort(key=lambda item: item.position)
            for ahead, behind in pairwise(class_cars):
                if not (running(ahead) and running(behind)):
                    continue
                gap = track_gap(ahead, behind, self.track_length)
                pair = (ahead.slot, behind.slot)
                known = self.battles.get(pair)
                limit = self.battle_gap + (BATTLE_END_MARGIN if known is not None else 0.0)
                if not 0 <= gap < limit:
                    continue
                if known is None:
                    battle = Battle(ahead.slot, behind.slot, ahead.car_class, places[ahead.slot], gap, 0.0, now)
                    events.append(self.event(BATTLE, now, (behind, ahead), places[ahead.slot], gap))
                else:
                    rate = (gap - known.gap) / elapsed if elapsed > 0 else known.trend
                    trend = known.trend + (rate - known.trend) * TREND_SMOOTHING
                    battle = known._replace(gap=gap, trend=trend, position=places[ahead.slot])
                battles[pair] = battle
        self.battles = battles
        return events

    @staticmethod
    def event(kind: str, time: float, cars: tuple[Standing, ...], position: int = 0, value: float = 0.0) -> Event:
        slots = tuple(car.slot for car in cars)
        return Event(
            key=f"{kind}|{time:.1f}|{'-'.join(map(str, slots))}",
            kind=kind,
            time=time,
            slots=slots,
            drivers=tuple(car.driver for car in cars),
            car_class=cars[0].car_class,
            position=position,
            value=value,
        )

    def stint_laps(self, car: Standing) -> int:
        """Laps since last pit exit (since the start if the car never stopped), -1 if its last stop was not seen"""
        state = self.cars.get(car.slot)
        if state is None:
            return car.laps if car.pitstops <= 0 else -1
        return max(car.laps - state.stint_lap, 0) if state.stint_lap >= 0 else -1


# Shots
@dataclass
class DirectorSettings:
    """How the director cuts (seconds of real time)"""

    min_shot: float = 8.0  # shortest shot, unless an urgent event comes
    max_shot: float = 30.0  # longest shot on the same story
    urgent_after: float = 2.5  # an urgent event cuts a shot this old at least
    interrupt_margin: float = 25.0  # score an event needs over current shot to cut it short
    switch_margin: float = 10.0  # score another story needs over current one after the shortest shot
    repeat_cooldown: float = 25.0  # a car just shown is less wanted this long
    repeat_penalty: float = 20.0
    manual_hold: float = 20.0  # operator cut: no automatic cut this long
    camera_style: str = "mixed"  # see CAMERA_STYLES
    battle_gap: float = 1.0  # seconds between two cars of a class: battle


class Candidate(NamedTuple):
    """Story worth showing: car to follow & why"""

    slot: int
    kind: str
    score: float
    key: str  # event key, battle key or roam key: same story while it stays
    event: Event | None = None
    battle: Battle | None = None


class Shot(NamedTuple):
    """Car & camera on air"""

    slot: int
    camera: str  # camera key, "" if left as it is
    kind: str
    key: str
    start: float  # clock


def place_bonus(position: int) -> float:
    """Front of class matters more: +10 for the lead, nothing from 6th"""
    return max(0.0, 10.0 - (position - 1) * 2.0) if position > 0 else 0.0


@dataclass
class Director:
    """Picks the next shot from race events & battles"""

    settings: DirectorSettings = field(default_factory=DirectorSettings)
    shot: Shot | None = None
    hold_until: float = 0.0  # clock: operator cut held until then
    shown: dict[int, float] = field(default_factory=dict)  # slot: clock it was last on air
    turns: dict[str, int] = field(default_factory=dict)  # kind: shots of that kind (cameras used in turn)

    def candidates(self, events: list[Event], battles: list[Battle], cars: list[Standing], now: float,
                   clock: float, race: bool, start: bool = False,
                   severity: dict[str, float] | None = None, seen: set[str] | frozenset[str] = frozenset(),
                   gained: dict[int, int] | None = None) -> list[Candidate]:
        """Stories worth showing, best first: race start (leader), live events still fresh, battles, then
        any car (roam)

        Args:
            seen: events already shown (on air, replayed, looked at): less wanted, never shown twice in a row.
            gained: class places gained since the start of each car (slot): cars climbing through the field
                are more wanted, also in their battles.
        """
        gained = gained or {}
        on_track = {car.slot: car for car in cars if not car.garage}
        result = []
        leader = next((car for car in cars if car.position == 1), None)
        if start and race and leader is not None and not leader.garage:
            result.append(Candidate(leader.slot, START, float(PRIORITY[START]), f"start|{leader.slot}"))
        for event in events:
            lifetime = LIFETIME.get(event.kind, 0.0)
            age = now - event.time
            if (lifetime <= 0 or not event.live or not event.slots or event.slots[0] not in on_track
                    or not 0 <= age <= lifetime):  # battles: shown while they last (battles list)
                continue
            base = float(PRIORITY[event.kind])
            if event.kind == FASTEST and not race:
                base = QUALIFY_FASTEST
            lost = severity.get(event.key, -1.0) if severity else -1.0
            if event.kind in (CONTACT, WALL) and lost >= HEAVY:  # big hit: before anything else
                base = PRIORITY[WINNER] + 5
            elif event.kind in (CONTACT, WALL) and 0 <= lost < LIGHT:  # touch, cars went on: minor story
                base *= 0.55
            score = base * (1.0 - 0.5 * age / lifetime) + place_bonus(event.position)
            if event.key in seen:  # shown already: not shown again unless nothing better
                score *= SEEN_SHARE
            result.append(Candidate(event.slots[0], event.kind, score, event.key, event=event))
        for battle in battles:
            if battle.behind not in on_track:
                continue
            closeness = max(0.0, 1.0 - battle.gap / max(self.settings.battle_gap, 0.1)) * 15.0
            closing = 5.0 if battle.trend < -0.02 else 0.0
            # Overtake coming: very close and closing fast
            imminent = IMMINENT_BONUS if battle.gap < IMMINENT_GAP and battle.trend < IMMINENT_TREND else 0.0
            climbing = min(max(gained.get(battle.behind, 0), 0), 10) * CLIMB_BONUS
            score = PRIORITY[BATTLE] + place_bonus(battle.position) + closeness + closing + imminent + climbing
            result.append(Candidate(battle.behind, BATTLE, score, f"battle|{battle.ahead}-{battle.behind}",
                                    battle=battle))
        # Roam: cars by place, the one not shown for longest first (leaders a little more wanted)
        ordered = sorted((car for car in on_track.values() if car.position > 0 and not car.in_pit),
                         key=lambda car: car.position)
        for car in ordered:
            unseen = clock - self.shown.get(car.slot, -1e9)
            score = PRIORITY[ROAM] + min(unseen, 120.0) / 30.0 + place_bonus(car.position) * 0.3
            if race and gained.get(car.slot, 0) >= CLIMB_PLACES:  # comeback through the field: worth following
                score += min(gained[car.slot], 10) * CLIMB_BONUS
            result.append(Candidate(car.slot, ROAM, score, f"roam|{car.slot}"))
        # Car just shown (not the one on air): less wanted for a while
        current = self.shot.slot if self.shot is not None else -1
        adjusted = []
        for candidate in result:
            last = self.shown.get(candidate.slot)
            if candidate.slot != current and last is not None and clock - last < self.settings.repeat_cooldown:
                candidate = candidate._replace(score=candidate.score - self.settings.repeat_penalty)
            adjusted.append(candidate)
        adjusted.sort(key=lambda candidate: candidate.score, reverse=True)
        return adjusted

    def decide(self, candidates: list[Candidate], clock: float) -> Candidate | None:
        """Story to cut to now, None to keep the shot on air"""
        if not candidates or clock < self.hold_until:
            return None
        best = candidates[0]
        if self.shot is None:
            return best
        settings = self.settings
        elapsed = clock - self.shot.start
        same = next((candidate for candidate in candidates if candidate.key == self.shot.key), None)
        current_score = same.score if same is not None else 0.0
        others = [candidate for candidate in candidates if candidate.slot != self.shot.slot]
        if elapsed < settings.min_shot:
            if (best.kind in URGENT and best.key != self.shot.key and elapsed >= settings.urgent_after
                    and best.score >= current_score + settings.interrupt_margin):
                return best
            return None
        if same is not None and same.kind != ROAM and elapsed < settings.max_shot:
            if best.key != self.shot.key and best.score > current_score + settings.switch_margin:
                return best
            return None
        # Nothing happening: cars shown in turn, a little longer each (no restless cutting)
        if self.shot.kind == ROAM and best.kind == ROAM and elapsed < settings.min_shot * ROAM_LENGTH:
            return None
        # Story over (or shown long enough): another car if any
        if others:
            return others[0]
        return None if same is not None else best

    def camera_for(self, kind: str) -> str:
        """Camera of next shot of that kind (cameras of kind used in turn), "" to leave camera as it is"""
        style = self.settings.camera_style
        if style == "keep":
            return ""
        plan = STYLE_CAMERAS.get(style) or CAMERA_PLAN.get(kind) or CAMERA_PLAN[ROAM]
        turn = self.turns.get(kind, 0)
        self.turns[kind] = turn + 1
        return plan[turn % len(plan)]

    def take(self, candidate: Candidate, clock: float) -> Shot:
        """Story cut to: shot on air from now (overtake coming: onboard of the car behind, with mixed cameras)"""
        self.leave(clock)
        battle = candidate.battle
        if (battle is not None and self.settings.camera_style == "mixed" and battle.gap < IMMINENT_GAP
                and battle.trend < IMMINENT_TREND):
            camera = OVERTAKE_CAMERA
        else:
            camera = self.camera_for(candidate.kind)
        self.shot = Shot(candidate.slot, camera, candidate.kind, candidate.key, clock)
        return self.shot

    def manual(self, slot: int, camera: str, clock: float) -> Shot:
        """Operator cut: held a while before the director cuts again"""
        self.leave(clock)
        self.shot = Shot(slot, camera, MANUAL, f"manual|{slot}", clock)
        self.hold_until = clock + self.settings.manual_hold
        return self.shot

    def leave(self, clock: float) -> None:
        if self.shot is not None:
            self.shown[self.shot.slot] = clock

    def reset(self) -> None:
        self.shot = None
        self.hold_until = 0.0
        self.shown.clear()
        self.turns.clear()
