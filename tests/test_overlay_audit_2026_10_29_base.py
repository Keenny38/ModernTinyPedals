"""Overlay audit 2026-10-29 (other categories): shared overlay hook vehicle_reset"""

import pytest

from neopedal import realtime_state
from neopedal.widget._base import guarded_timer_event
from tests.test_overlay_audit_2026_10_29_G import field, make, set_reader, update  # noqa: F401  (field: fixture)


class FakeOverlay:
    """Plain object with what guarded_timer_event reads (not a QWidget)"""

    widget_name = "fake"
    timer_failed = False

    def __init__(self):
        self.updates = []
        self.resets = 0

    def vehicle_reset(self):
        self.resets += 1

    @guarded_timer_event
    def timerEvent(self, qt_event):
        self.updates.append(self.resets)


def test_vehicle_reset_runs_once_before_update_after_resets_change(monkeypatch):
    monkeypatch.setattr(realtime_state, "resets", 3)
    overlay = FakeOverlay()
    overlay.timerEvent(None)
    overlay.timerEvent(None)
    assert overlay.resets == 0  # first update: no reset for state seen at start
    monkeypatch.setattr(realtime_state, "resets", 4)  # followed car changed, session changed or back to garage
    overlay.timerEvent(None)
    overlay.timerEvent(None)
    assert overlay.resets == 1
    assert overlay.updates == [0, 0, 1, 1]  # reset ran before the update that saw it


class IdleOverlay(FakeOverlay):
    @guarded_timer_event
    def timerEvent(self, qt_event):
        pass


def test_vehicle_reset_skipped_once_unloaded(monkeypatch):
    monkeypatch.setattr(realtime_state, "resets", 1)
    overlay = IdleOverlay()
    overlay.timerEvent(None)
    overlay.__dict__.clear()  # unloaded (Base.__unload_resource): state kept empty
    monkeypatch.setattr(realtime_state, "resets", 2)
    overlay.timerEvent(None)
    assert not overlay.__dict__  # no reset state written back (unloaded check reads empty __dict__)


# --- Review follow-ups: light impacts (kerbs, scraping) are not incidents anywhere, max range line cleared
def test_suspension_travel_recorded_through_light_impacts(field, monkeypatch):  # noqa: F811
    from neopedal.module.module_wheels import calc_suspension_travel
    from neopedal.module_info import WheelsInfo

    monkeypatch.setattr(realtime_state, "active", True)
    output = WheelsInfo()
    gen = calc_suspension_travel(output, 20, 1.0, 0.0, True)
    set_reader(monkeypatch, "wheel", "suspension_deflection", (30.0,) * 4)
    set_reader(monkeypatch, "tyre", "vertical_deflection", (5.0,) * 4)
    set_reader(monkeypatch, "wheel", "position_vertical", (0.1,) * 4)
    set_reader(monkeypatch, "wheel", "suspension_force", (3000.0,) * 4)
    set_reader(monkeypatch, "wheel", "offroad", False)
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    set_reader(monkeypatch, "timing", "elapsed", 100.0)
    set_reader(monkeypatch, "vehicle", "impact_time", 99.5)  # scraping half a second ago
    set_reader(monkeypatch, "vehicle", "impact_magnitude", 60.0)
    gen.send(0)
    assert output.maxSuspensionPosition[0] == 30.0  # recorded
    set_reader(monkeypatch, "wheel", "suspension_deflection", (40.0,) * 4)
    set_reader(monkeypatch, "vehicle", "impact_magnitude", 2500.0)  # real impact: skipped for 3 seconds
    gen.send(0)
    assert output.maxSuspensionPosition[0] == 30.0
    set_reader(monkeypatch, "vehicle", "impact_time", 101.0)  # light impact after it: still skipped
    set_reader(monkeypatch, "vehicle", "impact_magnitude", 50.0)
    set_reader(monkeypatch, "timing", "elapsed", 101.5)
    gen.send(0)
    assert output.maxSuspensionPosition[0] == 30.0
    set_reader(monkeypatch, "timing", "elapsed", 102.6)  # 3 seconds after real impact
    gen.send(0)
    assert output.maxSuspensionPosition[0] > 30.0  # recorded again (filtered max moves toward 40)


