"""Overlay themes & style tests"""

import pytest

from tinypedal.widget._style import (
    BACKGROUND,
    FOREGROUND,
    ON_COLOR,
    THEME_NAMES,
    StyledConfig,
    option_role,
    overlay_theme,
    theme_color,
    theme_overrides,
)

STYLE = {
    "overlay_theme": "Modern Dark",
    "enable_colorblind_colors": False,
    "enable_modern_font": True,
    "modern_font_name": "Bahnschrift",
    "corner_radius_scale": 0.2,
    "minimum_bar_gap": 2,
}
MODERN_DARK = overlay_theme(STYLE)


def test_theme_color():
    assert theme_color("#222222", MODERN_DARK) == "#1B1F27"
    assert theme_color("#ffffff", MODERN_DARK) == "#F4F6F9"
    assert theme_color("#88444444", MODERN_DARK) == "#88373E4C"  # keep alpha
    assert theme_color("#123456", MODERN_DARK) == "#123456"  # not in palette
    assert theme_color("#FFF", MODERN_DARK) == "#FFF"  # short form untouched
    assert theme_color("#GG2200", MODERN_DARK) == "#GG2200"  # not a color
    assert theme_color("", MODERN_DARK) == ""


def test_overlay_theme():
    assert THEME_NAMES == ("Modern Dark", "Modern Light", "Legacy Dark", "Legacy Light")
    assert overlay_theme({"overlay_theme": "Legacy Light"}) == (False, True, False)
    assert overlay_theme({"overlay_theme": "Modern Light", "enable_colorblind_colors": True}) == (True, True, True)
    assert overlay_theme({"overlay_theme": "High Contrast"}) == overlay_theme({})  # removed theme: Modern Dark
    assert not overlay_theme({"overlay_theme": "Legacy Dark"}).recolors  # classic colors


def test_only_default_values_are_restyled():
    default = {
        "font_name": "Consolas",
        "bar_gap": 0,
        "font_color": "#FFFFFF",
        "bkg_color": "#222222",
        "position_x": 0,
    }
    user = dict(default, font_color="#FF0000", position_x=100)
    overrides = theme_overrides(user, default, STYLE)
    assert overrides == {
        "font_name": "Bahnschrift",
        "bar_gap": 2,
        "bkg_color": "#1B1F27",
    }


def test_custom_font_and_gap_kept():
    default = {"font_name": "Consolas", "bar_gap": 0}
    user = {"font_name": "Arial", "bar_gap": 5}
    assert theme_overrides(user, default, STYLE) == {}


def test_legacy_themes_keep_classic_look():
    default = {"font_name": "Consolas", "bar_gap": 0, "font_color": "#FFFFFF"}
    assert theme_overrides(dict(default), default, dict(STYLE, overlay_theme="Legacy Dark")) == {}
    light = theme_overrides(dict(default), default, dict(STYLE, overlay_theme="Legacy Light"))
    assert light == {"font_color": "#000000"}  # colors only: no modern font, no bar gap


def test_styled_config_writes_through():
    source = {"font_color": "#FFFFFF", "position_x": 0}
    styled = StyledConfig(source, {"font_color": "#F4F6F9"})
    assert styled["font_color"] == "#F4F6F9"
    styled["position_x"] = 42
    assert source["position_x"] == 42
    assert source["font_color"] == "#FFFFFF"  # override never saved


@pytest.mark.parametrize(("theme", "colorblind", "expected"), [
    ("Modern Dark", False, "#FF4D4F"),
    ("Modern Dark", True, "#D55E00"),
    ("Legacy Dark", True, "#D55E00"),
])
def test_colorblind_variant(theme, colorblind, expected):
    default = {"font_color": "#FF2200"}
    style = dict(STYLE, overlay_theme=theme, enable_colorblind_colors=colorblind)
    assert theme_overrides(dict(default), default, style) == {"font_color": expected}


