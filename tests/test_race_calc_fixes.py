"""Race calculator fixes: live history deleted without losing the newest lap (copy on write), automatic save
failures told once & asked before closing, export feedback & atomic CSV, files dropped on the page, Recent menus"""

import os
from collections import deque

import pytest
from PySide6.QtCore import QMimeData, QUrl

from neopedal.module_info import ConsumptionDataSet, minfo
from neopedal.setting import cfg
from neopedal.ui.quick import stats_sharing
from tests.test_driver_stats_viewer import backend as stats_page  # noqa: F401 (fixtures)
from tests.test_driver_stats_viewer import dialogs, window  # noqa: F401
from tests.test_race_calculator import host, page  # noqa: F401

LAPS = [ConsumptionDataSet(lapNumber=number, isValidLap=1, lapTimeLast=90.0 + number * 0.01, lastLapUsedFuel=3.0)
        for number in range(100, 0, -1)]  # newest lap first


@pytest.fixture
def files(page, monkeypatch):  # noqa: F811
    """Toasts of files written: (text, path)"""
    from neopedal.ui import race_calculator

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(race_calculator.RaceCalculator, "toast_file",
                        lambda self, text, path: shown.append((text, path)))
    return shown


@pytest.fixture
def out(tmp_path):
    """Folder of files written by tests (tmp_path holds the user folders of ui_env)"""
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def race_plan_file(page, host, path) -> str:  # noqa: F811
    host.save_path = str(path)
    page.backend.saveRacePlan()
    return str(path)


def tyre_plan_file(page, host, path) -> str:  # noqa: F811
    host.save_path = str(path)
    page.backend.saveTyrePlan()
    return str(path)


def history_file(path) -> str:
    from neopedal.userfile.consumption_history import save_consumption_history_file

    save_consumption_history_file(LAPS[:3], f"{path.parent.as_posix()}/", path.stem)
    return str(path)


# --- Live history: laps deleted on a new data set, newest lap kept
def test_without_laps_keeps_newest_lap_of_full_history():
    from neopedal.ui.quick.race_backend import without_laps

    history = deque(LAPS, 100)  # full: newest lap on the left
    kept = without_laps(history, [LAPS[50]])
    assert kept is not history and list(history) == LAPS  # data set read by other threads never changed
    assert kept.maxlen == 100 and len(kept) == 99 and kept[0] == LAPS[0]
    assert LAPS[50] not in kept


def test_without_laps_placeholder_and_duplicates():
    from neopedal.ui.quick.race_backend import without_laps

    lap = LAPS[0]
    assert list(without_laps(deque([lap, lap, LAPS[1]], 100), [lap])) == [lap, LAPS[1]]  # each removed once
    empty = without_laps(deque([lap], 100), [lap])
    assert list(empty) == [ConsumptionDataSet()] and empty.maxlen == 100  # stint module reads [0]


def test_live_laps_deleted_by_swap(page, monkeypatch):  # noqa: F811
    from neopedal.api_control import api

    history = deque(LAPS, 100)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", history)
    monkeypatch.setattr(type(api.read.session), "combo_name", lambda self: "Spa - GT3", raising=False)
    backend = page.backend
    backend.setValidOnly(False)
    backend.loadLive()
    version = minfo.history.consumptionDataVersion
    serial = backend.history_serials[backend.history_data.index(LAPS[10])]
    backend.selectLap(serial, 0)
    backend.deleteSelectedLaps()
    swapped = minfo.history.consumptionDataSet
    assert swapped is not history and list(history) == LAPS  # old data set left whole for its readers
    assert swapped.maxlen == 100 and len(swapped) == 99 and swapped[0] == LAPS[0]  # newest lap kept
    assert minfo.history.consumptionDataVersion == version + 1
    assert backend.history_data[0] == LAPS[0] and LAPS[10] not in backend.history_data


