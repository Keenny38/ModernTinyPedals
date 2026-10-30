"""Audit sweep fixes: overlay readings & options (radar fade, brake average, top speed, low fuel...),
overlay placement, settings import, director log, gap texts

Widgets are built on default settings (ui_env) with a neutral API reader, then single readers and
data module outputs are set to the case under test. Nothing is ever asked to a real game.
"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.api_control import api
from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (modern design unless modern=False), deleted after test"""
    created = []

    def make(name: str, modern: bool = True, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def reader(monkeypatch, group: str, name: str, value):
    """Neutral API reader returns value"""
    monkeypatch.setattr(getattr(api.read, group), name, lambda *args, **kwargs: value)


# --- Radar: hidden from fade out radius, fully shown below fade in radius
@pytest.mark.parametrize("modern", [True, False])
def test_radar_fade_follows_fade_radius(widgets, monkeypatch, modern):
    widget = widgets("radar", modern=modern, enable_auto_hide=True, enable_radar_fade=True,
                     radar_fade_in_radius=0.1, radar_fade_out_radius=0.5)
    widget.always_show = False
    radius = widget.radar_radius
    for distance, alpha in ((0.5, 0.0), (0.7, 0.0), (0.1, 1.0), (0.05, 1.0), (0.3, 0.5)):
        monkeypatch.setattr(minfo.vehicles, "nearestLine", radius * distance)
        assert widget.radar_alpha() == pytest.approx(alpha), distance


# --- Brake temperature: average starts from first reading, restarts after pause
@pytest.mark.parametrize("modern", [True, False])
def test_brake_average_starts_from_first_reading(widgets, monkeypatch, modern):
    widget = widgets("brake_temperature", modern=modern, show_average=True)
    reader(monkeypatch, "brake", "temperature", (500.0, 500.0, 400.0, 400.0))
    reader(monkeypatch, "inputs", "brake_raw", 1.0)
    reader(monkeypatch, "timing", "elapsed", 10.0)
    widget.timerEvent(None)
    averages = widget.averages if modern else [bar.last for bar in widget.bars_btavg]
    assert averages == [500.0, 500.0, 400.0, 400.0]  # not 0 + a few degrees
    widget.post_update()  # new session or vehicle
    averages = widget.averages if modern else [bar.last for bar in widget.bars_btavg]
    assert averages == [0.0] * 4


# --- Speedometer: top speed of the previous session not kept
@pytest.mark.parametrize("modern", [True, False])
def test_top_speed_reset_after_pause(widgets, monkeypatch, modern):
    widget = widgets("speedometer", modern=modern, show_speed_fastest=True)
    reader(monkeypatch, "engine", "gear", 4)
    reader(monkeypatch, "vehicle", "speed", 80.0)
    widget.timerEvent(None)
    assert widget.speed_fast == 80.0
    widget.post_update()
    reader(monkeypatch, "vehicle", "speed", 30.0)
    widget.timerEvent(None)
    assert widget.speed_fast == 30.0


# --- Fuel: no low amount warning before consumption is known
@pytest.mark.parametrize("modern", [True, False])
def test_no_low_fuel_warning_without_estimate(widgets, monkeypatch, modern):
    widget = widgets("fuel", modern=modern)
    monkeypatch.setattr(minfo.fuel, "estimatedLaps", 0.0)
    monkeypatch.setattr(minfo.fuel, "estimatedValidConsumption", 0.0)
    states = []
    if modern:
        monkeypatch.setattr(widget, "refresh", lambda state: states.append(state[3]))
        widget.timerEvent(None)
        assert states == [False]
        monkeypatch.setattr(minfo.fuel, "estimatedValidConsumption", 3.0)
        widget.timerEvent(None)
        assert states[-1] is True
    else:
        widget.timerEvent(None)
        assert widget.cells["remaining"].bg == widget.bar_style_curr[0]
        monkeypatch.setattr(minfo.fuel, "estimatedValidConsumption", 3.0)
        widget.timerEvent(None)
        assert widget.cells["remaining"].bg == widget.bar_style_curr[1]


# --- Director events log: writer thread never left busy, no formula in CSV cells
def test_events_log_writer_survives_unexpected_error(tmp_path, monkeypatch):
    from neopedal.ui.quick import director_log as dlog

    calls = []

    def write(path, rows):
        calls.append(rows)
        if len(calls) == 1:
            raise RuntimeError("unexpected")

    monkeypatch.setattr(dlog, "write_log_rows", write)
    writer = dlog.LogWriter()
    writer.append(str(tmp_path / "log.csv"), [("a",)])
    assert writer.flush(2.0)  # not busy forever after the error
    writer.append(str(tmp_path / "log.csv"), [("b",)])
    assert writer.flush(2.0)
    assert calls == [[("a",)], [("b",)]]


def test_events_log_lines_safe_in_spreadsheet(tmp_path):
    from neopedal.ui.quick import director_log as dlog

    path = str(tmp_path / "events" / "log.csv")
    dlog.write_log_rows(path, [("1", "0:01:40", "Kind", "=HYPERLINK(\"x\")", "+1.2", "GT3", "@SUM(A1) / -x / \ud800")])
    with open(path, encoding="utf-8-sig") as file:
        line = file.read().splitlines()[1]
    assert "'=HYPERLINK" in line and ",+1.2," in line and "'@SUM" in line
    assert [dlog.safe_cell(text) for text in ("-3 laps", "+0.5", "-HYPERLINK", "Name", 12)] == [
        "-3 laps", "+0.5", "'-HYPERLINK", "Name", 12]


# --- Damage stats & differential (classic): "100%" not cut to "100"
def test_full_percentage_keeps_sign(widgets, monkeypatch):
    damage = widgets("damage_stats", modern=False, decimal_places=0)
    damage.update_integrity(damage.bar_aero, 1.0, damage.bar_style_aero, 0.5)
    assert damage.bar_aero.text == "100%"
    diff = widgets("differential", modern=False, decimal_places=0, show_inverted_locking=False)
    assert diff.format_reading(1.0) == "100%" and diff.format_reading(0.5) == " 50%"


# --- Running lap time: tenths rounded before minutes are taken
def test_running_lap_time_never_60_seconds():
    from neopedal.widget._modern.drivers import running_text

    assert running_text(59.96) == "1:00.0"
    assert running_text(119.97) == "2:00.0"
    assert running_text(83.44) == "1:23.4"
    assert running_text(-1.0) == "0:00.0"


# --- Cruise (classic): huge odometer digit count no longer fails widget start
def test_cruise_odometer_digits_limited(widgets):
    widget = widgets("cruise", modern=False, show_odometer=True, odometer_maximum_digits=5000)
    assert len(str(int(widget.odm_range))) <= 12


# --- Elevation (classic): map of one or two nodes drawn as temp map, no IndexError
def test_elevation_short_map_uses_temp_map(widgets):
    widget = widgets("elevation", modern=False)
    widget.create_elevation_path([(0.0, 10.0)])
    assert widget.map_scaled is None
    widget.create_elevation_path([(0.0, 10.0), (50.0, 12.0), (100.0, 11.0)])
    assert widget.map_scaled


# --- Sectors: data reset while driving (sector index -1) never shown as sector 3 or "0.000" target
@pytest.mark.parametrize("modern", [True, False])
def test_sectors_skip_unknown_sector(widgets, monkeypatch, modern):
    widget = widgets("sectors", modern=modern)
    for data in (minfo.sectors.sessionBest, minfo.sectors.allTimeBest):
        monkeypatch.setattr(data, "sectorIndex", 1)
    widget.timerEvent(None)  # driving in sector 2
    for data in (minfo.sectors.sessionBest, minfo.sectors.allTimeBest):
        monkeypatch.setattr(data, "sectorIndex", -1)  # sector data reset
    widget.timerEvent(None)
    for data in (minfo.sectors.sessionBest, minfo.sectors.allTimeBest):
        monkeypatch.setattr(data, "sectorIndex", 1)
    widget.timerEvent(None)  # reset not taken as a sector: synced again, no sector just finished awaited
    assert (widget.last_sector_index if modern else widget.last_sector_idx) == 1
    assert widget.sector_shown and not widget.freeze_timer_start


# --- Trailing: plot speed proportional to time scale, whatever the update interval
@pytest.mark.parametrize("modern", [True, False])
def test_trailing_time_scale_sets_plot_speed(widgets, modern):
    cfg.application["minimum_update_interval"] = 10

    def speed(**options):
        widget = widgets("trailing", modern=modern, display_scale=2, **options)
        return widget.display_scale / widget._update_interval  # pixels per ms

    base = speed(update_interval=20, time_scale=1)
    assert base == pytest.approx(0.1)
    assert speed(update_interval=40, time_scale=1) == pytest.approx(base)
    assert speed(update_interval=40, time_scale=2) == pytest.approx(base * 2)
    assert speed(update_interval=20, time_scale=0.5) == pytest.approx(base * 0.5)


# --- Laps & position (classic): predicted lap total updated while lap progress is unchanged (pit stop)
def test_laps_total_updated_while_stopped(widgets, monkeypatch):
    widget = widgets("laps_and_position", modern=False, show_laps=True)
    reader(monkeypatch, "session", "finish_type", False)  # timed race
    reader(monkeypatch, "lap", "number", 5)
    reader(monkeypatch, "lap", "progress", 0.5)
    reader(monkeypatch, "timing", "current_laptime", 50.0)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)
    reader(monkeypatch, "session", "remaining", 1000.0)
    widget.timerEvent(None)
    before = widget.bar_laps.text
    reader(monkeypatch, "session", "remaining", 900.0)  # stopped in pits: same lap progress, less time left
    widget.timerEvent(None)
    assert widget.bar_laps.text != before