@pytest.mark.parametrize("theme", ["Modern Light", "Legacy Light"])
def test_light_themes_stay_readable(theme):
    """Panels & text inverted, colors on panels darkened, text on colored background kept"""
    from tinypedal.widget._style import _contrast

    default = {
        "font_color_gap": "#FFFFFF", "background_color_gap": "#222222",  # text on panel
        "font_color_player": "#000000", "background_color_player": "#DDDDDD",  # highlighted row
        "font_color_flag": "#000000", "background_color_flag": "#FFFF00",  # text on colored background
        "font_color_gain": "#66EE00", "background_color_gain": "#333333",  # colored text on panel
        "bar_color": "#00CCFF",  # mark on panel
    }
    styled = {**default, **theme_overrides(dict(default), default, dict(STYLE, overlay_theme=theme))}
    rgb = {key: value[1:] for key, value in styled.items()}
    assert _contrast(rgb["background_color_gap"], "FFFFFF") < 1.5  # light panel
    assert _contrast(rgb["font_color_gap"], rgb["background_color_gap"]) > 7
    assert _contrast(rgb["font_color_player"], rgb["background_color_player"]) > 7  # dark row, light text
    assert styled["background_color_flag"] in ("#FFFF00", "#FDE047")  # kept (modern palette only)
    assert styled["font_color_flag"] in ("#000000", "#0E1116")
    assert _contrast(rgb["font_color_gain"], rgb["background_color_gain"]) >= 3
    assert _contrast(rgb["bar_color"], rgb["background_color_gap"]) >= 3


def test_option_role():
    options = {
        "font_color_x": "#000000", "background_color_x": "#222222", "font_color_y": "#AAAAAA",
        "font_color_z": "#333333", "font_color": "#FFFFFF", "background_color": "#FF2200",
    }
    assert option_role("background_color_x", options) == BACKGROUND
    assert option_role("bar_color", options) == FOREGROUND
    assert option_role("font_color_x", options) == ON_COLOR  # unreadable on own background: on a colored element
    assert option_role("font_color_y", options) == FOREGROUND  # light text on panel
    assert option_role("font_color_z", options) == ON_COLOR  # dark text without background
    assert option_role("font_color", options) == ON_COLOR  # on colored background


