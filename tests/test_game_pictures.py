"""Car brand & circuit pictures fetched from the game (LMU web UI), cached, shown in overlays, pages & stream

A fake game answers the web requests: nothing is ever asked to a real game in tests.
"""

import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from tinypedal.process import game_images as gi
from tinypedal.setting import cfg
from tinypedal.userfile import game_images

WHITE_LOGO = (b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">'
              b'<rect x="10" y="10" width="180" height="80" fill="#ffffff"/></svg>')
RED_LOGO = WHITE_LOGO.replace(b"#ffffff", b"#e02020")
VEHICLES = [
    {"name": "Ferrari AF Corse #50", "manufacturer": "Ferrari", "vehFile": "C:\\LMU\\Ferrari_499P\\499P_50.VEH",
     "fullPathTree": "LMU, Hypercar, Ferrari 499P"},
    {"name": "United Autosports #59", "manufacturer": "McLaren", "vehFile": "C:\\LMU\\McLaren\\720S_59.VEH",
     "fullPathTree": "LMU, GT3, McLaren 720S"},
]
CARS = [{"desc": "Ferrari AF Corse #50", "manufacturer": "Ferrari"}, {"desc": "BMW Team WRT #46", "manufacturer": "BMW"}]
TRACKS = [{"sceneDesc": "LEMANS_2023", "properTrackName": "Circuit de la Sarthe", "name": "Le Mans"}]


class FakeGame:
    """Game web server: answers of routes & pictures, requests made"""

    def __init__(self, running: bool = True):
        self.running = running
        self.answers: dict[str, tuple[int, bytes]] = {
            gi.VEHICLES_ROUTE: (200, json.dumps(VEHICLES).encode()),
            gi.CARS_ROUTE: (200, json.dumps(CARS).encode()),
            gi.TRACKS_ROUTE: (200, json.dumps(TRACKS).encode()),
            "/start/images/manufacturer/Brand=Ferrari.svg": (200, RED_LOGO),
            "/start/images/manufacturer/Brand=McLaren.svg": (200, WHITE_LOGO),
            "/start/images/manufacturer/Brand=BMW.svg": (200, WHITE_LOGO),
            "/start/images/manufacturer/Brand=BMW%20Dark.svg": (200, RED_LOGO),
            "/start/images/tracks/logos/lemanswec.svg": (200, WHITE_LOGO),
            "/start/images/tracks/cards/lemanswec.webp": (200, b"RIFF....WEBPVP8 "),
        }
        self.asked: list[str] = []

    def __call__(self, resource: str) -> tuple[int, bytes]:
        self.asked.append(resource)
        if not self.running:
            return 0, b""
        return self.answers.get(resource, (404, b"<html>not found</html>"))


@pytest.fixture
def game(ui_env, monkeypatch):
    """Fake running game, fresh picture cache in test folder"""
    fake = FakeGame()
    monkeypatch.setattr(game_images, "fetch_from_game", fake)
    cache = game_images.GameImages()
    monkeypatch.setattr(game_images, "images", cache)
    from tinypedal.ui.quick import game_pictures
    from tinypedal.userfile import custom_image
    monkeypatch.setattr(custom_image, "_tinted", {})
    monkeypatch.setattr(custom_image, "_own_logos", {})
    monkeypatch.setattr(game_pictures, "images", cache)
    monkeypatch.setattr(game_pictures, "light_theme", lambda: False)  # dark app pages unless test says
    return fake, cache


