"""Overlay settings package: export & import of one or several overlays (file), defaults left out, positions
kept or taken (moved to this screen), unknown overlays & options ignored, damaged files refused, preset
packages told apart, file drop routing, both pages' entries"""

import json
import zipfile

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog, QMessageBox

from neopedal.setting import cfg
from neopedal.userfile.overlay_package import (
    MAX_ENTRIES,
    PACKAGE_FORMAT,
    export_overlay_package,
    is_overlay_package,
    overlay_data,
    overlay_values,
    package_filename,
    package_format,
    read_overlay_package,
    scale_position,
)
from neopedal.userfile.preset_package import PACKAGE_FORMAT as PRESET_FORMAT
from neopedal.userfile.preset_package import export_preset_package, read_manifest

SCREEN = (0, 0, 1920, 1080)
DEFAULTS = {
    "relative": {"enable": False, "position_x": 10, "position_y": 20, "font_size": 15, "font_color": "#FFFFFF",
                 "show_name": True, "bar_gap": 1.5, "custom_image_file": "", "data_path": "data/"},
    "speedometer": {"enable": False, "position_x": 0, "position_y": 0, "font_size": 12, "font_weight": "Bold"},
}


def relative(**changes):
    return {**DEFAULTS["relative"], **changes}


def write_zip(path, manifest=None, files=None):
    with zipfile.ZipFile(path, "w") as package:
        if manifest is not None:
            package.writestr("manifest.json", manifest if isinstance(manifest, str) else json.dumps(manifest))
        for name, data in (files or {}).items():
            package.writestr(name, data if isinstance(data, str) else json.dumps(data))
    return str(path)


def manifest(**values):
    return {"format": PACKAGE_FORMAT, "version": 1, "app_version": "1.2.3", "setting_version": "2.51.0",
            "screen": [0, 0, 1920, 1080], **values}


# Package file
def test_round_trip_one_overlay_only_changed_options_and_position(tmp_path):
    path = str(tmp_path / "one.zip")
    options = relative(enable=True, font_size=20, custom_image_file="C:/me.png", data_path="D:/mine/")
    assert export_overlay_package(path, {"relative": options}, DEFAULTS, "1.2.3", "2.51.0", SCREEN) == 1
    with zipfile.ZipFile(path) as package:
        written = json.loads(package.read("overlays/relative.json"))
        info = json.loads(package.read("manifest.json"))
    # Defaults, overlay state & local files left out, position always written
    assert written == {"font_size": 20, "position_x": 10, "position_y": 20}
    assert info["format"] == PACKAGE_FORMAT and info["overlays"] == ["relative"] and info["screen"] == list(SCREEN)
    assert not (tmp_path / "one.zip.part").exists()
    read = read_overlay_package(path, DEFAULTS)
    assert read.overlays == {"relative": written}
    assert read.app_version == "1.2.3" and read.screen == SCREEN and not read.unknown and read.skipped == 0


def test_round_trip_several_overlays(tmp_path):
    path = str(tmp_path / "several.zip")
    overlays = {"relative": relative(show_name=False), "speedometer": {**DEFAULTS["speedometer"], "font_weight": "Normal"}}
    assert export_overlay_package(path, overlays, DEFAULTS, "1.2.3", "2.51.0") == 2
    read = read_overlay_package(path, DEFAULTS)
    assert read.overlays["relative"]["show_name"] is False
    assert read.overlays["speedometer"]["font_weight"] == "Normal"


def test_receiver_gets_default_plus_package_values():
    saved = relative(enable=True, font_size=30, font_color="#123456", position_x=500, position_y=600,
                     custom_image_file="C:/mine.png")
    package = {"font_color": "#ABCDEF", "position_x": 960, "position_y": 540}
    values = overlay_values(package, saved, DEFAULTS["relative"])
    # Changed by sender, back to default (sender kept it), receiver's state, files & position untouched
    assert values["font_color"] == "#ABCDEF" and values["font_size"] == 15
    assert "enable" not in values and "custom_image_file" not in values and "position_x" not in values


