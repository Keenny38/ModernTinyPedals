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
Module & widget list view

Each row: name, settings (gear) button and an on/off switch. Search box and All / Active /
Inactive filter on top, so a widget is found among dozens without scrolling.
"""

import logging
import unicodedata

from PySide6.QtCore import Property, QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, QSize, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import app_signal
from ..i18n import tr, trm
from ..i18n.options import module_label
from ..module_control import ModuleControl
from ..setting import cfg
from ._common import UIScaler
from .config import UserConfig

logger = logging.getLogger(__name__)

FILTER_ALL = 0
FILTER_ACTIVE = 1
FILTER_INACTIVE = 2
GEAR_SYMBOL = "\u2699\ufe0e"  # gear, text style (not color emoji)

# Widget categories: (name, widget name prefixes), first match wins, unmatched (plugins) are "Other"
WIDGET_CATEGORIES = (
    ("Timing", (
        "deltabest", "lap_time_history", "laps_and_position", "pit_stop_estimate", "relative", "rivals",
        "sectors", "session", "standings", "stint_history", "timing", "track_clock",
    )),
    ("Tyres & Wheels", ("friction_circle", "slip_", "tyre_", "wheel_")),
    ("Brakes", ("brake_",)),
    ("Driver Inputs", ("pedal", "steering_", "trailing")),
    ("Engine & Energy", (
        "battery", "cruise", "drs", "electric_motor", "engine", "fuel", "gear", "instrument", "lift_and_coast",
        "push_to_pass", "rpm_led", "speedometer", "virtual_energy",
    )),
    ("Chassis", (
        "acceleration", "damage", "differential", "force", "rake_angle", "ride_height", "roll_angle",
        "suspension_", "weight_distribution",
    )),
    ("Track & Traffic", (
        "black_box", "elevation", "flag", "heading", "navigation", "pace_notes", "radar", "track_", "traffic",
        "weather",
    )),
)
CATEGORY_ALL = "All Categories"
CATEGORY_OTHER = "Other"


def widget_category(name: str) -> str:
    """Category of widget, by name prefix"""
    for category, prefixes in WIDGET_CATEGORIES:
        if name.startswith(prefixes):
            return category
    return CATEGORY_OTHER


class ToggleSwitch(QAbstractButton):
    """On/off switch: rounded track, knob sliding to the right when on (animated)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._position = 0.0  # knob, 0 left (off) to 1 right (on)
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(120)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        height = round(self.fontMetrics().height() * 1.35)
        return QSize(round(height * 1.9), height)

    def setChecked(self, checked: bool):
        """Set state without animation (initial state, refresh)"""
        blocked = self.signalsBlocked()
        super().setChecked(checked)
        self._animation.stop()
        self._position = 1.0 if checked else 0.0
        self.update()
        self.blockSignals(blocked)

    def _animate(self, checked: bool):
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, value: float):
        self._position = value
        self.update()

    position = Property(float, _get_position, _set_position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        # Off track: visible on both themes (darker than a light window, lighter than a dark one)
        light_theme = palette.color(QPalette.ColorRole.Window).lightness() > 128
        off = palette.color(QPalette.ColorGroup.Active,
                            QPalette.ColorRole.Dark if light_theme else QPalette.ColorRole.Light)
        on = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        ratio = self._position
        track = QColor.fromRgbF(
            off.redF() + (on.redF() - off.redF()) * ratio,
            off.greenF() + (on.greenF() - off.greenF()) * ratio,
            off.blueF() + (on.blueF() - off.blueF()) * ratio,
        )
        if self.underMouse():
            track = track.lighter(115)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)
        margin = rect.height() * 0.14
        knob = rect.height() - margin * 2
        x = rect.left() + margin + (rect.width() - knob - margin * 2) * ratio
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, rect.top() + margin, knob, knob))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(on.lighter(130))
            painter.drawRoundedRect(rect, radius, radius)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


