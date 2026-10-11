"""Modern driver tables (standings, relative, rivals): only changed rows repainted, same pixels as a full repaint"""

from importlib import import_module

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from neopedal.widget._modern.table import Row

TABLES = ("standings", "relative", "rivals")


def full_image(widget) -> QImage:
    return widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)


def screen_matches_full(widget) -> bool:
    """Window as last painted on screen (backing store) same as a full repaint"""
    full = full_image(widget)
    screen = widget.backingStore().paintDevice().copy(0, 0, full.width(), full.height())
    return screen.convertToFormat(QImage.Format.Format_ARGB32) == full


def process_events():
    for _ in range(5):
        QApplication.processEvents()


def new_table(cfg, name: str, theme: str = "Modern Dark"):
    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = theme
    return create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)


def sample(widget):
    from neopedal.widget._modern.drivers import Context
    from neopedal.widget._modern.sample_field import sample_field

    field = sample_field()
    context = Context(in_race=True, player=field.vehicles[field.player_index], player_pit_request=False)
    return field, context


def changes(field):
    cars = field.vehicles
    player = cars[field.player_index]
    ahead = cars[player.classAheadIndex] if player.classAheadIndex >= 0 else cars[0]
    yield "lap time", lambda: setattr(ahead, "lastLapTime", ahead.lastLapTime + 0.5)
    yield "driver", lambda: setattr(cars[0], "driverName", "Z. Changed")
    yield "pit", lambda: setattr(ahead, "inPit", 1)
    yield "garage", lambda: setattr(cars[1], "inPit", 2)  # faded row
    yield "integrity", lambda: setattr(player, "vehicleIntegrity", 0.42)
    yield "brand", lambda: setattr(cars[2], "vehicleBrand", "Other")


@pytest.mark.parametrize("theme", ["Modern Dark", "Modern Light"])
@pytest.mark.parametrize("name", TABLES)
def test_changed_rows_match_full_repaint(ui_env, bundled_fonts, monkeypatch, name, theme):
    from neopedal.setting import cfg

    widget = new_table(cfg, name, theme)
    field, context = sample(widget)
    regions = []
    paint = widget.paint
    monkeypatch.setattr(widget, "paint", lambda painter: (regions.append(widget.paint_region), paint(painter)))
    try:
        widget.show_field(field, context)
        full_image(widget)  # shapes drawn from cache from second paint on: first paint not on screen
        widget.show()
        process_events()
        assert screen_matches_full(widget)
        partial = 0
        for change_name, change in changes(field):
            change()
            widget.show_field(field, context)
            full_image(widget)  # shapes of new size cached first, as for the full repaint compared with
            regions.clear()
            process_events()
            partial += bool(regions) and all(region is not None for region in regions)
            assert screen_matches_full(widget), f"{change_name}: partial repaint differs"
        assert partial >= 2
    finally:
        widget.hide()
        widget.deleteLater()


