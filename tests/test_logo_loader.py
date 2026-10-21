"""Logos found & read on logo loader thread: overlays & home page never wait for files"""

import os
import threading
from importlib import import_module

import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from neopedal.userfile import custom_image
from neopedal.userfile.custom_image import LOGO_LOADER, LogoLoader


def own_logo(folder: str, name: str, color: str):
    image = QImage(120, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.fillRect(10, 10, 100, 40, QColor(color))
    painter.end()
    assert image.save(os.path.join(folder, f"{name}.png"))


def process_events():
    for _ in range(5):
        QApplication.processEvents()


# --- Loader
def test_loader_runs_job_once_then_gives_result():
    loader = LogoLoader()
    started = threading.Event()
    release = threading.Event()
    runs = []

    def job():
        runs.append(1)
        started.set()
        release.wait(5)
        return "logo"

    assert loader.result("key", job) == (False, None)
    assert started.wait(5)
    assert loader.result("key", job) == (False, None)  # running: not queued again
    release.set()
    assert loader.wait()
    assert loader.finished == 1
    assert loader.result("key", job) == (True, "logo")  # taken
    assert runs == [1]


def test_loader_survives_failing_job_and_ends_when_idle(monkeypatch):
    loader = LogoLoader()
    monkeypatch.setattr(loader, "IDLE_SECONDS", 0.05)

    def broken():
        raise OSError("unreadable")

    loader.result("bad", broken)
    assert loader.wait()
    assert loader.result("bad", broken) == (True, None)
    thread = loader._thread
    if thread is not None:
        thread.join(5)
    assert loader._thread is None  # worker ended without jobs
    loader.result("good", lambda: 3)  # started again
    assert loader.wait()
    assert loader.result("good", lambda: 3) == (True, 3)


def test_loader_drops_results_nobody_took(monkeypatch):
    loader = LogoLoader()
    monkeypatch.setattr(loader, "MAX_RESULTS", 3)
    for key in range(6):
        loader.result(key, lambda key=key: key)
    assert loader.wait()
    assert len(loader._results) == 3
    assert loader.result(5, lambda: None) == (True, 5)


# --- Modern tables: logo shown once ready, same picture as when read at once
def new_standings(cfg):
    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    cfg.user.setting["standings"]["column_brand_logo"] = True
    return create_widget(import_module("neopedal.widget.standings"), cfg, "standings")


def test_table_logo_read_at_once_off_screen(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg

    own_logo(cfg.path.brand_logo, "Ferrari", "#e02020")
    widget = new_standings(cfg)
    try:
        assert not widget.brand_logo("Ferrari", "", 30, 15).isNull()  # preview & test renders: no wait
    finally:
        widget.deleteLater()


def test_table_logo_loaded_in_background_on_screen(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.widget._modern.drivers import Context
    from neopedal.widget._modern.sample_field import sample_field

    own_logo(cfg.path.brand_logo, "Ferrari", "#e02020")
    field = sample_field()
    for car in field.vehicles:
        car.vehicleBrand = "Ferrari"
    context = Context(in_race=True, player=field.vehicles[field.player_index], player_pit_request=False)
    reference = new_standings(cfg)  # off screen: logos read at once
    reference.show_field(field, context)
    reference.grab()  # shapes drawn from cache from second paint on
    expected = reference.grab().toImage()
    reference.deleteLater()

    widget = new_standings(cfg)
    gui_thread = threading.get_ident()
    threads = []
    release = threading.Event()
    lookup = custom_image.brand_logo_file
    monkeypatch.setattr(custom_image, "brand_logo_file",
                        lambda *args: (threads.append(threading.get_ident()), release.wait(5), lookup(*args))[2])
    try:
        widget.show_field(field, context)
        widget.show()
        process_events()
        assert widget.brand_logo("Ferrari", field.vehicles[0].vehicleName, 30, 15).isNull()  # not ready yet
        release.set()
        assert LOGO_LOADER.wait()
        updates = []
        update = widget.update
        monkeypatch.setattr(widget, "update", lambda *args: (updates.append(args), update(*args)))
        widget.show_field(field, context)  # rows unchanged, logos arrived: repainted
        assert () in updates
        process_events()
        assert LOGO_LOADER.wait()
        widget.show_field(field, context)
        process_events()
        assert threads and gui_thread not in threads  # files looked for on loader thread only
        assert widget.grab().toImage() == expected
    finally:
        release.set()
        widget.hide()
        widget.deleteLater()
    assert LOGO_LOADER.wait()


def test_table_logo_drawn_when_update_timer_stopped(ui_env, bundled_fonts, monkeypatch):
    """Paused or off track: rows not refreshed, logo arriving later still drawn (own check timer)"""
    from PySide6.QtTest import QTest

    from neopedal.setting import cfg
    from neopedal.widget._modern.drivers import Context
    from neopedal.widget._modern.sample_field import sample_field

    own_logo(cfg.path.brand_logo, "Ferrari", "#e02020")
    field = sample_field()
    for car in field.vehicles:
        car.vehicleBrand = "Ferrari"
    context = Context(in_race=True, player=field.vehicles[field.player_index], player_pit_request=False)
    widget = new_standings(cfg)
    release = threading.Event()
    lookup = custom_image.brand_logo_file
    monkeypatch.setattr(custom_image, "brand_logo_file", lambda *args: (release.wait(5), lookup(*args))[1])
    try:
        widget.show_field(field, context)
        widget.show()
        process_events()  # painted with initials, logo waited for
        timer = widget.__dict__["_logo_timer"]
        widget.brand_logo("Ferrari", field.vehicles[0].vehicleName, 30, 15)
        assert widget.__dict__["_logo_timer"] is timer  # one check timer, not one per deferred logo
        updates = []
        update = widget.update
        monkeypatch.setattr(widget, "update", lambda *args: (updates.append(args), update(*args)))
        QTest.qWait(400)
        assert not updates and timer.isActive()  # still loading: checked again
        release.set()
        assert LOGO_LOADER.wait()
        QTest.qWait(400)  # no show_field (update timer stopped)
        assert () in updates
        assert not widget.brand_logo("Ferrari", field.vehicles[0].vehicleName, 30, 15).isNull()
    finally:
        release.set()
        widget.hide()
        widget.deleteLater()
    assert LOGO_LOADER.wait()


def test_table_no_logo_not_looked_for_again_until_pictures_change(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.userfile.game_images import images

    widget = new_standings(cfg)
    calls = []
    lookup = custom_image.brand_logo_file
    monkeypatch.setattr(custom_image, "brand_logo_file", lambda *args: (calls.append(args), lookup(*args))[1])
    try:
        for _ in range(3):
            assert widget.brand_logo("Nobrand", "Car #1", 30, 15).isNull()
        assert len(calls) == 1  # no logo: remembered
        monkeypatch.setattr(images, "version", images.version + 1)
        widget.brand_logo("Nobrand", "Car #1", 30, 15)
        assert len(calls) == 2  # game pictures changed: looked for again
    finally:
        widget.deleteLater()


# --- Readable copies made when game saves a logo
def test_readable_copies_made_when_logo_arrives(ui_env, monkeypatch):
    from neopedal.process import game_images as gi
    from neopedal.userfile import game_images
    from tests.test_game_pictures import FakeGame

    fake = FakeGame()
    monkeypatch.setattr(game_images, "fetch_from_game", fake)
    cache = game_images.GameImages()
    monkeypatch.setattr(game_images, "images", cache)
    monkeypatch.setattr(custom_image, "_tinted", {})
    custom_image.watch_game_logos()
    custom_image.watch_game_logos()  # once per cache
    assert cache._file_listeners == [custom_image._picture_saved]
    assert cache.fetch_picture(gi.BRAND, "McLaren")  # white logo
    path = cache.picture_file(gi.BRAND, "McLaren")
    keys = {(key[0], key[1]) for key in custom_image._tinted}
    assert {(path, False), (path, True)} <= keys  # both backgrounds, on fetch thread (here: test thread)
    light = custom_image._tinted[next(key for key in custom_image._tinted if key[:2] == (path, True))]
    assert light != path and os.path.isfile(light)  # white logo: dark copy for light background
    assert custom_image.pregenerate_logos(cache) == 0  # nothing left to make
    assert custom_image.pregenerate_logos(None) == 0


@pytest.fixture(autouse=True)
def loader_idle():
    """Jobs of a test done before next test (paths of test folder)"""
    yield
    assert LOGO_LOADER.wait()
