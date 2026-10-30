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
Tyre overview Widget, modern design

Car seen from above: chassis in the middle, one card per tyre at its corner. Each card draws its tyre with
inner / center / outer bands in heatmap colors (temperatures written on them, tread grooves), a tread gauge
along it, then the readings on the car side: compound badge (or alert), pressure with its place in the target
range, carcass & inner layer temperatures, tread left & laps left. Every part has its own on/off option
(tyre drawing off: surface temperatures in a row of the readings).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen

from ...i18n import tr_overlay as tr
from ..tyre_overview import ALERTS, DASH, NO_READING, PRESSURE_HIGH, PRESSURE_LOW, WHEELS, TyreOverviewMixin, WheelCard
from .base import CENTER, LEFT, RIGHT, ModernOverlay
from .draw import bar, panel, readable_on, rounded
from .quad import tile_shades

if TYPE_CHECKING:
    from ...template.widget_config_types import TyreOverviewConfig

# Info rows of a card: (key, height in unit)
HEADER_H = 0.85
SURFACE_H = 0.9
PRESSURE_H = 1.1
RANGE_H = 0.4
LAYERS_H = 0.8
WEAR_H = 0.8
TYRE_RATIO = 1.3  # tyre height / width, seen from above
RANGE_MARGIN = 0.18  # pressure scale reaches past target range by this share of the range on both sides


