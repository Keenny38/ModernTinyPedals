"""Broadcast Director & stream overlays fixes: championship save failures reported (import success only once saved,
message of the action), league logo locked reported (graphics follow the files left), confirmations before a new
access token & layout resets with one undo, "/" focuses the car search of the director"""

import os

import pytest
from PySide6.QtCore import QMetaObject, QObject, Qt
from PySide6.QtTest import QTest

from tests.test_audit_g_qml_pages import item_named, pump, shown_director, wait_until
from tests.test_broadcast_director import car, director_page  # noqa: F401
from tests.test_stream_overlay import page_backend, process_events, server  # noqa: F401


@pytest.fixture
def english():
    from neopedal import i18n

    i18n.set_language("English")


def failing(*_args, **_kwargs):
    raise PermissionError("file locked")


# Championships
def test_championship_import_success_only_once_saved(director_page, english, tmp_path, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import director_graphics as dg

    backend = director_page.backend
    graphics = backend.graphics
    path = tmp_path / "Endurance Cup.csv"
    path.write_text("Driver;Points\nA;50\nB;80\n", encoding="utf-8")
    with monkeypatch.context() as patch:
        patch.setattr(dg, "save_championships", failing)
        assert not graphics.import_championship(str(path))
    assert backend.noticeError and backend.notice == "Championship not imported: file locked"
    assert graphics.championshipNames == []  # list as saved
    assert graphics.import_championship(str(path))
    assert not backend.noticeError and backend.notice == "2 drivers imported"
    assert graphics.championshipNames == ["Endurance Cup"]


def test_championship_remove_failure_and_choice_not_saved_again(director_page, english, tmp_path,  # noqa: F811
                                                                 monkeypatch):
    from neopedal.ui.quick import director_graphics as dg
    from neopedal.ui.quick import director_shared as ds

    backend = director_page.backend
    graphics = backend.graphics
    for name, rows in (("Cup", "A;GT3;50\nB;Hyper;80\n"), ("Trophy", "C;GT3;10\n")):
        path = tmp_path / f"{name}.csv"
        path.write_text("Driver;Class;Points\n" + rows, encoding="utf-8")
        assert graphics.import_championship(str(path))
    graphics.showOnDemand("champ")
    assert graphics.graphics_state()["champ"]["title"] == "Trophy"
    saves = []
    with monkeypatch.context() as patch:
        patch.setattr(dg, "save_championships", saves.append)
        graphics.setChampionship(0)
        graphics.setChampionshipClass("Hyper")
    assert saves == []  # championship list unchanged: file not written again
    champ = graphics.graphics_state()["champ"]
    assert (champ["title"], champ["subtitle"]) == ("Cup", "Hyper")
    with monkeypatch.context() as patch:
        patch.setattr(dg, "save_championships", failing)
        graphics.removeChampionship()
    assert backend.noticeError and backend.notice == "Championship not removed: file locked"
    assert graphics.championshipNames == ["Cup", "Trophy"] and graphics.graphics_state()["champ"]["title"] == "Cup"
    graphics.removeChampionship()
    assert graphics.championshipNames == ["Trophy"] and graphics.graphics_state()["champ"]["title"] == "Trophy"
    assert [item["name"] for item in ds.load_championships()] == ["Trophy"]
    graphics.removeChampionship()
    assert graphics.championshipNames == [] and graphics.onDemand == ""
    assert graphics.graphics_state()["champ"] is None


# League logo
def test_locked_logo_reported_and_graphics_follow_files(director_page, english, tmp_path,  # noqa: F811
                                                        monkeypatch):
    from neopedal import stream_director as sd
    from neopedal.ui.quick import director_graphics as dg

    backend = director_page.backend
    graphics = backend.graphics
    graphics.clear_logo()  # no branding folder yet: nothing to remove
    assert not backend.noticeError
    picture = tmp_path / "league.png"
    picture.write_bytes(b"\x89PNG fake")
    assert graphics.set_logo(str(picture))
    with monkeypatch.context() as patch:
        patch.setattr(dg.os, "remove", failing)
        assert not graphics.clear_logo()
        assert backend.noticeError and backend.notice == "Logo not removed: file locked"
        assert sd.brand_pictures()[0].startswith("/api/director/brand/logo.png")
        assert graphics.graphics_state()["brand"]["logo"].startswith("/api/director/brand/logo.png")  # still shown
        other = tmp_path / "other.jpg"
        other.write_bytes(b"jpg")
        assert not graphics.set_logo(str(other))  # old logo locked: new one not added beside it
        assert backend.notice == "Logo not saved: file locked"
        assert sorted(os.listdir(sd.brand_folder())) == ["logo.png"]
    assert graphics.clear_logo() and graphics.graphics_state()["brand"]["logo"] == ""


# Layout resets & undo
def test_graphics_layout_reset_of_preset_in_use_and_undo(director_page, english):  # noqa: F811
    from neopedal.stream_director import director_layout

    backend = director_page.backend
    graphics = backend.graphics
    director_layout.set("", {"tower": [0.2, 0.2, 1.0]})
    director_layout.set("race", {"map": [0.7, 0.7, 1.5]})
    graphics.setLayoutPreset("race")
    graphics.resetGraphicsLayout()  # preset in use only (the one the editor changes)
    assert director_layout.get("race") == {} and director_layout.get("") == {"tower": [0.2, 0.2, 1.0]}
    assert graphics.canUndoLayoutReset
    graphics.undoLayoutReset()
    assert director_layout.get("race") == {"map": [0.7, 0.7, 1.5]} and not graphics.canUndoLayoutReset
    assert backend.notice == "Previous layout restored"
    # Layout saved by the editor after the reset: never overwritten by the undo
    graphics.resetGraphicsLayout()
    director_layout.set("race", {"tower": [0.5, 0.5, 1.0]})
    assert not graphics.canUndoLayoutReset
    graphics.undoLayoutReset()
    assert director_layout.get("race") == {"tower": [0.5, 0.5, 1.0]} and backend.noticeError
    # Nothing placed: nothing to undo
    director_layout.set("race", {})
    graphics.resetGraphicsLayout()
    assert not graphics.canUndoLayoutReset
    graphics.setLayoutPreset("")
    director_layout.set("", {})


def test_graphics_layout_reset_at_once_undo_in_toast_and_ctrl_z(director_page, english):  # noqa: F811
    """Reversible reset: never confirmed, Undo in the one toast of the page & Ctrl+Z (no Undo button of its own)"""
    from neopedal.stream_director import director_layout

    backend, root = shown_director(director_page, car(1, 1), car(2, 2, distance=600.0))
    director_layout.set("", {"tower": [0.2, 0.2, 1.0]})
    backend.graphics.resetGraphicsLayout()
    pump()
    assert director_layout.get("") == {}
    root.forceActiveFocus()
    QTest.keyClick(director_page.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)  # Ctrl+Z
    pump()
    assert director_layout.get("") == {"tower": [0.2, 0.2, 1.0]} and not backend.graphics.canUndoLayoutReset
    panel = root.findChild(QObject, "graphicsPopup")
    panel.setProperty("tab", 2)  # style & layout
    panel.setProperty("visible", True)
    pump()
    button = item_named(root, "resetGraphicsLayout") or panel.findChild(QObject, "resetGraphicsLayout")
    assert root.findChild(QObject, "resetGraphicsLayoutDialog") is None
    assert (item_named(root, "undoGraphicsLayoutReset") or panel.findChild(QObject, "undoGraphicsLayoutReset")) is None
    QMetaObject.invokeMethod(button, "click")
    pump()
    assert director_layout.get("") == {} and backend.graphics.canUndoLayoutReset and button.property("visible")
    toasts = [item for item in root.findChildren(QObject) if item.objectName() == "bridgeToast"]
    assert len(toasts) == 1  # one toast in the page
    toast = toasts[0]
    assert toast.property("shown") and toast.property("actionText") == "Undo"
    assert toast.property("text") == "Graphics back to their places"
    director_page.view.rootContext().contextProperty("dialogs").toastAction()  # Undo of the toast
    pump()
    assert director_layout.get("") == {"tower": [0.2, 0.2, 1.0]} and not backend.graphics.canUndoLayoutReset
    panel.setProperty("visible", False)
    backend.notify("Camera refused", True)  # refused command: same toast, in red
    pump()
    assert toast.property("level") == "error" and toast.property("actionText") == ""
    assert toast.property("text") == "Camera refused"
    director_layout.set("", {})
    assert not director_page.view.errors()


def test_stream_layout_reset_undo(page_backend, english):  # noqa: F811
    from neopedal.stream_overlay import stream_layout

    backend = page_backend
    stream_layout.set("16:9", {"gear": [0.5, 0.25, 1.5]})
    backend.refresh(force=True)
    assert backend.layoutPlaced and not backend.canUndoReset
    backend.resetLayout()
    assert stream_layout.get("16:9") == {} and backend.canUndoReset
    backend.setLayoutFormat(1)  # other format: its own layout, nothing to undo there
    assert not backend.canUndoReset
    backend.setLayoutFormat(0)
    backend.undoResetLayout()
    assert stream_layout.get("16:9") == {"gear": [0.5, 0.25, 1.5]} and not backend.canUndoReset
    assert backend.noticeText == "Previous layout restored"
    backend.resetLayout()
    stream_layout.set("16:9", {"radar": [0.1, 0.1, 1.0]})  # saved by the layout editor meanwhile
    assert not backend.canUndoReset
    backend.undoResetLayout()
    assert stream_layout.get("16:9") == {"radar": [0.1, 0.1, 1.0]}
    stream_layout.set("16:9", {})


def test_stream_page_confirms_new_token_resets_with_undo(page_backend, english):  # noqa: F811
    from PySide6.QtCore import QCoreApplication, QEvent

    from neopedal.setting import cfg
    from neopedal.stream_overlay import stream_layout
    from neopedal.ui.stream_overlay_view import StreamOverlaysView

    stream_layout.set("16:9", {"gear": [0.5, 0.25, 1.5]})
    view = StreamOverlaysView(None)
    try:
        view.resize(1200, 800)
        view.show()
        process_events(0.2)
        root = view.view.rootObject()
        token = cfg.user.config["stream_overlay"]["access_token"]
        dialog = root.findChild(QObject, "newTokenDialog")
        QMetaObject.invokeMethod(root.findChild(QObject, "newTokenButton"), "click")
        assert wait_until(lambda: dialog.property("visible"))
        assert cfg.user.config["stream_overlay"]["access_token"] == token  # asked first
        QMetaObject.invokeMethod(dialog, "accept")
        process_events(0.05)
        assert cfg.user.config["stream_overlay"]["access_token"] != token
        # Layout reset: reversible, at once (never confirmed), Undo in the toast & Ctrl+Z
        assert root.findChild(QObject, "resetStreamLayoutDialog") is None
        assert root.findChild(QObject, "undoStreamLayoutReset") is None
        QMetaObject.invokeMethod(root.findChild(QObject, "resetStreamLayout"), "click")
        process_events(0.05)
        assert stream_layout.get("16:9") == {}
        toast = root.findChild(QObject, "bridgeToast")
        assert toast.property("shown") and toast.property("actionText") == "Undo"
        view.view.rootContext().contextProperty("dialogs").toastAction()
        process_events(0.05)
        assert stream_layout.get("16:9") == {"gear": [0.5, 0.25, 1.5]}
        QMetaObject.invokeMethod(root.findChild(QObject, "resetStreamLayout"), "click")
        process_events(0.05)
        assert stream_layout.get("16:9") == {}
        view.view.setFocus()
        QTest.keyClick(view.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        process_events(0.05)
        assert stream_layout.get("16:9") == {"gear": [0.5, 0.25, 1.5]}
        assert not view.view.errors()
    finally:
        stream_layout.set("16:9", {})
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# Director car search
def test_slash_focuses_car_search_unless_typing(director_page):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0))
    search = item_named(root, "carSearch")
    item_named(root, "carList").forceActiveFocus()
    pump()
    QTest.keyClick(director_page.view, Qt.Key.Key_Slash, Qt.KeyboardModifier.NoModifier)
    assert wait_until(lambda: search.property("activeFocus"))
    assert search.property("text") == ""  # "/" not typed in the field
    # Typing in another field: "/" is a character there
    backend.selectCar(1)
    pump()
    note = item_named(root, "noteField")
    note.forceActiveFocus()
    QTest.keyClicks(director_page.view, "a/b")
    pump()
    assert note.property("text") == "a/b" and not search.property("activeFocus")
    QTest.keyClick(director_page.view, Qt.Key.Key_Escape)
    pump()
    assert not director_page.view.errors()
