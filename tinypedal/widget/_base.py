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
Overlay base window, events.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, overload

from PySide6.QtCore import QBasicTimer, QEvent, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Slot
from PySide6.QtGui import QActionGroup, QFont, QFontMetrics, QGuiApplication, QPalette, QPixmap
from PySide6.QtWidgets import QGridLayout, QLayout, QMenu, QWidget

from .. import app_signal, overlay_signal, realtime_state
from ..const_app import APP_NAME
from ..i18n import tr
from ..i18n.options import module_label
from ..perf_monitor import timed_event
from ..regex_pattern import CHOICE_COMMON, FONT_WEIGHT_MAP
from ..setting import Setting
from ._common import FontMetrics, MousePosition
from ._edit_frame import EditFrame, scale_widget_setting
from ._edit_mode import apply_values, edit_mode, forget_overlay, step_text, sync_edit_mode
from ._layout_guide import end_layout_guide, layout_guide
from ._painter import OverlayStyle, RawImage, RawText
from ._snapping import centered, fit_on_screens, step_on_grid
from ._snapping import move_to_screen as place_on_screen
from ._style import StyledConfig, overlay_theme, scale_overrides, theme_overrides

logger = logging.getLogger(__name__)
mousepos = MousePosition()  # single instance shared by all widgets
FADE_MS = 250
ARROW_KEYS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}
OPACITY_STEPS = (100, 90, 80, 70, 60, 50, 40)  # percent, context menu
# Window content (own or child widget repainted: update request on window) or place changed
PAINT_EVENTS = frozenset((
    QEvent.Type.UpdateRequest, QEvent.Type.Paint, QEvent.Type.Show, QEvent.Type.Hide,
    QEvent.Type.Move, QEvent.Type.Resize,
))


class PaintCounter:
    """Overlay window changes (GUI thread): each change gives the window a new "paint_serial",
    so stream & VR capture skip windows unchanged since their last copy"""

    count = 0


def position_values(pos: QPoint) -> dict:
    """Position options of overlay at pos"""
    return {"position_x": pos.x(), "position_y": pos.y()}


def store_screen_layout(config: Setting):
    """Remember widget positions for current screen setup"""
    if not config.application.get("enable_layout_per_screen_setup", False):
        return
    from ..template.setting_widget import WIDGET_FILENAME
    from ..userfile.layout_profile import profile_filename, screen_key, store_layout

    store_layout(
        config.user.setting, WIDGET_FILENAME,
        profile_filename(config.path.settings, config.filename.setting), screen_key())


def context_visible(context: str) -> bool:
    """Whether widget with visibility context is shown in current session & pit state"""
    if context == "Always" or not realtime_state.active:
        return True
    session = realtime_state.session_type
    if context == "Race":
        return session == 4
    if context == "Qualifying & Race":
        return session in (2, 4)
    if context == "Practice & Qualifying":
        return session in (0, 1, 2, 3)
    if context == "On Track":
        return not realtime_state.in_pits
    if context == "In Pits":
        return realtime_state.in_pits
    return True


