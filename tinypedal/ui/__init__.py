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
Application UI, style
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


class UIScaler:
    """UI font & size scaler"""
    # Global base font size in point (not counting dpi scale)
    FONT_POINT = QApplication.font().pointSize()
    FONT_DPI = QFontMetrics(QApplication.font()).fontDpi()
    # Global base font size in pixel (dpi scaled)
    # dpi scale = font dpi / 96
    # px = (pt * dpi scale) * 96 / 72
    # px = pt * font dpi / 72
    FONT_DPI_SCALE = FONT_DPI / 96
    FONT_PIXEL_SCALED = FONT_POINT * FONT_DPI / 72

    @classmethod
    def font(cls, scale: float) -> float:
        """Scale UI font size (points) by base font size (not counting dpi scale)"""
        return cls.FONT_POINT * scale

    @classmethod
    def size(cls, scale: float) -> int:
        """Scale UI size (pixels) by base font size (scaled with dpi)"""
        return round(cls.FONT_PIXEL_SCALED * scale)

    @classmethod
    def pixel(cls, pixel: int):
        """Scale pixel size by base font DPI scale"""
        return round(cls.FONT_DPI_SCALE * pixel)


def resolve_color_theme(color_theme: str) -> str:
    """Window color theme in use: "Dark" or "Light", "System" follows OS setting"""
    if color_theme != "System":
        return color_theme
    if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return "Light"
    return "Dark"


def set_style_palette(color_theme: str):
    """Set style palette"""
    if resolve_color_theme(color_theme) == "Dark":
        palette_theme = palette_dark()
    else:
        palette_theme = palette_light()

    palette = QGuiApplication.palette()
    group_active = QPalette.ColorGroup.Active
    group_inactive = QPalette.ColorGroup.Inactive
    group_disabled = QPalette.ColorGroup.Disabled
    for color_active, color_inactive, color_disabled, color_role in palette_theme:
        palette.setColor(group_active, color_role, color_active)
        palette.setColor(group_inactive, color_role, color_inactive)
        palette.setColor(group_disabled, color_role, color_disabled)
    QApplication.setPalette(palette)


def palette_light():
    """Set palette light"""
    return (
        #   Active   Inactive   Disabled  Role
        ("#F4F5F8", "#F4F5F8", "#ECEDF1", QPalette.ColorRole.Window),
        ("#1F2328", "#1F2328", "#8C9096", QPalette.ColorRole.WindowText),
        ("#FFFFFF", "#FFFFFF", "#F3F4F6", QPalette.ColorRole.Base),
        ("#F6F7F9", "#F6F7F9", "#EEEFF2", QPalette.ColorRole.AlternateBase),
        ("#FFFFFF", "#FFFFFF", "#FFFFFF", QPalette.ColorRole.ToolTipBase),
        ("#1F2328", "#1F2328", "#1F2328", QPalette.ColorRole.ToolTipText),
        ("#8C9096", "#8C9096", "#8C9096", QPalette.ColorRole.PlaceholderText),
        ("#1F2328", "#1F2328", "#8C9096", QPalette.ColorRole.Text),
        ("#FFFFFF", "#FFFFFF", "#F3F4F6", QPalette.ColorRole.Button),
        ("#1F2328", "#1F2328", "#8C9096", QPalette.ColorRole.ButtonText),
        ("#FFFFFF", "#FFFFFF", "#FFFFFF", QPalette.ColorRole.BrightText),
        ("#FFFFFF", "#FFFFFF", "#FFFFFF", QPalette.ColorRole.Light),
        ("#E9EAED", "#E9EAED", "#F3F4F6", QPalette.ColorRole.Midlight),
        ("#A3A7AD", "#A3A7AD", "#A3A7AD", QPalette.ColorRole.Dark),
        ("#D0D3D8", "#D0D3D8", "#D0D3D8", QPalette.ColorRole.Mid),
        ("#1F2328", "#1F2328", "#1F2328", QPalette.ColorRole.Shadow),
        ("#2F6FEB", "#2B63D1", "#DADDE2", QPalette.ColorRole.Highlight),
        ("#FFFFFF", "#FFFFFF", "#5F6368", QPalette.ColorRole.HighlightedText),
        ("#1A7FE0", "#1A7FE0", "#8C9096", QPalette.ColorRole.Link),
        ("#8E44AD", "#8E44AD", "#8C9096", QPalette.ColorRole.LinkVisited),
    )