def test_classic_suspension_max_range_line_cleared(field, monkeypatch):  # noqa: F811
    from neopedal.module_info import minfo

    monkeypatch.setattr(minfo.wheels, "currentSuspensionPosition", [20.0] * 4)
    monkeypatch.setattr(minfo.wheels, "maxSuspensionPosition", [50.0] * 4)
    widget = make("suspension_position", False, show_maximum_position_range=True, position_maximum_range=100)
    update(widget)
    bar = widget.bars_susp[0]
    assert bar.rect_max.width() > 0
    monkeypatch.setattr(minfo.wheels, "maxSuspensionPosition", [0.0] * 4)  # vehicle reset: not recorded yet
    update(widget)
    assert bar.rect_max.width() == 0 or bar.rect_max.x() >= bar.width()  # no line of previous car
    widget.deleteLater()


def test_roll_ratio_full_ratio_fits_zero_decimal(field, monkeypatch):  # noqa: F811
    widget = make("roll_angle", False, decimal_places=0, show_roll_angle_ratio=True,
                  show_degree_and_percentage_sign=True, prefix_roll_angle_ratio="")
    assert widget.bar_ratio.width() >= widget.bar_ratio.fontMetrics().horizontalAdvance("100%")
    widget.deleteLater()


# --- Engine & engine temperature: one game overheating warning option for both designs (formerly two)
@pytest.mark.parametrize("highlight, warning, classic, expected", [
    (False, True, False, True),  # former defaults: on for both designs now
    (None, None, False, None),  # options never saved: new default (True) added by validation
    (True, True, False, True),
    (False, False, False, False),  # modern turned off: kept off
    (True, False, False, False),  # modern turned off, classic on, modern design drawn: modern choice
    (True, False, True, True),  # classic layout on this overlay: classic choice
    (False, True, True, True),  # classic left at its former default: new default
])
@pytest.mark.parametrize("name", ["engine", "engine_temperature"])
def test_overheating_options_merged_with_choices_kept(name, highlight, warning, classic, expected):
    from neopedal.setting_preupdate import preupdate_user_setting

    widget = {"enable_classic_layout": classic}
    if highlight is not None:
        widget["show_game_overheating_highlight"] = highlight
    if warning is not None:
        widget["show_game_overheating_warning"] = warning
    preset = {name: widget}
    preupdate_user_setting((2, 51, 4), preset)
    assert "show_game_overheating_highlight" not in widget
    assert widget.get("show_game_overheating_warning") == expected
    current = {name: {"show_game_overheating_highlight": True, "show_game_overheating_warning": False}}
    preupdate_user_setting((2, 51, 5), current)  # saved by this version: nothing changed
    assert current[name] == {"show_game_overheating_highlight": True, "show_game_overheating_warning": False}


def test_old_preset_file_loads_merged_overheating_option():
    from neopedal import setting_validator, version
    from neopedal.setting import cfg
    from neopedal.userfile.json_setting import copy_setting

    cfg.default.set_default()
    default = copy_setting(dict(cfg.default.setting))
    for name in ("engine", "engine_temperature"):
        assert default[name]["show_game_overheating_warning"] is True  # both designs, on by default
        assert "show_game_overheating_highlight" not in default[name]
    old = copy_setting(default)
    old["preset"]["version"] = "2.51.3"
    old["engine"]["show_game_overheating_highlight"] = True  # turned on for classic layout
    old["engine"]["show_game_overheating_warning"] = True
    old["engine_temperature"]["show_game_overheating_highlight"] = False
    old["engine_temperature"]["show_game_overheating_warning"] = False  # turned off for modern design
    updated = setting_validator.PresetValidator.user_preset(old, default)
    assert updated["preset"]["version"] == version.SETTING_VERSION
    assert updated["engine"]["show_game_overheating_warning"] is True
    assert updated["engine_temperature"]["show_game_overheating_warning"] is False
    assert "show_game_overheating_highlight" not in updated["engine"]
    assert "show_game_overheating_highlight" not in updated["engine_temperature"]
    assert list(updated["engine"]) == list(default["engine"])  # option at its place in options page


def test_overheating_option_shown_for_both_designs(ui_env):
    from neopedal.setting import cfg
    from neopedal.widget._modern import design_option_keys

    for name in ("engine", "engine_temperature"):
        keys = list(cfg.user.setting[name])
        cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
        classic = design_option_keys(cfg, name, keys)
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
        modern = design_option_keys(cfg, name, keys)
        assert "show_game_overheating_warning" in classic and "show_game_overheating_warning" in modern