def sort_key(text: str) -> str:
    """Alphabetical sort key in any language: ignore case & accents (é = e)"""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class PreviewPopup(QLabel):
    """Widget preview shown next to cursor while hovering a widget row"""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("previewPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMargin(UIScaler.pixel(6))
        self._cache: dict[str, QPixmap | str] = {}
        self._name = ""

    def clear_cache(self):
        self._cache.clear()

    def show_widget(self, name: str, global_pos: QPoint):
        """Render (cached) & show preview of widget"""
        if name != self._name:
            self._name = name
            preview = self._cache.get(name)
            if preview is None:
                preview = self._render(name)
                self._cache[name] = preview
            if isinstance(preview, QPixmap):
                self.setPixmap(preview)
            else:
                self.setText(preview)
            self.adjustSize()
        offset = UIScaler.pixel(18)
        screen = self.screen().availableGeometry() if self.screen() else None
        x, y = global_pos.x() + offset, global_pos.y() + offset
        if screen is not None:
            x = min(x, screen.right() - self.width())
            y = min(y, screen.bottom() - self.height())
            if x < global_pos.x() < x + self.width() and y < global_pos.y() < y + self.height():
                y = global_pos.y() - self.height() - offset  # never under cursor
        self.move(x, y)
        self.show()

    def hide_preview(self):
        self._name = ""
        self.hide()

    @staticmethod
    def _render(name: str) -> QPixmap | str:
        from .widget_preview import render_widget

        try:
            pixmap = render_widget(cfg, name, dict(cfg.user.setting[name]))
        except Exception as error:  # plugins & widgets that need live data
            logger.debug("Preview error: %s", error, exc_info=True)
            return tr("Preview not available")
        limit = UIScaler.size(30)
        if pixmap.width() > limit or pixmap.height() > limit:
            pixmap = pixmap.scaled(limit, limit, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        return pixmap


class ModuleList(QWidget):
    """Module & widget list view"""

    def __init__(self, parent, module_control: ModuleControl):
        """Initialize module list setting

        Args:
            module_control: Module control (or widget) object.
        """
        super().__init__(parent)
        self.module_control = module_control
        self.items: dict[str, QListWidgetItem] = {}

        # Search & filter bar
        self.search_box = QLineEdit(self)
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText(f"{tr('Search')}...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.apply_filter)

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        layout_filter = QHBoxLayout()
        layout_filter.setSpacing(UIScaler.pixel(4))
        for filter_id, text in ((FILTER_ALL, "All"), (FILTER_ACTIVE, "Active"), (FILTER_INACTIVE, "Inactive")):
            chip = QPushButton(tr(text))
            chip.setObjectName("filterChip")
            chip.setCheckable(True)
            chip.setChecked(filter_id == FILTER_ALL)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.filter_group.addButton(chip, filter_id)
            layout_filter.addWidget(chip)
        self.filter_group.idClicked.connect(self.apply_filter)
        # Category filter, widgets only
        self.category_box = QComboBox(self)
        self.category_box.setVisible(module_control.type_id == "widget")
        self.category_box.addItem(tr(CATEGORY_ALL), CATEGORY_ALL)
        for category in (*(category for category, _ in WIDGET_CATEGORIES), CATEGORY_OTHER):
            self.category_box.addItem(tr(category), category)
        self.category_box.currentIndexChanged.connect(self.apply_filter)
        layout_filter.addWidget(self.category_box)
        layout_filter.addStretch(1)
        self.label_loaded = QLabel("")
        self.label_loaded.setObjectName("countBadge")
        layout_filter.addWidget(self.label_loaded)

        # List box
        self.listbox_module = QListWidget(self)
        self.listbox_module.setUniformItemSizes(True)
        # No selection: rows only carry their switch, a selected row would look enabled
        self.listbox_module.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.listbox_module.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.create_list()
        # Widget preview on hover
        self.preview_popup: PreviewPopup | None = None
        if module_control.type_id == "widget":
            self.preview_popup = PreviewPopup()
            self.destroyed.connect(self.preview_popup.deleteLater)
            self.listbox_module.setMouseTracking(True)
            self.listbox_module.viewport().installEventFilter(self)

        # Button
        button_enable = QPushButton(tr("Enable All"))
        button_enable.clicked.connect(self.module_button_enable_all)

        button_disable = QPushButton(tr("Disable All"))
        button_disable.clicked.connect(self.module_button_disable_all)

        layout_button = QHBoxLayout()
        layout_button.addWidget(button_enable)
        layout_button.addStretch(1)
        layout_button.addWidget(button_disable)

        # Layout
        layout_main = QVBoxLayout()
        layout_main.setSpacing(UIScaler.pixel(6))
        layout_main.addWidget(self.search_box)
        layout_main.addLayout(layout_filter)
        layout_main.addWidget(self.listbox_module)
        layout_main.addLayout(layout_button)
        margin = UIScaler.pixel(8)
        layout_main.setContentsMargins(margin, margin, margin, margin)
        self.setLayout(layout_main)

    def create_list(self):
        """Create module list"""
        for _name in sorted(self.module_control.names, key=lambda name: sort_key(module_label(name))):
            item = QListWidgetItem()
            item.setText(module_label(_name))
            item.setData(Qt.ItemDataRole.UserRole, _name)
            self.items[_name] = item
            self.listbox_module.addItem(item)
            module_item = ModuleControlItem(self, _name, self.module_control)
            self.listbox_module.setItemWidget(item, module_item)
            self.update_item_style(_name)

    def eventFilter(self, watched, event):
        """Show widget preview while hovering row name"""
        popup = self.preview_popup
        if popup is not None and watched is self.listbox_module.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                item = self.listbox_module.itemAt(event.position().toPoint())
                # Only over the name, not over switch & settings button
                if item is not None and event.position().x() < self.listbox_module.viewport().width() * 0.55:
                    popup.show_widget(item.data(Qt.ItemDataRole.UserRole), event.globalPosition().toPoint())
                else:
                    popup.hide_preview()
            elif event_type in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.Wheel):
                popup.hide_preview()
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        if self.preview_popup is not None:
            self.preview_popup.hide_preview()
        super().hideEvent(event)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh module & button toggle state"""
        if self.preview_popup is not None:
            self.preview_popup.clear_cache()  # setting or preset changed
        listbox_module = self.listbox_module
        for row_index in range(listbox_module.count()):
            item = listbox_module.item(row_index)
            listbox_module.itemWidget(item).update_state()
        self.apply_filter()

    def refresh_label(self):
        """Refresh count badge"""
        self.label_loaded.setText(
            f"{self.module_control.number_active} / {self.module_control.number_total}")
        self.label_loaded.setToolTip(tr("Enabled"))

    def is_enabled(self, name: str) -> bool:
        return bool(cfg.user.setting[name]["enable"])

    def update_item_style(self, name: str):
        """Active rows in full color, inactive ones dimmed"""
        item = self.items.get(name)
        if item is None:
            return
        palette = self.palette()
        group = QPalette.ColorGroup.Active if self.is_enabled(name) else QPalette.ColorGroup.Disabled
        item.setForeground(palette.color(group, QPalette.ColorRole.WindowText))

    def changeEvent(self, event):
        """Theme switched: rows colored again from the new palette"""
        if event.type() == QEvent.Type.PaletteChange:
            for name in self.items:
                self.update_item_style(name)
        super().changeEvent(event)

    def apply_filter(self, *_args):
        """Show rows matching search text and All / Active / Inactive filter"""
        text = self.search_box.text().strip().lower()
        mode = self.filter_group.checkedId()
        category = self.category_box.currentData() if self.module_control.type_id == "widget" else CATEGORY_ALL
        for name, item in self.items.items():
            enabled = self.is_enabled(name)
            visible = (
                (not text or text in item.text().lower() or text in name.lower())
                and (mode == FILTER_ALL or (mode == FILTER_ACTIVE) == enabled)
                and category in (CATEGORY_ALL, widget_category(name))
            )
            item.setHidden(not visible)

    def module_button_enable_all(self):
        """Enable all modules"""
        if self.module_control.number_active != self.module_control.number_total:
            if self.confirm_batch_toggle("Enable"):
                self.module_control.enable_all()
                app_signal.refresh.emit(True)

    def module_button_disable_all(self):
        """Disable all modules"""
        if self.module_control.number_active and self.confirm_batch_toggle("Disable"):
            self.module_control.disable_all()
            app_signal.refresh.emit(True)

    def confirm_batch_toggle(self, confirm_type: str) -> bool:
        """Batch toggle confirmation"""
        if not cfg.application["show_confirmation_for_batch_toggle"]:
            return True
        msg_text = f"<b>{confirm_type}</b> all {self.module_control.type_id}s?"
        confirm_msg = QMessageBox.question(
            self, tr("Confirm"), trm(msg_text),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        return confirm_msg == QMessageBox.StandardButton.Yes


class ModuleControlItem(QWidget):
    """Module control item: settings button & on/off switch, on the right of the row"""

    def __init__(self, parent, module_name: str, module_control: ModuleControl):
        """Initialize list box setting

        Args:
            module_name: Module (or widget) name string.
            module_control: Module control (or widget) object.
        """
        super().__init__(parent)
        self._parent = parent
        self.module_name = module_name
        self.module_control = module_control

        self.button_toggle = ToggleSwitch(self)
        self.button_toggle.setObjectName("buttonToggle")
        self.button_toggle.setChecked(self.is_enabled())
        self.button_toggle.setToolTip(tr("Enable / Disable"))
        # Use "clicked" to avoid trigger with "setChecked"
        self.button_toggle.clicked.connect(self.toggle_state)

        button_config = QPushButton(GEAR_SYMBOL)
        button_config.setObjectName("buttonConfig")
        button_config.setToolTip(tr("Config"))
        button_config.setCursor(Qt.CursorShape.PointingHandCursor)
        button_config.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button_config.pressed.connect(self.open_config_dialog)

        layout_item = QHBoxLayout()
        layout_item.setContentsMargins(0, 0, UIScaler.pixel(4), 0)
        layout_item.addStretch(1)
        layout_item.setSpacing(UIScaler.pixel(6))
        layout_item.addWidget(button_config)
        layout_item.addWidget(self.button_toggle)
        self.setLayout(layout_item)

    def is_enabled(self) -> bool:
        """Is module enabled"""
        return cfg.user.setting[self.module_name]["enable"]

    def toggle_state(self):
        """Toggle button state"""
        self.module_control.toggle(self.module_name)
        self.update_button_text()
        self._parent.apply_filter()

    def update_state(self):
        """Update button toggle state"""
        self.button_toggle.setChecked(self.is_enabled())
        self.update_button_text()

    def update_button_text(self):
        """Update row style & count badge"""
        self._parent.update_item_style(self.module_name)
        self._parent.refresh_label()

    def open_config_dialog(self):
        """Config dialog"""
        _dialog = UserConfig(
            parent=self._parent,
            key_name=self.module_name,
            preset_name=cfg.filename.setting,
            config_type=self.module_control.type_id,
            user_setting=cfg.user.setting,
            default_setting=cfg.default.setting,
            reload_func=self.reload_module,
        )
        _dialog.open()

    def reload_module(self):
        """Reload module & button state"""
        self.module_control.reload(self.module_name)
        self.update_state()