def wait_for(condition, seconds: float = 5.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return condition()


# --- Cache & game lists
def test_game_lists_read_and_logos_fetched_in_background(game):
    fake, cache = game
    assert cache.brand_logo("Ferrari") == ""  # not cached yet: fetched in background
    assert wait_for(lambda: os.path.isfile(cache.picture_file(gi.BRAND, "Ferrari")))
    assert wait_for(lambda: os.path.isfile(cache.picture_file(gi.TRACK_LOGO, "lemanswec")))
    assert wait_for(lambda: os.path.isfile(cache.picture_file(gi.BRAND_DARK, "BMW")))
    assert cache.brand("Ferrari AF Corse #50") == "Ferrari"
    assert cache.brand("bmw team wrt #46") == "BMW"  # race car list, name case ignored
    assert cache.brand("", "mclaren 720S GT3") == "McLaren"  # model text
    assert cache.brand("Unknown car", "Glickenhaus 007") == "Glickenhaus"
    assert cache.track("Circuit de la Sarthe") == "lemanswec"
    assert cache.vehicle("United Autosports #59").file == "720S_59"
    assert cache.brand_logo("BMW", dark=True).endswith(os.path.join("brand_dark", "BMW.svg"))
    # Catalog kept for next runs (game not running then)
    fake.running = False
    later = game_images.GameImages()
    later.load_catalog()
    assert later.brand("Ferrari AF Corse #50") == "Ferrari" and later.track("Le Mans") == "lemanswec"
    assert later.brand_logo("Ferrari").endswith("Ferrari.svg")  # cached file, no game needed
    assert later.stop()


def test_stop_ends_fetch_thread_and_lookup_restarts_it(game):
    _, cache = game
    cache.brand_logo("Ferrari")
    thread = cache._thread
    assert thread is not None and thread.is_alive()
    assert cache.stop()
    assert not thread.is_alive() and cache._thread is None
    assert cache.stop()  # no thread: nothing to do
    cache.brand_logo("Ferrari")  # next lookup starts a new thread, queued fetch still done
    assert cache._thread is not None and cache._thread is not thread
    assert wait_for(lambda: os.path.isfile(cache.picture_file(gi.BRAND, "Ferrari")))


def test_pictures_game_does_not_have_not_asked_again(game):
    fake, cache = game
    assert not cache.fetch_picture(gi.BRAND, "Nobody")  # 404
    assert not os.path.exists(cache.picture_file(gi.BRAND, "Nobody"))
    asked = len(fake.asked)
    cache.request(gi.BRAND, "Nobody")
    assert len(fake.asked) == asked and not cache._queued  # known missing: not queued
    fake.answers["/start/images/cars/FrontThumbnail/bad_frontAngle.webp"] = (200, b"<html>login</html>"[1:])
    assert not cache.fetch_picture(gi.CAR_THUMBNAIL, "bad")  # not a picture
    with open(os.path.join(cache.folder, game_images.CATALOG_FILE), encoding="utf-8") as file:
        saved = json.load(file)
    assert "/start/images/manufacturer/Brand=Nobody.svg" in saved["missing"]


def test_game_not_running_left_alone(game):
    fake, cache = game
    fake.running = False
    assert not cache.read_game_lists()
    asked = len(fake.asked)
    cache.request(gi.BRAND, "Ferrari")
    assert len(fake.asked) == asked and not cache._queued  # waits RETRY_GAME before asking again
    assert cache.file(gi.BRAND, "") == ""


def test_listeners_told_once_saved(game):
    _, cache = game
    calls = []
    cache.add_listener(lambda: calls.append(cache.version))
    assert cache.fetch_picture(gi.BRAND, "McLaren")
    assert calls == [cache.version]
    cache.remove_listener(calls.append)  # not registered: ignored
    assert not cache.fetch_picture(gi.BRAND, "McLaren")  # already cached


# --- Picture files for Qt
def test_read_picture_sharp_at_size(game, tmp_path):
    from tinypedal.userfile.custom_image import is_light_logo, read_picture

    path = tmp_path / "logo.svg"
    path.write_bytes(WHITE_LOGO)
    image = read_picture(str(path), 40, 40, 2.0)
    assert (image.width(), image.height()) == (80, 40)  # aspect kept, drawn at device pixels
    assert image.devicePixelRatio() == 2.0
    assert is_light_logo(image)
    red = tmp_path / "red.svg"
    red.write_bytes(RED_LOGO)
    assert not is_light_logo(read_picture(str(red), 40, 40))
    assert read_picture(str(tmp_path / "missing.svg"), 40, 40).isNull()


def test_light_background_gets_dark_copy_of_white_logo(game):
    from tinypedal.userfile.custom_image import logo_for_background, read_picture

    _, cache = game
    assert cache.fetch_picture(gi.BRAND, "McLaren") and cache.fetch_picture(gi.BRAND, "Ferrari")
    white = cache.picture_file(gi.BRAND, "McLaren")
    dark = logo_for_background(white, True)
    assert dark != white and os.path.abspath(dark).startswith(os.path.abspath(cache.folder)) and dark.endswith(".png")
    pixel = read_picture(dark, 80, 40).pixelColor(40, 20)
    assert pixel.alpha() > 200 and pixel.lightness() < 80
    assert logo_for_background(white, False) == white  # white logo reads on dark background
    colored = cache.picture_file(gi.BRAND, "Ferrari")
    assert logo_for_background(colored, True) == colored == logo_for_background(colored, False)


def test_dark_background_gets_light_copy_of_black_logo(game, tmp_path):
    from tinypedal.userfile.custom_image import logo_for_background, read_picture

    black = tmp_path / "black.svg"  # black wordmark with an orange swoosh (kept)
    black.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">'
                      b'<rect x="0" y="0" width="150" height="100" fill="#000000"/>'
                      b'<rect x="160" y="0" width="40" height="100" fill="#ff8000"/></svg>')
    light = logo_for_background(str(black), False)
    assert light != str(black) and "on_dark_" in os.path.basename(light)
    image = read_picture(light, 200, 100)
    assert image.pixelColor(40, 50).lightness() > 200  # black part made light
    assert image.pixelColor(190, 50).hsvHue() in range(20, 40)  # orange kept
    assert logo_for_background(str(black), True) == str(black)  # black logo reads on light background
    shield = tmp_path / "shield.svg"  # black shield with a white lion: readable as it is
    shield.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">'
                       b'<rect width="100" height="100" fill="#000000"/><circle cx="50" cy="50" r="30" fill="#ffffff"/>'
                       b'</svg>')
    assert logo_for_background(str(shield), False) == str(shield)