def test_theme_selects_design(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.widget._modern import uses_modern_design
    from tinypedal.widget._modern.theme import build_theme

    style = cfg.user.config["overlay_style"]
    saved = style["overlay_theme"]
    try:
        style["overlay_theme"] = "Legacy Light"
        assert not uses_modern_design(cfg, "speedometer")
        style["overlay_theme"] = "Modern Light"
        assert uses_modern_design(cfg, "speedometer")
        theme = build_theme(style)
        assert theme.surface.lightness() > 200 and theme.text.lightness() < 60
        assert theme.border.red() == 0  # dark hairline on light panels
        style["overlay_theme"] = "Modern Dark"
        assert build_theme(style).border.red() == 255
    finally:
        style["overlay_theme"] = saved


@pytest.mark.parametrize(("before", "colorblind"), [
    ({"enable_modern_style": False, "overlay_theme": "Modern Dark"}, False),
    ({"enable_modern_style": True, "overlay_theme": "Colorblind Safe"}, True),
    ({"overlay_theme": "Classic"}, False),
    ({"overlay_theme": "High Contrast"}, False),
    ({"overlay_theme": "My custom theme"}, False),
    ({"overlay_theme": "Legacy Light"}, False),  # dev build saved before update
])
def test_overlay_theme_migration(before, colorblind):
    """Update: Modern Dark for everyone, former Colorblind Safe theme kept as colorblind safe colors"""
    from tinypedal.setting_preupdate import preupdate_global_setting

    setting = {"overlay_style": dict(before)}
    preupdate_global_setting((2, 50, 3), setting)
    assert setting["overlay_style"]["overlay_theme"] == "Modern Dark"
    assert "enable_modern_style" not in setting["overlay_style"]
    assert setting["overlay_style"].get("enable_colorblind_colors", False) == colorblind


def test_window_theme_migration():
    from tinypedal.setting_preupdate import preupdate_global_setting

    for before in ("Dark", "Light", "System", "Legacy Light"):
        setting = {"application": {"window_color_theme": before}}
        preupdate_global_setting((2, 50, 3), setting)
        assert setting["application"]["window_color_theme"] == "Modern Dark"  # update: Modern Dark for everyone
    setting = {"application": {"window_color_theme": "Legacy Light"}, "overlay_style": {"overlay_theme": "Modern Light"}}
    preupdate_global_setting((2, 50, 4), setting)  # chosen after update: kept
    assert setting["application"]["window_color_theme"] == "Legacy Light"
    assert setting["overlay_style"]["overlay_theme"] == "Modern Light"


def test_overlay_scale_overrides():
    from tinypedal.widget._style import scale_overrides

    wcfg = {"font_size": 15, "bar_height": 10, "update_interval": 20, "driver_name_width": 18, "show_x": True,
            "display_scale": 1.0, "inner_gap": 2}
    assert scale_overrides(wcfg, 1.0) == {}
    scaled = scale_overrides(wcfg, 1.5)
    assert scaled == {"font_size": 22, "bar_height": 15}  # character counts & intervals untouched
    assert scale_overrides({"font_size": 15}, 10)["font_size"] == 45  # clamped to 3x


def test_overlay_scale_applied_to_widget(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.widget import speedometer

    cfg.user.config["overlay_style"]["overlay_scale"] = 2.0
    try:
        widget = speedometer.Realtime(cfg, "speedometer")
        assert widget.wcfg["font_size"] == round(cfg.user.setting["speedometer"]["font_size"] * 2)
        widget.wcfg["position_x"] = 123  # saved through to user setting
        assert cfg.user.setting["speedometer"]["position_x"] == 123
        assert cfg.user.setting["speedometer"]["font_size"] != widget.wcfg["font_size"]  # scale never saved
        widget.deleteLater()
    finally:
        cfg.user.config["overlay_style"]["overlay_scale"] = 1.0


def test_visibility_context():
    from tinypedal import realtime_state
    from tinypedal.widget._base import context_visible

    saved = realtime_state.active, realtime_state.session_type, realtime_state.in_pits
    try:
        realtime_state.active = False
        assert context_visible("Race")  # not driving: auto hide decides
        realtime_state.active = True
        realtime_state.session_type, realtime_state.in_pits = 2, False
        assert context_visible("Always") and context_visible("Qualifying & Race")
        assert not context_visible("Race") and context_visible("On Track") and not context_visible("In Pits")
        realtime_state.session_type, realtime_state.in_pits = 4, True
        assert context_visible("Race") and context_visible("In Pits") and not context_visible("On Track")
        assert not context_visible("Practice & Qualifying")
    finally:
        realtime_state.active, realtime_state.session_type, realtime_state.in_pits = saved


def test_every_widget_has_visibility_context():
    from tinypedal.template.setting_widget import WIDGET_DEFAULT

    assert all(setting["visibility_context"] == "Always" for setting in WIDGET_DEFAULT.values())


def test_edit_frame_resize(ui_env, monkeypatch):
    from PySide6.QtCore import QPoint

    from tinypedal.setting import cfg
    from tinypedal.widget import _base, speedometer
    from tinypedal.widget._edit_frame import drag_factor, scale_widget_setting

    assert drag_factor((100, 50), QPoint(50, 0)) == 1.5
    assert drag_factor((100, 50), QPoint(0, -25)) == 0.5
    assert drag_factor((100, 50), QPoint(-1000, 0)) == 0.3  # clamped
    setting = {"font_size": 10, "bar_height": 4, "driver_name_width": 18}
    assert scale_widget_setting(setting, 2) == {"font_size": 20, "bar_height": 8}

    reloads = []
    monkeypatch.setattr(_base, "reload_widget", reloads.append)
    cfg.overlay["fixed_position"] = False
    font_size = cfg.user.setting["speedometer"]["font_size"]
    widget = speedometer.Realtime(cfg, "speedometer")
    widget.start()
    try:
        from PySide6.QtCore import QCoreApplication, QEvent

        frame = widget._edit_frame
        assert not frame.handle.isVisibleTo(widget)  # unlocked but not hovered: hidden while driving
        QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.Enter))
        assert frame.handle.isVisibleTo(widget) and frame.outline.isVisibleTo(widget)
        QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))
        assert not frame.handle.isVisibleTo(widget)
        frame.set_visible(False)  # locked: never shown
        QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.Enter))
        assert not frame.outline.isVisibleTo(widget)
        widget._edit_frame.handle.on_resized(2.0)
        assert cfg.user.setting["speedometer"]["font_size"] == font_size * 2
        # Reload is queued: run it while still faked, else it reloads the real overlay in a later test
        QCoreApplication.processEvents()
        assert reloads == ["speedometer"]
    finally:
        cfg.user.setting["speedometer"]["font_size"] = font_size
        widget.stop()