def test_only_changed_rows_invalidated(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg

    widget = new_table(cfg, "standings")
    field, context = sample(widget)
    widget.show_field(field, context)
    widget.grab()  # painted once: static layer made
    updates = []
    monkeypatch.setattr(widget, "update", lambda *args: updates.append(args))
    widget.show_field(field, context)
    assert not updates  # nothing changed
    rows = widget.row_slots(widget.state)
    car = field.vehicles[0]
    car.lastLapTime += 1.0
    widget.show_field(field, context)
    assert len(updates) == 1 and len(updates[0]) == 1  # one row
    rect = updates[0][0]
    assert sum(1 for top in rows if widget.row_update_rect(top) == rect) == 1
    assert rect.width() == widget.width() and rect.height() < widget.table.row_height + 4


def test_rows_skipped_outside_paint_region(ui_env, bundled_fonts, monkeypatch):
    from PySide6.QtGui import QRegion

    from neopedal.setting import cfg

    widget = new_table(cfg, "standings")
    field, context = sample(widget)
    widget.show_field(field, context)
    drawn = []
    original = widget.draw_row_background
    monkeypatch.setattr(widget, "draw_row_background",
                        lambda painter, rect, row, index: (drawn.append(index), original(painter, rect, row, index)))
    widget.grab()
    total = len(drawn)
    car_slots = [top for top, (row, _) in widget.row_slots(widget.state).items() if isinstance(row, Row)]
    assert total == len(car_slots)  # class headers have no row background
    drawn.clear()
    top = car_slots[0]
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    widget.render(image, sourceRegion=QRegion(widget.row_update_rect(top)))
    assert drawn[0] == 1 and len(drawn) <= 2  # first row (next one if a pixel of it reaches in)


def test_rows_with_logos_match_full_repaint(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.userfile.custom_image import LOGO_LOADER
    from tests.test_logo_loader import own_logo

    own_logo(cfg.path.brand_logo, "Ferrari", "#e02020")
    own_logo(cfg.path.brand_logo, "BMW", "#ffffff")
    cfg.user.setting["standings"]["column_brand_logo"] = True
    widget = new_table(cfg, "standings")
    field, context = sample(widget)
    for index, car in enumerate(field.vehicles):
        car.vehicleBrand = ("Ferrari", "BMW", "Unknown")[index % 3]

    def settle():
        for _ in range(3):  # logos read in background, then rows repainted
            assert LOGO_LOADER.wait()
            widget.show_field(field, context)
            full_image(widget)
            process_events()

    try:
        widget.show_field(field, context)
        widget.show()
        settle()
        assert screen_matches_full(widget)
        for brand in ("BMW", "Unknown", "Ferrari"):
            field.vehicles[3].vehicleBrand = brand
            field.vehicles[4].lastLapTime += 0.3
            settle()
            assert screen_matches_full(widget), brand
    finally:
        widget.hide()
        widget.deleteLater()


def random_change(field, rng):
    """One random change of a random car: times, gaps, name, pit, integrity, energy, brand"""
    car = rng.choice(field.vehicles)
    kind = rng.randrange(8)
    if kind == 0:
        car.lastLapTime += rng.choice((0.0004, 0.013, rng.uniform(-2, 2)))
    elif kind == 1:
        car.bestLapTime = rng.uniform(90, 120)
    elif kind == 2:
        car.gapBehindNext = car.gapBehindNextInClass = rng.uniform(0, 60)
        car.gapBehindLeader = car.gapBehindLeaderInClass = rng.uniform(0, 120)
    elif kind == 3:
        car.driverName = rng.choice(("A. Driver", "B. Longer Driver Name", "C. D"))
    elif kind == 4:
        car.inPit = rng.choice((0, 0, 1, 2))
    elif kind == 5:
        car.vehicleIntegrity = rng.choice((1.0, 0.82, 0.4))
    elif kind == 6:
        car.energyRemaining = rng.random()
    else:
        car.incidents = rng.randint(0, 12)


@pytest.mark.parametrize("name", TABLES)
def test_random_changes_match_full_repaint(ui_env, bundled_fonts, monkeypatch, name):
    """After any sequence of changes, the window as repainted row by row equals a full repaint"""
    import random

    from PySide6.QtCore import QEvent

    from neopedal.setting import cfg

    rng = random.Random(name)
    widget = new_table(cfg, name)
    field, context = sample(widget)
    try:
        widget.show_field(field, context)
        full_image(widget)
        widget.show()
        process_events()
        for step in range(30):
            for _ in range(rng.randint(1, 3)):
                random_change(field, rng)
            widget.show_field(field, context)
            full_image(widget)  # shapes of new size cached first, as for the full repaint compared with
            process_events()
            assert screen_matches_full(widget), f"step {step}: partial repaint differs"
    finally:
        widget.hide()
        widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("scale", ("1.25", "1.5", "2"))
def test_random_changes_at_screen_scale(scale):
    """Same at 125, 150 & 200 % screen scale (own process)"""
    from tests.test_black_box_regions import run_scaled

    run_scaled(f"{__file__}::test_random_changes_match_full_repaint", scale)
    run_scaled(f"{__file__}::test_changed_rows_match_full_repaint", scale)
