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
Module list view (overlays have their own page, see overlay_view)

Each row: name, settings (gear) button and an on/off switch. Search box and All / Active /
Inactive filter on top.
"""

import unicodedata
from functools import partial
from typing import cast

import shiboken6
from PySide6.QtCore import Property, QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSize, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
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

FILTER_ALL = 0
FILTER_ACTIVE = 1
FILTER_INACTIVE = 2
GEAR_SYMBOL = "\u2699\ufe0e"  # gear, text style (not color emoji)

def reload_module(module_control, module_name: str, item=None):
    """Reload module (after config saved), then state of its list item if still shown"""
    module_control.reload(module_name)
    if item is not None and shiboken6.isValid(item):
        item.update_state()


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


class ModuleList(QWidget):
    """Module list view"""

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
            chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # reached by Tab, mouse click keeps search focus
            self.filter_group.addButton(chip, filter_id)
            layout_filter.addWidget(chip)
        self.filter_group.idClicked.connect(self.apply_filter)
        layout_filter.addStretch(1)
        self.label_loaded = QLabel("")
        self.label_loaded.setObjectName("countBadge")
        layout_filter.addWidget(self.label_loaded)

        # List box
        self.listbox_module = QListWidget(self)
        self.listbox_module.setUniformItemSizes(True)
        # No selection: rows only carry their switch, a selected row would look enabled
        self.listbox_module.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        # Reached by Tab: arrow keys move current row, Space toggles it, Enter opens its config
        self.listbox_module.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.listbox_module.installEventFilter(self)
        self.create_list()
        self.refresh_label()  # count badge shown from start, not after first toggle

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

    def list_key_pressed(self, key: int) -> bool:
        """Keyboard on module list: Space toggles current row, Enter opens its config, True if used"""
        listbox = self.listbox_module
        if listbox.currentRow() < 0 or listbox.currentItem().isHidden():
            first = next((row for row in range(listbox.count()) if not listbox.item(row).isHidden()), -1)
            listbox.setCurrentRow(first)
            if key not in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return first >= 0  # first key shows current row
        item = listbox.currentItem()
        row_widget = listbox.itemWidget(item) if item is not None else None
        if not isinstance(row_widget, ModuleControlItem):
            return False
        if key == Qt.Key.Key_Space:
            row_widget.button_toggle.click()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            row_widget.open_config_dialog()
            return True
        return False

    def eventFilter(self, watched, event):
        """Keyboard on module list"""
        if watched is self.listbox_module and event.type() == QEvent.Type.KeyPress:
            if self.list_key_pressed(event.key()):
                return True
        return super().eventFilter(watched, event)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh module & button toggle state"""
        listbox_module = self.listbox_module
        for row_index in range(listbox_module.count()):
            item = listbox_module.item(row_index)
            cast(ModuleControlItem, listbox_module.itemWidget(item)).update_state()
        self.apply_filter()
        self.refresh_label()

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
        """Show rows matching search words (case & accents ignored) and All / Active / Inactive filter"""
        words = sort_key(self.search_box.text()).split()
        mode = self.filter_group.checkedId()
        for name, item in self.items.items():
            enabled = self.is_enabled(name)
            found = sort_key(f"{item.text()} {name.replace('_', ' ')}")
            visible = (
                all(word in found for word in words)
                and (mode == FILTER_ALL or (mode == FILTER_ACTIVE) == enabled)
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
            reload_func=partial(reload_module, self.module_control, self.module_name, self),
        )
        _dialog.open()

    def reload_module(self):
        """Reload module & button state"""
        reload_module(self.module_control, self.module_name, self)
