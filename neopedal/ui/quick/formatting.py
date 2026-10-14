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
Date & time texts shown by pages and written to exported files, one helper per format

Timestamps are seconds since epoch, shown in local time; None for now.
"""

from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import QDate, QDateTime, QLocale

from ...i18n import current_language, tr


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
    """Day & month as 24/10, "" if none"""
    return time.strftime("%d/%m", time.localtime(timestamp)) if timestamp > 0 else ""


def day_month_minutes(timestamp: float) -> str:
    """Day, month & time as 24/10 18:05, "" if none"""
    return time.strftime("%d/%m %H:%M", time.localtime(timestamp)) if timestamp > 0 else ""


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


def format_date(timestamp: float) -> str:
    """Short date in language format (24/10/2025 in French), "-" if none"""
    if timestamp <= 0:
        return "-"
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
    """Short date & time in app language format, "" if none"""
    if timestamp <= 0:
        return ""
    day = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return f"{QLocale(current_language()).toString(day, QLocale.FormatType.ShortFormat)} {clock_minutes(timestamp)}"