def test_logo_drawn_on_part_of_picture_gets_copy_without_margins(game, tmp_path):
    from tinypedal.userfile.custom_image import drawn_rect, logo_for_background, read_picture

    wordmark = tmp_path / "wordmark.png"  # red wordmark drawn in the middle of a square picture
    image = QImage(240, 180, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    for y in range(80, 100):
        for x in range(20, 220):
            image.setPixelColor(x, y, QColor(220, 30, 30))
    assert image.save(str(wordmark))
    assert drawn_rect(image).getRect() == (20, 80, 200, 20)
    for light_background in (False, True):
        trimmed = logo_for_background(str(wordmark), light_background)
        assert trimmed != str(wordmark) and os.path.isfile(trimmed)
        copy = read_picture(trimmed, 1000, 1000)
        assert round(copy.width() / copy.height()) == 10  # margins gone, logo drawn as big as its cell
        assert copy.pixelColor(copy.width() // 2, copy.height() // 2).red() > 200  # colors kept
    empty = QImage(10, 10, QImage.Format.Format_ARGB32)
    empty.fill(QColor(0, 0, 0, 0))
    assert drawn_rect(empty).isNull()


def test_own_logo_matches_brand_words(game):
    from tinypedal.userfile.custom_image import own_logo_file

    for name in ("Corvette", "Chevrolet", "Ford", "Mercedes-AMG"):
        image = QImage(8, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        image.save(os.path.join(cfg.path.brand_logo, f"{name}.png"))
    folder = cfg.path.brand_logo
    assert own_logo_file(folder, "Chevrolet Corvette").endswith("Corvette.png")  # last word first
    assert own_logo_file(folder, "Ford Mustang").endswith("Ford.png")
    assert own_logo_file(folder, "mercedes amg").endswith("Mercedes-AMG.png")
    assert own_logo_file(folder, "Toyota", "Toyota") == ""
    assert own_logo_file(folder, "Unknown", "Ford").endswith("Ford.png")  # game brand name


def test_own_brand_logo_first(game):
    from tinypedal.userfile.custom_image import brand_logo_file

    _, cache = game
    assert cache.fetch_picture(gi.BRAND, "Ferrari")
    own = os.path.join(cfg.path.brand_logo, "Ferrari.png")
    image = QImage(20, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor("blue"))
    assert brand_logo_file(cfg.path.brand_logo, "Ferrari").endswith(os.path.join("brand", "Ferrari.svg"))
    image.save(own)
    assert brand_logo_file(cfg.path.brand_logo, "Ferrari") == own
    assert brand_logo_file(cfg.path.brand_logo, "", vehicle_name="Ferrari AF Corse #50") == own  # game car list


# --- Overlays: brand logo column
def test_modern_driver_table_draws_game_logo(game, bundled_fonts, monkeypatch):
    from importlib import import_module

    from tests.test_widget_benchmark import fill_field
    from tinypedal.module_info import minfo
    from tinypedal.widget._modern import create_widget

    _, cache = game
    for name in ("dataSet", "totalVehicles", "playerIndex", "leaderIndex"):
        monkeypatch.setattr(minfo.vehicles, name, getattr(minfo.vehicles, name))
    fill_field(6)
    for car in minfo.vehicles.dataSet:
        car.vehicleBrand = "Ferrari"
    assert cfg.default.setting["standings"]["column_brand_logo"]  # on by default
    widget = create_widget(import_module("tinypedal.widget.standings"), cfg, "standings")
    try:
        assert widget.brand_logo("Ferrari", "", 30, 15).isNull()  # not fetched yet
        assert wait_for(lambda: os.path.isfile(cache.picture_file(gi.BRAND, "Ferrari")))
        assert not widget.brand_logo("Ferrari", "", 30, 15).isNull()  # looked for again: game pictures changed
        widget.brand_logo("Ferrari", "Ferrari AF Corse #50", 30, 15)
        widget.brand_logo("Ferrari", "Ferrari AF Corse #51", 30, 15)
        assert len(widget._logo_cache) == 1  # cars of a brand share their logo
    finally:
        widget.deleteLater()


# --- Pages
def test_page_urls_and_notifier(game, monkeypatch):
    from tinypedal.ui.quick import game_pictures as gp

    _, cache = game
    assert cache.fetch_picture(gi.TRACK_LOGO, "lemanswec") and cache.fetch_picture(gi.BRAND, "BMW")
    url = gp.track_logo_url("Circuit de la Sarthe")
    assert url.startswith("file:") and url.endswith("lemanswec.svg")
    assert gp.brand_logo_url(brand="BMW").endswith("BMW.svg")
    assert gp.brand_logo_url() == ""
    monkeypatch.setattr(gp, "light_theme", lambda: True)
    assert "/tinted/on_light_" in gp.brand_logo_url(brand="BMW")  # game dark logo not cached: dark copy
    assert wait_for(lambda: os.path.isfile(cache.picture_file(gi.BRAND_DARK, "BMW")))  # asked meanwhile
    assert gp.brand_logo_url(brand="BMW").endswith("brand_dark/BMW.svg")  # dark logo of game (red: kept)
    logos = gp.LogoCache()
    assert logos.track("Le Mans", "") == gp.track_logo_url("Le Mans") != url  # dark copy on light theme
    notifier = gp.notifier()
    cache.add_listener(notifier._picture_arrived)
    cache.changed()
    QCoreApplication.processEvents()
    assert notifier._timer.isActive()  # pages told once pictures stop arriving


def test_results_rows_show_logos(game):
    from tinypedal.process.results_file import Entry, SessionResult
    from tinypedal.ui.quick import results_backend as rb

    _, cache = game
    assert cache.fetch_picture(gi.TRACK_LOGO, "lemanswec") and cache.fetch_picture(gi.BRAND, "Ferrari")
    entry = Entry("Alice", "AF Corse", "Ferrari AF Corse #50", "Ferrari 499P", "Hyper", "50", 1, 1, 1, 1, 10,
                  200.0, 0.0, 1, "Finished Normally", "", True, True, "", (), ())
    result = SessionResult("x.xml", "LMU", "", "", 0.0, "Race", "Race", "24 Heures du Mans", "Circuit de la Sarthe",
                           "", 13626.0, "", 0, 0, 10, (entry,), ())
    from PySide6.QtCore import QDate
    assert rb.session_row(result, QDate.currentDate())["trackLogo"].endswith("lemanswec.svg")
    assert rb.classification_rows(result, "", "")[0]["brandLogo"].endswith("Ferrari.svg")
    assert rb.session_header(result)["trackLogo"]


# --- Stream overlay
def test_stream_picture_links_stay_in_folders(game):
    from tinypedal import stream_overlay as so

    _, cache = game
    assert cache.fetch_picture(gi.BRAND, "Ferrari")
    path = cache.picture_file(gi.BRAND, "Ferrari")
    link = so.picture_link(path)
    assert link == "/pictures/brand/Ferrari.svg"
    assert so.picture_file(link[10:]) == os.path.abspath(path)
    assert so.picture_link(os.path.join(os.path.dirname(cache.folder), "elsewhere.svg")) == ""
    for bad in ("../config.json", "brand/../../x.svg", "brand/%2e%2e/x.svg", "brand/x.exe", "own/../brand/x.png"):
        assert so.picture_file(bad) == ""
    own = os.path.join(cfg.path.brand_logo, "Ferrari.png")
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("blue"))
    image.save(own)
    assert so.picture_link(own) == "/pictures/own/Ferrari.png" and so.picture_file("own/Ferrari.png")