def test_positions_taken_and_moved_to_this_screen():
    saved = relative(position_x=5, position_y=5)
    package = {"position_x": 960, "position_y": 540}
    values = overlay_values(package, saved, DEFAULTS["relative"], keep_positions=False,
                            source=SCREEN, target=(0, 0, 2560, 1440))
    assert (values["position_x"], values["position_y"]) == (1280, 720)
    assert scale_position(100, 100, SCREEN, SCREEN) == (100, 100)
    assert scale_position(1920 + 100, 50, (1920, 0, 1920, 1080), (0, 0, 3840, 2160)) == (200, 100)


def test_unknown_overlay_and_options_ignored(tmp_path):
    path = write_zip(tmp_path / "other.zip", manifest(), {
        "overlays/relative.json": {"font_size": 18, "future_option": 1, "font_color": 5, "show_name": "yes",
                                   "enable": True, "data_path": "C:/", "position_x": 10 ** 9},
        "overlays/future_overlay.json": {"font_size": 1},
        "overlays/../../evil.json": {"font_size": 1},
        "readme.txt": "hello",
    })
    read = read_overlay_package(path, DEFAULTS)
    assert read.overlays == {"relative": {"font_size": 18}}
    assert read.unknown == ["future_overlay"]
    assert read.skipped == 6
    assert "relative: future_option (unknown option)" in read.left_out
    assert "relative: font_color (wrong type)" in read.left_out
    assert "relative: enable (kept on each computer)" in read.left_out
    assert "relative: position_x (invalid position)" in read.left_out


def test_damaged_or_oversized_packages_refused(tmp_path):
    with pytest.raises(ValueError):  # no manifest
        read_overlay_package(write_zip(tmp_path / "a.zip", None, {"overlays/relative.json": {}}), DEFAULTS)
    with pytest.raises(ValueError):  # broken manifest
        read_overlay_package(write_zip(tmp_path / "b.zip", "{not json"), DEFAULTS)
    with pytest.raises(ValueError):  # newer package version
        read_overlay_package(write_zip(tmp_path / "c.zip", manifest(version=99)), DEFAULTS)
    with pytest.raises(ValueError):  # overlay file not json
        read_overlay_package(write_zip(tmp_path / "d.zip", manifest(), {"overlays/relative.json": "{oops"}), DEFAULTS)
    with pytest.raises(ValueError):  # overlay file not options
        read_overlay_package(write_zip(tmp_path / "e.zip", manifest(), {"overlays/relative.json": [1, 2]}), DEFAULTS)
    with pytest.raises(ValueError):  # oversized overlay file
        big = json.dumps({"font_size": 1, "x": "a" * (1024 * 1024)})
        read_overlay_package(write_zip(tmp_path / "f.zip", manifest(), {"overlays/relative.json": big}), DEFAULTS)
    with pytest.raises(ValueError):  # too many entries
        files = {f"junk/{index}.txt": "" for index in range(MAX_ENTRIES + 1)}
        read_overlay_package(write_zip(tmp_path / "g.zip", manifest(), files), DEFAULTS)
    with pytest.raises(ValueError):  # oversized manifest
        read_overlay_package(write_zip(tmp_path / "h.zip", json.dumps(manifest(pad="a" * 70_000))), DEFAULTS)
    not_zip = tmp_path / "i.zip"
    not_zip.write_bytes(b"not a zip")
    with pytest.raises(zipfile.BadZipFile):
        read_overlay_package(str(not_zip), DEFAULTS)
    assert package_format(str(not_zip)) == ""


def test_invalid_screen_and_version_fall_back(tmp_path):
    path = write_zip(tmp_path / "s.zip", manifest(screen=[0, 0, 0, 0], setting_version="garbage", app_version=3),
                     {"overlays/relative.json": {"font_size": 16}})
    read = read_overlay_package(path, DEFAULTS)
    assert read.screen == SCREEN and read.app_version == "" and read.overlays == {"relative": {"font_size": 16}}