def test_live_delete_and_new_lap_never_lost(page, monkeypatch):  # noqa: F811
    """Lap added by stint module while laps are deleted & saved: waits for the lock, added on top of the swap"""
    import threading

    from neopedal.api_control import api
    from neopedal.module.module_stint import prepend
    from neopedal.ui.quick import race_history

    history = deque(LAPS, 100)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", history)
    monkeypatch.setattr(type(api.read.session), "combo_name", lambda self: "Spa - GT3", raising=False)
    new_lap = ConsumptionDataSet(lapNumber=101, isValidLap=1, lapTimeLast=91.5, lastLapUsedFuel=3.0)
    added = threading.Event()
    saved: list[list] = []

    def add_lap():  # stint module side: same locked swap as record_consumption_history
        with minfo.history.consumptionLock:
            minfo.history.consumptionDataSet = prepend(minfo.history.consumptionDataSet, new_lap)
        added.set()

    def write_history(filepath, filename, extension, laps):
        worker = threading.Thread(target=add_lap)
        worker.start()
        assert not added.wait(0.2)  # lap waits while deletion is saved
        saved.append(list(laps))
        return True

    monkeypatch.setattr(race_history, "write_history", write_history)
    backend = page.backend
    backend.setValidOnly(False)
    backend.loadLive()
    backend.selectLap(backend.history_serials[backend.history_data.index(LAPS[0])], 0)
    backend.deleteSelectedLaps()
    assert added.wait(2)
    final = list(minfo.history.consumptionDataSet)
    assert final[0] == new_lap and LAPS[0] not in final and final[1:] == LAPS[1:]
    assert saved == [LAPS[1:]]  # deleted lap never in the saved file


