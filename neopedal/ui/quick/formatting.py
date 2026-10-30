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
Date & time texts shown by pages and written to exported files, one helper per format; values in units of user
setting (temperature, distance)

Timestamps are seconds since epoch, shown in local time; None for now. Pages show dates in format of app language
(date_locale: system format when the system speaks it); fixed ISO formats only for file names & exported files.
"""

from __future__ import annotations

import re
import time
from datetime import date

from PySide6.QtCore import QDate, QDateTime, QLocale

from ... import units
from ...i18n import current_language, tr
from ...process.results_text import MISSING, number_text
from ...setting import cfg


# Fixed formats
def iso_minutes(timestamp: float | None = None) -> str:
    """Date & time as 2025-10-24 18:05"""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def iso_day(timestamp: float | None = None) -> str:
    """Date as 2025-10-24"""
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def file_stamp(timestamp: float | None = None) -> str:
    """Date & time usable in a file or folder name: 2025-10-24 18-05-09"""
    return time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(timestamp))


def day_month(timestamp: float) -> str:
    """Day & month in language format (24/10 in French, 10/24 in US English), "" if none"""
    if timestamp <= 0:
        return ""
    day = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return date_locale().toString(day, day_month_format())


def day_month_minutes(timestamp: float) -> str:
    """Day, month & time in language format (24/10 18:05), "" if none"""
    return f"{day_month(timestamp)} {clock_minutes(timestamp)}" if timestamp > 0 else ""


def day_month_year_minutes(timestamp: float | None = None) -> str:
    """Date & time as 24/10/2025 18:05"""
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(timestamp))


def clock_minutes(timestamp: float | None = None) -> str:
    """Time of day as hh:mm"""
    return time.strftime("%H:%M", time.localtime(timestamp))


def clock_seconds(timestamp: float | None = None) -> str:
    """Time of day as hh:mm:ss"""
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


# Formats of app language
def localized_number(value: float, decimals: int) -> str:
    """Number with decimals in language format (2,5 in French)"""
    return date_locale().toString(float(value), "f", decimals)


def country_name(code: str) -> str:
    """Country of ISO code ("FR" -> "France", English name), code if unknown"""
    territory = QLocale.codeToTerritory(code) if len(code) == 2 else QLocale.Country.AnyCountry
    return code if territory == QLocale.Country.AnyCountry else QLocale.territoryToString(territory)


def date_locale() -> QLocale:
    """Date format of system, or of app language if system speaks another one"""
    system = QLocale.system()
    code = current_language()
    if system.name().split("_")[0] == code:
        return system
    return QLocale(code)


def day_month_format() -> str:
    """Short date format of language without its year: dd/MM from dd/MM/yyyy, M/d from M/d/yy"""
    pattern = date_locale().dateFormat(QLocale.FormatType.ShortFormat)
    shorter = re.sub(r"^y+\W*|\W*y+$", "", pattern)
    return shorter if "y" not in shorter and "d" in shorter and "M" in shorter else "dd/MM"


def format_date(timestamp: float) -> str:
    """Short date in language format (24/10/2025 in French), missing text if none"""
    if timestamp <= 0:
        return MISSING
    day = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return date_locale().toString(day, QLocale.FormatType.ShortFormat)


def format_day(day: date) -> str:
    """Short date of a calendar day in language format"""
    return date_locale().toString(QDate(day.year, day.month, day.day), QLocale.FormatType.ShortFormat)


def day_text(timestamp: float, today: QDate) -> str:
    """Day of a replay: Today, Yesterday, or long date in app language ("Samedi 3 octobre 2026")"""
    if timestamp <= 0:
        return tr("Unknown Date")
    day = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    if day == today:
        return tr("Today")
    if day == today.addDays(-1):
        return tr("Yesterday")
    text = QLocale(current_language()).toString(day, QLocale.FormatType.LongFormat)
    return text[:1].upper() + text[1:]


def date_text(timestamp: float) -> str:
    """Short date & time in language format (24/10/2025 18:05), "" if none: dates of every page"""
    if timestamp <= 0:
        return ""
    day = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return f"{date_locale().toString(day, QLocale.FormatType.ShortFormat)} {clock_minutes(timestamp)}"


# Values in units of user setting, shared by pages (Stats, Race calculator, Results...)
def fahrenheit() -> bool:
    return cfg.units.get("temperature_unit") == "Fahrenheit"


def temperature_symbol() -> str:
    return "°F" if fahrenheit() else "°C"


def temperature_value(celsius: float) -> float:
    """Temperature in user unit"""
    return units.celsius_to_fahrenheit(celsius) if fahrenheit() else celsius


def temperature_text(celsius: float, decimals: int = 0) -> str:
    """Temperature in user unit: "24 °C", "75 °F", missing text if unknown (-999 and below)"""
    if celsius <= -999:
        return MISSING
    return f"{number_text(temperature_value(celsius), decimals)} {temperature_symbol()}"


def odometer_text(meters: float, decimals: int = 2) -> str:
    """Track or driven length in user odometer unit: "5,79 km", "3,60 mi", "5793 m", missing text if none"""
    if meters <= 0:
        return MISSING
    unit = cfg.units.get("odometer_unit")
    if unit == "Mile":
        return f"{number_text(units.meter_to_mile(meters), decimals)} mi"
    if unit == "Meter":
        return f"{number_text(meters)} m"
    return f"{number_text(units.meter_to_kilometer(meters), decimals)} km"