def test_preset_and_overlay_packages_told_apart(tmp_path):
    overlay_zip = str(tmp_path / "overlays.zip")
    export_overlay_package(overlay_zip, {"relative": relative()}, DEFAULTS, "1", "2.51.0")
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "race.json").write_text("{}", encoding="utf-8")
    preset_zip = str(tmp_path / "preset.zip")
    export_preset_package(preset_zip, f"{settings}/", "race.json")
    assert is_overlay_package(overlay_zip) and not is_overlay_package(preset_zip)
    assert package_format(preset_zip) == PRESET_FORMAT
    with pytest.raises(ValueError):
        read_overlay_package(preset_zip, DEFAULTS)
    with zipfile.ZipFile(overlay_zip) as package, pytest.raises(ValueError):
        read_manifest(package)


def test_package_file_name():
    assert package_filename(["Relative"]) == "NeoPedal-overlay-Relative.zip"
    assert package_filename(['Bad:/ name?']) == "NeoPedal-overlay-Bad name.zip"
    assert package_filename(["A", "B", "C"]) == "NeoPedal-overlays-3.zip"


def test_overlay_data_counts_only_known_options():
    assert overlay_data({"unknown": 1, "font_size": 15, "show_name": False}, DEFAULTS["relative"]) == {"show_name": False}


# App: export & import dialogs
def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


class FakeDialog:
    """Overlay checklist answered by test"""

    def __init__(self, record, picked=None, keep=True, accept=True):
        self.record = record
        self.picked = picked
        self.keep = keep
        self.accepted = accept

    def __call__(self, parent, title, text, items, checked, selections=(), keep_positions=None, ok_text=""):
        self.record.update(title=title, text=text, items=items, checked=set(checked),
                           selections=dict(selections), keep_shown=keep_positions is not None)
        return self

    def exec(self):
        return QDialog.DialogCode.Accepted if self.accepted else QDialog.DialogCode.Rejected

    def checked_names(self):
        return list(self.record["checked"]) if self.picked is None else self.picked

    def keep_positions(self):
        return self.keep


@pytest.fixture
def share(ui_env, monkeypatch, tmp_path):
    from neopedal.ui import overlay_share

    record: dict = {"warnings": [], "toasts": []}
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: record["warnings"].append(text))
    monkeypatch.setattr(overlay_share, "show_toast", lambda parent, text: record["toasts"].append(text))
    monkeypatch.setattr(overlay_share, "save_filename", lambda parent, name: str(tmp_path / name))
    monkeypatch.setattr(overlay_share, "screen_rect", lambda: SCREEN)
    overlay_share.test_record = record  # type: ignore[attr-defined]
    return overlay_share


class Host:
    def __init__(self):
        self.notices = []

    def confirm(self, text):
        return True

    def notify(self, text):
        self.notices.append(text)


class Control:
    def __init__(self):
        from neopedal.template.setting_widget import WIDGET_DEFAULT

        self.names = list(WIDGET_DEFAULT)


class Page:
    """Overlay Options page: real backend"""

    def __init__(self):
        from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend

        self.host = Host()
        self.backend = OverlayOptionsBackend(None, self.host, Control())

    def close(self):
        self.backend.close()
        self.backend.deleteLater()
        flush()


@pytest.fixture
def page(ui_env):
    page = Page()
    yield page
    page.close()


def test_export_ticks_given_overlay_else_enabled_ones(share, monkeypatch, tmp_path):
    record = share.test_record
    for options in cfg.user.setting.values():
        if "enable" in options:
            options["enable"] = False
    cfg.user.setting["relative"]["font_size"] = 21
    cfg.user.setting["speedometer"]["enable"] = True
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(record))
    assert share.export_overlay_settings(None, ["relative"]) == 1
    assert record["checked"] == {"relative"}
    label = dict(record["items"])["relative"]
    assert "1 option(s) changed" in label
    assert "relative" in record["selections"]["With changes"]
    path = tmp_path / "NeoPedal-overlay-Relative.zip"
    assert path.exists() and "<b>1</b> overlay(s)" in record["toasts"][-1]
    with zipfile.ZipFile(path) as package:
        assert json.loads(package.read("overlays/relative.json"))["font_size"] == 21
    # Nothing given: enabled overlays ticked
    assert share.export_overlay_settings(None) == 1
    assert record["checked"] == {"speedometer"}


