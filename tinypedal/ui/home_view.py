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
Home page: state at a glance (game, preset, widgets, overlay, version) & shortcuts
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..api_control import api
from ..const_app import APP_NAME, VERSION
from ..i18n import tr, trm
from ..module_control import mctrl, wctrl
from ..setting import cfg
from ..update import update_checker
from ._common import UIScaler


def api_state_text() -> tuple[str, bool]:
    """API state text & whether game is running"""
    if cfg.api["enable_active_state_override"]:
        state = "overriding"
    else:
        state = api.read.state.version()
    return state, bool(state) and state not in ("not running", "0.0")


class HomeCard(QFrame):
    """Title, big value, detail line and optional action button"""

    def __init__(self, parent, title: str, action_text: str = "", action: Callable[[], object] | None = None):
        super().__init__(parent)
        self.setObjectName("homeCard")
        self.label_title = QLabel(tr(title), self)
        self.label_title.setEnabled(False)  # muted color
        self.label_value = QLabel("", self)
        self.label_value.setObjectName("homeValue")
        self.label_value.setTextFormat(Qt.TextFormat.RichText)
        self.label_detail = QLabel("", self)
        self.label_detail.setWordWrap(True)
        self.label_detail.setEnabled(False)
        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(10)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(UIScaler.pixel(2))
        layout.addWidget(self.label_title)
        layout.addWidget(self.label_value)
        layout.addWidget(self.label_detail)
        layout.addStretch(1)
        if action is not None:
            button = QPushButton(tr(action_text), self)
            button.clicked.connect(action)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)

    def set_text(self, value: str, detail: str = ""):
        if self.label_value.text() != value:
            self.label_value.setText(value)
        if self.label_detail.text() != detail:
            self.label_detail.setText(detail)


class HomeView(QWidget):
    """Home page"""

    def __init__(self, parent, window, select_page: Callable[[str], object]):
        super().__init__(parent)
        content = QWidget(self)
        content.setObjectName("pageStack")
        layout_content = QVBoxLayout(content)
        margin = UIScaler.pixel(10)
        layout_content.setContentsMargins(margin, margin, margin, margin)
        layout_content.setSpacing(UIScaler.pixel(8))

        header = QLabel(f"<b>{APP_NAME}</b>", content)
        header.setObjectName("homeHeader")
        layout_content.addWidget(header)

        self.card_game = HomeCard(content, "Game")
        self.card_preset = HomeCard(content, "Preset", "Open", lambda: select_page("preset"))
        self.card_widget = HomeCard(content, "Widget", "Open", lambda: select_page("widget"))
        self.card_module = HomeCard(content, "Module", "Open", lambda: select_page("module"))
        self.card_overlay = HomeCard(content, "Overlay", "Command Palette", window.open_command_palette)
        self.card_version = HomeCard(content, "Version", "Tools", lambda: select_page("tools"))
        grid = QGridLayout()
        grid.setSpacing(UIScaler.pixel(8))
        cards = (self.card_game, self.card_preset, self.card_widget, self.card_module, self.card_overlay, self.card_version)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 2, index % 2)
        layout_content.addLayout(grid)

        tip = QLabel(tr("Tip: press Ctrl+K to find any widget, option, tool or preset. "
                        "Drop a preset or plugin file on this window to import it."), content)
        tip.setWordWrap(True)
        tip.setEnabled(False)
        layout_content.addWidget(tip)
        layout_content.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.addWidget(scroll)

        # Game state changes without refresh signal
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_live)
        self._timer.start(1000)
        self.refresh()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self):
        """Refresh all cards"""
        preset = cfg.filename.setting[:-5]
        locked = f" ({tr('locked')})" if cfg.filename.setting in cfg.user.filelock else ""
        autoload = tr("Auto Load Primary Preset") + ": " + (tr("On") if cfg.application["enable_auto_load_preset"] else tr("Off"))
        self.card_preset.set_text(f"<b>{preset}</b>{locked}", autoload)
        self.card_widget.set_text(
            f"<b>{wctrl.number_active}</b> / {wctrl.number_total}", tr("Enabled"))
        self.card_module.set_text(
            f"<b>{mctrl.number_active}</b> / {mctrl.number_total}", tr("Enabled"))
        if update_checker.is_updates():
            detail = trm(update_checker.message())
        else:
            detail = ""
        self.card_version.set_text(f"<b>v{VERSION}</b>", detail)
        self.refresh_live()

    def refresh_live(self):
        """Refresh game & overlay state"""
        state, running = api_state_text()
        dot = "#3DDC84" if running else "#808080"
        self.card_game.set_text(
            f"<span style='color:{dot}'>●</span> <b>{api.alias}</b>",
            tr("Running") if running else tr("Not running") if state == "not running" else state)
        flags = (
            tr("Auto Hide") if cfg.overlay["auto_hide"] else "",
            tr("VR Compatibility") if cfg.overlay["vr_compatibility"] else "",
        )
        self.card_overlay.set_text(
            f"<b>{tr('Locked') if cfg.overlay['fixed_position'] else tr('Unlocked')}</b>",
            " · ".join(flag for flag in flags if flag))
