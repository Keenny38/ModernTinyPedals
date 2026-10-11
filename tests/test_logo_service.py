"""Logo service: readable copies decided once (kept on disk), made per logo without blocking other lookups, made in
background for pages, home cards & classic overlays (same pixels as when read at once)"""

import os
import threading
import time
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest

from neopedal.process import game_images as gi
from neopedal.userfile import custom_image, game_images
from neopedal.userfile.custom_image import LOGO_LOADER, LogoLoader
from tests.test_game_pictures import FakeGame


def logo_file(path: str, color: str, margins: int = 10, width: int = 120, height: int = 60, fmt=None) -> str:
    image = QImage(width, height, fmt or QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.fillRect(margins, margins, width - margins * 2, height - margins * 2, QColor(color))
    painter.end()
    assert image.save(path)
    return path


@pytest.fixture
def game(ui_env, monkeypatch):
    """Fresh picture cache in test folder, fake game"""
    fake = FakeGame()
    monkeypatch.setattr(game_images, "fetch_from_game", fake)
    cache = game_images.GameImages()
    monkeypatch.setattr(game_images, "images", cache)
    from neopedal.ui.quick import game_pictures

    monkeypatch.setattr(game_pictures, "images", cache)
    monkeypatch.setattr(game_pictures, "light_theme", lambda: False)
    monkeypatch.setattr(custom_image, "_tinted", {})
    monkeypatch.setattr(custom_image, "_own_logos", {})
    yield fake, cache
    assert LOGO_LOADER.wait()


@pytest.fixture(autouse=True)
def loader_idle():
    yield
    assert LOGO_LOADER.wait()


def process_events(seconds: float = 0.0):
    end = time.time() + seconds
    while True:
        QCoreApplication.processEvents()
        if time.time() >= end:
            return
        time.sleep(0.01)


# --- Readable copies
def test_other_logos_not_blocked_while_one_is_made(game, monkeypatch, tmp_path):
    slow = logo_file(str(tmp_path / "slow.png"), "#e02020", 0)
    quick = logo_file(str(tmp_path / "quick.png"), "#20e020", 0)
    started, release = threading.Event(), threading.Event()
    make = custom_image._make_logo_for_background

    def blocking(path, light_background, stamp):
        if path == slow:
            started.set()
            release.wait(5)
        return make(path, light_background, stamp)

    monkeypatch.setattr(custom_image, "_make_logo_for_background", blocking)
    results = []
    thread = threading.Thread(target=lambda: results.append(custom_image.logo_for_background(slow, False)))
    thread.start()
    try:
        assert started.wait(5)
        begin = time.perf_counter()
        assert custom_image.logo_for_background(quick, False) == quick  # other logo: no wait
        assert time.perf_counter() - begin < 2
        assert thread.is_alive()
    finally:
        release.set()
        thread.join(5)
    assert results == [slow] and not custom_image._making


def test_decision_kept_on_disk_for_next_runs(game, monkeypatch, tmp_path):
    colored = logo_file(str(tmp_path / "colored.png"), "#e02020", 0)  # readable as it is: no copy
    white = logo_file(str(tmp_path / "white.png"), "#ffffff")  # light background: dark copy
    assert custom_image.logo_for_background(colored, True) == colored
    copy = custom_image.logo_for_background(white, True)
    assert copy != white
    names = os.listdir(os.path.join(game[1].folder, custom_image.TINTED_FOLDER))
    assert sorted(name.rsplit(".", 1)[1] for name in names) == ["keep", "png"]
    monkeypatch.setattr(custom_image, "_tinted", {})  # next run
    read = custom_image.read_picture
    monkeypatch.setattr(custom_image, "read_picture", lambda *args: pytest.fail("logo read again"))
    assert custom_image.logo_for_background(colored, True) == colored
    assert custom_image.logo_for_background(white, True) == copy
    monkeypatch.setattr(custom_image, "read_picture", read)
    later = time.time() + 10
    os.utime(colored, (later, later))  # logo changed: decided again
    assert custom_image.logo_for_background(colored, True) == colored
    assert len(os.listdir(os.path.join(game[1].folder, custom_image.TINTED_FOLDER))) == 3


def test_unreadable_logo_not_remembered(game, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a picture")
    assert custom_image.logo_for_background(str(broken), False) == str(broken)
    assert not os.path.isdir(os.path.join(game[1].folder, custom_image.TINTED_FOLDER))


def test_deferred_lookup_answers_only_decided_logos(game, tmp_path):
    white = logo_file(str(tmp_path / "white.png"), "#ffffff")
    with custom_image.deferred_logos() as deferral:
        assert custom_image.logo_for_background(white, True) == ""
        assert custom_image.logo_for_background("", True) == ""
    assert deferral.missed
    copy = custom_image.logo_for_background(white, True)
    with custom_image.deferred_logos() as deferral:
        assert custom_image.logo_for_background(white, True) == copy
    assert not deferral.missed
    assert getattr(custom_image._deferred, "state", None) is None  # left as it was


# --- Pregeneration
def test_saved_logo_only_given_copies(game, monkeypatch):
    _, cache = game
    custom_image.watch_game_logos()
    made = []
    monkeypatch.setattr(custom_image, "pregenerate_logo", made.append)
    versions = (cache.version, cache.logos_version, cache.lists_version)
    cache.changed(gi.BRAND, "brand/McLaren.svg")
    cache.changed(gi.CAR_THUMBNAIL, "car_thumbnail/car.webp")
    assert made == ["brand/McLaren.svg"]  # car picture: nothing to make, other logos not checked again
    assert (cache.version, cache.logos_version, cache.lists_version) == (
        versions[0] + 2, versions[1] + 1, versions[2])
    cache.changed()  # game lists read
    assert (cache.logos_version, cache.lists_version) == (versions[1] + 2, versions[2] + 1) and len(made) == 1


def test_logos_of_earlier_runs_given_copies_in_background(game, tmp_path):
    _, cache = game
    folder = os.path.join(cache.folder, gi.BRAND)
    os.makedirs(folder)
    white = logo_file(os.path.join(folder, "White.png"), "#ffffff")
    colored = logo_file(os.path.join(folder, "Colored.png"), "#e02020", 0)
    custom_image.watch_game_logos()  # first logo lookup
    assert LOGO_LOADER.wait()
    for path in (white, colored):
        stamp = os.path.getmtime(path)
        assert all(custom_image._known_logo((path, light, stamp)) is not None for light in (False, True))
    assert custom_image.pregenerate_logos(cache) == 0


def test_background_jobs_run_after_others():
    loader = LogoLoader()
    release = threading.Event()
    order = []
    loader.run("block", lambda: release.wait(5))
    loader.run("later", lambda: order.append("background"), background=True)
    assert not loader.run("later", lambda: order.append("again"), background=True)  # queued already
    loader.result("now", lambda: order.append("asked"))
    release.set()
    assert loader.wait()
    assert order == ["asked", "background"]
    assert loader.finished == 1 and list(loader._results) == ["now"]  # dropped results not kept


# --- Pages
def test_page_logo_made_in_background(game, monkeypatch):
    from neopedal.ui.quick import game_pictures as gp

    _, cache = game
    assert cache.fetch_picture(gi.BRAND, "McLaren")  # white logo, no copy for light pages yet
    monkeypatch.setattr(gp, "light_theme", lambda: True)
    gui = threading.get_ident()
    readers = []
    read = custom_image.read_picture
    monkeypatch.setattr(custom_image, "read_picture",
                        lambda *args: (readers.append(threading.get_ident()), read(*args))[1])
    notifier = gp.notifier()
    notifier._timer.stop()
    logos = gp.LogoCache()
    assert logos.brand("", "McLaren") == ""  # copy made meanwhile
    assert LOGO_LOADER.wait()
    process_events()
    assert notifier._timer.isActive()  # pages told
    url = logos.brand("", "McLaren")
    assert "/tinted/on_light_" in url and url == gp.brand_logo_url(brand="McLaren")
    assert readers and gui not in readers
    notifier._timer.stop()


def test_page_logos_kept_when_pictures_arrive(game, monkeypatch):
    from neopedal.ui.quick import game_pictures as gp

    _, cache = game
    asked = []
    monkeypatch.setattr(gp, "brand_logo_url", lambda *names: asked.append(names) or ("logo" if names[1] else ""))
    logos = gp.LogoCache()
    assert logos.brand("Car", "Ferrari") == "logo" and logos.brand("Car", "") == ""
    cache.changed(gi.CAR_PICTURE, "car_picture/car.webp")
    logos.brand("Car", "Ferrari")
    logos.brand("Car", "")
    assert asked == [("Car", "Ferrari"), ("Car", ""), ("Car", "")]  # names without logo only
    monkeypatch.setattr(gp, "light_theme", lambda: True)
    logos.brand("Car", "Ferrari")
    cache.changed(gi.BRAND_DARK, "brand_dark/Ferrari.svg")
    logos.brand("Car", "Ferrari")
    assert asked[-2:] == [("Car", "Ferrari")] * 2  # light pages: dark logo of game may replace it
    cache.changed()
    count = len(asked)
    monkeypatch.setattr(gp, "light_theme", lambda: False)
    logos.brand("Car", "Ferrari")
    assert len(asked) == count + 1  # game lists: brand names may change


# --- Home cards
def test_home_last_session_logos_in_background(ui_env, monkeypatch):
    from neopedal.ui import home_view
    from neopedal.ui.home_view import HomeCard
    from neopedal.userfile.driver_history import SessionRecord

    record = SessionRecord(time=1759660000, track="Spa", vehicle="Hyper - Ferrari", session=2, best=123.456)
    calls = []
    monkeypatch.setattr(home_view, "game_logos",
                        lambda *args, **kwargs: calls.append((threading.get_ident(), kwargs.get("light"))) or ())
    card = HomeCard(None, "Last Session", ("", "H"), "")
    try:
        card.show_logos(("last", 1), lambda: home_view.record_logos(record, True))
        assert card.label_logos.isHidden() and card.logos == ()
        assert LOGO_LOADER.wait()
        QTest.qWait(300)
        assert card.logos == ("last", 1)  # waited result taken by check timer
        assert calls == [(calls[0][0], True)] and calls[0][0] != threading.get_ident()
    finally:
        card.deleteLater()


def test_home_card_logos_read_in_background_same_pixels(ui_env, tmp_path):
    from PySide6.QtGui import QPixmap

    from neopedal.ui._common import UIScaler
    from neopedal.ui.home_view import HomeCard

    paths = (logo_file(str(tmp_path / "a.png"), "#e02020"), logo_file(str(tmp_path / "b.png"), "#2020e0", 0))
    card = HomeCard(None, "Last Session", ("", "H"), "")
    try:
        card.set_logos(paths)
        assert card.logos == ()  # read meanwhile
        assert LOGO_LOADER.wait()
        QTest.qWait(300)
        assert card.logos == paths and not card.label_logos.isHidden()
        shown = card.label_logos.pixmap().toImage()
        height = UIScaler.pixel(22)
        ratio = card.devicePixelRatioF()
        expected = HomeCard(None, "Last Session", ("", "H"), "")
        expected.draw_logos(tuple(custom_image.load_picture(path, height * 3, height, ratio) for path in paths))
        assert shown == expected.label_logos.pixmap().toImage()
        expected.deleteLater()
        card.set_logos(())
        assert LOGO_LOADER.wait()
        QTest.qWait(300)
        assert card.label_logos.isHidden() and isinstance(card.label_logos.pixmap(), QPixmap)
    finally:
        card.deleteLater()


# --- Classic overlays
@pytest.mark.parametrize("fmt", [QImage.Format.Format_ARGB32, QImage.Format.Format_RGB32, QImage.Format.Format_Indexed8])
def test_classic_logo_read_in_background_same_pixels(ui_env, tmp_path, fmt):
    from neopedal.setting import cfg

    folder = cfg.path.brand_logo
    if fmt == QImage.Format.Format_Indexed8:
        image = QImage(90, 30, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        painter.fillRect(5, 5, 80, 20, QColor("#e0a020"))
        painter.end()
        image.convertToFormat(fmt).save(os.path.join(folder, "Brand.png"))
    else:
        logo_file(os.path.join(folder, "Brand.png"), "#e0a020", 3, 90, 30, fmt)
    svg = os.path.join(folder, "..", "vector.svg")
    with open(svg, "w", encoding="utf-8") as file:
        file.write('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><circle cx="50" cy="50" r="40" '
                   'fill="#20a0e0"/></svg>')
    for width, height in ((40, 14), (12, 14)):
        expected = custom_image.load_brand_logo_image(folder, "Brand", width, height)
        path, picture = custom_image.brand_logo_picture(folder, "Brand", width, height)
        assert not expected.isNull()
        assert custom_image.brand_logo_pixmap(path, picture, width, height).toImage() == expected.toImage()
    expected = custom_image.load_picture(svg, 40, 14)
    picture = custom_image.read_picture(svg, 40, 14)
    assert custom_image.brand_logo_pixmap(svg, picture, 40, 14).toImage() == expected.toImage()
    assert custom_image.brand_logo_pixmap("", QImage(), 40, 14).isNull()


def new_classic_standings(cfg):
    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
    cfg.user.setting["standings"]["show_brand_logo"] = True
    return create_widget(import_module("neopedal.widget.standings"), cfg, "standings")


def test_classic_logo_at_once_off_screen(ui_env, bundled_fonts):
    from neopedal.setting import cfg

    logo_file(os.path.join(cfg.path.brand_logo, "Ferrari.png"), "#e02020")
    widget = new_classic_standings(cfg)
    try:
        assert type(widget).__module__ == "neopedal.widget.standings"
        pixmap = widget.set_brand_logo("Ferrari")
        expected = custom_image.load_brand_logo_image(cfg.path.brand_logo, "Ferrari", widget.brd_width,
                                                      widget.brd_height)
        assert not pixmap.isNull() and pixmap.toImage() == expected.toImage()
    finally:
        widget.deleteLater()


def test_classic_logo_loaded_in_background_on_screen(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.userfile.game_images import images

    logo_file(os.path.join(cfg.path.brand_logo, "Ferrari.png"), "#e02020")
    widget = new_classic_standings(cfg)
    expected = custom_image.load_brand_logo_image(cfg.path.brand_logo, "Ferrari", widget.brd_width, widget.brd_height)
    gui = threading.get_ident()
    threads = []
    release = threading.Event()
    lookup = custom_image.brand_logo_file
    monkeypatch.setattr(custom_image, "brand_logo_file",
                        lambda *args: (threads.append(threading.get_ident()), release.wait(5), lookup(*args))[2])
    try:
        widget.show()
        target = widget.bars_brd[0]
        target.last = None
        widget.update_brd(target, "Ferrari", False, 0)  # row shown
        assert target.image.isNull()  # same as without logo meanwhile
        widget.update_brd(widget.bars_brd[1], "Nobrand", False, 0)
        release.set()
        assert LOGO_LOADER.wait()
        updates = []
        update = target.update
        monkeypatch.setattr(target, "update", lambda *args: (updates.append(args), update(*args)))
        QTest.qWait(400)  # no row update: logo drawn once read
        assert updates and not target.image.isNull()
        assert target.image.toImage() == expected.toImage()
        assert threads and gui not in threads
        count = len(threads)
        for _ in range(3):
            assert widget.set_brand_logo("Nobrand").isNull()  # no logo: remembered
        assert len(threads) == count
        monkeypatch.setattr(images, "version", images.version + 1)  # car picture: not looked for again
        widget.set_brand_logo("Nobrand")
        assert LOGO_LOADER.wait() and len(threads) == count
        monkeypatch.setattr(images, "logos_version", images.logos_version + 1)  # game logo saved
        widget.set_brand_logo("Nobrand")
        assert LOGO_LOADER.wait() and len(threads) == count + 1
    finally:
        release.set()
        widget.hide()
        widget.deleteLater()