def test_export_cancelled_writes_nothing(share, monkeypatch, tmp_path):
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(share.test_record, accept=False))
    assert share.export_overlay_settings(None, ["relative"]) == 0
    assert not list(tmp_path.glob("*.zip"))


def test_export_uses_shown_values_of_options_page(share, monkeypatch, tmp_path):
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(share.test_record))
    share.export_overlay_settings(None, ["relative"], lambda name: {**cfg.user.setting[name], "font_size": 33})
    with zipfile.ZipFile(tmp_path / "NeoPedal-overlay-Relative.zip") as package:
        assert json.loads(package.read("overlays/relative.json"))["font_size"] == 33


def export_relative(tmp_path, **changes) -> str:
    options = {**cfg.user.setting["relative"], **changes}
    path = str(tmp_path / "shared.zip")
    export_overlay_package(path, {"relative": options}, cfg.default.setting, "9.9.9", "2.51.0", SCREEN)
    return path


def test_import_sets_pending_edits_positions_kept(share, page, monkeypatch, tmp_path):
    record = share.test_record
    path = export_relative(tmp_path, font_size=27, position_x=900, position_y=400)
    cfg.user.setting["relative"]["font_weight"] = "Normal"  # receiver's change: back to sender's default
    saved_position = cfg.user.setting["relative"]["position_x"]
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(record))
    assert share.import_overlay_file(None, path, page)
    assert record["keep_shown"] and "Made with NeoPedal 9.9.9" in record["text"]
    backend = page.backend
    assert backend.value("relative", "font_size") == 27
    assert backend.value("relative", "font_weight") == cfg.default.setting["relative"]["font_weight"]
    assert backend.value("relative", "position_x") == saved_position
    assert cfg.user.setting["relative"]["font_size"] != 27  # not saved before Apply
    assert backend.overlay == "relative" and backend.canUndo
    assert "saved with Apply" in page.host.notices[-1]
    backend.undo()
    assert backend.value("relative", "font_size") == cfg.user.setting["relative"]["font_size"]


def test_import_positions_replaced(share, page, monkeypatch, tmp_path):
    path = export_relative(tmp_path, position_x=900, position_y=400)
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(share.test_record, keep=False))
    assert share.import_overlay_file(None, path, page)
    assert (page.backend.value("relative", "position_x"), page.backend.value("relative", "position_y")) == (900, 400)


def test_import_unticked_overlay_left_alone(share, page, monkeypatch, tmp_path):
    path = str(tmp_path / "two.zip")
    overlays = {"relative": {**cfg.user.setting["relative"], "font_size": 27},
                "speedometer": {**cfg.user.setting["speedometer"], "font_size": 31}}
    export_overlay_package(path, overlays, cfg.default.setting, "1", "2.51.0")
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(share.test_record, picked=["speedometer"]))
    assert share.import_overlay_file(None, path, page)
    assert page.backend.value("speedometer", "font_size") == 31
    assert page.backend.value("relative", "font_size") != 27


def test_import_invalid_value_skipped(share, page, monkeypatch, tmp_path):
    path = write_zip(tmp_path / "bad.zip", manifest(), {
        "overlays/relative.json": {"font_color_same_lap": "not a color", "font_weight": "Huge", "font_size": 22,
                                   "bar_gap": 99999}})
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(share.test_record))
    assert share.import_overlay_file(None, path, page)
    assert page.backend.value("relative", "font_size") == 22
    assert page.backend.value("relative", "bar_gap") == 2000  # out of limits: brought within
    assert page.backend.errorCount == 0
    notice = page.host.notices[-1]
    assert "3 value(s) skipped or corrected:" in notice
    assert "relative: bar_gap 99999 -&gt; 2000 (limit)" in notice
    assert "relative: font_weight (invalid value, skipped: not a choice)" in notice


def test_import_refused_on_locked_preset(share, page, monkeypatch, tmp_path):
    path = export_relative(tmp_path, font_size=27)
    monkeypatch.setitem(cfg.user.filelock, cfg.filename.setting, {"version": "1"})
    monkeypatch.setattr(share, "pick_dialog", FakeDialog(share.test_record))
    assert not share.import_overlay_file(None, path, page)
    assert "locked" in share.test_record["warnings"][-1]
    assert page.backend.pendingCount == 0