def test_cached_fill_matches_direct_fill(ui_env):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPixmap

    from tinypedal.widget import _painter

    saved = _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects
    try:
        for corner, depth in ((0.0, True), (0.2, False), (0.2, True)):
            _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = corner, depth
            images = []
            for cached in (True, False):
                pixmap = QPixmap(60, 30)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                rect = QRectF(2, 3, 50, 20)
                if cached:
                    scratch = QPixmap(60, 30)
                    scratch_painter = QPainter(scratch)
                    _painter.fill_rect(scratch_painter, rect, "#336699")  # first draw of size: direct
                    scratch_painter.end()
                    _painter.fill_rect(painter, rect, "#336699")  # drawn again: cached pixmap
                    assert _painter._background_cache
                else:
                    radius = 20 * corner
                    _painter._fill_rect_direct(painter, rect, "#336699", radius, depth)
                painter.end()
                images.append(pixmap.toImage())
            differences = sum(
                1 for x in range(60) for y in range(30) if images[0].pixel(x, y) != images[1].pixel(x, y))
            assert differences == 0, (corner, depth, differences)
    finally:
        _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = saved


def test_hidden_widget_does_not_update(ui_env):
    from tinypedal import overlay_signal, realtime_state
    from tinypedal.setting import cfg
    from tinypedal.widget import speedometer

    saved = realtime_state.active, realtime_state.hidden, cfg.overlay["fixed_position"]
    realtime_state.active, realtime_state.hidden = True, False
    cfg.overlay["fixed_position"] = True
    widget = speedometer.Realtime(cfg, "speedometer")
    widget.start()
    try:
        assert widget._update_timer.isActive()
        realtime_state.hidden = True
        overlay_signal.hidden.emit(True)
        assert not widget._update_timer.isActive()
        realtime_state.hidden = False
        overlay_signal.hidden.emit(False)
        assert widget._update_timer.isActive()
    finally:
        widget.stop()
        realtime_state.active, realtime_state.hidden, cfg.overlay["fixed_position"] = saved


def test_character_bar_width_not_scaled():
    from tinypedal.widget._edit_frame import scale_widget_setting
    from tinypedal.widget._style import scale_overrides

    wcfg = {"font_size": 10, "bar_width": 5}
    assert scale_overrides(wcfg, 2.0, "fuel") == {"font_size": 20}  # bar_width = characters
    assert scale_overrides(wcfg, 2.0, "brake_pressure") == {"font_size": 20, "bar_width": 10}  # pixels
    setting = dict(wcfg)
    scale_widget_setting(setting, 2.0, "acceleration")
    assert setting == {"font_size": 20, "bar_width": 5}


def test_animated_fill_not_cached(ui_env):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPixmap

    from tinypedal.widget import _painter

    saved = _painter.OverlayStyle.corner_scale
    _painter.OverlayStyle.corner_scale = 0.2
    _painter._background_cache.clear()
    try:
        pixmap = QPixmap(300, 30)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        for width in range(100, 200):  # bar growing every frame
            _painter.fill_rect(painter, QRectF(0, 0, width, 20), "#FF0000")
        painter.end()
        assert not _painter._background_cache
    finally:
        _painter.OverlayStyle.corner_scale = saved


def test_black_box_updates_while_hidden():
    from tinypedal.widget import black_box, speedometer, trailing

    assert black_box.Realtime.update_while_hidden and trailing.Realtime.update_while_hidden
    assert not speedometer.Realtime.update_while_hidden


def render_raw_text(text: str, alignment, font, offset_y: int = 0, static: bool = True):
    """Render RawText cell, or the same cell drawn with drawText(rect) as before layout cache"""
    from PySide6.QtCore import QPoint, QRectF
    from PySide6.QtGui import QImage, QPainter, QRegion
    from PySide6.QtWidgets import QWidget

    from tinypedal.widget._painter import RawText, fill_rect

    class DrawTextCell(RawText):
        def paintEvent(self, event):
            painter = QPainter(self)
            self._pen_text.setColor(self.fg)
            painter.setPen(self._pen_text)
            fill_rect(painter, QRectF(0, 0, self._width, self._height), self.bg)
            painter.drawText(0, self._offset_y, self._width, self._height, self._alignment, self.text)

    cell = (RawText if static else DrawTextCell)(
        None, font=font, text=text, offset_y=offset_y, fg_color="#FFFFFF", alignment=alignment)  # no background: text only
    cell.resize(70, 20)
    image = QImage(70, 20, QImage.Format.Format_ARGB32)
    image.fill(0)
    cell.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)  # no window background
    return cell, image