# --- Automatic saves: told once per failure streak, asked before closing
def test_plan_file_failure_told_once(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_files

    backend = page.backend
    real_write = race_files.atomic_write

    def failing(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(race_files, "atomic_write", failing)
    before = len(host.toasts)
    backend.write_plan_file()
    backend.write_plan_file()
    assert len(host.toasts) == before + 1 and "Race Plan overlay: disk full" in host.toasts[-1]
    monkeypatch.setattr(race_files, "atomic_write", real_write)
    backend.write_plan_file()  # saved again: streak over
    assert "plan" not in backend.save_failed
    monkeypatch.setattr(race_files, "atomic_write", failing)
    backend.write_plan_file()
    assert len(host.toasts) == before + 2  # new streak told again


def test_tyre_autosave_failure_asked_before_close(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_tyre_tab

    backend = page.backend
    real_save = race_tyre_tab.save_tyre_strategy_file

    def failing(**kwargs):
        raise OSError("read-only folder")

    monkeypatch.setattr(race_tyre_tab, "save_tyre_strategy_file", failing)
    before = len(host.toasts)
    backend.addTyre()
    backend.autosave_tyres()
    backend.autosave_tyres()
    assert len(host.toasts) == before + 1 and "tyre plan automatically: read-only folder" in host.toasts[-1]
    assert page.confirm_discard() and "could not be saved automatically" in host.asked[-1]  # answered yes
    asked = len(host.asked)
    monkeypatch.setattr(race_tyre_tab, "save_tyre_strategy_file", real_save)
    assert page.confirm_discard() and len(host.asked) == asked  # saved again when closing: nothing asked


def test_pending_autosave_written_before_close(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_tyre_tab

    monkeypatch.setattr(race_tyre_tab, "save_tyre_strategy_file", lambda **kwargs: (_ for _ in ()).throw(OSError("x")))
    page.backend.addTyre()  # autosave waiting
    assert page.backend._autosave_timer.isActive()
    monkeypatch.setattr(page, "confirm", lambda text: False)
    assert not page.confirm_discard()  # written now, failed: page kept open


# --- Exports: told with folder action, CSV written atomically
def test_plan_csv_exported_and_told(page, host, files, out):  # noqa: F811
    target = out / "plan.csv"
    host.save_path = str(target)
    page.backend.exportPlanCsv()
    assert target.read_text(encoding="utf-8").startswith(page.backend.visible_plan()[0][0])
    assert files == [("Exported: <b>plan.csv</b>", str(target))]
    assert os.listdir(out) == ["plan.csv"]  # no temporary file left


def test_plan_csv_failure_keeps_old_file(page, host, files, out, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_files

    target = out / "plan.csv"
    target.write_text("old", encoding="utf-8")

    def half_written(filename, header, rows):
        with open(filename, "w", encoding="utf-8") as file:
            file.write("half")
        raise OSError("disk full")

    monkeypatch.setattr(race_files, "write_plan_csv", half_written)
    host.save_path = str(target)
    page.backend.exportPlanCsv()
    assert target.read_text(encoding="utf-8") == "old" and os.listdir(out) == ["plan.csv"]
    assert "disk full" in host.warnings[-1] and not files


def test_plan_image_saved_and_told(page, host, files, out):  # noqa: F811
    target = out / "plan.png"
    host.save_path = str(target)
    page.backend.savePlanImage()
    assert target.read_bytes()[:4] == b"\x89PNG" and files == [("Exported: <b>plan.png</b>", str(target))]
    assert os.listdir(out) == ["plan.png"]


def test_stats_csv_atomic_and_told(stats_page, out, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QFileDialog

    from neopedal.ui import toast

    target = out / "stats.csv"
    shown = []
    monkeypatch.setattr(toast, "show_toast", lambda widget, text, **kwargs: shown.append((text, kwargs)))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    stats_page.exportCsv(False)
    assert target.read_text(encoding="utf-8-sig").startswith("Vehicle")
    assert shown[-1][0] == "Exported: <b>stats.csv</b>" and callable(shown[-1][1]["action"])
    monkeypatch.setattr(stats_sharing, "csv_text", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    assert not stats_page.write_csv(str(target))  # failed half way: old export left whole
    assert target.read_text(encoding="utf-8-sig").startswith("Vehicle") and os.listdir(out) == ["stats.csv"]


def test_stats_history_csv_told(stats_page, out, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QFileDialog

    from neopedal.ui import toast
    from neopedal.userfile.driver_history import SessionRecord

    target = out / "history.csv"
    shown = []
    stats_page.history = [SessionRecord(time=1.0e9, track=stats_page.selected_stats_key, vehicle="Car")]
    monkeypatch.setattr(toast, "show_toast", lambda widget, text, **kwargs: shown.append(text))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    stats_page.exportHistory("csv")
    assert target.exists() and shown == ["Exported: <b>history.csv</b>"]
    assert os.listdir(out) == ["history.csv"]


# --- Files dropped: on the page or on the main window
def test_race_files_classified():
    from neopedal.ui import file_drop

    assert file_drop.race_file_kind("C:/a/Spa.consumption") == file_drop.DROP_HISTORY
    assert file_drop.race_file_kind("plan.RACE-PLAN") == file_drop.DROP_RACE_PLAN
    assert file_drop.race_file_kind("x.tyre-strategy") == file_drop.DROP_TYRE_PLAN
    assert file_drop.race_file_kind("x.json") == "" and file_drop.classify("x.json") == file_drop.DROP_PRESET
    assert file_drop.classify("plan.race-plan") == file_drop.DROP_RACE
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in ("C:/a.race-plan", "C:/b.txt", "C:/c.ld", "C:/d.json")])
    assert [os.path.basename(path) for path in file_drop.dropped_files(mime)] == ["a.race-plan", "c.ld", "d.json"]


def test_files_dropped_on_page_opened(page, host, out):  # noqa: F811
    backend = page.backend
    plan = race_plan_file(page, host, out / "Le Mans.race-plan")
    tyres = tyre_plan_file(page, host, out / "Wet.tyre-strategy")
    history = history_file(out / "Spa - GT3.consumption")
    backend.newTyrePlan()
    urls = [QUrl.fromLocalFile(path) for path in (plan, tyres, history)]
    assert backend.canDrop(urls) and not backend.canDrop([QUrl.fromLocalFile(str(out / "a.txt"))])
    backend.dropFiles([*urls, QUrl.fromLocalFile(str(out / "notes.txt"))])
    assert backend.tyres.name == "Wet" and not backend.live_source and backend.source_name == "Spa - GT3"
    assert len(backend.history_data) == 3
    assert "Unsupported file: <b>notes.txt</b>" in host.toasts[-1]


def test_file_dropped_on_main_window_opens_race_calculator(page, host, out, monkeypatch):  # noqa: F811
    from neopedal.ui import file_drop, tools_view

    history = history_file(out / "Monza - LMP2.consumption")
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: page if path.endswith("RaceCalculator") else None)
    assert file_drop.handle_drop(None, [history]) == []
    assert page.backend.source_name == "Monza - LMP2"


# --- Recent menus
def test_recent_files_kept_newest_first(page, host, out):  # noqa: F811
    from neopedal.ui.quick.race_backend import MAX_RECENT, RaceBackend

    backend = page.backend
    paths = [race_plan_file(page, host, out / f"plan {index}.race-plan") for index in range(MAX_RECENT + 1)]
    host.open_path = paths[3]
    backend.openRacePlan()
    recent = [item["path"] for item in backend.recentFiles["race_plan"]]
    assert len(recent) == MAX_RECENT and os.path.basename(recent[0]) == "plan 3.race-plan"
    assert os.path.basename(recent[1]) == f"plan {MAX_RECENT}.race-plan" and paths[0] not in recent
    assert cfg.user.config["fuel_calculator"]["recent_race_plan_file_names"].split("|") == recent
    os.remove(recent[1])  # deleted meanwhile: left out
    other = RaceBackend(page, page)
    assert [item["path"] for item in other.recentFiles["race_plan"]] == [recent[0], *recent[2:]]
    other.release()


def test_recent_file_opened_or_dropped_when_missing(page, host, out):  # noqa: F811
    backend = page.backend
    tyres = tyre_plan_file(page, host, out / "Dry.tyre-strategy")
    history = history_file(out / "Spa.consumption")
    backend.loadLive()
    host.open_path = history
    backend.loadFile()
    assert [item["name"] for item in backend.recentFiles["history"]] == ["Spa.consumption"]
    backend.newTyrePlan()
    backend.openRecent("tyre_plan", backend.recentFiles["tyre_plan"][0]["path"])
    assert backend.tyres.name == "Dry"
    os.remove(tyres)
    backend.refreshRecent()
    assert backend.recentFiles["tyre_plan"] == []
    os.remove(history)
    backend.openRecent("history", backend.recentFiles["history"][0]["path"])
    assert backend.recentFiles["history"] == [] and "File not found" in host.warnings[-1]


def test_auto_loaded_combo_plan_not_recent(page, host, out):  # noqa: F811
    backend = page.backend
    plan = race_plan_file(page, host, out / "combo.race-plan")
    backend.keep_recent("race_plan", [])
    assert backend.load_race_plan(plan, quiet=True)
    assert backend.recentFiles["race_plan"] == []


def menu_texts(menu) -> list[str]:
    from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject

    items = [QMetaObject.invokeMethod(menu, "itemAt", Q_RETURN_ARG("QQuickItem*"), Q_ARG(int, index))
             for index in range(menu.property("count"))]
    return [item.property("text") or "" for item in items]


def test_qml_page_loads_with_recent_menus(page, host, out):  # noqa: F811
    from PySide6.QtCore import QCoreApplication, QObject

    view = page.ensure_view()
    menu = view.rootObject().findChild(QObject, "loadFileMenu")
    assert menu_texts(menu) == ["Load File...", "", "No recent files"]
    host.open_path = history_file(out / "Spa.consumption")
    page.backend.loadFile()  # first of Recent menus, after the Load File action
    page.backend.setTab(1)
    QCoreApplication.processEvents()
    assert not view.errors(), [error.toString() for error in view.errors()]
    assert menu_texts(menu) == ["Load File...", "", "Spa.consumption"]


@pytest.mark.parametrize("language", ["English", "Français"])
def test_header_fits_page_width(ui_env, host, monkeypatch, language):  # noqa: F811
    """Header row never wider than the page: labels, then switch labels & logo dropped as room runs out (last level:
    narrowest header, fits page minimum width with real fonts, not offscreen font boxes)"""
    from PySide6.QtCore import QCoreApplication, QEvent, QObject

    from neopedal import i18n
    from neopedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    i18n.set_language(language)
    dialog = race_calculator.RaceCalculator(None)
    try:
        dialog.move(-6000, -6000)
        dialog.show()
        dialog.backend.setGameData(True)
        root = dialog.ensure_view().rootObject()
        header = root.findChild(QObject, "headerRow")
        levels = []
        for width in (520, 650, 760, 900, 1100, 1900, 760):
            dialog.resize(width, 700)
            for _ in range(5):
                QCoreApplication.processEvents()
            levels.append(root.property("headerLevel"))
            fits = header.property("implicitWidth") <= root.property("width")
            assert fits or levels[-1] == 2, (width, levels[-1])
        assert levels[0] == 2 and levels[5] == 0 and levels[2] == levels[6]  # same level back at same width
        assert levels[:6] == sorted(levels[:6], reverse=True)
    finally:
        i18n.set_language("English")
        dialog.set_unmodified()
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