# --- Heading (modern): second decimal place of yaw & slip readings kept
def test_modern_heading_two_decimals(widgets, monkeypatch):
    widget = widgets("heading", decimal_places=2)
    states = []
    monkeypatch.setattr(widget, "refresh", states.append)

    def read():
        widget.slip_angle = 3.456
        return 10.0

    monkeypatch.setattr(widget, "read_heading", read)
    widget.timerEvent(None)
    assert states[-1][3] == pytest.approx(3.46)


# --- Tyre pressure: deviation average starts from first reading, restarts after pause
@pytest.mark.parametrize("modern", [True, False])
def test_pressure_average_starts_from_first_reading(widgets, monkeypatch, modern):
    widget = widgets("tyre_pressure", modern=modern, show_pressure_deviation=True)
    reader(monkeypatch, "tyre", "pressure", (170.0, 171.0, 172.0, 173.0))
    widget.timerEvent(None)
    averages = widget.averages if modern else widget.tpavg
    assert averages == [170.0, 171.0, 172.0, 173.0]
    widget.post_update()
    assert (widget.averages if modern else widget.tpavg) == [0.0] * 4


# --- Track notes: pit note of same index as last track note shown again, no note never kept hidden
@pytest.mark.parametrize("modern", [True, False])
def test_track_notes_timer_per_note_kind(widgets, monkeypatch, modern):
    widget = widgets("track_notes", modern=modern, maximum_display_duration=5,
                     show_pit_notes_while_in_pit=True, enable_auto_hide_if_not_available=False)
    reader(monkeypatch, "vehicle", "in_garage", False)
    reader(monkeypatch, "vehicle", "in_pits", False)
    monkeypatch.setattr(minfo.tracknotes.out, "currentNote", {"note": "T1"})
    monkeypatch.setattr(minfo.tracknotes.out, "currentIndex", 1)
    monkeypatch.setattr(minfo.tracknotes.pit, "currentNote", {"note": "Pit"})
    monkeypatch.setattr(minfo.tracknotes.pit, "currentIndex", 1)
    for elapsed in (0.0, 10.0):
        reader(monkeypatch, "timing", "elapsed", elapsed)
        widget.read_notes()
    assert widget.notes_hidden  # shown longer than maximum duration
    reader(monkeypatch, "vehicle", "in_pits", True)  # pit note, same index
    reader(monkeypatch, "timing", "elapsed", 11.0)
    widget.read_notes()
    assert not widget.notes_hidden
    reader(monkeypatch, "timing", "elapsed", 20.0)
    widget.read_notes()
    assert widget.notes_hidden
    reader(monkeypatch, "vehicle", "in_pits", False)  # track without note: "not available" shown
    monkeypatch.setattr(minfo.tracknotes.out, "currentNote", {})
    widget.read_notes()
    assert not widget.notes_hidden


