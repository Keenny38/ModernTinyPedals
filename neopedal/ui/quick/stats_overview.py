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
Driver stats viewer part (StatsOverview, mixin of DriverStatsBackend): All Tracks: driver card, daily driving activity, recent sessions
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from PySide6.QtCore import Property, QDateTime, QLocale, QUrl, Slot

from ... import calculation as calc
from ...i18n import current_language, tr, trm
from ...process import results_index as ri
from ...process.results_text import MISSING, laptime_text
from ...rank_info import online_enabled, ranks
from ...setting import cfg
from ..lap_viewer import signed
from .formatting import country_name, date_locale, format_date, format_day, localized_number
from .stats_analysis import (
    Upcoming,
    average_gained,
    clean_streak,
    distribution,
    history_years,
    period_bounds,
    record_day,
    rivals,
    stats_track,
    weekly_progress,
)
from .stats_common import (
    ACTIVITY_STEPS,
    ACTIVITY_WEEKS,
    ALL_TRACKS,
    RECENT_SESSIONS,
    UPCOMING_EVERY,
    badge_card,
    format_duration,
    level_letter,
    level_text,
    other_account_rows,
    plural,
    race_result,
    rank_info_text,
    rank_rows,
    result_tone,
    session_code,
    session_kind,
    session_name,
    valid_laptime,
)
from .stats_core import StatsCore
from .stats_io import (
    StatsHost,
    read_official_races,
)

logger = logging.getLogger(__name__)
MAX_WEEKLY_ROWS = 6  # rows of the progress card (most important first: goals reached, records, goals near)


def race_preparation():
    """prepare_race(parent, track, vehicle, lap_time) of the race calculator, None if it has none (looked up
    when a menu opens: the calculator page is imported only then)"""
    try:
        from .. import race_calculator
    except ImportError:
        return None
    prepare = getattr(race_calculator, "prepare_race", None)
    return prepare if callable(prepare) else None


