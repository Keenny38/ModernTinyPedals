"""Modern overlay style tests"""

from tinypedal.widget._style import StyledConfig, modern_overrides, remap_color

STYLE = {
    "enable_modern_style": True,
    "overlay_theme": "Modern Dark",
    "enable_modern_font": True,
    "modern_font_name": "Bahnschrift",
    "corner_radius_scale": 0.2,
    "minimum_bar_gap": 2,
}


def test_remap_color():
    assert remap_color("#222222") == "#1B1F27"
    assert remap_color("#ffffff") == "#F4F6F9"
    assert remap_color("#88444444") == "#88373E4C"  # keep alpha
    assert remap_color("#123456") == "#123456"  # not in palette
    assert remap_color("#FFF") == "#FFF"  # short form untouched
    assert remap_color("") == ""


def test_only_default_values_are_restyled():
    default = {
        "font_name": "Consolas",
        "bar_gap": 0,
        "font_color": "#FFFFFF",
        "bkg_color": "#222222",
        "position_x": 0,
    }
    user = dict(default, font_color="#FF0000", position_x=100)
    overrides = modern_overrides(user, default, STYLE)
    assert overrides == {
        "font_name": "Bahnschrift",
        "bar_gap": 2,
        "bkg_color": "#1B1F27",
    }


def test_custom_font_and_gap_kept():
    default = {"font_name": "Consolas", "bar_gap": 0}
    user = {"font_name": "Arial", "bar_gap": 5}
    assert modern_overrides(user, default, STYLE) == {}


def test_disabled_options():
    default = {"font_name": "Consolas", "font_color": "#FFFFFF"}
    style = dict(STYLE, overlay_theme="Classic", enable_modern_font=False)
    assert modern_overrides(dict(default), default, style) == {}


def test_styled_config_writes_through():
    source = {"font_color": "#FFFFFF", "position_x": 0}
    styled = StyledConfig(source, {"font_color": "#F4F6F9"})
    assert styled["font_color"] == "#F4F6F9"
    styled["position_x"] = 42
    assert source["position_x"] == 42
    assert source["font_color"] == "#FFFFFF"  # override never saved


def test_theme_palettes():
    from tinypedal.widget._style import OVERLAY_THEMES, overlay_theme_names

    assert overlay_theme_names()[:len(OVERLAY_THEMES)] == tuple(OVERLAY_THEMES)
    default = {"font_color": "#FF2200"}
    for theme, expected in (
        ("Modern Dark", "#FF4D4F"),
        ("High Contrast", "#FF3B3B"),
        ("Colorblind Safe", "#D55E00"),
    ):
        style = dict(STYLE, overlay_theme=theme)
        assert modern_overrides(dict(default), default, style) == {"font_color": expected}
    assert modern_overrides(dict(default), default, dict(STYLE, overlay_theme="Classic")) == {}


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