# --- Steering meter (classic): scale marks spread over the whole scale whatever the degree option
def test_steering_meter_scale_marks_cover_scale(widgets):
    widget = widgets("steering_meter", modern=False)
    for degree in (5, 0, -90):
        gap, count = widget.scale_mark(degree, 900, 200)
        assert gap > 0 and gap * count <= 200
    assert widget.scale_mark(90, 900, 200) == (40.0, 5)


# --- Speed delta: zero or negative display range still shows the delta
def test_speed_delta_display_range_positive():
    from neopedal.widget.speed_delta import display_range

    assert display_range(-5.0, 1) == 5.0
    assert display_range(0.0, 1) == 0.1
    assert display_range(0, 0) == 1
    assert display_range(20.0, 1) == 20.0


# --- Classic designs: same option limits as modern design
def test_classic_option_limits_as_modern(widgets):
    toe = widgets("wheel_toe", modern=False, decimal_places_toe_angle=0, show_total_toe_angle=True,
                  decimal_places_total_toe_angle=0)
    assert toe.decimals_toe == 0 and toe.decimals_total == 0
    weight = widgets("weight_distribution", modern=False, decimal_places=0)
    assert weight.format_dist(52.34, "").rstrip("%") == "52"
    history = widgets("stint_history", modern=False, stint_history_count=10000)
    assert history.stint_slot == 100
    rank = widgets("driver_rank", modern=False, show_progress=False)
    assert rank.value_width >= len("Platinum 3")
    delta = widgets("deltabest", modern=False, show_delta_bar=True, delta_bar_length=0)
    assert delta.width() >= delta.delta_width


