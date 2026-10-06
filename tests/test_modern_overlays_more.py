"""Modern design of black box, chat, elevation, flag, race notifications, RPM LED, steering meter &
spotter, spotter clear signal & cars coming up behind (both designs)."""

import math
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, QPointF, QRectF, Qt, QTimerEvent
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from tests.test_widget_benchmark import fill_field
from tinypedal.api_control import api
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.template.setting_widget import WIDGET_DEFAULT
from tinypedal.widget._modern import create_widget, modern_module

OWN_DESIGNS = ("chat", "elevation", "flag", "race_notifications", "rpm_led", "spotter", "steering_meter")
FIELD_ATTRIBUTES = {
    minfo.vehicles: (
        "dataSet", "dataSetVersion", "totalVehicles", "playerIndex", "leaderIndex", "nearestLine", "nearestTraffic",
        "nearestYellowAhead", "nearestYellowBehind", "nearestBlueClass",
    ),
    minfo.relative: ("standings", "drawOrder"),
    minfo.mapping: ("elevations", "sectors", "lastModified"),
    minfo.fuel: ("amountCurrent", "estimatedLaps"),
    minfo.energy: ("available", "amountCurrent", "estimatedLaps"),
}


@pytest.fixture
def widgets(ui_env, bundled_fonts, monkeypatch):
    """Build widgets by name (modern design unless modern=False), field of 20 cars, deleted after test"""
    for owner, names in FIELD_ATTRIBUTES.items():
        for name in names:  # restored after test
            monkeypatch.setattr(owner, name, getattr(owner, name))
    fill_field(20)
    cfg.overlay["fixed_position"] = True
    created = []

    def make(name: str, modern: bool = True, theme: str = "Modern Dark", **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = theme if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def reader(monkeypatch, group: str, name: str, value):
    """Neutral API reader returns value (or calls it)"""
    func = value if callable(value) else (lambda *args, **kwargs: value)
    monkeypatch.setattr(getattr(api.read, group), name, func)


def render(widget) -> QImage:
    """Widget painted on transparent image"""
    pixmap = QPixmap(widget.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
    return pixmap.toImage()


def update(widget, frames: int = 1) -> QImage:
    image = QImage()
    for _ in range(frames):
        widget.timerEvent(QTimerEvent(0))
        image = render(widget)
    return image


def visible_pixels(image: QImage) -> int:
    return sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
               if image.pixelColor(x, y).alpha() > 0)


def has_color(image: QImage, color: QColor, tolerance: int = 40) -> bool:
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            pixel = image.pixelColor(x, y)
            if (pixel.alpha() > 200 and abs(pixel.red() - color.red()) < tolerance
                    and abs(pixel.green() - color.green()) < tolerance and abs(pixel.blue() - color.blue()) < tolerance):
                return True
    return False


def place_cars(positions):
    """Relative positions of other cars (meters, -x left, -y ahead), rest far away"""
    cars = [car for car in minfo.vehicles.dataSet[:minfo.vehicles.totalVehicles] if not car.isPlayer]
    for car in cars:
        car.relativeRotatedPositionX = car.relativeRotatedPositionY = 300.0
        car.inPit = 0
    for car, (pos_x, pos_y) in zip(cars, positions):
        car.relativeRotatedPositionX, car.relativeRotatedPositionY = pos_x, pos_y
    minfo.vehicles.dataSetVersion += 1


# --- Every overlay has a modern design
def test_every_overlay_has_modern_design():
    from tinypedal.template.widget.modern import MODERN_DESIGNS

    builtin = {name for name in WIDGET_DEFAULT if not name.startswith("plugin_")}
    assert builtin <= MODERN_DESIGNS


@pytest.mark.parametrize("name", OWN_DESIGNS)
def test_own_design_reads_existing_options(name):
    from tinypedal.widget._modern.base import ModernOverlay

    realtime = modern_module(name).Realtime
    assert issubclass(realtime, ModernOverlay)
    assert not [key for key in realtime.options if key not in WIDGET_DEFAULT[name]]
    assert not [key for key in realtime.options if "color" in key and not key.startswith("show_")]


@pytest.mark.parametrize("name", OWN_DESIGNS)
@pytest.mark.parametrize("theme", ["Modern Dark", "Modern Light"])
def test_renders_in_both_themes(widgets, name, theme):
    cfg.overlay["fixed_position"] = False  # overlays drawn only with data are previewed
    widget = widgets(name, theme=theme)
    update(widget, 3)
    assert widget.width() > 10 and widget.height() > 10
    cfg.overlay["fixed_position"] = True


@pytest.mark.parametrize("name", ["chat", "flag", "race_notifications", "spotter"])
def test_overlays_page_picture_before_update(widgets, name):
    """Overlays drawn only with live data show a sample before first update (picture of Overlays page)"""
    widget = widgets(name)
    assert visible_pixels(render(widget)) > 0
    if name == "flag":
        assert len(widget.samples) == len(widget.keys) == 12


# --- Steering meter
def test_steering_meter_bar_side_and_angle(widgets, monkeypatch):
    reader(monkeypatch, "inputs", "steering_range_physical", 540.0)
    reader(monkeypatch, "inputs", "steering_raw", -0.5)
    widget = widgets("steering_meter", manual_steering_range=0)
    image = update(widget)
    assert widget.state == (-0.5, "135°")
    assert widget.mark_gap > 0  # scale marks every 90 degrees
    track = widget.track
    left_quarter = image.pixelColor(round(track.left() + track.width() * 0.3), round(track.center().y()))
    right_quarter = image.pixelColor(round(track.left() + track.width() * 0.7), round(track.center().y()))
    assert left_quarter.blue() > right_quarter.blue()  # accent bar on left half
    reader(monkeypatch, "inputs", "steering_raw", 3.0)  # out of range: clamped
    update(widget)
    assert widget.state == (1.0, "270°")
    hidden = widgets("steering_meter", show_steering_angle=False, show_scale_mark=False)
    update(hidden)
    assert hidden.state[1] == "" and hidden.mark_gap == 0


# --- RPM LED
def test_rpm_led_zone_tints(widgets, monkeypatch):
    reader(monkeypatch, "engine", "rpm_max", 8000.0)
    reader(monkeypatch, "engine", "rpm", 0.0)
    widget = widgets("rpm_led", number_of_led=10)
    update(widget)
    from tinypedal.widget._modern.rpm_led import LOW, REDLINE, SAFE

    assert widget.zones[0] == LOW and widget.zones[-1] == REDLINE and SAFE in widget.zones
    assert all(state == 0 for state in widget.state)  # nothing lit at idle


# --- Race notifications
def test_race_notifications_icons_and_time_left(widgets):
    from tinypedal.widget._modern.race_notifications import ICONS, TIME_STEPS
    from tinypedal.widget.race_notifications import GAIN, TITLES, Message

    assert set(TITLES) <= set(ICONS)
    widget = widgets("race_notifications", display_duration=4)
    clock = {"now": 10.0}
    widget.clock = lambda: clock["now"]
    widget.events.poll = lambda now: []
    widget.add_messages([Message("Position", "P3 +1", GAIN)], 10.0)
    clock["now"] = 11.0
    image = update(widget)
    key, _title, detail, kind, _step, left = widget.state[0]
    assert (key, detail, kind) == ("Position", "P3 +1", GAIN)
    assert left == round(0.75 * TIME_STEPS) / TIME_STEPS
    assert has_color(image, widget.theme.positive)


# --- Flag
def test_flag_chips_only_while_active(widgets, monkeypatch):
    minfo.fuel.amountCurrent = 50.0
    minfo.fuel.estimatedLaps = 15.0
    minfo.energy.available = False
    widget = widgets("flag")
    update(widget)
    assert widget.state == ()
    assert visible_pixels(render(widget)) == 0
    reader(monkeypatch, "switch", "speed_limiter", True)
    reader(monkeypatch, "vehicle", "speed", 22.2)  # 80 km/h
    reader(monkeypatch, "session", "sector_yellow_flags", (True, False, True))
    reader(monkeypatch, "session", "yellow_flag_state", 4)
    reader(monkeypatch, "vehicle", "repair_time", 31.6)
    image = update(widget)
    chips = {chip.caption: chip for chip in widget.state}
    assert chips["Limiter"].value == "79.92" and chips["Limiter"].color == "negative"
    assert chips["Sector yellow"].value == "S1 S3"
    assert chips["FCY"].value == "Pits open" and chips["Repairs"].value == "32s"
    order = [chip.caption for chip in widget.state]
    assert order.index("Limiter") < order.index("Repairs") < order.index("Sector yellow") < order.index("FCY")
    assert has_color(image, widget.theme.negative)
    reader(monkeypatch, "session", "yellow_flag_state", 7)
    update(widget)
    assert widget.state[-1].value == "Red flag" and widget.state[-1].color == "negative"


def test_flag_yellow_blue_low_fuel_and_custom_text(widgets, monkeypatch):
    reader(monkeypatch, "session", "yellow_flag", True)
    reader(monkeypatch, "session", "blue_flag", True)
    reader(monkeypatch, "session", "in_race", True)
    minfo.vehicles.nearestYellowAhead = 250.0
    minfo.vehicles.nearestBlueClass = ""
    minfo.fuel.amountCurrent = 3.5
    minfo.fuel.estimatedLaps = 1.2
    minfo.energy.available = False
    widget = widgets("flag", yellow_flag_text="YEL", layout=1)
    update(widget)
    chips = {chip.caption: chip for chip in widget.state}
    assert chips["YEL"].value == "+250m"  # custom text replaces design caption
    assert chips["Blue flag"].value.endswith("s")
    assert chips["Low fuel"].value == "3.50L"
    assert widget.width() > widget.height()  # horizontal layout


def test_flag_display_order(widgets, monkeypatch):
    reader(monkeypatch, "switch", "speed_limiter", True)
    reader(monkeypatch, "vehicle", "repair_time", 10.0)
    widget = widgets("flag", display_order_scheduled_repairs=0)
    update(widget)
    assert widget.state[0].caption == "Repairs"


# --- Chat
def test_chat_wrap_senders_and_new_messages(widgets, monkeypatch):
    from time import time

    from tinypedal.widget._modern.chat import split_sender

    assert split_sender("Race Control: track clear") == ("Race Control", "track clear")
    assert split_sender("no sender here") == ("", "no sender here")
    now = time()
    messages = (
        (now - 20.0, "A. Driver: " + "long message " * 12),
        (now - 1.0, "B. Driver: hi"),
    )
    reader(monkeypatch, "session", "chat_messages", messages)
    widget = widgets("chat", number_of_lines=6, line_width=30, maximum_display_duration=30, new_message_duration=5)
    image = update(widget)
    lines = widget.state
    assert lines[-1].name == "B. Driver" and lines[-1].text == "hi" and lines[-1].new
    first = [line for line in lines if line.name == "A. Driver"]
    assert len(lines) == 6 or first  # oldest lines dropped first
    assert not any(line.new for line in lines[:-1])
    for line in lines:
        width = widget.advance("value", line.text)
        assert width <= widget.text_w + 0.5
    assert lines[0].name == "" or lines[0].first  # continuation lines have no sender
    assert has_color(image, widget.theme.accent)  # new message edge
    # Fading at end of display duration
    old = ((now - 29.5, "C: bye"),)
    reader(monkeypatch, "session", "chat_messages", old)
    update(widget)
    assert widget.state[0].step < 8


def test_chat_hidden_without_message(widgets, monkeypatch):
    reader(monkeypatch, "session", "chat_messages", ())
    widget = widgets("chat")
    image = update(widget)
    assert widget.state == () and visible_pixels(image) == 0


# --- Elevation
def test_elevation_profile_and_position(widgets, monkeypatch):
    points = [(distance, 10.0 + 5.0 * math.sin(distance / 300.0)) for distance in range(0, 4000, 20)]
    minfo.mapping.elevations = tuple(points)
    minfo.mapping.sectors = (60, 130)
    minfo.mapping.lastModified = 123.0
    reader(monkeypatch, "lap", "progress", 0.5)
    reader(monkeypatch, "vehicle", "position_vertical", 12.34)
    widget = widgets("elevation")
    image = update(widget)
    assert not widget.line.isEmpty() and len(widget.sector_xs) == 2
    x, reading = widget.state
    assert x == pytest.approx(widget.chart.left() + widget.chart.width() * 0.5, abs=0.1)
    assert reading == "12.3m"
    y = widget.profile_y(x)
    assert widget.chart.top() <= y <= widget.chart.bottom()
    assert has_color(image, widget.theme.accent)
    assert widget.scale_text.startswith("1:")


def test_elevation_without_map(widgets, monkeypatch):
    minfo.mapping.elevations = None
    minfo.mapping.lastModified = -5.0
    widget = widgets("elevation", show_elevation_reading=False, show_elevation_scale=False)
    update(widget)
    assert widget.line.isEmpty() and widget.profile_y(10.0) is None
    assert widget.header.height() == 0


# --- Spotter: clear signal & cars coming up behind
def test_side_closeness_and_approach():
    from tinypedal.widget.spotter import side_approach, side_overlap

    left, right = side_overlap([(-4.0, 0.0), (2.0, 0.0)], 4.6, 5.0, 2.6)
    assert not left.critical and 0 < left.closeness < 1
    assert right.critical and right.closeness == 1.0
    left, right = side_approach([(-2.5, 9.6), (2.5, 4.7), (0.3, 6.0), (2.5, 30.0), (math.nan, 5.0)], 4.6, 5.0, 10.0, 1.1)
    assert left == 0.5  # 5 m behind player rear, of 10
    assert right == 1.0  # about to overlap
    assert side_approach([(-2.5, 6.0)], 4.6, 5.0, 0.0) == (0.0, 0.0)  # disabled


@pytest.mark.parametrize("modern", [True, False])
def test_spotter_clear_signal(widgets, modern):
    from tinypedal.widget.spotter import CLEAR_STEPS

    widget = widgets("spotter", modern, clear_signal_duration=1.0)
    clock = {"now": 100.0}
    widget.clock = lambda: clock["now"]
    place_cars([(-2.0, 0.5)])
    update(widget)
    assert widget.state.left.lit and widget.state.clear == (0, 0)
    place_cars([])
    clock["now"] = 100.5
    widget.timerEvent(QTimerEvent(0))
    assert widget.state.clear[0] == CLEAR_STEPS and not widget.state.left.lit
    clock["now"] = 101.0
    image = update(widget)
    assert 0 < widget.state.clear[0] < CLEAR_STEPS and widget.state.shown
    assert visible_pixels(image) > 0
    clock["now"] = 101.6
    widget.timerEvent(QTimerEvent(0))
    assert widget.state.clear == (0, 0) and not widget.state.shown


@pytest.mark.parametrize("modern", [True, False])
def test_spotter_approaching_car(widgets, modern):
    widget = widgets("spotter", modern, approaching_distance=10.0, horizontal_gap=100, bar_height=200)
    place_cars([(2.4, 9.6)])
    image = update(widget)
    assert widget.state.approach == (0.0, 0.5) and not widget.state.right.lit
    right_bar = widget.width() - 4
    assert image.pixelColor(right_bar, widget.height() - 3).alpha() > 0  # bottom of right bar lit
    assert image.pixelColor(right_bar, 3).alpha() == 0
    off = widgets("spotter", modern, show_approaching_cars=False, show_clear_signal=False)
    update(off)
    assert off.state.approach == (0.0, 0.0)


def test_spotter_closeness_color(widgets):
    widget = widgets("spotter", horizontal_gap=60, bar_height=100)
    place_cars([(-2.0, 0.0)])
    image = update(widget)
    assert widget.state.left.critical
    assert has_color(image, widget.theme.negative)


# --- Black box
def test_black_box_modern_design(widgets):
    from tinypedal.widget._modern.base import design_font_family
    from tinypedal.widget._modern.black_box import COLOR_TOKENS
    from tinypedal.widget._modern.restyle import token_color

    widget = widgets("black_box", enable_auto_resize=False)
    assert type(widget).__module__ == "tinypedal.widget._modern.black_box"
    style = cfg.user.config["overlay_style"]
    assert widget.wcfg["font_name"] == design_font_family(style)
    default = cfg.default.setting["black_box"]
    for key in ("throttle_color", "rpm_led_low_color", "damage_panel_impact_cone_color"):
        assert widget.wcfg[key] == token_color(widget.theme, COLOR_TOKENS[key], default[key])
    assert QColor(widget.wcfg["damage_panel_impact_cone_color"]).alpha() == QColor(default["damage_panel_impact_cone_color"]).alpha()
    assert widget.font_label.capitalization().name == "AllUppercase"
    update(widget, 2)
    image = widget.grab().toImage()
    assert not image.isNull() and widget.width() > 50


def test_black_box_user_color_kept_and_classic_layout(widgets):
    widget = widgets("black_box", enable_auto_resize=False, throttle_color="#123456")
    assert widget.wcfg["throttle_color"] == "#123456"
    classic = widgets("black_box", enable_classic_layout=True, throttle_color="#2FC46A")
    assert type(classic).__module__ == "tinypedal.widget.black_box"
    legacy = widgets("black_box", modern=False, enable_classic_layout=False)
    assert type(legacy).__module__ == "tinypedal.widget.black_box"


def test_black_box_leds_lit_and_zones(widgets):
    widget = widgets("black_box", enable_auto_resize=False, show_rpm_leds=True)
    widget.rpm_max = 8000.0
    widget.rpm = 6500.0
    pixmap = QPixmap(widget.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    widget.draw_leds(painter, QRectF(QPointF(4, 4), widget.rect_leds.size()))
    painter.end()
    image = pixmap.toImage()
    assert has_color(image, QColor(widget.wcfg["rpm_led_low_color"]))
