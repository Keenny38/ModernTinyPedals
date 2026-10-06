"""Modern design of graphic overlays: friction circle, heading, instrument, navigation, radar, steering
wheel, track map, track notes, trailing & weather forecast. Data read like classic widgets (shared
mixins), drawn as shapes in theme colors; options shown are the ones the design reads."""

import math
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, QTimerEvent
from PySide6.QtGui import QColor, QImage

from tests.test_widget_benchmark import fill_field
from tinypedal.api_control import api
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.template.setting_widget import WIDGET_DEFAULT
from tinypedal.widget._modern import create_widget, modern_module
from tinypedal.widget._modern.base import DASH

GRAPHIC_WIDGETS = (
    "friction_circle", "heading", "instrument", "navigation", "radar", "steering_wheel", "track_map", "track_notes",
    "trailing", "weather_forecast",
)
FIELD_ATTRIBUTES = {
    minfo.vehicles: (
        "dataSet", "dataSetVersion", "totalVehicles", "playerIndex", "leaderIndex", "nearestLine", "nearestTraffic",
    ),
    minfo.relative: ("standings", "drawOrder"),
}


@pytest.fixture
def widgets(ui_env, bundled_fonts, monkeypatch):
    """Build widgets by name (modern design unless modern=False), field of 20 cars, deleted after test"""
    for owner, names in FIELD_ATTRIBUTES.items():
        for name in names:  # restored after test
            monkeypatch.setattr(owner, name, getattr(owner, name))
    fill_field(20)
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
    """Widget painted on transparent image (grab() fills window background)"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QWidget

    pixmap = QPixmap(widget.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
    return pixmap.toImage()


def update(widget, frames: int = 1) -> QImage:
    """Update & paint widget, last frame image"""
    image = QImage()
    for frame in range(frames):
        minfo.vehicles.dataSetVersion = frame + 1
        widget.timerEvent(QTimerEvent(0))
        image = render(widget)
    return image


def visible_pixels(image: QImage) -> int:
    """Pixels drawn (sampled), alpha kept (QColor(image.pixel()) drops it)"""
    return sum(1 for y in range(0, image.height(), 3) for x in range(0, image.width(), 3)
               if image.pixelColor(x, y).alpha() > 0)


def has_color(image: QImage, color: QColor, tolerance: int = 40) -> bool:
    """Some pixel close to color"""
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            pixel = image.pixelColor(x, y)
            if (pixel.alpha() > 200 and abs(pixel.red() - color.red()) < tolerance
                    and abs(pixel.green() - color.green()) < tolerance and abs(pixel.blue() - color.blue()) < tolerance):
                return True
    return False


# --- Every graphic overlay has its own design now (no classic drawing restyle)
@pytest.mark.parametrize("name", GRAPHIC_WIDGETS)
def test_own_design_reads_existing_options(name):
    from tinypedal.widget._modern.base import ModernOverlay

    realtime = modern_module(name).Realtime
    assert issubclass(realtime, ModernOverlay)
    assert realtime.options
    assert not [key for key in realtime.options if key not in WIDGET_DEFAULT[name]]
    assert not [key for key in realtime.options if "color" in key and not key.startswith("show_")]


@pytest.mark.parametrize("name", GRAPHIC_WIDGETS)
@pytest.mark.parametrize("theme", ["Modern Dark", "Modern Light"])
def test_renders_in_both_themes(widgets, name, theme):
    widget = widgets(name, theme=theme, **({"enable_auto_hide": False} if name == "radar" else {}))
    assert widget.theme.surface.lightness() > 128 if theme == "Modern Light" else widget.theme.surface.lightness() < 128
    update(widget, 3)
    assert widget.width() > 10 and widget.height() > 10


# --- Friction circle
def test_friction_circle_trace_and_readings(widgets, monkeypatch):
    widget = widgets("friction_circle", trace_maximum_samples=20)
    for index in range(30):
        monkeypatch.setattr(minfo.force, "lgtGForceRaw", math.sin(index / 3))
        monkeypatch.setattr(minfo.force, "latGForceRaw", -1.5 * math.cos(index / 3))
        update(widget)
    assert len(widget.trace) == 20  # oldest samples dropped
    lat, lgt = widget.state[3]
    assert lat.text == f"{abs(round(-1.5 * math.cos(29 / 3), 3)):.2f}"
    assert lgt.sub.endswith(f"{abs(minfo.force.maxLgtGForce):.2f}")
    assert (widget.trace[-1].x() > widget.center.x()) == (minfo.force.latGForceRaw > 0)
    widget.post_update()
    assert not widget.trace


def test_friction_circle_inverted_and_extreme_values(widgets, monkeypatch):
    monkeypatch.setattr(minfo.force, "lgtGForceRaw", 1.0)
    monkeypatch.setattr(minfo.force, "latGForceRaw", 0.5)
    normal = widgets("friction_circle")
    update(normal)
    widget = widgets("friction_circle", show_inverted_orientation=True)
    update(widget)
    assert widget.trace[-1].y() - widget.center.y() == pytest.approx(normal.center.y() - normal.trace[-1].y())
    assert widget.trace[-1].x() - widget.center.x() == pytest.approx(normal.center.x() - normal.trace[-1].x())
    monkeypatch.setattr(minfo.force, "lgtGForceRaw", float("inf"))
    monkeypatch.setattr(minfo.force, "latGForceRaw", float("nan"))
    update(widget)
    plot = widget.plot
    assert plot.top() - plot.height() <= widget.trace[-1].y() <= plot.bottom() + plot.height()


# --- Heading
def test_heading_readings_and_lines(widgets, monkeypatch):
    widget = widgets("heading", show_slip_angle_reading=True, decimal_places=1)
    assert [chip[0] for chip in widget.chips] == ["yaw", "slip"]
    reader(monkeypatch, "vehicle", "speed", 30.0)
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", 0.5)
    monkeypatch.setattr(minfo.wheels, "averageFrontSlipAngle", -3.25)
    positions = iter(((0.0, 0.0), (10.0, 1.0), (20.0, 2.5)))
    current = {"pos": (0.0, 0.0)}

    def step():
        current["pos"] = next(positions)
    reader(monkeypatch, "vehicle", "position_longitudinal", lambda: current["pos"][0])
    reader(monkeypatch, "vehicle", "position_lateral", lambda: current["pos"][1])
    for _ in range(3):
        step()
        update(widget)
    heading, _, yaw, slip = widget.state
    assert heading == pytest.approx(math.degrees(0.5) + 180, abs=0.1)
    assert slip == -3.2 or slip == -3.3
    assert widget.angle_text(slip).startswith("3.") and widget.angle_text(slip).endswith("°")
    assert -180 <= yaw <= 180
    for _, _, box, _, _ in widget.chips:
        assert widget.rect().contains(box.toRect())


def test_heading_labels_translated():
    from tinypedal.i18n.fr_overlay import OVERLAY_LABELS

    assert OVERLAY_LABELS["Yaw"] == "Lacet" and "Front slip" in OVERLAY_LABELS


# --- Instrument
def test_instrument_lights(widgets, monkeypatch):
    theme_widget = widgets("instrument", layout=0)
    assert theme_widget.height() > theme_widget.width()  # column
    widget = widgets("instrument", layout=1, display_order_wheel_slip=0)
    assert widget.keys[0] == "wheel_slip" and widget.width() > widget.height()
    theme = widget.theme
    reader(monkeypatch, "switch", "headlights", 1)
    reader(monkeypatch, "switch", "ignition_starter", 1)
    reader(monkeypatch, "engine", "rpm", 0.0)  # stalled
    reader(monkeypatch, "switch", "auto_clutch", 1)
    reader(monkeypatch, "inputs", "clutch", 0.5)
    reader(monkeypatch, "inputs", "brake_raw", 1.0)
    reader(monkeypatch, "inputs", "throttle_raw", 0.0)
    monkeypatch.setattr(minfo.wheels, "slipRatio", [-0.5, 0.0, 0.0, 0.0])
    image = update(widget)
    lights = dict(zip(widget.keys, widget.state))
    assert lights["headlights"].lit and lights["headlights"].fill is None
    assert lights["ignition"].fill == theme.warning
    assert lights["clutch"].lit and lights["clutch"].fill == theme.accent
    assert lights["wheel_lock"].fill == theme.negative
    assert lights["wheel_slip"].fill is None and not lights["wheel_slip"].lit
    assert has_color(image, theme.negative) and has_color(image, theme.accent)
    reader(monkeypatch, "engine", "rpm", 3000.0)
    update(widget)
    assert dict(zip(widget.keys, widget.state))["ignition"].fill is None  # running


# --- Navigation & track map: recorded oval map
@pytest.fixture
def oval(monkeypatch):
    """Recorded oval map, cars spread on it"""
    nodes = 200
    coords = tuple((600 * math.cos(i / nodes * math.tau), 350 * math.sin(i / nodes * math.tau)) for i in range(nodes))
    mapping = minfo.mapping
    for name, value in (
        ("coordinates", coords), ("elevations", tuple((i / nodes * 4000.0, 0.0) for i in range(nodes))),
        ("sectors", (66, 133)), ("lastModified", 2.0), ("pitEntryPosition", 3800.0), ("pitExitPosition", 200.0),
    ):
        monkeypatch.setattr(mapping, name, value)
    monkeypatch.setattr(minfo.delta, "deltaBestData", tuple((i / 100 * 4000.0, i / 100 * 90.0) for i in range(101)))
    monkeypatch.setattr(minfo.delta, "lapTimePace", 91.0)
    for index, data in enumerate(minfo.vehicles.dataSet):
        data.worldPositionX, data.worldPositionY = coords[index * 9 % nodes]
        data.relativeRotatedPositionX, data.relativeRotatedPositionY = (index - 10) * 3.0, (index - 10) * 8.0
        data.relativeStraightDistance = abs(index - 10) * 8.0
        data.isLapped = (index % 3) - 1
    return coords


def test_navigation_view(widgets, oval, monkeypatch):
    reader(monkeypatch, "vehicle", "position_longitudinal", 600.0)
    reader(monkeypatch, "vehicle", "position_lateral", 0.0)
    widget = widgets("navigation")
    image = update(widget, 2)
    assert widget.map_path is not None and widget.sector_path is not None
    assert visible_pixels(image) > 500
    assert has_color(image, widget.theme.accent)  # player
    assert image.pixelColor(2, 2).alpha() == 0  # round view
    widget = widgets("navigation", show_circle_vehicle_shape=True, show_vehicle_class_standings=True,
                     show_fade_out=False)
    assert visible_pixels(update(widget, 2)) > 500


def test_track_map_cars_safety_car_and_predictions(widgets, oval, monkeypatch):
    widget = widgets("track_map", enable_multi_class_styling=False, show_safety_car=True,
                     show_pitout_prediction=True, show_pitstop_duration=True)
    reader(monkeypatch, "lap", "safety_car_active", True)
    reader(monkeypatch, "lap", "safety_car_distance", 1000.0)
    player = minfo.vehicles.dataSet[minfo.vehicles.playerIndex]
    player.inPit = 1
    player.pitTimer.elapsed = 12.0
    image = update(widget, 2)
    assert widget.map_scaled and widget.circular_map
    assert widget.safetycar_position(widget.map_scaled) is not None
    assert list(widget.pitout_predictions(widget.map_scaled, player))
    theme = widget.theme
    assert has_color(image, theme.caution)  # safety car
    assert has_color(image, theme.accent)  # player
    assert has_color(image, theme.negative)  # prediction ring


def test_track_map_class_colors_and_circle_map(widgets, oval, monkeypatch):
    widget = widgets("track_map", enable_multi_class_styling=True, show_custom_player_color_in_multi_class=True)
    update(widget)
    cars = minfo.vehicles.dataSet
    opponent = next(car for car in cars if not car.isPlayer and not car.inPit and not car.isYellow)
    assert widget.car_color(cars[minfo.vehicles.playerIndex]) == widget.theme.accent
    assert widget.car_color(opponent) not in (widget.theme.accent, widget.theme.text)
    monkeypatch.setattr(minfo.mapping, "coordinates", None)
    circle = widgets("track_map", show_vehicle_class_standings=True)
    assert visible_pixels(update(circle)) > 100
    assert circle.map_scaled is None


# --- Radar
def test_radar_auto_hide_and_overlap(widgets, oval, monkeypatch):
    widget = widgets("radar", enable_auto_hide=True, enable_radar_fade=False)
    monkeypatch.setattr(minfo.vehicles, "nearestLine", 999.0)  # nobody near
    reader(monkeypatch, "timing", "elapsed", 100.0)
    update(widget)
    reader(monkeypatch, "timing", "elapsed", 110.0)
    image = update(widget)
    assert not widget.show_radar and visible_pixels(image) == 0
    widget = widgets("radar", enable_auto_hide=False, show_overlap_indicator=True)
    cars = minfo.vehicles.dataSet
    for car in cars:
        car.relativeRotatedPositionX, car.relativeRotatedPositionY = 100.0, 100.0  # out of range
    alongside = next(car for car in cars if not car.isPlayer)
    alongside.relativeRotatedPositionX, alongside.relativeRotatedPositionY = 2.4, 0.5  # right side, close
    image = update(widget)
    assert widget.show_radar and visible_pixels(image) > 500
    assert has_color(image, widget.theme.negative, 60)  # critical glow
    assert image.pixelColor(1, 1).alpha() == 0  # edge faded out


def test_radar_fade_with_distance(widgets, monkeypatch):
    widget = widgets("radar", enable_auto_hide=True, enable_radar_fade=True)
    monkeypatch.setattr(minfo.vehicles, "nearestLine", widget.radar_radius * 0.95)
    widget.always_show = False
    assert 0 <= widget.radar_alpha() < 1
    monkeypatch.setattr(minfo.vehicles, "nearestLine", 0.0)
    assert widget.radar_alpha() == 1


# --- Steering wheel
def test_steering_wheel_rotation_arc_and_reading(widgets, monkeypatch):
    reader(monkeypatch, "inputs", "steering_raw", 0.25)
    reader(monkeypatch, "vehicle", "speed", 30.0)
    widget = widgets("steering_wheel", manual_steering_range=540, show_steering_angle=True,
                     show_rotation_line_while_stationary_only=True)
    update(widget)
    assert widget.state == (67.5, False)  # moving: no rotation arc
    reader(monkeypatch, "vehicle", "speed", 0.0)
    image = update(widget)
    assert widget.state == (67.5, True)
    assert has_color(image, widget.theme.accent)
    assert widget.image is None  # no custom image set


def test_steering_wheel_custom_image(widgets, tmp_path):
    from PySide6.QtGui import QPixmap

    path = tmp_path / "wheel.png"
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#FF00FF"))
    pixmap.save(str(path))
    widget = widgets("steering_wheel", show_custom_steering_wheel=True, custom_steering_wheel_image_file=str(path))
    assert widget.image is not None
    assert has_color(update(widget), QColor("#FF00FF"))
    missing = widgets("steering_wheel", show_custom_steering_wheel=True,
                      custom_steering_wheel_image_file=str(tmp_path / "missing.png"))
    assert missing.image is None  # drawn wheel


# --- Track notes
def test_track_notes_comments_lines_and_auto_hide(widgets, monkeypatch):
    reader(monkeypatch, "vehicle", "in_pits", False)
    note = {"track note": "Turn 1", "comment": "Brake at 100\\nThird gear", "distance": 120.5}
    monkeypatch.setattr(minfo.tracknotes.out, "currentNote", note)
    monkeypatch.setattr(minfo.tracknotes.out, "nextNote", {"distance": 480.0})
    monkeypatch.setattr(minfo.tracknotes.out, "currentIndex", 1)
    widget = widgets("track_notes", show_comments=True, show_debugging=True, track_notes_uppercase=True,
                     maximum_display_duration=-1)
    height = widget.height()
    update(widget)
    texts = dict(zip(widget.keys, widget.state))
    assert texts["track_notes"] == ("TURN 1",)
    assert texts["comments"] == ("Brake at 100", "Third gear")
    assert texts["debugging"] == ("120.50m » 480.00m",)
    assert widget.height() > height  # second comment line
    monkeypatch.setattr(minfo.tracknotes.out, "currentNote", {})
    hidden = widgets("track_notes", enable_auto_hide_if_not_available=True)
    image = update(hidden)
    assert hidden.notes_hidden and visible_pixels(image) == 0


# --- Trailing
def test_trailing_samples_and_pause(widgets, monkeypatch):
    clock = {"time": 0.0}
    reader(monkeypatch, "timing", "elapsed", lambda: clock["time"])
    reader(monkeypatch, "inputs", "throttle", 0.75)
    reader(monkeypatch, "inputs", "brake", 0.0)
    widget = widgets("trailing", show_wheel_lock=True, show_tc_activation=True, maximum_paused_frames=0)
    throttle = next(plot for plot in widget.plots if plot.name == "throttle")
    lock = next(plot for plot in widget.plots if plot.name == "wheel_lock")
    for _ in range(5):
        clock["time"] += 0.02
        update(widget)
    assert list(throttle.samples)[:5] == [0.75] * 5
    assert all(value < 0 for value in lock.samples)  # not locking: no dot
    count = len(throttle.samples)
    update(widget)  # time unchanged: one paused frame allowed
    update(widget)
    assert len(throttle.samples) <= count + 1
    assert widget.plots[-1].name == "abs_activation" or widget.plots[-1].name == "tc_activation"  # order 1 on top
    image = widget.grab().toImage()
    assert has_color(image, widget.theme.positive)


# --- Weather forecast
def test_weather_forecast_columns(widgets, monkeypatch):
    from tinypedal.process.weather import WeatherNode

    nodes = (WeatherNode(0.0, 1, 20.0, 0.0), WeatherNode(0.2, 6, 18.0, 0.4), WeatherNode(0.5, 10, 16.0, 0.9))
    reader(monkeypatch, "session", "weather_forecast", nodes)
    reader(monkeypatch, "session", "finish_type", 0)
    reader(monkeypatch, "session", "end", 3600.0)
    reader(monkeypatch, "session", "elapsed", 0.0)
    reader(monkeypatch, "session", "cloud_coverage", 2)
    reader(monkeypatch, "session", "ambient_temperature", 22.0)
    reader(monkeypatch, "session", "raininess", 0.1)
    widget = widgets("weather_forecast", number_of_forecasts=4, show_unavailable_data=False,
                     show_rain_chance_reading=True)
    width = widget.width()
    update(widget)
    assert [slot.sky for slot in widget.state] == [2, 6, 10]  # unavailable forecasts hidden
    assert widget.width() < width
    assert widget.state[1].time == "12m" and widget.state[2].rain_text == "90%"
    shown = widgets("weather_forecast", number_of_forecasts=4, show_unavailable_data=True, layout=1)
    update(shown)
    assert len(shown.state) == 5 and shown.state[-1].temperature == DASH
    assert shown.tile_left(0) > shown.tile_left(1)  # now on right


def test_weather_icons_for_every_sky(widgets):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter, QPixmap

    from tinypedal.widget._modern.theme import build_theme
    from tinypedal.widget._modern.weather_forecast import weather_icon

    for theme_name in ("Modern Dark", "Modern Light"):
        theme = build_theme({"overlay_theme": theme_name})
        for sky in range(11):
            pixmap = QPixmap(40, 40)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            weather_icon(painter, QRectF(4, 4, 32, 32), sky, theme, 2.0)
            painter.end()
            assert visible_pixels(pixmap.toImage()) > 10, sky


# --- Classic widgets keep their drawing, read data through the same mixins
@pytest.mark.parametrize("name", GRAPHIC_WIDGETS)
def test_classic_layout_kept(widgets, name):
    from tinypedal.widget._modern.base import ModernOverlay

    widget = widgets(name, modern=False)
    assert not isinstance(widget, ModernOverlay)
    update(widget, 2)
    modern = widgets(name, enable_classic_layout=True)
    assert not isinstance(modern, ModernOverlay)