def test_raw_text_cached_layout_matches_draw_text():
    """Cached text layout (QStaticText) draws text at the same pixels as drawText(rect, alignment)"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tinypedal.main import load_bundled_fonts
    from tinypedal.widget._painter import OverlayStyle

    load_bundled_fonts()  # same glyphs on every platform
    app = QApplication.instance()
    saved = app.styleSheet(), OverlayStyle.corner_scale, OverlayStyle.depth_effects
    # Text only: app style (set by UI tests) & overlay cell style (set by widget tests) left out
    app.setStyleSheet("")
    OverlayStyle.corner_scale, OverlayStyle.depth_effects = 0.0, False
    try:
        compare_raw_text_layouts(Qt.AlignmentFlag)
    finally:
        app.setStyleSheet(saved[0])
        OverlayStyle.corner_scale, OverlayStyle.depth_effects = saved[1:]


def compare_raw_text_layouts(align):
    from PySide6.QtGui import QFont

    from tinypedal.const_file import FontFile

    for bold in (False, True):
        font = QFont(FontFile.MODERN_FAMILY)
        font.setPixelSize(15)
        font.setBold(bold)
        for alignment in (align.AlignCenter, align.AlignLeft | align.AlignVCenter, align.AlignRight | align.AlignVCenter):
            for text in ("P12", "1:23.456 ", " -0.5", "21°C", "WWWWWWWWWWWW"):
                for offset_y in (0, 2):
                    _, image = render_raw_text(text, alignment, font, offset_y)
                    _, reference = render_raw_text(text, alignment, font, offset_y, static=False)
                    assert image == reference, (bold, int(alignment), text, offset_y)


def test_raw_text_layout_cache_invalidated():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont

    font = QFont("Consolas")
    font.setPixelSize(15)
    cell, _ = render_raw_text("P1", Qt.AlignmentFlag.AlignCenter, font)
    assert cell._static_source == "P1"
    position = cell._static_pos
    bigger = QFont(font)
    bigger.setPixelSize(18)
    cell.setFont(bigger)  # font change: laid out again on next paint
    assert cell._static_source is None
    cell.text = "P10"
    cell.grab()
    assert cell._static_source == "P10" and cell._static_pos != position
    position = cell._static_pos
    cell.resize(90, 20)
    cell.grab()
    assert cell._static_pos.x() > position.x()  # centered in wider cell


def test_transparent_cell_not_shaded():
    """Depth shading & rounded corners only on visible panels, transparent cells draw nothing"""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget import _painter

    saved = _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects
    _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = 0.2, True
    try:
        image = QImage(40, 20, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        for _ in range(2):  # direct, then cached size
            _painter.fill_rect(painter, QRectF(0, 0, 40, 20), Qt.GlobalColor.transparent)
            _painter.fill_rect(painter, QRectF(0, 0, 40, 20), "#00000000")
        painter.end()
        assert all(image.pixel(x, y) == 0 for x in range(40) for y in range(20))
    finally:
        _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = saved


def test_raw_text_background_kept_while_unchanged():
    """Cell keeps its background pixmap while color, size & style stay, same pixels as fill_rect"""
    from PySide6.QtCore import QPoint, QRectF
    from PySide6.QtGui import QImage, QPainter, QRegion
    from PySide6.QtWidgets import QWidget

    from tinypedal.widget import _painter

    saved = _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects
    _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = 0.2, True
    try:
        cell = _painter.RawText(None, text="", bg_color="#336699")
        cell.resize(60, 20)
        cell.grab()
        cell.grab()  # size seen twice: cached
        pixmap = cell._bg_pixmap
        assert pixmap is not None
        cell.grab()
        assert cell._bg_pixmap is pixmap  # reused, no style lookup
        cell.bg = "#993366"
        cell.grab()
        assert cell._bg_pixmap is not pixmap
        images = []
        for direct in (False, True):  # cell render, then same fill drawn by fill_rect
            image = QImage(60, 20, QImage.Format.Format_ARGB32)
            image.fill(0)
            if direct:
                painter = QPainter(image)
                _painter.fill_rect(painter, QRectF(0, 0, 60, 20), "#993366")
                painter.end()
            else:
                cell.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
            images.append(image)
        assert images[0] == images[1]
        _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = 0.0, False
        cell.grab()  # flat style: plain fill, no pixmap needed
        assert cell._bg_pixmap is not None  # kept for when style comes back, not used
    finally:
        _painter.OverlayStyle.corner_scale, _painter.OverlayStyle.depth_effects = saved