def test_import_damaged_or_preset_package_told(share, page, tmp_path):
    record = share.test_record
    damaged = tmp_path / "damaged.zip"
    damaged.write_bytes(b"garbage")
    assert not share.import_overlay_file(None, str(damaged), page)
    settings = tmp_path / "settings2"
    settings.mkdir()
    (settings / "race.json").write_text("{}", encoding="utf-8")
    preset_zip = str(tmp_path / "preset.zip")
    export_preset_package(preset_zip, f"{settings}/", "race.json")
    assert not share.import_overlay_file(None, preset_zip, page)
    assert "preset package" in record["warnings"][-1]
    unknown = write_zip(tmp_path / "unknown.zip", manifest(), {"overlays/future.json": {"a": 1}})
    assert not share.import_overlay_file(None, unknown, page)
    assert "No overlay" in record["warnings"][-1]
    assert page.backend.pendingCount == 0


def test_page_slots_call_host(ui_env):
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend

    calls = []
    host = Host()
    host.export_overlays = calls.append  # type: ignore[attr-defined]
    host.import_overlays = lambda: calls.append("import")  # type: ignore[attr-defined]
    backend = OverlayOptionsBackend(None, host, Control())
    backend.selectOverlay("relative")
    backend.exportOverlays()
    backend.importOverlays()
    assert calls == [["relative"], "import"]
    backend.close()
    backend.deleteLater()
    flush()


def test_overlays_page_slots(ui_env):
    from neopedal.ui.quick.overlay_backend import OverlayBackend

    class FakeControl:
        names = ("relative", "speedometer")
        active_modules: dict = {}

    exported, imported = [], []
    backend = OverlayBackend(None, FakeControl(), lambda name: None, lambda text: True, lambda: None,
                             exported.append, lambda: imported.append(True))
    backend.exportSettings("relative")
    backend.exportSettings("")
    backend.exportSettings("not_an_overlay")
    backend.importSettings()
    assert exported == [["relative"], [], []] and imported == [True]
    backend.close()
    backend.deleteLater()
    flush()


# File drop
def test_file_drop_routes_by_manifest(ui_env, monkeypatch, tmp_path):
    from neopedal.ui import file_drop, overlay_share

    overlay_zip = str(tmp_path / "overlays.zip")
    export_overlay_package(overlay_zip, {"relative": dict(cfg.user.setting["relative"])}, cfg.default.setting, "1", "2.51.0")
    settings = tmp_path / "settings3"
    settings.mkdir()
    (settings / "race.json").write_text("{}", encoding="utf-8")
    preset_zip = str(tmp_path / "preset.zip")
    export_preset_package(preset_zip, f"{settings}/", "race.json")
    assert file_drop.classify(overlay_zip) == file_drop.DROP_OVERLAYS
    assert file_drop.classify(preset_zip) == file_drop.DROP_PACKAGE
    imported = []
    monkeypatch.setattr(overlay_share, "import_overlay_file", lambda window, path: imported.append(path))
    assert file_drop.handle_drop(object(), [overlay_zip]) == []
    assert imported == [overlay_zip]


def test_pick_dialog_selections_and_keep_positions(ui_env):
    from PySide6.QtWidgets import QDialogButtonBox

    from neopedal.ui.overlay_share import OverlayPickDialog

    dialog = OverlayPickDialog(
        None, "Title", "Text", [("relative", "Relative"), ("speedometer", "Speedometer")], ["speedometer"],
        selections=[("All", ["relative", "speedometer"]), ("None", ())], keep_positions=True, ok_text="Import")
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert dialog.checked_names() == ["speedometer"] and ok.isEnabled() and ok.text() == "Import"
    dialog.check_only(["relative", "speedometer"])
    assert dialog.checked_names() == ["relative", "speedometer"]
    dialog.check_only(())
    assert dialog.checked_names() == [] and not ok.isEnabled()
    assert dialog.keep_positions()
    dialog.keep_box.setChecked(False)
    assert not dialog.keep_positions()
    dialog.deleteLater()
    flush()