class Realtime(TyreOverviewMixin, ModernOverlay):
    """Draw widget"""

    wcfg: TyreOverviewConfig

    options = (
        "font_size", "show_car_body", "show_wheel_label", "show_tyre_compound", "show_tyre_alerts",
        "flat_spot_threshold", "show_alert_highlight", "show_tyre_graphic", "show_tread_grooves",
        "show_surface_temperature", "show_inner_center_outer", "show_carcass_temperature",
        "show_inner_layer_temperature", "show_layer_labels", "show_degree_sign", "enable_heatmap_auto_matching",
        "heatmap_name", "enable_heatmap_from_optimal_temperature", "show_pressure", "show_pressure_unit",
        "enable_tyre_pressure_target", "show_pressure_target_range", "tyre_pressure_target_minimum",
        "tyre_pressure_target_maximum", "tyre_pressure_target_rear_minimum", "tyre_pressure_target_rear_maximum",
        "tyre_target_by_compound", "show_tread_gauge", "show_wear", "show_wear_per_lap", "show_lifespan_laps",
        "warning_threshold_remaining", "warning_threshold_laps",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_overview()
        unit = self.unit
        self.add_font("tiny", 0.5, "bold", caps=True)
        self.add_font("band", 0.52, "bold")  # temperatures on tyre bands
        self.add_font("big", 1.05, "bold")  # pressure
        wcfg = self.wcfg
        self.show_body = bool(wcfg["show_car_body"])
        self.show_highlight = self.show_alerts and bool(wcfg["show_alert_highlight"])
        self.show_graphic = bool(wcfg["show_tyre_graphic"])
        self.show_grooves = self.show_graphic and bool(wcfg["show_tread_grooves"])
        self.show_layer_labels = bool(wcfg["show_layer_labels"])
        self.show_range = self.use_target and bool(wcfg["show_pressure_target_range"])
        self.show_gauge = bool(wcfg["show_tread_gauge"])
        self.need_wear = self.need_wear or self.show_gauge
        pad = unit * 0.3
        self.card_pad = card_pad = unit * 0.22
        self.chassis_w = unit * (1.1 if self.show_body else 0.3)  # middle of the car, between left & right cards
        row_gap = unit * 0.22
        # Tyre: three bands wide enough for their temperature, taller than wide (seen from above)
        bands = 3 if self.ico else 1
        band_w = max(self.text_width("band", f"888{self.sign}") + unit * 0.1, unit * (0.75 if bands == 3 else 2.0))
        self.band_inset = unit * 0.09
        tyre_w = band_w * bands + self.band_inset * 2 if self.show_surface else unit * 1.8
        self.gauge_w = unit * 0.26
        chip_text = self.text_width("small", f"888{self.sign}")
        layer_label = max(self.text_width("tiny", tr(label)) for label in ("Carc.", "Inner")) if self.show_layer_labels else 0.0
        rows = []
        if self.show_caption:
            rows.append(("header", HEADER_H))
        if self.show_surface and not self.show_graphic:  # temperatures in a row instead of on tyre
            rows.append(("surface", SURFACE_H))
        if self.show_pressure:
            rows.append(("pressure", PRESSURE_H))
            if self.show_range:
                rows.append(("range", RANGE_H))
        if self.show_carcass or self.show_inner:
            rows.append(("layers", LAYERS_H))
        if self.need_wear and (self.show_wear or self.show_wear_lap or self.show_laps):
            rows.append(("wear", WEAR_H))
        info_w = max(
            self.text_width("big", "888.8") + self.text_width("small", self.symbol_pres) + unit * 0.3,
            (layer_label + chip_text + unit * 0.75) * 2 + unit * 0.12,
            (chip_text + unit * 0.3) * bands,
            self.text_width("small", "88%") + sum(self.text_width("label", text) for text in (
                "▼8.88", f"99+ {tr('Laps').lower()}")) + unit * 0.7,
            unit * 4.6,
        ) if rows else 0.0
        info_h = sum(height for _, height in rows) * unit
        content_h = max(info_h, tyre_w * TYRE_RATIO if self.show_graphic else 0.0, unit * 2.0)
        # Parts of a card from outer side (corner of the car) toward the chassis, with gap before each
        parts = [(key, width, gap) for key, width, gap, shown in (
            ("tyre", tyre_w, 0.0, self.show_graphic), ("gauge", self.gauge_w, unit * 0.15, self.show_gauge),
            ("info", info_w, unit * 0.25, bool(rows))) if shown]
        if parts:
            parts[0] = (parts[0][0], parts[0][1], 0.0)
        content_w = sum(width + gap for _, width, gap in parts) or unit * 2.0
        card_w = card_pad * 2 + content_w
        card_h = card_pad * 2 + content_h
        width = pad * 2 + card_w * 2 + self.chassis_w
        self.cards: list[QRectF] = []
        self.tyres: list[QRectF] = []
        self.gauges: list[QRectF] = []
        self.rows: list[dict[str, QRectF]] = []
        for index in range(4):
            right_side = index % 2
            left = pad + (card_w + self.chassis_w) * right_side
            top = pad + (card_h + row_gap) * (index // 2)
            card = QRectF(left, top, card_w, card_h)
            inner = card.adjusted(card_pad, card_pad, -card_pad, -card_pad)
            places = {}
            offset = 0.0
            for key, part_w, gap in parts:
                offset += gap
                x = inner.right() - offset - part_w if right_side else inner.left() + offset  # mirrored on right
                places[key] = QRectF(x, inner.top(), part_w, content_h)
                offset += part_w
            gauge = places.get("gauge", QRectF())
            if gauge.isValid() and not self.show_graphic:  # gauge along readings
                gauge.setTop(inner.top() + (content_h - info_h) / 2)
                gauge.setHeight(info_h or content_h)
            info = places.get("info", QRectF())
            row_top = inner.top() + (content_h - info_h) / 2  # readings centered along tyre
            slots = {}
            for key, height in rows:
                slots[key] = QRectF(info.left(), row_top, info_w, height * unit)
                row_top += height * unit
            self.cards.append(card)
            self.tyres.append(places.get("tyre", QRectF()))
            self.gauges.append(gauge)
            self.rows.append(slots)
        self.labels = tuple(tr(label) for label in WHEELS)
        self.alert_labels = {key: tr(label) for key, label in ALERTS.items()}
        self.laps_label = tr("Laps").lower()
        self._band_shapes: dict[tuple[int, int], tuple[tuple[QRectF, QPainterPath, QLinearGradient | None], ...]] = {}
        self.set_size(width, pad * 2 + card_h * 2 + row_gap)

    # Static: panel, chassis & axles, cards
    def paint_static(self, painter: QPainter):
        theme = self.theme
        unit = self.unit
        panel(painter, QRectF(self.rect()), theme, self.panel_radius(), self.depth_effects)
        if self.show_body:  # axles from card to card, behind cards
            pen = QPen(theme.tint(theme.text_faint, 120), unit * 0.22)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for left, right in ((self.cards[0], self.cards[1]), (self.cards[2], self.cards[3])):
                painter.drawLine(left.center(), QPointF(right.center().x(), left.center().y()))
            painter.setPen(Qt.PenStyle.NoPen)
        for card in self.cards:
            rounded(painter, card, self.radius(0.45), theme.surface_raised)
        if self.show_body:
            self.draw_chassis(painter)

    def draw_chassis(self, painter: QPainter):
        """Tapered body between the cards, nose up"""
        theme = self.theme
        unit = self.unit
        front, rear = self.cards[0], self.cards[2]
        middle = self.width() / 2
        body_w = self.chassis_w * 0.62
        top = front.top() + self.card_pad - unit * 0.1
        bottom = rear.bottom() - self.card_pad + unit * 0.1
        nose_w = body_w * 0.45
        path = QPainterPath()
        path.moveTo(middle - nose_w / 2, top)
        path.lineTo(middle + nose_w / 2, top)
        path.cubicTo(middle + body_w / 2, top + unit, middle + body_w / 2, top + unit, middle + body_w / 2,
                     front.center().y())
        path.lineTo(middle + body_w / 2, bottom - unit * 0.6)
        path.quadTo(middle + body_w / 2, bottom, middle, bottom)
        path.quadTo(middle - body_w / 2, bottom, middle - body_w / 2, bottom - unit * 0.6)
        path.lineTo(middle - body_w / 2, front.center().y())
        path.cubicTo(middle - body_w / 2, top + unit, middle - body_w / 2, top + unit, middle - nose_w / 2, top)
        gradient = QLinearGradient(middle - body_w / 2, 0, middle + body_w / 2, 0)
        gradient.setColorAt(0.0, theme.surface_alt)
        gradient.setColorAt(0.5, theme.surface_strong)
        gradient.setColorAt(1.0, theme.surface_alt)
        painter.fillPath(path, QBrush(gradient))
        painter.setPen(QPen(theme.border, max(unit * 0.06, 1.0)))
        painter.drawPath(path)
        cockpit = QRectF(middle - body_w * 0.28, (front.center().y() + rear.center().y()) / 2 - unit * 0.7,
                         body_w * 0.56, unit * 1.2)
        painter.setPen(Qt.PenStyle.NoPen)
        rounded(painter, cockpit, cockpit.width() / 2, theme.tint(theme.text_faint, 90))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read_cards())

    def paint(self, painter: QPainter):
        for index, card in enumerate(self.state):
            if self.show_graphic:
                self.draw_tyre(painter, index, card)
            if self.show_gauge:
                self.draw_gauge(painter, index, card)
            if card.alert and self.show_highlight:
                self.draw_alert_border(painter, self.cards[index])
            for key, rect in self.rows[index].items():
                getattr(self, f"draw_{key}")(painter, rect, index, card)

    # Tyre
    def draw_tyre(self, painter: QPainter, index: int, card: WheelCard):
        theme = self.theme
        unit = self.unit
        tyre = self.tyres[index]
        radius = self.tyre_radius(index)
        # Rubber: dark tyre with sidewall rim
        rounded(painter, tyre, radius, QColor(24, 25, 28) if not theme.light else QColor(46, 48, 54))
        if card.alert == "detached":  # no tyre: dashed outline
            pen = QPen(theme.text_dim, max(unit * 0.08, 1.0), Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(tyre, radius, radius)
            painter.setPen(Qt.PenStyle.NoPen)
            self.draw_text(painter, tyre, self.alert_labels["detached"], "tiny", theme.text_dim, CENTER, elide=False)
            return
        tread, band_radius = self.tread_of(index)
        temps = card.temps if self.show_surface else ()
        for part, (rect, path, gradient) in enumerate(self.band_shapes(index, max(len(temps), 1))):
            value = temps[part] if part < len(temps) else -273.0
            fill = self.heat(index, value)
            color = fill if fill is not None else theme.surface_alt
            if gradient is not None:
                top, bottom = tile_shades(color)
                gradient.setColorAt(0.0, bottom)  # stops replaced (same positions)
                gradient.setColorAt(0.5, top)
                gradient.setColorAt(1.0, bottom)
                brush: QColor | QBrush = QBrush(gradient)
            else:
                brush = color
            painter.fillPath(path, brush)
            if temps:
                self.draw_text(painter, rect, self.temperature_text(value), "band",
                               readable_on(color), CENTER, elide=False)
        if self.show_grooves:  # thin dark lines across the tyre
            groove = QColor(0, 0, 0, 46)
            step = unit * 0.55
            y = tread.top() + step
            while y < tread.bottom() - step * 0.5:
                if abs(y - tread.center().y()) > unit * 0.45:  # leave room for temperatures
                    painter.fillRect(QRectF(tread.left(), y, tread.width(), max(unit * 0.06, 1.0)), groove)
                y += step
        if card.alert and self.show_highlight:  # puncture or flat spot: tinted tyre & mark
            color = theme.negative if card.alert == "puncture" else theme.warning
            rounded(painter, tread, band_radius, theme.tint(color, 70))
            mark = min(tyre.width() * 0.5, unit * 1.0)
            dot = QRectF(tyre.center().x() - mark / 2, tyre.bottom() - mark - unit * 0.25, mark, mark)
            rounded(painter, dot, mark / 2, color)
            self.draw_text(painter, dot, "!", "strong", readable_on(color), CENTER, elide=False)

    def tyre_radius(self, index: int) -> float:
        """Corner radius of tyre drawing"""
        unit = self.unit
        return min(self.tyres[index].width() * 0.32, unit * 0.7) * min(self.corner, 1.0) + unit * 0.12

    def tread_of(self, index: int) -> tuple[QRectF, float]:
        """Tread area inside tyre drawing & corner radius of its bands"""
        inset = self.band_inset
        tread = self.tyres[index].adjusted(inset, inset * 1.6, -inset, -inset * 1.6)
        return tread, max(self.tyre_radius(index) - inset, self.unit * 0.1)

    def band_shapes(self, index: int, bands: int) -> tuple[tuple[QRectF, QPainterPath, QLinearGradient | None], ...]:
        """Rect, shape & gradient (depth effects on, colors set when drawn) of each tread band, built once per tyre &
        band count (fixed size: a boolean union of paths in every paint was the costliest part of the drawing)"""
        key = (index, bands)
        shapes = self._band_shapes.get(key)
        if shapes is not None:
            return shapes
        tread, band_radius = self.tread_of(index)
        band_w = tread.width() / bands
        built = []
        for part in range(bands):
            rect = QRectF(tread.left() + band_w * part, tread.top(), band_w, tread.height())
            # Bands joined: only outer corners rounded
            path = QPainterPath()
            path.addRoundedRect(rect, band_radius, band_radius)
            if bands > 1:
                square = QPainterPath()
                inner_side = rect.adjusted(band_w / 2 if part == 0 else 0, 0,
                                           -band_w / 2 if part == bands - 1 else 0, 0)
                square.addRect(inner_side)
                path = path.united(square) if part in (0, bands - 1) else square
            # Rounded rubber: lit in the middle
            gradient = QLinearGradient(rect.left(), 0, rect.right(), 0) if self.depth_effects else None
            built.append((rect, path, gradient))
        shapes = self._band_shapes[key] = tuple(built)
        return shapes

    def draw_gauge(self, painter: QPainter, index: int, card: WheelCard):
        """Tread left: vertical gauge along tyre, filled from bottom"""
        theme = self.theme
        warn = 0 <= card.remaining <= self.warn_remaining
        color = theme.negative if warn else theme.caution if 0 <= card.remaining <= self.warn_remaining * 2 \
            else theme.positive
        bar(painter, self.gauges[index], max(card.remaining, 0) / 100, color, theme.surface_alt,
            self.gauge_w / 2, vertical=True)

    def draw_alert_border(self, painter: QPainter, rect: QRectF):
        pen = QPen(self.theme.negative, max(self.unit * 0.1, 1.5))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = pen.widthF() / 2
        radius = self.radius(0.45)
        painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)

    # Readings
    def align(self, index: int) -> Qt.AlignmentFlag:
        """Readings aligned toward the tyre side"""
        return RIGHT if index % 2 else LEFT

    def draw_header(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        theme = self.theme
        right_side = index % 2
        size = rect.height() * 0.78
        badge = QRectF(rect.right() - size if right_side else rect.left(), rect.center().y() - size / 2, size, size)
        label_rect = rect.adjusted(0 if right_side else size + self.unit * 0.25, 0,
                                   -(size + self.unit * 0.25) if right_side else 0, 0)
        if card.alert:
            text, color = self.alert_labels[card.alert], theme.negative
        else:
            text, color = self.labels[index] if self.show_label else "", theme.text_muted
        if text:
            self.draw_text(painter, label_rect, text, "label", color, self.align(index))
        if card.compound and card.compound_color is not None:  # standard badge: letter on compound color square
            rounded(painter, badge, self.radius(0.25), card.compound_color)
            self.draw_text(painter, badge, card.compound, "tiny" if len(card.compound) > 1 else "label",
                           readable_on(card.compound_color), CENTER, elide=False)

    def draw_pressure(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        theme = self.theme
        color = (theme.blue if card.pressure_state == PRESSURE_LOW
                 else theme.negative if card.pressure_state == PRESSURE_HIGH else theme.text)
        value = self.pressure_text(card.pressure)
        value_w = self.advance("big", value)  # cached (big & small roles not in capitals)
        symbol_w = self.advance("small", self.symbol_pres) if self.show_pressure_unit else 0.0
        gap = self.unit * 0.2 if self.show_pressure_unit else 0.0
        if index % 2:
            symbol = QRectF(rect.right() - symbol_w, rect.top(), symbol_w, rect.height())
            number = QRectF(symbol.left() - gap - value_w, rect.top(), value_w, rect.height())
        else:
            number = QRectF(rect.left(), rect.top(), value_w, rect.height())
            symbol = QRectF(number.right() + gap, rect.top(), symbol_w, rect.height())
        self.draw_text(painter, number, value, "big", color, LEFT, elide=False)
        if self.show_pressure_unit:
            self.draw_text(painter, symbol.adjusted(0, rect.height() * 0.12, 0, 0), self.symbol_pres, "small",
                           theme.text_muted, LEFT, elide=False)

    def draw_range(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        """Pressure on a scale around target range: window in green, marker at pressure"""
        theme = self.theme
        low, high = self.targets[index]
        if high <= low:
            return
        margin = (high - low) * RANGE_MARGIN + 1.0
        scale_low, scale_high = low - margin, high + margin
        track = QRectF(rect.left(), rect.center().y() - rect.height() * 0.16, rect.width(), rect.height() * 0.32)
        rounded(painter, track, track.height() / 2, theme.surface_alt)

        def x_of(value: float) -> float:
            share = (value - scale_low) / (scale_high - scale_low)
            return track.left() + track.width() * min(max(share, 0.0), 1.0)

        window = QRectF(x_of(low), track.top(), x_of(high) - x_of(low), track.height())
        rounded(painter, window, track.height() / 2, theme.tint(theme.positive, 150))
        if card.pressure > 0:
            color = (theme.blue if card.pressure_state == PRESSURE_LOW
                     else theme.negative if card.pressure_state == PRESSURE_HIGH else theme.text)
            size = rect.height() * 0.78
            x = x_of(card.pressure)
            dot = QRectF(x - size / 2, rect.center().y() - size / 2, size, size)
            rounded(painter, dot, size / 2, theme.surface)
            rounded(painter, dot.adjusted(size * 0.18, size * 0.18, -size * 0.18, -size * 0.18), size / 3, color)

    def draw_surface(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        """Surface temperatures in a row of heatmap chips (tyre drawing off)"""
        theme = self.theme
        temps = card.temps or (NO_READING,) * (3 if self.ico else 1)
        gap = self.unit * 0.1
        width = (rect.width() - gap * (len(temps) - 1)) / len(temps)
        for part, value in enumerate(temps):
            cell = QRectF(rect.left() + (width + gap) * part, rect.top() + rect.height() * 0.08, width,
                          rect.height() * 0.84)
            color = self.heat(index, value) or theme.surface_alt
            rounded(painter, cell, self.radius(0.3), color)
            self.draw_text(painter, cell, self.temperature_text(value), "small", readable_on(color), CENTER,
                           elide=False)

    def draw_layers(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        theme = self.theme
        layers = [(label, value) for label, value, shown in (
            ("Carc.", card.carcass, self.show_carcass), ("Inner", card.inner, self.show_inner)) if shown]
        gap = self.unit * 0.12
        width = (rect.width() - gap * (len(layers) - 1)) / len(layers)
        for part, (label, value) in enumerate(layers):
            cell = QRectF(rect.left() + (width + gap) * part, rect.top() + rect.height() * 0.1, width,
                          rect.height() * 0.8)
            rounded(painter, cell, self.radius(0.3), theme.surface_alt)
            color = self.heat(index, value)
            dot = cell.height() * 0.36
            if color is not None:
                rounded(painter, QRectF(cell.left() + dot * 0.6, cell.center().y() - dot / 2, dot, dot), dot / 2,
                        color)
            inner = cell.adjusted(dot * 1.7, 0, -self.unit * 0.15, 0)
            if self.show_layer_labels:
                self.draw_text(painter, inner, tr(label), "tiny", theme.text_muted, LEFT)
            self.draw_text(painter, inner, self.temperature_text(value), "small", theme.text,
                           RIGHT if self.show_layer_labels else CENTER, elide=False)

    def draw_wear(self, painter: QPainter, rect: QRectF, index: int, card: WheelCard):
        theme = self.theme
        parts = []
        if self.show_wear:
            warn = 0 <= card.remaining <= self.warn_remaining
            parts.append((self.remaining_text(card.remaining), "small", theme.negative if warn else theme.text))
        if self.show_wear_lap:
            text = self.wear_text(card.wear)
            parts.append((f"▼{text}" if text != DASH else DASH, "label", theme.text_dim))
        if self.show_laps:
            warn = 0 <= card.laps <= self.warn_laps
            parts.append((f"{self.laps_text(card.laps)} {self.laps_label}", "label",
                          theme.negative if warn else theme.text_dim))
        if not parts:
            return
        # Justified: measured texts with even spaces between them
        widths = [self.advance(role, text.upper() if role in self._caps_roles else text)  # cached
                  for text, role, _ in parts]
        space = (rect.width() - sum(widths)) / max(len(parts) - 1, 1)
        left = rect.left()
        for (text, role, color), width in zip(parts, widths, strict=True):
            self.draw_text(painter, QRectF(left, rect.top(), width, rect.height()), text, role, color, LEFT,
                           elide=False)
            left += width + space