class Base(QWidget):
    """Base window"""

    # Keep updating while hidden: widget records its own data (incidents, input history)
    update_while_hidden = False

    def __init__(self, config: Setting, widget_name: str):
        super().__init__()
        self.widget_name = widget_name

        # Base config
        self.cfg = config

        # Widget config
        self.wcfg = validate_option(self.cfg.user.setting[widget_name])

        # Overlay style
        style = self.cfg.user.config["overlay_style"]
        self.modern_style = overlay_theme(style).modern
        if self.modern_style:
            OverlayStyle.corner_scale = min(max(style["corner_radius_scale"], 0), 0.5)
            OverlayStyle.depth_effects = bool(style.get("enable_depth_effects", True))
        else:
            OverlayStyle.corner_scale = 0
            OverlayStyle.depth_effects = False
        # Theme colors (also legacy light & colorblind variants), modern font
        themed = theme_overrides(self.wcfg, self.cfg.default.setting[widget_name], style)
        if themed or self.modern_style:
            self.wcfg = StyledConfig(self.wcfg, themed)
        # Modern design restyle of classic drawing (see widget._modern.restyle)
        design = self.design_overrides(style)
        if design:
            self.wcfg = StyledConfig(self.wcfg, design)
        # Global overlay scale
        scaled = scale_overrides(self.wcfg, style.get("overlay_scale", 1.0), widget_name)
        if scaled:
            self.wcfg = StyledConfig(self.wcfg, scaled)

        # Base setting
        self.setWindowTitle(f"{APP_NAME} - {widget_name.capitalize()}")
        self.move(self.wcfg["position_x"], self.wcfg["position_y"])

        # Visibility: fade in & out
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.finished.connect(self.__fade_finished)
        self._fade_enabled = bool(style.get("enable_fade_animation", True))

        # Set update timer
        self._update_timer = QBasicTimer()
        self._update_interval = max(
            self.wcfg["update_interval"],
            self.cfg.application["minimum_update_interval"],
        )

        # Position when grabbed with mouse (undo history)
        self._drag_start: QPoint | None = None

    def design_overrides(self, style: dict) -> dict:
        """Option overrides of design (override), applied before overlay scale"""
        return {}

    def start(self):
        """Set initial widget state in orders, and start update"""
        self.__connect_signal()
        self.__set_window_attributes()  # 1
        self._edit_frame = EditFrame(self, module_label(self.widget_name), self.__resize_by_handle)
        self.__set_window_flags()  # 2
        self.__toggle_timer(not realtime_state.active)
        self.__keep_on_screen()
        sync_edit_mode()

    def stop(self):
        """Stop and close widget"""
        widget_name = self.widget_name
        forget_overlay(widget_name)
        self._fade.stop()
        self.__toggle_timer(True)
        self.__break_signal()
        self.__unload_resource()
        if not self.close():
            logger.error("FAILED TO CLOSE: widget %s", widget_name)

    @property
    def closed(self) -> bool:
        """Close state"""
        return not self.__dict__ and self.close()

    def post_update(self):
        """Run once after state inactive"""

    def __unload_resource(self):
        """Unload widget resource"""
        self.__dict__.clear()

    def screen_opacity(self) -> float:
        """Window opacity on screen: none for overlay shown on stream only while locked (see stream_overlay),
        visible while unlocked for positioning"""
        if self.cfg.overlay["fixed_position"] and self.wcfg.get("stream_visibility") == "Stream Only":
            return 0.0
        return self.wcfg["opacity"]

    def __set_window_attributes(self):
        """Set window attributes"""
        self.setWindowOpacity(self.screen_opacity())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if self.cfg.compatibility["enable_translucent_background"]:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            self.__set_window_style()

    def __set_window_flags(self):
        """Set window flags"""
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if not self.cfg.overlay["vr_compatibility"]:  # hide taskbar widget
            self.setWindowFlag(Qt.WindowType.Tool, True)
        if self.cfg.compatibility["enable_bypass_window_manager"]:
            self.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint, True)
        self.__toggle_lock(locked=self.cfg.overlay["fixed_position"])

    def __set_window_style(self):
        """Set window style"""
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, self.cfg.compatibility["background_color_global"])
        self.setPalette(palette)

    def __save_position(self, store_now: bool = True):
        """Save widget position

        Args:
            store_now: write screen layout profile now, else once moves stop (arrow keys).
        """
        save_changes = False
        x_pos = self.x()
        y_pos = self.y()
        if self.wcfg["position_x"] != x_pos:
            self.wcfg["position_x"] = x_pos
            save_changes = True
        if self.wcfg["position_y"] != y_pos:
            self.wcfg["position_y"] = y_pos
            save_changes = True
        if save_changes:
            self.cfg.save()
            if store_now:
                store_screen_layout(self.cfg)
            else:
                edit_mode().store_layout_soon()

    def __keep_on_screen(self):
        """Overlay outside of every screen (monitor gone, preset made on another computer)
        brought back on nearest screen, position not saved (back in place once screen is back)"""
        if (
            not self.cfg.compatibility.get("enable_window_position_correction", True)
            or self.cfg.user.config.get("vr_overlay", {}).get("enable_vr_overlay", False)  # drawn in headset
            or QGuiApplication.platformName() == "offscreen"  # no real screen (tests, self test)
        ):
            return
        pos = fit_on_screens(self.geometry(), [screen.geometry() for screen in QGuiApplication.screens()])
        if pos is not None:
            logger.info("OVERLAY: %s outside of screens, shown at %d, %d", self.widget_name, pos.x(), pos.y())
            self.move(pos)

    def __set_input_transparent(self, transparent: bool) -> bool:
        """Clicks go through overlay (locked) or not, returns whether window was hidden by change

        Window shown: native window flag changed in place, no hide & show (no flicker of every
        overlay on lock & unlock). Not created yet: widget flag set, window created with it.
        """
        flag = Qt.WindowType.WindowTransparentForInput
        flags = self.windowFlags()
        if bool(flags & flag) == transparent:
            return False
        handle = self.windowHandle()
        if handle is not None and self.isVisible():
            new_flags = flags | flag if transparent else flags ^ flag
            self.overrideWindowFlags(new_flags)
            handle.setFlags(new_flags)
            return False
        self.setWindowFlag(flag, transparent)  # hides window
        return True

    @Slot(bool)  # type: ignore[operator]
    def __toggle_lock(self, locked: bool):
        """Toggle widget lock state"""
        hidden = self.__set_input_transparent(locked)
        # Visual edit mode while unlocked
        self._edit_frame.set_visible(not locked)
        self._edit_frame.set_editing(realtime_state.editing and not locked)
        # Need re-check after lock/unlock (shown while unlocked, visibility context while locked)
        self.__refresh_visibility(animate=not hidden)

    @Slot(bool)  # type: ignore[operator]
    def __set_editing(self, editing: bool):
        """Edit mode started or ended: outline always shown, overlay shown even if hidden"""
        self._edit_frame.set_editing(editing and not self.cfg.overlay["fixed_position"])
        self.__refresh_visibility()

    def apply_placement(self):
        """Position, opacity or visibility options changed (undo, context menu): applied at once"""
        self.move(self.wcfg["position_x"], self.wcfg["position_y"])
        self.__refresh_visibility(animate=False)

    @Slot(bool)  # type: ignore[operator]
    def __toggle_vr_compat(self, enabled: bool):
        """Toggle widget VR compatibility"""
        self.setWindowFlag(Qt.WindowType.Tool, not enabled)
        # Need re-check
        self.__refresh_visibility(animate=False)

    @Slot(bool)  # type: ignore[operator]
    def __toggle_timer(self, paused: bool):
        """Toggle widget timer state"""
        if paused:
            self._update_timer.stop()
            self.post_update()
        elif self.update_while_hidden or not self.should_hide():  # hidden widget resumes when shown
            self._update_timer.start(self._update_interval, self)

    def __resize_by_handle(self, factor: float):
        """Scale widget pixel sizes (saved to preset), then reload widget"""
        setting = self.cfg.user.setting[self.widget_name]
        before = dict(setting)
        changed = scale_widget_setting(setting, factor, self.widget_name)
        if changed:
            edit_mode().record(self.widget_name, "Resize", {key: before[key] for key in changed}, changed)
            self.cfg.save()
            QTimer.singleShot(0, lambda name=self.widget_name: reload_widget(name))

    def should_hide(self) -> bool:
        """Hidden by auto hide, hotkey, or visibility context, always shown in edit mode"""
        if realtime_state.editing:
            return False
        if realtime_state.hidden:
            return True
        if not self.cfg.overlay["fixed_position"]:
            return False  # unlocked: always visible for positioning
        return not context_visible(self.wcfg.get("visibility_context", "Always"))

    @Slot(bool)  # type: ignore[operator]
    def __set_hidden(self, _hidden: bool):
        self.__refresh_visibility()

    @Slot()  # type: ignore[operator]
    def __context_changed(self):
        self.__refresh_visibility()

    def __refresh_visibility(self, animate: bool = True):
        """Show or hide widget, fade if enabled"""
        hide = self.should_hide()
        opacity = self.screen_opacity()
        # No update while hidden (hotkey, visibility context), saves CPU while driving
        if realtime_state.active:
            if hide and not self.update_while_hidden:
                self._update_timer.stop()
            elif not self._update_timer.isActive():
                self._update_timer.start(self._update_interval, self)
        self._fade.stop()
        if not (animate and self._fade_enabled) or opacity <= 0:  # nothing to fade on screen (stream only)
            self.setWindowOpacity(opacity)
            self.setHidden(hide)
            return
        if hide:
            if self.isVisible():
                self._fade.setStartValue(self.windowOpacity())
                self._fade.setEndValue(0.0)
                self._fade.start()
        else:
            if not self.isVisible():
                self.setWindowOpacity(0.0)
                self.show()
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(opacity)
            self._fade.start()

    def __fade_finished(self):
        if self._fade.endValue() == 0.0:
            self.hide()
            self.setWindowOpacity(self.screen_opacity())

    def __connect_signal(self):
        """Connect overlay lock and hide signal"""
        overlay_signal.locked.connect(self.__toggle_lock)
        overlay_signal.hidden.connect(self.__set_hidden)
        overlay_signal.context.connect(self.__context_changed)
        overlay_signal.paused.connect(self.__toggle_timer)
        overlay_signal.iconify.connect(self.__toggle_vr_compat)
        overlay_signal.editing.connect(self.__set_editing)

    def __break_signal(self):
        """Disconnect overlay lock and hide signal"""
        overlay_signal.locked.disconnect(self.__toggle_lock)
        overlay_signal.hidden.disconnect(self.__set_hidden)
        overlay_signal.context.disconnect(self.__context_changed)
        overlay_signal.paused.disconnect(self.__toggle_timer)
        overlay_signal.iconify.disconnect(self.__toggle_vr_compat)
        overlay_signal.editing.disconnect(self.__set_editing)

    def mouseMoveEvent(self, event):
        """Update widget position"""
        if mousepos.valid() and event.buttons() == Qt.MouseButton.LeftButton:
            # Magnetic snapping (Ctrl: free move), grid, Shift: one axis, see _common.MousePosition
            self.move(mousepos.position(self, event.globalPosition().toPoint(), event.modifiers()))
            # Show layout guide while dragging
            if self.cfg.application["show_layout_guides"]:
                guide = layout_guide()
                if guide.isVisible():
                    guide.track(self)
                else:
                    grid_size = self.cfg.application["grid_move_size"] if self.cfg.overlay["enable_grid_move"] else 0
                    guide.begin(self, grid_size)
            edit_mode().placement_changed(self.widget_name)

    def mousePressEvent(self, event):
        """Set offset position & press state, select widget"""
        # Certain situation or platform can bypass "WindowTransparentForInput" flag
        # Make sure overlay cannot be dragged while "fixed_position" enabled
        if self.cfg.overlay["fixed_position"]:
            return
        if event.buttons() == Qt.MouseButton.LeftButton:
            self._drag_start = self.pos()
            mousepos.config(
                event.position().toPoint(),
                self.cfg.overlay["enable_grid_move"],
                self.cfg.application["grid_move_size"],
                self.cfg.application["snap_gap"],
                self.cfg.application["snap_distance"],
                magnetic=self.cfg.application.get("enable_magnetic_snap", True),
                start=self.pos(),
            )
        edit_mode().select(self.widget_name)

    def mouseReleaseEvent(self, event):
        """Save position on release"""
        dragged = mousepos.valid()
        mousepos.reset()
        end_layout_guide()
        start, self._drag_start = self._drag_start, None
        if dragged and start is not None and start != self.pos():
            edit_mode().record(self.widget_name, "Move", position_values(start), position_values(self.pos()))
        self.__save_position()

    def keyPressEvent(self, event):
        """Unlocked overlay (clicked one has keyboard focus): arrow keys move it, undo & redo"""
        if self.cfg.overlay["fixed_position"]:
            super().keyPressEvent(event)
            return
        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        editor = edit_mode()
        if key in ARROW_KEYS and not ctrl:
            self.nudge_position(*ARROW_KEYS[key], 10 if shift else 1)
        elif ctrl and key == Qt.Key.Key_Z:
            editor.redo() if shift else editor.undo()
        elif ctrl and key == Qt.Key.Key_Y:
            editor.redo()
        elif key == Qt.Key.Key_Escape:
            editor.deselect(self.widget_name)
        elif key == Qt.Key.Key_Delete:
            self.disable_overlay()
        else:
            super().keyPressEvent(event)

    def event(self, event):
        """Count window repaints & moves (paint serial, see PaintCounter)"""
        result = super().event(event)
        # Not once stopped: its Hide event would set an attribute again, never seen "closed" (reload waits)
        if event.type() in PAINT_EVENTS and self.__dict__:
            PaintCounter.count += 1
            self.paint_serial = PaintCounter.count
        return result

    def changeEvent(self, event):
        """Overlay no longer active window (game or app clicked): not selected"""
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            name = self.__dict__.get("widget_name")  # gone once widget stopped
            if name:
                edit_mode().deselect(name)
        super().changeEvent(event)

    def nudge_position(self, step_x: int, step_y: int, count: int = 1):
        """Move by one pixel (or grid step) per count, presses in a row are one undo step"""
        grid = self.cfg.application["grid_move_size"] if self.cfg.overlay["enable_grid_move"] else 1
        pos = QPoint(
            step_on_grid(self.x(), step_x, grid, count) if step_x else self.x(),
            step_on_grid(self.y(), step_y, grid, count) if step_y else self.y(),
        )
        self.move_overlay(pos, "Move", merge=True)

    def move_overlay(self, pos: QPoint, action: str, merge: bool = False):
        """Move to position (keyboard, menu), saved & undoable

        Args:
            pos: new position.
            action: name of undo step.
            merge: merge with previous step (arrow key presses), screen layout saved once they stop.
        """
        before = position_values(self.pos())
        self.move(pos)
        edit_mode().record(self.widget_name, action, before, position_values(self.pos()), merge)
        self.__save_position(store_now=not merge)
        edit_mode().placement_changed(self.widget_name)

    def center_on_screen(self, horizontal: bool):
        """Center on its screen (centering rect of widget), horizontally or vertically"""
        pos = centered(self.centering_rect(), self.screen().geometry(), horizontal, self.pos())
        self.move_overlay(pos, "Centering")

    def move_to_screen(self, screen: Any):
        """Same relative place on another screen"""
        pos = place_on_screen(self.geometry(), self.screen().geometry(), screen.geometry())
        self.move_overlay(pos, "Move to Screen")

    def change_options(self, action: str, values: dict):
        """Change options from context menu, saved & undoable"""
        before = {key: self.wcfg.get(key) for key in values}
        edit_mode().record(self.widget_name, action, before, values)
        apply_values(self.widget_name, values)

    def disable_overlay(self):
        """Turn overlay off, undoable"""
        name = self.widget_name
        edit_mode().record(name, "Disable", {"enable": True}, {"enable": False})
        disable_widget(name)

    def contextMenuEvent(self, event):
        """Widget context menu"""
        name = self.widget_name
        editor = edit_mode()
        editor.select(name)
        menu = QMenu()
        actions = {}

        def add(menu_: QMenu, text: str, callback, checked: bool | None = None):
            action = menu_.addAction(text)
            if checked is not None:
                action.setCheckable(True)
                action.setChecked(checked)
            actions[action] = callback
            return action

        show_name = menu.addAction(module_label(name))
        show_name_font = show_name.font()
        show_name_font.setBold(True)
        show_name.setFont(show_name_font)
        menu.addSeparator()

        add(menu, tr("Config"), lambda: config_widget(name))
        menu.addSeparator()
        add(menu, tr("Center Horizontally"), lambda: self.center_on_screen(horizontal=True))
        add(menu, tr("Center Vertically"), lambda: self.center_on_screen(horizontal=False))
        screens = QGuiApplication.screens()
        if len(screens) > 1:
            menu_screen = menu.addMenu(tr("Move to Screen"))
            primary = QGuiApplication.primaryScreen()
            for index, screen in enumerate(screens, 1):
                size = screen.geometry()
                text = f"{tr('Screen')} {index}   {size.width()} \u00D7 {size.height()}"
                if screen is primary:
                    text = f"{text}   ({tr('Primary')})"
                add(menu_screen, text, lambda screen=screen: self.move_to_screen(screen), screen is self.screen())
        menu.addSeparator()

        menu_visibility = menu.addMenu(tr("Visibility"))
        group = QActionGroup(menu_visibility)
        current = self.wcfg.get("visibility_context", "Always")
        for choice in CHOICE_COMMON["^visibility_context$"]:
            group.addAction(add(menu_visibility, tr(choice), lambda choice=choice: self.change_options(
                "Visibility", {"visibility_context": choice}), choice == current))
        menu_opacity = menu.addMenu(tr("Opacity"))
        group = QActionGroup(menu_opacity)
        current_opacity = round(self.wcfg["opacity"] * 100)
        for percent in OPACITY_STEPS:
            group.addAction(add(menu_opacity, f"{percent}%", lambda percent=percent: self.change_options(
                "Opacity", {"opacity": percent / 100}), percent == current_opacity))
        menu.addSeparator()

        step = editor.history.peek_undo()
        if step is not None:
            add(menu, f"{tr('Undo')}{step_text(step)}", editor.undo)
        add(menu, tr("Reload"), lambda: reload_widget(name))
        add(menu, tr("Disable"), self.disable_overlay)
        extra_actions = tuple(self.menu_actions())
        if extra_actions:
            menu.addSeparator()
            for text, callback in extra_actions:
                add(menu, tr(text), callback)
        menu.addSeparator()
        if not realtime_state.editing:
            add(menu, tr("Edit Mode"), editor.enter)
        add(menu, tr("Lock Overlay"), lock_overlay)

        callback = actions.get(exec_menu(menu, event.globalPos()))
        if callback is not None:
            callback()

    def menu_actions(self):
        """Widget specific context menu entries: (name, callback) pairs, shown after the common ones"""
        return ()

    def centering_rect(self) -> QRect:
        """Part of widget centered on screen by Center actions (widget coordinates)

        Whole widget by default. A widget with a side part (such as an attached panel) can
        return its main part only, so that part is what ends up centered.
        """
        return self.rect()

    def closeEvent(self, event):
        """Ignore attempts to close via window Close button when VR compatibility enabled"""
        if self.__dict__:
            event.ignore()