def palette_dark():
    """Set palette dark"""
    return (
        #   Active   Inactive   Disabled  Role
        ("#111318", "#111318", "#0F1115", QPalette.ColorRole.Window),
        ("#E9ECF2", "#E9ECF2", "#7C828D", QPalette.ColorRole.WindowText),
        ("#181B21", "#181B21", "#15171C", QPalette.ColorRole.Base),
        ("#1C1F26", "#1C1F26", "#1A1C22", QPalette.ColorRole.AlternateBase),
        ("#23262E", "#23262E", "#23262E", QPalette.ColorRole.ToolTipBase),
        ("#E8EAED", "#E8EAED", "#E8EAED", QPalette.ColorRole.ToolTipText),
        ("#8A8D93", "#8A8D93", "#8A8D93", QPalette.ColorRole.PlaceholderText),
        ("#E8EAED", "#E8EAED", "#7A7D83", QPalette.ColorRole.Text),
        ("#20232B", "#20232B", "#1A1C22", QPalette.ColorRole.Button),
        ("#E8EAED", "#E8EAED", "#7A7D83", QPalette.ColorRole.ButtonText),
        ("#FFFFFF", "#FFFFFF", "#FFFFFF", QPalette.ColorRole.BrightText),
        ("#5A5D63", "#5A5D63", "#3A3C40", QPalette.ColorRole.Light),
        ("#262A33", "#262A33", "#20232A", QPalette.ColorRole.Midlight),
        ("#121315", "#121315", "#101113", QPalette.ColorRole.Dark),
        ("#2E323C", "#2E323C", "#262931", QPalette.ColorRole.Mid),
        ("#0B0B0C", "#0B0B0C", "#0B0B0C", QPalette.ColorRole.Shadow),
        ("#4C8DFF", "#3B78E7", "#2E323C", QPalette.ColorRole.Highlight),
        ("#FFFFFF", "#FFFFFF", "#9AA0A6", QPalette.ColorRole.HighlightedText),
        ("#5AAEFF", "#5AAEFF", "#7A7D83", QPalette.ColorRole.Link),
        ("#C58AF9", "#C58AF9", "#7A7D83", QPalette.ColorRole.LinkVisited),
    )