def test_modern_differential_starts_fully_locked(widgets):
    widget = widgets("differential")
    assert set(widget.locking.values()) == {1.0}


# --- Black box: tyre pressure in bar shown to 0.01 bar (about 1 kPa, as kPa & psi)
def test_black_box_bar_pressure_decimals(widgets):
    cfg.units["tyre_pressure_unit"] = "bar"
    assert widgets("black_box").pres_decimals == 2


# --- Brake performance & engine temperature (classic): neutral color for a delta shown as 0
def test_zero_delta_neutral_color(widgets):
    brake = widgets("brake_performance", modern=False, show_delta_braking_rate=True,
                    show_delta_braking_rate_in_percentage=False)
    brake.update_delta_rate(brake.bar_delta_rate, 0.001)
    assert brake.bar_delta_rate.bg == brake.bar_style_delta_rate[2]
    brake.update_delta_rate(brake.bar_delta_rate, 0.5)
    assert brake.bar_delta_rate.bg == brake.bar_style_delta_rate[1]
    engine = widgets("engine_temperature", modern=False, show_rate_of_change=True, show_oil_temperature=True)
    engine.update_rate(engine.bar_oil_rate, 0.0001)
    assert engine.bar_oil_rate.fg == engine.bar_style_rate[2]


# --- Flag: low fuel needs known consumption, energy (percent) not compared with fuel volume (liter)
def test_flag_low_amount():
    from neopedal.widget.flag import is_low_amount

    wcfg = {"low_fuel_volume_threshold": 20, "low_fuel_lap_threshold": 2, "low_energy_percentage_threshold": 100}
    assert is_low_amount(wcfg, False, 10.0, 1.5, 3.0)
    assert not is_low_amount(wcfg, False, 10.0, 0.0, 0.0)  # consumption not known yet
    assert not is_low_amount(wcfg, False, 30.0, 1.5, 3.0)  # lengthy track: more than volume threshold
    assert is_low_amount(wcfg, True, 30.0, 1.5, 12.0)  # energy percent: own threshold (default: laps only)
    assert not is_low_amount(wcfg, True, 30.0, 3.0, 12.0)
    wcfg["low_energy_percentage_threshold"] = 20
    assert not is_low_amount(wcfg, True, 30.0, 1.5, 12.0)  # lengthy track: more than energy threshold
    assert is_low_amount(wcfg, True, 15.0, 1.5, 12.0)


# --- Gear & pedal (classic): change of motor state or filtered input redrawn even with an equal sum
def test_redraw_on_change_with_equal_sum(widgets):
    gear = widgets("gear", modern=False, show_battery_bar=True)
    gear.update_battbar(gear.bar_battbar, 50.0, 2)  # draining
    gear.update_battbar(gear.bar_battbar, 49.0, 3)  # regenerating, same sum
    assert gear.bar_battbar.input_color == gear.battbar_color[1]
    pedal = widgets("pedal", modern=False, show_throttle=True)
    pedal.update_pedal(pedal.bar_throttle, 0.5 + 0.3, 0.5)
    pedal.update_pedal(pedal.bar_throttle, 0.4 + 0.4, 0.4)
    assert pedal.bar_throttle.last == (0.4, 0.8)