class StatsOverview(StatsHost):
    """All Tracks: driver card, daily driving activity, recent sessions"""

    def driver_card(self) -> dict:
        """Driver card, made again only when results, fixes or ranks changed"""
        from ...userfile.badge_icons import icons

        key = (self._results_serial, len(self._fixes), current_language(), ranks.serial, icons.version)
        if key != self._driver_key:
            self._driver_key = key
            self._driver = self.driver_data()
        return self._driver

    def driver_data(self) -> dict:
        """Driver card (All Tracks): game profile, Steam picture, races of results files, lap times to complete"""
        profile = self.profile
        races = [summary for summary in self.results if summary.kind == "Race"]
        player = ranks.player
        others = ranks.others
        if profile is None and not races and player is None and not others:
            return {"visible": False}
        if profile is not None:
            name = profile.name
        else:
            name = races[-1].driver if races else player.name if player is not None else ""
        details = []
        if profile is not None:
            details = [country_name(profile.nationality), profile.team, f"#{profile.number}" if profile.number else ""]
        figures = []
        if races:
            record = ri.race_record(races)
            gained, counted = average_gained(races)
            streak = clean_streak(races)
            figures = [
                {"label": tr("Races"), "value": str(record.races)},
                {"label": tr("Wins"), "value": str(record.wins)},
                {"label": tr("Podiums"), "value": str(record.podiums)},
                {"label": tr("Avg. Finish"),
                 "value": f"P{localized_number(record.average_finish, 1)}" if record.average_finish else MISSING},
                {"label": tr("Clean Races"), "value": f"{record.clean}/{record.races}"},
                {"label": tr("Contacts/Race"), "value": localized_number(record.contacts / record.races, 1)},
                {"label": tr("Clean Streak"), "value": str(streak),
                 "tip": tr("Latest races in a row without contact nor penalty")},
                {"label": tr("Places Gained"), "value": signed(gained, 1) if counted else MISSING,
                 "tip": trm(f"Average class places gained from start to finish, {counted} races") if counted else ""},
            ]
        fixes = len(self._fixes)
        return {
            "visible": True,
            "name": name,
            "initials": "".join(word[:1] for word in name.split()[:2]).upper(),
            "detail": " · ".join(part for part in details if part),
            "avatar": QUrl.fromLocalFile(profile.avatar).toString() if profile is not None and profile.avatar else "",
            "figures": figures,
            "ranks": rank_rows(player, ranks.history_of(player.steam_id) if player is not None else ()),
            "ranksInfo": rank_info_text(player),
            "badge": badge_card(player),
            "otherAccounts": other_account_rows(others),
            "info": trm(f"From {len(races)} race results of the game, class positions") if races else "",
            "fixes": fixes,
            "fixText": trm(f"{fixes} lap time(s) found in race results") if fixes else "",
        }

    @Property(dict, notify=StatsCore.driverChanged)
    def driver(self) -> dict:
        """Driver card: name, initials, detail, avatar URL, figures (label, value), ranks (see rank_rows), ranksInfo,
        badge (see badge_card), info, fixes, fixText"""
        return self._driver

    @Slot(str)
    def openResults(self, path: str):
        """Session of results file shown in race results page"""
        if not path:
            return
        from ..tools_view import open_tool

        page = open_tool("race_results_viewer.RaceResultsViewer", self._window)
        backend = getattr(page, "backend", None)
        if backend is not None:
            backend.open_path(path)

    # Daily driving activity of last weeks (or of a year), driving time by track & class, recent sessions
    @property
    def activity_year(self) -> int:
        """Year of daily activity shown, 0 for the last weeks"""
        year = self.viewer_config().get("activity_year", 0)
        return year if isinstance(year, int) and year >= 0 else 0

    def activity_data(self) -> dict:
        """Driving time of each day of last ACTIVITY_WEEKS weeks (or of a year, Monday first), month & day names,
        summary, driving time by track & by class of the period, years with sessions

        Days: level (0 none, 1-4 driving time, -1 future or other year), tooltip. Computed again only when history,
        day or year changes.
        """
        today = date.today()
        year = self.activity_year
        key = (self._history_stamp, today, current_language(), year)
        if key == self._activity_key and self._activity:
            return self._activity
        first_day, last_day = period_bounds(year, today)
        if year:
            start = first_day - timedelta(days=first_day.weekday())
            weeks = ((last_day - start).days + 7) // 7
        else:
            start = today - timedelta(days=today.weekday() + (ACTIVITY_WEEKS - 1) * 7)
            weeks = ACTIVITY_WEEKS
        end = start + timedelta(days=weeks * 7 - 1)
        seconds: dict[date, float] = {}
        sessions: dict[date, int] = {}
        for record in reversed(self.history):  # newest first: older records skipped at once
            day = record_day(record)
            if day is None:
                continue
            if day < start:
                break
            if day > end:
                continue
            seconds[day] = seconds.get(day, 0.0) + record.seconds
            sessions[day] = sessions.get(day, 0) + 1
        days = []
        streak = longest = 0
        for number in range(weeks * 7):
            day = start + timedelta(days=number)
            if day > today or (year and not first_day <= day <= last_day):
                days.append({"level": -1, "tip": ""})
                continue
            count = sessions.get(day, 0)
            driven = seconds.get(day, 0.0)
            streak = streak + 1 if count else 0
            longest = max(longest, streak)
            level = 0 if not count else 1 + sum(driven >= step for step in ACTIVITY_STEPS)
            detail = (f"{plural(count, 'session', 'sessions')} · {format_duration(driven)}" if count
                      else tr("No driving"))
            days.append({"level": level, "tip": f"{format_day(day)}\n{detail}"})
        locale = date_locale()
        months = []
        for week in range(weeks):
            first = start + timedelta(days=week * 7)
            if week == 0 or first.month != (first - timedelta(days=7)).month:
                months.append({"week": week, "text": locale.monthName(first.month, QLocale.FormatType.ShortFormat)})
        driven_days = len(seconds)
        if driven_days:
            summary = " · ".join((
                plural(driven_days, "day driven", "days driven"),
                format_duration(sum(seconds.values())),
                f"{tr('longest streak')} {plural(longest, 'day', 'days')}",
            ))
        elif self.history:
            summary = tr("No driving in this period.")
        else:
            summary = tr("No session recorded yet: history starts with your next session.")
        self._activity_key = key
        years = [{"text": tr("Last 12 Months"), "value": 0}] + [
            {"text": str(number), "value": number} for number in history_years(self.history)]
        if year and all(entry["value"] != year for entry in years):
            years.append({"text": str(year), "value": year})
        tracks, classes = distribution(self.history, first_day, last_day, self.class_of)
        return {"weeks": weeks, "days": days, "months": months, "summary": summary,
                "dayNames": [locale.dayName(number, QLocale.FormatType.ShortFormat) for number in (1, 3, 5)],
                "years": years, "yearIndex": next(index for index, entry in enumerate(years) if entry["value"] == year),
                "tracks": self.share_rows(tracks, True), "classes": self.share_rows(classes, False)}

    def share_rows(self, items: list[tuple[str, float]], tracks: bool) -> list[dict]:
        """Driving time rows: name ("" for other tracks), time, share of the most driven (bar), share of total"""
        top = max((seconds for _, seconds in items), default=0.0)
        total = sum(seconds for _, seconds in items)
        return [{"name": name or tr("Other Tracks"), "time": format_duration(seconds),
                 "ratio": seconds / top if top else 0.0,
                 "share": f"{localized_number(seconds / total * 100, 0)} %" if total else "",
                 "logo": self.logos.track(name) if tracks and name else ""} for name, seconds in items]

    @Slot(int)
    def setActivityYear(self, index: int):
        """Year of daily activity (entry of activity years, 0: last 12 months), saved"""
        years = self._activity.get("years", [])
        value = years[index]["value"] if 0 <= index < len(years) else 0
        self.save_viewer_config(activity_year=value)
        self._activity = self.activity_data()
        self.publish("activity", self._activity, self.activityChanged)

    # People met in online races (results files)
    def rivals_data(self) -> list[dict]:
        """Rivals shown: name, races together, ahead / behind, best lap gap, last race date"""
        rows = []
        summaries = {summary.path: summary for summary in self.results}
        for rival in rivals(self.results):
            track, vehicle = self.result_combo(summaries.get(rival.path))
            rows.append({
                "name": rival.name, "races": rival.races, "ahead": rival.ahead, "behind": rival.behind,
                # last race together: results file, its track & your vehicle in stats ("" if not in stats)
                "path": rival.path, "track": track, "vehicle": vehicle,
                "record": f"{rival.ahead}-{rival.behind}",
                "tone": "gain" if rival.ahead > rival.behind else "loss" if rival.behind > rival.ahead else "",
                "gap": signed(rival.gap, 3) if rival.gap is not None else "",
                "gapTone": "" if rival.gap is None or abs(rival.gap) < 0.0005 else "loss" if rival.gap > 0 else "gain",
                "last": format_date(rival.last),
                "tip": trm(f"{rival.races} online races together, last on {format_date(rival.last)}: finished ahead "
                           f"{rival.ahead} times, behind {rival.behind} times")
                + (("\n" + trm(f"Best lap gap (yours minus theirs, mean): {signed(rival.gap, 3)} s"))
                   if rival.gap is not None else ""),
            })
        return rows

    def result_combo(self, summary: ri.ResultSummary | None) -> tuple[str, str]:
        """Driver stats track & vehicle of a results session ("" when not in stats)"""
        if summary is None:
            return "", ""
        track = next((key for key in self.stats_temp if key and ri.same_track(key, summary)), "")
        vehicles = self.stats_temp.get(track, {}) if track else {}
        if not isinstance(vehicles, dict):
            return track, ""
        vehicle = (self._linked or {}).get(summary.path, "")
        if vehicle not in vehicles:
            vehicle = ri.vehicle_key(summary, vehicles, self.classification(), cfg.user.brands)
        return track, vehicle

    def rivals_card(self) -> list[dict]:
        """Rivals, made again only when results files were read again"""
        key = (self._results_serial, current_language())
        if key != self._rivals_key:
            self._rivals_key = key
            self._rivals = self.rivals_data()
        return self._rivals

    @Property(list, notify=StatsCore.rivalsChanged)
    def rivals(self) -> list[dict]:
        """People met in online races of your class: name, races, record, tone, gap, gapTone, last, tip"""
        return self._rivals

    # Official races to come (RaceControl daily races, option: asks RaceControl with your game sign in)
    @property
    def upcoming_enabled(self) -> bool:
        return bool(self.viewer_config().get("enable_upcoming_races", False))

    def load_upcoming(self, force: bool = False):
        """Races to come asked in background (option on, signed in to RaceControl), at most every UPCOMING_EVERY"""
        if not self.upcoming_enabled or self._released or self.jobs.is_busy("upcoming"):
            return
        if not online_enabled():
            self._upcoming_events, self._upcoming_note = [], tr(
                "Turn on online ranks (RaceControl) in Configuration to see the official races to come.")
            self.publish_upcoming()
            return
        if not force and time.monotonic() - self._upcoming_time < UPCOMING_EVERY and self._upcoming_time:
            return
        self._upcoming_time = time.monotonic()
        self._upcoming_note = tr("Reading official races…") if not self._upcoming_events else self._upcoming_note
        self.publish_upcoming()
        self.jobs.run("upcoming", read_official_races, self.upcoming_read, self.upcoming_failed, key="upcoming")

    def upcoming_read(self, result: tuple[list[Upcoming], dict[str, tuple[str, ...]]]):
        if self._released:
            return
        self._upcoming_events, self._game_tracks = result
        self._upcoming_note = "" if self._upcoming_events else tr(
            "No official race to come found (game closed, or not signed in to RaceControl).")
        self.publish_upcoming()

    def upcoming_failed(self, error: BaseException):
        logger.warning("DRIVER STATS: official races not read", exc_info=(type(error), error, error.__traceback__))
        if not self._released:
            self._upcoming_note = tr("Official races could not be read.")
            self.publish_upcoming()

    def publish_upcoming(self):
        self.publish("upcoming", self.upcoming_data(), self.upcomingChanged)

    def upcoming_data(self) -> dict:
        """Races to come with your best lap of each class on their track: enabled, note, races"""
        if not self.upcoming_enabled:
            return {"enabled": False, "note": "", "races": []}
        races = []
        tracks = [key for key in self.stats_temp if key]
        for event in self._upcoming_events:
            track = stats_track(event, tracks, self._game_tracks)
            bests = []
            vehicles = self.stats_temp.get(track, {}) if track else {}
            classes: dict[str, tuple[float, str]] = {}
            for vehicle, data in vehicles.items() if isinstance(vehicles, dict) else ():
                best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
                name = self.class_of(str(vehicle))
                if best and (name not in classes or best < classes[name][0]):
                    classes[name] = (best, str(vehicle))
            for name, (best, vehicle) in sorted(classes.items()):
                reference = self.reference_for(track, vehicle)
                level = reference.level(best) if reference else -1
                bests.append({"vehicleClass": name, "best": calc.sec2laptime_full(best), "level": level_text(level),
                              "color": self.level_color(level), "letter": level_letter(level), "vehicle": vehicle,
                              "seconds": best})
            driven = self.track_last_driven.get(track, 0.0) if track else 0.0
            races.append({
                "tier": tr(event.tier.capitalize()), "title": event.title, "track": track or event.track,
                "start": QDateTime.fromSecsSinceEpoch(int(event.start)).toString(
                    date_locale().dateTimeFormat(QLocale.FormatType.ShortFormat)),
                "classes": " · ".join(event.classes), "bests": bests, "known": bool(track),
                "logo": self.logos.track(track) if track else "",
                "note": trm(f"Last driven {format_date(driven)}") if driven else tr("Never driven here"),
            })
        return {"enabled": True, "note": self._upcoming_note, "races": races}

    @Property(dict, notify=StatsCore.upcomingChanged)
    def upcoming(self) -> dict:
        """Official races to come: enabled, note, races (tier, title, track, start, classes, bests, known, logo, note)"""
        return self._published.get("upcoming", {"enabled": False, "note": "", "races": []})

    @Property(bool, notify=StatsCore.upcomingChanged)
    def upcomingEnabled(self) -> bool:
        return self._published.get("upcoming", {}).get("enabled", False)

    @Slot(bool)
    def setUpcomingEnabled(self, enabled: bool):
        """Official races to come shown (asks RaceControl with your game sign in), saved"""
        self.save_viewer_config(enable_upcoming_races=enabled)
        if enabled:
            self.load_upcoming(force=True)
        else:
            self.jobs.cancel("upcoming")
            self._upcoming_events, self._upcoming_note = [], ""
        self.publish_upcoming()

    @Slot()
    def refreshUpcoming(self):
        self.load_upcoming(force=True)

    @Property(dict, notify=StatsCore.activityChanged)
    def activity(self) -> dict:
        """Daily driving activity (All Tracks): weeks, days (level, tip), months (week, text), summary"""
        return self._activity

    def recent_sessions(self) -> list[dict]:
        """Latest sessions of tracks with stats, newest first"""
        rows = []
        for record in reversed(self.history):
            vehicles = self.stats_temp.get(record.track)
            if not isinstance(vehicles, dict) or record.vehicle not in vehicles:
                continue  # removed since
            data = vehicles[record.vehicle]
            best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
            laptime = record.best if record.best > 0 and not (best and record.best < best - 0.0005) else 0.0
            rows.append({
                "track": record.track, "vehicle": record.vehicle, "date": format_date(record.time),
                "trackLogo": self.logos.track(record.track),
                "session": session_name(record.session), "kind": session_kind(record.session),
                "code": session_code(record.session),
                "best": laptime_text(laptime),
                "pb": bool(best and laptime and abs(laptime - best) < 0.0005), "result": race_result(record),
                "resultTone": result_tone(record),
                "podium": record.position if record.finish == 1 and 0 < record.position <= 3 else 0,
                "results": summary.path if (summary := self.record_result(record)) is not None else "",
            })
            if len(rows) >= RECENT_SESSIONS:
                break
        return rows

    @Property(list, notify=StatsCore.recentChanged)
    def recent(self) -> list[dict]:
        """Latest sessions (All Tracks): track, vehicle, date, session, kind, best lap, pb, result"""
        return self._recent

    # Progress of the last days (All Tracks card, see stats_analysis.weekly_progress)
    def weekly_card(self) -> dict:
        """Progress of the last WEEK_DAYS days: summary text, rows (kind, glyph, text, detail, tone, track,
        vehicle), more (rows left out); made again only when history, stats, goals, language or the hour changed"""
        now = time.time()
        goals = self.goals()
        key = (self._history_stamp, self._stats_serial, int(now // 3600), current_language(),
               tuple(sorted(goals.items())))
        if key == self._weekly_key:
            return self._weekly
        self._weekly_key = key
        bests = {(str(track), str(vehicle)): valid_laptime(data.get("pb", 0))
                 for track, vehicles in self.stats_temp.items() if track and isinstance(vehicles, dict)
                 for vehicle, data in vehicles.items() if isinstance(data, dict)}
        rows = []
        summary = ""
        for item in weekly_progress(self.history, goals, now, bests=bests):
            kind = item["kind"]
            if kind == "summary":
                summary = " · ".join((plural(item["sessions"], "session", "sessions"),
                                      format_duration(item["seconds"]), plural(item["laps"], "lap", "laps")))
                continue
            if kind == "goal_reached":
                row = {"glyph": "\ue73e", "tone": "gain",  # check mark
                       "detail": f"{tr('Goal reached')} {calc.sec2laptime_full(item['goal'])}"}
            elif kind == "record":
                first = not item["previous"]
                gain = "" if first else f" ({signed(-item['gain'], 3)} s)"
                row = {"glyph": "\ue735", "tone": "" if first else "gain",  # star
                       "detail": f"{tr('First lap time') if first else tr('New personal best')} "
                                 f"{calc.sec2laptime_full(item['best'])}{gain}"}
            else:  # goal_near
                row = {"glyph": "\uf272", "tone": "",  # target
                       "detail": f"{tr('Gap to goal')} {signed(item['gap'], 3)} s "
                                 f"({calc.sec2laptime_full(item['goal'])})"}
            row.update({"kind": kind, "text": f"{item['track']} · {item['vehicle']}", "track": item["track"],
                        "vehicle": item["vehicle"]})
            rows.append(row)
        self._weekly = {"summary": summary, "rows": rows[:MAX_WEEKLY_ROWS],
                        "more": max(len(rows) - MAX_WEEKLY_ROWS, 0)}
        return self._weekly

    @Property(dict, notify=StatsCore.weeklyChanged)
    def weekly(self) -> dict:
        """Progress of the last days (All Tracks): summary ("" when nothing driven), rows, more (rows left out)"""
        return self._published.get("weekly", {"summary": "", "rows": [], "more": 0})

    # Menu of a track & vehicle shown outside the table (official race, rival, progress row)
    @Slot(str, str, str, result=list)
    def comboActions(self, track: str, vehicle: str, path: str) -> list[dict]:
        """Entries of the menu of a track & vehicle (vehicle may be empty: track only), path: results file
        ("" if none): id, text, enabled"""
        known = bool(track) and track in self.stats_temp
        actions = [
            {"id": "stats", "text": tr("Show this track & car") if vehicle else tr("Track Stats"),
             "enabled": known},
            {"id": "laps", "text": tr("Open Recorded Laps"), "enabled": bool(self.lap_folder_of(track, vehicle))},
            {"id": "prepare", "text": tr("Prepare Race in Calculator"),
             "enabled": bool(track) and race_preparation() is not None},
        ]
        if path:
            actions.append({"id": "results", "text": tr("Results"), "enabled": True})
        return actions

    @Slot(str, str, str, str)
    def runComboAction(self, action: str, track: str, vehicle: str, path: str):
        """Entry of comboActions chosen"""
        if action == "stats":
            if vehicle:
                self.openSession(track, vehicle)
            elif track in self.stats_temp:
                self.selectTrack(track)
        elif action == "laps":
            self.open_laps(track, vehicle)
        elif action == "prepare":
            self.prepare_race(track, vehicle)
        elif action == "results":
            self.openResults(path)

    def prepare_race(self, track: str, vehicle: str) -> bool:
        """Race calculator opened for a track & vehicle (its personal best as lap time), False if unavailable"""
        prepare = race_preparation()
        if prepare is None or not track:
            return False
        vehicles = self.stats_temp.get(track, {})
        data = vehicles.get(vehicle, {}) if vehicle and isinstance(vehicles, dict) else {}
        best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
        window = self._window
        parent = window.window() if getattr(window, "in_app_page", False) else window
        try:
            return bool(prepare(parent, track, vehicle, best))
        except Exception:  # calculator of another page: logged, never breaks this page
            logger.exception("DRIVER STATS: race calculator not prepared for %s, %s", track, vehicle)
            return False

    @Slot(str, str)
    def openSession(self, track: str, vehicle: str):
        """Recent session clicked: its track shown, its vehicle selected"""
        if track not in self.stats_temp:
            return
        self.selectTrack(track)
        self.selectRow(vehicle)

    @Slot()
    def showAllTracks(self):
        self.selectTrack(ALL_TRACKS)