def set_style_window(base_font_pt: int) -> str:
    """Set style window (not affecting overlay)"""
    # Scale font (point size)
    font_pt_item_name = 1.2 * base_font_pt
    font_pt_item_button = 1.05 * base_font_pt
    font_pt_item_toggle = 1.0 * base_font_pt
    font_pt_text_browser = 0.9 * base_font_pt
    font_pt_app_name = 1.4 * base_font_pt

    # Size
    border_radius_button = 0.4  # em
    border_radius_input = 4  # px
    border_radius_card = 8  # px, list & search box

    # Color
    palette = QApplication.palette()
    palette.setCurrentColorGroup(QPalette.ColorGroup.Active)
    color_active_window_text = palette.windowText().color().name()
    color_active_window = palette.window().color().name()
    color_active_base = palette.base().color().name()
    color_active_button = palette.button().color().name()
    color_active_mid = palette.mid().color().name()
    color_active_midlight = palette.midlight().color().name()
    color_active_highlighted_text = palette.highlightedText().color().name()
    color_active_highlight = palette.highlight().color().name()
    color_selection = f"#CC{color_active_highlight[1:]}"  # 80% alpha highlight

    palette.setCurrentColorGroup(QPalette.ColorGroup.Inactive)
    color_inactive_highlighted_text = palette.highlightedText().color().name()
    color_inactive_highlight = palette.highlight().color().name()

    palette.setCurrentColorGroup(QPalette.ColorGroup.Disabled)
    color_disabled_window_text = palette.windowText().color().name()
    color_disabled_highlighted_text = palette.highlightedText().color().name()
    color_disabled_highlight = palette.highlight().color().name()

    # Strip off indentation & comment
    return re.sub(r"\s{4,}|\/\*.*\/", "", f"""
        /* Misc */
        QSizeGrip {{
            image: none;
            width: 4px;
        }}
        QToolTip {{
            color: {color_active_window_text};
            background: {color_active_window};
            border: 1px solid {color_active_mid};
            padding: 0.2em 0.3em;
        }}
        QStatusBar::item {{
            border: none;
        }}

        /* Generic push button */
        QPushButton {{
            color: {color_active_window_text};
            background: {color_active_button};
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_button}em;
            padding: 0.3em 0.8em;
        }}
        QPushButton:hover {{
            border-color: {color_active_highlight};
        }}
        QPushButton:pressed,
        QPushButton:checked {{
            color: {color_inactive_highlighted_text};
            background: {color_inactive_highlight};
            border-color: {color_inactive_highlight};
        }}
        QPushButton:default {{
            border-color: {color_active_highlight};
        }}
        QPushButton:disabled {{
            color: {color_disabled_window_text};
            background: {color_active_window};
        }}
        CompactButton {{
            padding: 0.2em 0.1em;
        }}

        /* Generic text input */
        QLineEdit,
        QPlainTextEdit,
        QTextEdit {{
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_input}px;
            padding: 0.1em 0.25em;
            selection-color: {color_active_highlighted_text};
            selection-background-color: {color_active_highlight};
        }}
        QLineEdit:focus,
        QPlainTextEdit:focus,
        QTextEdit:focus {{
            border-color: {color_active_highlight};
        }}
        QLineEdit:disabled {{
            color: {color_disabled_window_text};
        }}

        /* Generic combo box */
        QComboBox {{
            color: {color_active_window_text};
            background: {color_active_button};
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_input}px;
            padding: 0.1em 1.6em 0.1em 0.4em;
        }}
        QComboBox:hover {{
            border-color: {color_active_highlight};
        }}
        QComboBox:disabled {{
            color: {color_disabled_window_text};
        }}
        QComboBox QAbstractItemView {{
            background: {color_active_base};
            border: 1px solid {color_active_mid};
            selection-color: {color_active_highlighted_text};
            selection-background-color: {color_active_highlight};
            outline: none;
        }}

        /* Generic checkbox & radio button (filled square/dot, no checkmark glyph) */
        QCheckBox::indicator,
        QRadioButton::indicator {{
            width: 1em;
            height: 1em;
            border: 1px solid {color_active_mid};
            background: {color_active_base};
        }}
        QCheckBox::indicator {{
            border-radius: {border_radius_input}px;
        }}
        QRadioButton::indicator {{
            border-radius: 0.5em;
        }}
        QCheckBox::indicator:hover,
        QRadioButton::indicator:hover {{
            border-color: {color_active_highlight};
        }}
        QCheckBox::indicator:checked,
        QRadioButton::indicator:checked {{
            background: {color_active_highlight};
            border-color: {color_active_highlight};
        }}
        QCheckBox:disabled,
        QRadioButton:disabled {{
            color: {color_disabled_window_text};
        }}
        QCheckBox::indicator:disabled,
        QRadioButton::indicator:disabled {{
            border-color: {color_disabled_window_text};
        }}

        /* Generic slider */
        QSlider::groove:horizontal {{
            height: 4px;
            background: {color_active_mid};
            border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{
            background: {color_active_highlight};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            width: 1em;
            height: 1em;
            margin: -0.4em 0;
            border-radius: 0.5em;
            background: {color_active_window_text};
        }}
        QSlider::handle:horizontal:hover {{
            background: {color_active_highlight};
        }}

        /* Tabs */
        QTabWidget::pane {{
            border: none;
            border-top: 1px solid {color_active_mid};
        }}
        QTabBar::tab {{
            color: {color_disabled_window_text};
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            padding: 0.4em 0.5em;
            font-weight: 600;
        }}
        QTabBar::tab:hover {{
            color: {color_active_window_text};
            border-bottom-color: {color_active_mid};
        }}
        QTabBar::tab:selected {{
            color: {color_active_window_text};
            border-bottom-color: {color_active_highlight};
        }}

        /* Menu */
        QMenuBar {{
            background: {color_active_window};
            border-bottom: 1px solid {color_active_mid};
        }}
        QMenuBar::item {{
            padding: 0.25em 0.6em;
            border-radius: {border_radius_input}px;
            background: transparent;
        }}
        QMenuBar::item:selected {{
            background: {color_active_midlight};
        }}
        QMenu {{
            background: {color_active_base};
            border: 1px solid {color_active_mid};
            padding: 0.2em;
        }}
        QMenu::item {{
            padding: 0.3em 1.5em 0.3em 1.8em;
            border-radius: {border_radius_input}px;
        }}
        QMenu::item:selected {{
            color: {color_active_highlighted_text};
            background: {color_active_highlight};
        }}
        QMenu::item:disabled {{
            color: {color_disabled_window_text};
            background: transparent;
        }}
        QMenu::separator {{
            height: 1px;
            background: {color_active_mid};
            margin: 0.2em 0.4em;
        }}

        /* Table header */
        QHeaderView::section {{
            color: {color_active_window_text};
            background: {color_active_window};
            border: none;
            border-right: 1px solid {color_active_mid};
            border-bottom: 1px solid {color_active_mid};
            padding: 0.2em 0.4em;
        }}
        QTableView {{
            gridline-color: {color_active_mid};
        }}

        /* Scroll bar */
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 0;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {color_active_mid};
            min-height: 24px;
            border-radius: 3px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background: {color_active_mid};
            min-width: 24px;
            border-radius: 3px;
            margin: 2px;
        }}
        QScrollBar::handle:hover {{
            background: {color_disabled_window_text};
        }}
        QScrollBar::add-line,
        QScrollBar::sub-line {{
            width: 0;
            height: 0;
        }}
        QScrollBar::add-page,
        QScrollBar::sub-page {{
            background: none;
        }}

        /* Main window (app only, overlay widgets keep their own fonts) */
        AppWindow, AppWindow QWidget, AppWindow QMenu {{
            font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif;
        }}
        AppWindow QMenuBar {{
            border-bottom: none;
            padding: 0.25em 0.3em;
        }}
        AppWindow QMenuBar::item {{
            padding: 0.3em 0.7em;
            border-radius: {border_radius_card}px;
        }}
        AppWindow QMenu {{
            border-radius: {border_radius_card}px;
            padding: 0.3em;
        }}
        #navRail {{
            background: {color_active_window};
            border-right: 1px solid {color_active_midlight};
        }}
        #navRailScroll, #navRailList {{
            background: transparent;
        }}
        #navRailScroll QScrollBar:vertical {{
            width: 6px;
        }}
        #navRailScroll QScrollBar::handle:vertical {{
            margin: 1px;
        }}
        #homeCard {{
            background: {color_active_base};
            border: 1px solid {color_active_midlight};
            border-radius: {border_radius_card}px;
        }}
        #homeValue {{
            font-size: {font_pt_app_name}pt;
        }}
        #homeHeader {{
            font-size: {font_pt_app_name}pt;
        }}
        #previewPopup {{
            background: {color_active_window};
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_card}px;
        }}
        #toast {{
            color: {color_active_window_text};
            background: {color_active_base};
            border: 1px solid {color_active_highlight};
            border-radius: {border_radius_card}px;
        }}
        #pageStack {{
            background: {color_active_window};
        }}

        /* Main status bar: pills */
        AppWindow QStatusBar {{
            border-top: 1px solid {color_active_midlight};
            padding: 0.15em 0.3em;
        }}
        AppWindow QStatusBar > QPushButton {{
            font-size: {font_pt_text_browser}pt;
            color: {color_disabled_window_text};
            border: 1px solid {color_active_mid};
            background: transparent;
            border-radius: 0.8em;
            padding: 0.15em 0.7em;
            margin: 0.15em 0.1em;
        }}
        AppWindow QStatusBar > QPushButton::hover {{
            color: {color_active_window_text};
            border-color: {color_active_highlight};
            background: transparent;
        }}
        AppWindow QStatusBar > #pillApi[running="true"] {{
            color: #3DDC84;
            border-color: #2E7D52;
        }}
        AppWindow QStatusBar > QPushButton::menu-indicator {{
            image: none;
            width: 0;
        }}
        AppWindow QStatusBar #labelSaving {{
            font-size: {font_pt_text_browser}pt;
            color: {color_disabled_window_text};
            padding: 0 0.4em;
        }}

        /* Notify bar */
        NotifyBar QPushButton {{
            font-weight: bold;
            padding: 0.2em;
            border: none;
            border-radius: 0;
            color: {color_active_highlighted_text};
        }}
        NotifyBar QPushButton::menu-indicator {{
            image: none;
            width: 0;
        }}
        NotifyBar UpdatesNotifyButton {{
            background: {color_active_highlight};
        }}

        /* Module list (tab): search, filter chips, rows with gear button & switch */
        ModuleList #searchBox {{
            font-size: {font_pt_item_button}pt;
            padding: 0.3em 0.5em;
            border-radius: {border_radius_card}px;
            background: {color_active_base};
        }}
        ModuleList #filterChip {{
            font-size: {font_pt_text_browser}pt;
            color: {color_disabled_window_text};
            background: transparent;
            border: 1px solid {color_active_mid};
            border-radius: 0.8em;
            padding: 0.15em 0.8em;
        }}
        ModuleList #filterChip:hover {{
            color: {color_active_window_text};
            border-color: {color_active_highlight};
        }}
        ModuleList #filterChip:checked {{
            color: {color_active_highlighted_text};
            background: {color_active_highlight};
            border-color: {color_active_highlight};
        }}
        ModuleList #countBadge {{
            font-size: {font_pt_text_browser}pt;
            font-weight: bold;
            color: {color_active_window_text};
            background: {color_active_midlight};
            border-radius: 0.7em;
            padding: 0.1em 0.6em;
        }}
        ModuleList > QListView {{
            font-size: {font_pt_item_name}pt;
            outline: none;
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_card}px;
            background: {color_active_base};
            padding: 0.2em;
        }}
        ModuleList > QListView::item {{
            border: none;
            border-radius: {border_radius_input}px;
            min-height: 1.5em;
            padding: 0.2em 0.25em 0.2em 0.5em;
            margin: 1px 0;
        }}
        ModuleList > QListView::item:selected {{
            background: transparent;
        }}
        ModuleList > QListView::item:hover {{
            background: {color_active_midlight};
        }}
        ModuleControlItem #buttonConfig {{
            font-family: "Segoe UI Symbol", "DejaVu Sans", sans-serif;
            font-size: {font_pt_item_name}pt;
            color: {color_disabled_window_text};
            background: transparent;
            border: none;
            border-radius: {border_radius_input}px;
            padding: 0 0.25em;
        }}
        ModuleControlItem #buttonConfig:hover {{
            color: {color_active_highlight};
            background: {color_active_mid};
        }}

        /* Preset list (tab) */
        PresetList > QListView,
        RestoreBackup > QListView {{
            font-size: {font_pt_item_name}pt;
            outline: none;
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_card}px;
            background: {color_active_base};
            padding: 0.2em;
        }}
        PresetList > QListView::item,
        RestoreBackup > QListView::item {{
            border: none;
            min-height: 1.25em;
            padding: 0.25em 0.25em 0.25em 0;
        }}
        PresetList > QListView::item:selected,
        RestoreBackup > QListView::item:selected {{
            selection-color: {color_active_highlighted_text};
            background: {color_active_highlight};
        }}
        PresetTagItem QLabel {{
            font-size: {font_pt_item_button}pt;
            color: {color_active_highlighted_text};
            border-radius: {border_radius_button}em;
            margin-left: 0.2em;
        }}
        PresetTagItem #trackTag {{
            background: {color_active_highlight};
        }}

        /* Preset transfer (dialog) */
        PresetTransfer > QListView {{
            outline: none;
            background: {color_active_window};
        }}
        PresetTransfer > QListView::item {{
            border: none;
            min-height: 1.75em;
        }}
        PresetTransfer > QListView::item:selected {{
            selection-color: {color_active_highlighted_text};
            background: {color_disabled_highlight};
        }}
        PresetTransfer > QListView QCheckBox {{
            font-size: {font_pt_item_name}pt;
            margin: 0.25em;
            border-radius: {border_radius_button}em;
        }}
        PresetTransfer ListHeader {{
            background: {color_active_base};
        }}
        PresetTransfer ListHeader QLabel {{
            font-size: {font_pt_item_name}pt;
            color: {color_disabled_highlighted_text};
            padding: 0 0.1em;
        }}
        PresetTransfer ListHeader CompactButton {{
            border: none;
            font-size: {font_pt_item_button}pt;
            padding: 0.2em;
        }}
        PresetTransfer ListHeader CompactButton::checked {{
            color: {color_inactive_highlighted_text};
            background: {color_inactive_highlight};
        }}
        PresetTransfer ListHeader CompactButton::hover,
        PresetTransfer ListHeader CompactButton::checked:hover {{
            color: {color_active_highlighted_text};
            background: {color_active_highlight};
        }}

        /* Spectate list (tab) */
        SpectateList > QListView,
        HotkeyList > QListView {{
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_card}px;
            background: {color_active_base};
        }}
        SpectateList > QListView {{
            font-size: {font_pt_item_button}pt;
            outline: none;
        }}
        SpectateList > QListView::item {{
            min-height: 1.75em;
            border: none;
        }}
        SpectateList > QListView::item:selected {{
            selection-color: {color_active_highlighted_text};
            background: {color_active_highlight};
        }}

        /* Hotkey list (tab) */
        HotkeyList > QListView {{
            font-size: {font_pt_item_name}pt;
            outline: none;
        }}
        HotkeyList > QListView QLabel {{
            font-size: {font_pt_item_name}pt;
            font-weight: bold;
            color: {color_inactive_highlighted_text};
            background: {color_inactive_highlight};
        }}
        HotkeyList > QListView QLabel:disabled {{
            color: {color_disabled_window_text};
            background: {color_disabled_highlight};
        }}
        HotkeyList > QListView::item {{
            border: none;
            min-height: 1.75em;
            color: {color_active_window_text};
        }}
        HotkeyList > QListView::item:selected {{
            background: transparent;
        }}
        HotkeyList > QListView::item:hover {{
            background: {color_disabled_highlight};
        }}
        HotkeyList > QListView::item:disabled {{
            color: {color_disabled_window_text};
        }}
        HotkeyConfigItem QPushButton {{
            font-size: {font_pt_item_toggle}pt;
            font-weight: bold;
            border: none;
            border-radius: {border_radius_button}em;
            height: none;
            margin: 0.25em 0.25em 0.25em 0;
            padding: 0 0.2em;
            color: {color_disabled_highlighted_text};
            background: {color_disabled_highlight};
        }}
        HotkeyConfigItem QPushButton::checked {{
            color: {color_inactive_highlighted_text};
            background: {color_inactive_highlight};
        }}
        HotkeyConfigItem QPushButton::hover,
        HotkeyConfigItem QPushButton::checked:hover {{
            color: {color_active_highlighted_text};
            background: {color_active_highlight};
        }}
        HotkeyConfigItem QPushButton::disabled {{
            color: {color_disabled_highlighted_text};
            background: {color_disabled_highlight};
        }}

        /* Base dialog */
        BaseDialog QStatusBar {{
            font-weight:bold;
        }}
        BaseDialog QTextBrowser {{
            font-size: {font_pt_text_browser}pt;
        }}
        BaseEditor QTableWidget ColorEdit {{
            border: none;
        }}

        /* Race calculator (fuel & tyres): cards, key figure tiles, results */
        RaceCalculator #fuelCard,
        RaceCalculator #fuelTile,
        DriverStatsViewer #fuelCard,
        DriverStatsViewer #fuelTile {{
            background: {color_active_base};
            border: 1px solid {color_active_midlight};
            border-radius: {border_radius_card}px;
        }}
        RaceCalculator #fuelCardTitle,
        DriverStatsViewer #fuelCardTitle {{
            font-size: {font_pt_item_button}pt;
            font-weight: bold;
        }}
        RaceCalculator #fuelTileValue,
        DriverStatsViewer #fuelTileValue {{
            font-size: {font_pt_app_name}pt;
            font-weight: bold;
        }}
        RaceCalculator #fuelValue {{
            font-weight: bold;
        }}
        RaceCalculator #fuelSource {{
            font-size: {font_pt_item_button}pt;
        }}
        RaceCalculator QLabel[warning="true"] {{
            color: #FF4400;
        }}
        RaceCalculator QAbstractSpinBox {{
            border: 1px solid {color_active_mid};
            border-radius: {border_radius_input}px;
            padding: 0.15em 0.35em;
            background: {color_active_window};
        }}
        RaceCalculator QAbstractSpinBox:focus {{
            border-color: {color_active_highlight};
        }}
        RaceCalculator QAbstractSpinBox:disabled {{
            color: {color_disabled_window_text};
        }}
        RaceCalculator #fuelSegment {{
            border-radius: 0;
            padding: 0.25em 0.6em;
        }}
        RaceCalculator #fuelSegment:first {{
            border-top-left-radius: {border_radius_input}px;
            border-bottom-left-radius: {border_radius_input}px;
        }}
        RaceCalculator #fuelSegment:last {{
            border-top-right-radius: {border_radius_input}px;
            border-bottom-right-radius: {border_radius_input}px;
        }}
        RaceCalculator PitStopPreview {{
            font-size: {font_pt_text_browser}pt;
        }}
        RaceCalculator QTableWidget {{
            background: {color_active_base};
            alternate-background-color: {color_active_window};
        }}

        /* Driver stats viewer: table & level marks (cards & tiles shared with race calculator) */
        DriverStatsViewer QTableWidget {{
            background: {color_active_base};
            alternate-background-color: {color_active_window};
        }}
        DriverStatsViewer #statsMark {{
            color: {color_active_highlight};
            font-weight: bold;
        }}
        DriverStatsViewer #statsTrack {{
            font-size: {font_pt_item_button}pt;
            font-weight: bold;
            padding: 0.2em 0.5em;
        }}

        /* What's new: header, version chip, theme cards, primary action */
        ReleaseNotesDialog #notesBody {{
            background: transparent;
        }}
        ReleaseNotesDialog #notesTitle {{
            font-size: {font_pt_app_name}pt;
            font-weight: bold;
        }}
        ReleaseNotesDialog #notesChip {{
            color: {color_active_highlighted_text};
            background: {color_active_highlight};
            border-radius: 0.6em;
            padding: 0.1em 0.6em;
            font-weight: bold;
        }}
        ReleaseNotesDialog #notesCard {{
            background: {color_active_base};
            border: 1px solid {color_active_midlight};
            border-radius: {border_radius_card}px;
        }}
        ReleaseNotesDialog #notesCardTitle {{
            font-size: {font_pt_item_button}pt;
            font-weight: bold;
            color: {color_active_highlight};
        }}
        ReleaseNotesDialog #notesItems {{
            font-size: {font_pt_item_toggle}pt;
        }}
        ReleaseNotesDialog #notesMono {{
            font-family: "Cascadia Mono", "Consolas", monospace;
            font-size: {font_pt_text_browser}pt;
        }}
        ReleaseNotesDialog #notesToggle {{
            border: none;
            background: transparent;
            color: {color_disabled_window_text};
            padding: 0.2em 0;
        }}
        ReleaseNotesDialog #notesToggle:hover {{
            color: {color_active_window_text};
        }}
        ReleaseNotesDialog #notesPrimary {{
            color: {color_active_highlighted_text};
            background: {color_active_highlight};
            border-color: {color_active_highlight};
            font-weight: bold;
        }}

        /* About dialog */
        About QLabel {{
            font-size: {font_pt_text_browser}pt;
        }}
        About QTextBrowser {{
            border: none;
        }}
        About #labelAppName {{
            font-size: {font_pt_app_name}pt;
        }}

        /* Config dialog */
        UserConfig #widgetPreview {{
            background: #39424E;
        }}
        UserConfig OptionSection {{
            font-size: {font_pt_app_name}pt;
            font-weight: bold;
            color: {color_active_window_text};
            border-bottom: 2px solid {color_active_highlight};
            padding: 0.6em 0 0.2em 0;
        }}
        UserConfig OptionGroup {{
            font-size: {font_pt_item_name}pt;
            font-weight: bold;
            color: {color_active_window_text};
            background: {color_disabled_highlight};
            padding: 0.2em 0;
        }}

        /* Display order dialog */
        DisplayOrder > QListView {{
            font-size: {font_pt_item_name}pt;
            outline: none;
        }}
        DisplayOrder > QListView::item {{
            margin: 1px;
            padding: 0.1em;
            border: 0.1em solid {color_disabled_highlight};
        }}
        DisplayOrder > QListView::item:selected {{
            selection-color: {color_active_highlighted_text};
            background: {color_selection};
            border: 0.1em solid {color_active_highlight};
        }}
        DisplayOrder > QListView::item:hover {{
            border: 0.1em solid {color_active_highlight};
        }}

        /* Tyre strategy planner (dialog) */
        TyreSetList {{
            font-size: {font_pt_item_toggle}pt;
            font-weight: bold;
            outline: none;
        }}
        TyreSetList::item {{
            margin: 1px;
            padding: 0.1em;
            border: 0.1em solid {color_disabled_highlight};
        }}
        TyreSetList::item:selected {{
            selection-color: {color_active_highlighted_text};
            background: {color_selection};
            border: 0.1em solid {color_active_highlight};
        }}
        TyreSetItemTag QLabel {{
            font-size: {font_pt_text_browser}pt;
            font-weight: bold;
            color: {color_active_highlighted_text};
            border-radius: {border_radius_button}em;
            margin-left: 0.2em;
        }}
        TyrePlanTable {{
            font-size: {font_pt_item_toggle}pt;
            font-weight: bold;
            outline: none;
        }}
        TyrePlanTable::item {{
            margin: 1px;
            padding: 0.1em;
            border: 0.1em solid {color_disabled_highlight};
        }}
        TyrePlanTable::item:selected {{
            margin: 1px;
            padding: 0.1em;
            selection-color: {color_active_highlighted_text};
            background: {color_selection};
        }}
        TyreStatusBar QLabel {{
            font-weight:bold;
        }}
        """)