# --- Race plan: unreadable plan file logged (plan made from race calculator inputs instead)
def test_race_plan_unreadable_file_logged(tmp_path, caplog):
    from neopedal.widget.race_plan import load_plan_input

    assert load_plan_input(str(tmp_path / "missing.json")) is None
    broken = tmp_path / "plan.json"
    broken.write_text('{"setup": {"race_length": "abc"}', encoding="utf-8")
    assert load_plan_input(str(broken)) is None
    assert "plan.json not read" in caplog.text


# --- Overlay stopped although never started (start failed before connecting signals): closed without error
def test_stop_without_start(widgets, caplog):
    import warnings

    widget = widgets("speedometer")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no "failed to disconnect" warning either
        widget.stop()
    assert widget.closed


# --- Recorder: compressed lap saved although the new file is briefly locked (antivirus, sync)
def test_gzip_lap_saved_after_brief_lock(tmp_path, monkeypatch):
    import gzip
    import os

    from neopedal.module import module_recorder
    from neopedal.userfile import replace_retry  # noqa: F401  (retried replace used)

    real_replace = os.replace
    calls = []

    def locked_once(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError(32, "in use")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", locked_once)
    monkeypatch.setattr("neopedal.userfile.REPLACE_RETRY_DELAY", 0.0, raising=False)
    filename = str(tmp_path / "lap.csv.gz")
    assert module_recorder.write_gzip_file(filename, "a,b\n1,2\n")
    with gzip.open(filename, "rt", encoding="utf-8") as file:
        assert file.read() == "a,b\n1,2\n"


# --- Lap files: corrupt or crafted file never read whole into memory
def test_lap_file_reading_bounded(tmp_path, monkeypatch):
    from neopedal.userfile import telemetry_lap

    long_line = tmp_path / "long.csv"
    long_line.write_text("time,distance\n" + "1" * (telemetry_lap.MAX_LINE_LENGTH + 10) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        telemetry_lap.load_lap(str(long_line))
    monkeypatch.setattr(telemetry_lap, "MAX_FILE_ROWS", 3)
    many = tmp_path / "many.csv"
    many.write_text("time,distance\n" + "".join(f"{n},{n}\n" for n in range(10)), encoding="utf-8")
    with pytest.raises(ValueError):
        telemetry_lap.load_lap(str(many))
    info = tmp_path / "info.csv"
    info.write_text("# " + "x" * (telemetry_lap.MAX_INFO_LENGTH + 10) + "\n", encoding="utf-8")
    assert telemetry_lap.read_lap_info(str(info)) == {}


# --- Gap texts: rounded before minutes are taken, minutes keep the asked decimals
def test_gap_text_rounding_near_a_minute():
    from neopedal.process.results_text import gap_seconds_text

    assert gap_seconds_text(59.97, 1) == "+1:00.0"
    assert gap_seconds_text(59.9996) == "+1:00.000"
    assert gap_seconds_text(62.3456) == "+1:02.346"
    assert gap_seconds_text(62.36, 1) == "+1:02.4"
    assert gap_seconds_text(59.94, 1) == "+59.9"


# --- VR: placement kept within what the OpenXR layer draws
def test_vr_placement_within_layer_limits():
    from neopedal.vr_overlay import placement_from

    placement = placement_from({"overlay_width_meters": float("nan"), "distance_meters": 150.0,
                                "vertical_offset_meters": -500.0, "horizontal_offset_meters": float("inf"),
                                "enable_attach_to_headset": False})
    assert tuple(placement)[:4] == (0.8, 100.0, -100.0, 0.0)


# --- Overlay Options preview: pace & track notes drawn on sample notes (was: empty, auto hidden without notes)
@pytest.mark.parametrize("theme", ["Modern Dark", "Legacy Dark"])
@pytest.mark.parametrize("name", ["pace_notes", "track_notes"])
def test_notes_preview_not_empty(ui_env, bundled_fonts, name, theme):
    from neopedal.ui.widget_preview import render_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = theme
    picture = render_widget(cfg, name, dict(cfg.user.setting[name], enable_classic_layout=theme != "Modern Dark"))
    assert picture.width() > 50 and picture.height() > 10