class Overlay(Base):
    """Inherit base window, add common GUI methods"""

    def __init_subclass__(cls, **kwargs):
        """Record update & paint time of each widget class (only while performance monitor is enabled)"""
        super().__init_subclass__(**kwargs)
        for method_name, event in (("timerEvent", "update"), ("paintEvent", "paint")):
            # Also wrap methods from mixins (ex. Black box parts), which come before Overlay
            for klass in cls.__mro__:
                if klass is Overlay:
                    break
                method = klass.__dict__.get(method_name)
                if method is not None:
                    if not getattr(method, "timed", False):  # not wrapped by a parent widget already
                        setattr(cls, method_name, timed_event(method, event))
                    break

    def config_font(self, name: str = "", size: float = 1, weight: str = "") -> QFont:
        """Config font

        Used for draw text in widget that uses QPainter,
        or get font metrics reading for sizing elements.

        Args:
            name: font name string.
            size: font size in pixel, minimum limit 1px.
            weight (optional): font weight name string, convert name to capital.

        Returns:
            QFont object.
        """
        font = self.font()  # get existing widget font
        font.setFamily(name)
        font.setPixelSize(max(int(size), 1))
        if weight:
            font.setWeight(FONT_WEIGHT_MAP[weight])
        if self.modern_style:
            font.setFeature(QFont.Tag("tnum"), 1)  # fixed width digits for proportional font
            font.setFeature(QFont.Tag("calt"), 0)  # no ligature, such as "--" or "->"
            font.setFeature(QFont.Tag("liga"), 0)
        return font

    def get_font_metrics(self, font: QFont) -> FontMetrics:
        """Get font metrics

        Args:
            font: QFont object.

        Returns:
            FontMetrics object.
        """
        # Disable font hinting for more accuracy (necessary for pyside6)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        font_metrics = QFontMetrics(font)
        char_width = font_metrics.averageCharWidth()
        if self.modern_style:  # avoid clipping digits with proportional font
            char_width = max(char_width, font_metrics.horizontalAdvance("0"))
        return FontMetrics(
            width=char_width,
            height=font_metrics.height(),
            leading=font_metrics.leading(),
            capital=font_metrics.capHeight(),
            descent=font_metrics.descent(),
            voffset=self.__calc_font_offset(font_metrics),
        )

    def __calc_font_offset(self, metrics: QFontMetrics) -> int:
        """Calculate auto font vertical offset

        Find difference between actual height and height reading
        and use as offset for center vertical alignment position
        for overlay that uses QPainter drawing.

        Args:
            metrics: FontMetrics object.

        Returns:
            Calculated font offset in pixel.
        """
        if self.wcfg["enable_auto_font_offset"]:
            if self.modern_style:  # center capital letters, independent of font leading
                return round(metrics.height() / 2 - metrics.ascent() + metrics.capHeight() / 2)
            return (
                metrics.capHeight()
                + metrics.descent() * 2
                + metrics.leading() * 2
                - metrics.height()
            )
        return self.wcfg["font_offset_vertical"]

    @staticmethod
    def set_padding(size: int, scale: float, side: int = 2) -> int:
        """Set padding

        Args:
            size: reference font size in pixel.
            scale: scale font size for relative padding.
            side: number of sides to add padding.

        Returns:
            Padding size in pixel.
        """
        return round(size * scale) * side

    @staticmethod
    def set_text_alignment(align: int | str = 0) -> Qt.AlignmentFlag:
        """Set text alignment

        Args:
            align: 0 or "Center", 1 or "Left", 2 or "Right".

        Returns:
            Qt alignment.
        """
        if align == 0 or align == "Center":
            return Qt.AlignmentFlag.AlignCenter
        if align == 1 or align == "Left":
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

    @overload
    def set_rawtext(self, *, count: Literal[1] = 1, **kwargs: Any) -> RawText: ...

    @overload
    def set_rawtext(self, *, count: int, **kwargs: Any) -> tuple[RawText, ...]: ...

    def set_rawtext(  # type: ignore[misc]  # overloads only narrow return type by count
        self,
        *,
        font: QFont | None = None,
        text: str = "",
        width: int = 0,
        height: int = 0,
        fixed_width: int = 0,
        fixed_height: int = 0,
        offset_y: int = 0,
        fg_color: str = "",
        bg_color: str = "",
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        last: Any | None = None,
        count: int = 1,
    ) -> tuple[RawText, ...] | RawText:
        """Set RawText, keyword arguments only

        Args:
            font: QFont.
            text: bar text.
            width: fixed width in pixel.
            height: fixed height in pixel.
            fixed_width: fixed width in pixel, takes priority over width.
            fixed_height: fixed height in pixel, takes priority over height.
            offset_y: font vertical offset in pixel.
            fg_color: foreground (font) color.
            bg_color: background color.
            alignment: Qt.AlignmentFlag.
            last: cache last data for comparison.
            count: number of RawText to set.

        Returns:
            A single or multiple(tuple) RawText instances,
            depends on count value (default 1).
        """
        bar_set = (
            RawText(
                parent=self,
                font=font,
                width=width,
                height=height,
                fixed_width=fixed_width,
                fixed_height=fixed_height,
                offset_y=offset_y,
                fg_color=fg_color,
                bg_color=bg_color,
                text=text,
                alignment=alignment,
                last=last,
            )
            for _ in range(count)
        )
        if count > 1:
            return tuple(bar_set)
        return next(bar_set)

    @overload
    def set_rawimage(self, *, count: Literal[1] = 1, **kwargs: Any) -> RawImage: ...

    @overload
    def set_rawimage(self, *, count: int, **kwargs: Any) -> tuple[RawImage, ...]: ...

    def set_rawimage(  # type: ignore[misc]  # overloads only narrow return type by count
        self,
        *,
        image: QPixmap | None = None,
        width: int = 0,
        height: int = 0,
        fixed_width: int = 0,
        fixed_height: int = 0,
        bg_color: str = "",
        last: Any | None = None,
        count: int = 1,
    ) -> tuple[RawImage, ...] | RawImage:
        """Set RawImage, keyword arguments only

        Args:
            image: QPixmap image.
            width: fixed width in pixel.
            height: fixed height in pixel.
            fixed_width: fixed width in pixel, takes priority over width.
            fixed_height: fixed height in pixel, takes priority over height.
            bg_color: background color.
            last: cache last data for comparison.
            count: number of RawImage to set.

        Returns:
            A single or multiple(tuple) RawImage instances,
            depends on count value (default 1).
        """
        bar_set = (
            RawImage(
                parent=self,
                image=image,
                width=width,
                height=height,
                fixed_width=fixed_width,
                fixed_height=fixed_height,
                bg_color=bg_color,
                last=last,
            )
            for _ in range(count)
        )
        if count > 1:
            return tuple(bar_set)
        return next(bar_set)

    @staticmethod
    def set_grid_layout_vert(
        layout: QGridLayout,
        targets: tuple[QWidget, ...],
        row_start: int = 1,
        column: int = 4,
    ):
        """Set grid layout - vertical

        Default row index start from 1; reserve row index 0 for caption.
        """
        for index, target in enumerate(targets):
            layout.addWidget(target, index + row_start, column)

    @staticmethod
    def set_grid_layout_quad(
        layout: QGridLayout,
        targets: tuple[QWidget | QLayout, ...],
        row_start: int = 1,
        column_start: int = 0,
        column_offset: int = 9,
    ):
        """Set grid layout - quad - (0,1), (2,3), (4,5), ...

        Default row index start from 1; reserve row index 0 for caption.
        """
        for index, target in enumerate(targets):
            row = row_start + (index // 2)
            column = column_start + (index % 2) * column_offset
            if isinstance(target, QWidget):
                layout.addWidget(target, row, column)
            else:
                layout.addLayout(target, row, column)

    @staticmethod
    def set_grid_layout_table_row(
        layout: QGridLayout,
        targets: tuple[QWidget, ...],
        column_start: int = 0,
        row: int = 0,
        right_to_left: bool = False,
        hide_start: int = 99999,
    ):
        """Set grid layout - table by keys of each row"""
        if right_to_left:
            enum_target = enumerate(reversed(targets), column_start)
        else:
            enum_target = enumerate(targets, column_start)
        for column, target in enum_target:
            layout.addWidget(target, row, column)
            if hide_start <= column:
                target.hide()

    @staticmethod
    def set_grid_layout_table_column(
        layout: QGridLayout,
        targets: tuple[QWidget, ...],
        row_start: int = 0,
        column: int = 0,
        bottom_to_top: bool = False,
        hide_start: int = 99999,
    ):
        """Set grid layout - table by keys of each column"""
        if bottom_to_top:
            enum_target = enumerate(reversed(targets), row_start)
        else:
            enum_target = enumerate(targets, row_start)
        for row, target in enum_target:
            layout.addWidget(target, row, column)
            if hide_start <= row:
                target.hide()

    @staticmethod
    def set_grid_layout(
        gap: int = 0,
        gap_hori: int = -1,
        gap_vert: int = -1,
        margin: int = -1,
        align: Qt.AlignmentFlag | None = None,
    ) -> QGridLayout:
        """Set grid layout (QGridLayout)"""
        layout = QGridLayout()
        layout.setSpacing(gap)
        if gap_hori >= 0:
            layout.setHorizontalSpacing(gap_hori)
        if gap_vert >= 0:
            layout.setVerticalSpacing(gap_vert)
        if margin >= 0:
            layout.setContentsMargins(margin, margin, margin, margin)
        if align is not None:
            layout.setAlignment(align)
        return layout

    def set_primary_layout(
        self,
        layout: QLayout,
        margin: int = 0,
        align: Qt.AlignmentFlag | None = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
    ):
        """Set primary layout"""
        layout.setContentsMargins(margin, margin, margin, margin)
        if align is not None:
            layout.setAlignment(align)
        self.setLayout(layout)

    def set_primary_orient(
        self,
        target: QWidget | QGridLayout,
        column: int = 0,
        row: int = 0,
        option: str | None = "layout",
        default: str | int = 0,
    ):
        """Set primary layout (QGridLayout) orientation

        Orientation is defined by "layout" option in Widget JSON.

        Args:
            target: QWidget or QGridLayout that adds to primary layout.
            column: column index determines display order.
            row: row index determines side display order.
            option: layout option name in Widget JSON.
            default: default layout orientation, 0 = vertical, 1 = horizontal.
        """
        layout = self.layout()
        assert isinstance(layout, QGridLayout)
        if self.wcfg.get(option, 0) == default:
            order = column, row  # Vertical layout
        else:
            order = row, column  # Horizontal layout
        if isinstance(target, QWidget):
            layout.addWidget(target, *order)
        else:
            layout.addLayout(target, *order)


def validate_option(config: dict) -> dict:
    """Post validation for options"""
    # Check column/row index order, correct any overlapping indexes
    column_set = []
    for key in config:
        if key.startswith("display_order"):
            while config[key] in column_set:
                config[key] += 1
            column_set.append(config[key])
    return config


def exec_menu(menu: QMenu, pos: QPoint):
    """Show context menu, returns chosen action (replaced in tests)"""
    return menu.exec(pos)


def lock_overlay():
    """Lock overlay (leaves edit mode)"""
    from ..overlay_control import octrl

    octrl.toggle.lock()


def disable_widget(widget_name: str):
    """Disable widget"""
    from ..module_control import wctrl
    wctrl.toggle(widget_name)
    app_signal.refresh.emit(True)


def reload_widget(widget_name: str):
    """Reload widget"""
    from ..module_control import wctrl
    wctrl.reload(widget_name)
    app_signal.refresh.emit(True)


def config_widget(widget_name: str):
    """Open Overlay Options page at widget"""
    from PySide6.QtWidgets import QApplication, QMainWindow

    from ..ui.overlay_options import open_overlay_options

    # Find main window instance
    for _widget in QApplication.topLevelWidgets():
        if isinstance(_widget, QMainWindow):
            break
    else:
        return
    open_overlay_options(_widget, widget_name)
