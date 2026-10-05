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
Corner report of lap viewer: one HTML file, nothing outside it (map picture embedded), no Qt

Per corner table of corner tab (time delta, speeds, braking & full throttle points, driving), totals, coaching notes
& track map colored by time lost in each corner. Texts come translated & formatted from the page.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

STYLE = """
body { font-family: "Segoe UI", "Barlow", Arial, sans-serif; color: #1F2937; margin: 24px; }
h1 { font-size: 22px; margin: 0 0 4px 0; }
h2 { font-size: 16px; margin: 22px 0 8px 0; }
.sub { color: #6B7280; margin: 0 0 4px 0; }
.laps span { display: inline-block; margin-right: 14px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 5px; margin-right: 5px; }
table { border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: #6B7280; font-weight: 600; border-bottom: 1px solid #D1D5DB; padding: 5px 8px; }
td { padding: 4px 8px; border-bottom: 1px solid #F3F4F6; white-space: nowrap; }
tr.total td { font-weight: 700; background: #F9FAFB; }
tr.ideal td { color: #7C3AED; font-weight: 600; }
.gain { color: #15803D; font-weight: 600; }
.loss { color: #B91C1C; font-weight: 600; }
.note { margin: 6px 0; }
.note b { display: inline-block; min-width: 60px; }
.map { max-width: 100%; border: 1px solid #E5E7EB; border-radius: 8px; }
.foot { color: #9CA3AF; font-size: 12px; margin-top: 24px; }
"""


def cell(text: str, color: str = "") -> str:
    """Table cell, colored by judgement (gain, loss)"""
    css = f' class="{color}"' if color in ("gain", "loss") else ""
    return f"<td{css}>{html.escape(str(text))}</td>"


def build_report(title: str, subtitle: str, laps: Sequence[dict], headers: Sequence[str], keys: Sequence[str],
                 rows: Sequence[dict], coaching: Sequence[dict], coaching_title: str, png: str = "",
                 map_title: str = "", footer: str = "", image_src: str = "", image_size: tuple[int, int] = (0, 0),
                 ) -> str:
    """Self-contained HTML report

    Args:
        laps: shown laps: label, color (#RRGGBB), role text (reference, compared).
        headers, keys: table column titles & row keys (key + "Color" gives cell judgement: gain, loss).
        rows: corner table rows of page (kind: corner, sum, total, ideal).
        coaching: corners where compared lap loses most time: label, loss, causes.
        png: map picture, base64 PNG ("" if none).
        image_src: map picture address instead of embedded picture (PDF: resource of text document).
        image_size: map picture width & height on page ((0, 0): picture size).
    """
    parts = [
        "<!DOCTYPE html>", '<html><head><meta charset="utf-8">',
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>", f'<p class="sub">{html.escape(subtitle)}</p>', '<p class="laps">',
    ]
    for lap in laps:
        color = html.escape(str(lap.get("color", "#9CA3AF")))
        role = f" ({html.escape(str(lap['role']))})" if lap.get("role") else ""
        parts.append(f'<span><i class="dot" style="background:{color}"></i>{html.escape(str(lap.get("label", "")))}'
                     f"{role}</span>")
    parts.append("</p>")
    if coaching:
        parts.append(f"<h2>{html.escape(coaching_title)}</h2>")
        for tip in coaching:
            causes = " · ".join(str(cause) for cause in tip.get("causes", []))
            parts.append(f'<p class="note"><b>{html.escape(str(tip.get("label", "")))}</b> '
                         f'<span class="loss">{html.escape(str(tip.get("loss", "")))}</span> '
                         f"{html.escape(causes)}</p>")
    parts.append("<table><tr>" + "".join(f"<th>{html.escape(header)}</th>" for header in headers) + "</tr>")
    for row in rows:
        kind = str(row.get("kind", "corner"))
        css = ' class="total"' if kind in ("sum", "total") else ' class="ideal"' if kind == "ideal" else ""
        parts.append(f"<tr{css}>" + "".join(cell(row.get(key, ""), str(row.get(f"{key}Color", "")))
                                            for key in keys) + "</tr>")
    parts.append("</table>")
    if png or image_src:
        source = html.escape(image_src) if image_src else f"data:image/png;base64,{png}"
        size = f' width="{int(image_size[0])}" height="{int(image_size[1])}"' if all(image_size) else ""
        new_page = ' style="page-break-before: always"' if image_src else ""  # PDF: heading & map on one page
        parts.append(f"<h2{new_page}>{html.escape(map_title)}</h2>")
        parts.append(f'<p><img class="map" alt="{html.escape(map_title)}" src="{source}"{size}></p>')
    if footer:
        parts.append(f'<p class="foot">{html.escape(footer)}</p>')
    parts.append("</body></html>")
    return "\n".join(parts)
