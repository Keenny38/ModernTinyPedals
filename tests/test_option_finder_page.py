"""Find Option page: ranked results (accents & case ignored), values & changed marks, group chips, changed only,
switch on / off in place, reset, open settings page of option, Qt Quick page"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tinypedal.const_file import ConfigType
from tinypedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def finder(ui_env, monkeypatch):
    from tinypedal.ui.quick import finder_backend

    opened = []
    applied = []
    monkeypatch.setattr(finder_backend, "run_after_saving", lambda callback: applied.append(callback))
    backend = finder_backend.FinderBackend(None, opened.append)
    backend.opened, backend.applied = opened, applied
    yield backend
    backend.deleteLater()
    flush()


def keys(finder) -> list[str]:
    return [row["key"] for row in finder.model.rows]


def test_ranked_search_option_name_first(ui_env):
    from tinypedal.ui import option_finder

    entries = option_finder.build_index()
    results = option_finder.search_options(entries, "opacity")
    assert results[0].key == "opacity"  # exact option name first
    accents = option_finder.search_options(entries, "OPACITY")
    assert [entry.key for entry in accents] == [entry.key for entry in results]
    assert len(option_finder.search_options(entries, "opacity", limit=0)) >= len(results)
    assert option_finder.search_options(entries, "  ") == []


def test_french_search_ignores_accents(ui_env):
    from tinypedal.i18n import set_language
    from tinypedal.ui import option_finder

    set_language("Français")
    try:
        entries = option_finder.build_index()
        with_accent = option_finder.search_options(entries, "opacité")
        without = option_finder.search_options(entries, "opacite")
        assert with_accent and [entry.key for entry in with_accent] == [entry.key for entry in without]
    finally:
        set_language("English")


def test_rows_show_values_and_highlight(finder):
    finder.setSearch("minimize tray")
    row = finder.model.rows[0]
    assert row["option"] == "minimize_to_tray" and row["kind"] == "bool" and row["group"] == ConfigType.CONFIG
    assert "<b>" in row["label"] and row["value"] in ("On", "Off") and row["sectionLabel"]
    finder.setSearch("background color locked")
    row = finder.model.rows[0]
    assert row["kind"] == "color" and row["color"] == cfg.user.config["notification"]["background_color_locked_preset"]


def test_group_chips_and_counts(finder):
    finder.setSearch("opacity")
    counts = {chip["key"]: chip["count"] for chip in finder.groups}
    assert counts[""] == counts[ConfigType.WIDGET] + counts[ConfigType.MODULE] + counts[ConfigType.SETTING] + counts[
        ConfigType.CONFIG]
    finder.setGroup(ConfigType.WIDGET)
    assert finder.foundCount == counts[ConfigType.WIDGET]
    assert all(row["group"] == ConfigType.WIDGET for row in finder.model.rows)
    finder.setGroup("nonsense")  # ignored
    assert finder.group == ConfigType.WIDGET


def test_changed_only_without_search(finder):
    assert keys(finder) == [] and not finder.searching
    finder.setChangedOnly(True)
    assert keys(finder) == []  # defaults everywhere
    cfg.user.setting["speedometer"]["opacity"] = 0.5
    cfg.user.config["application"]["snap_gap"] = 3
    finder.refresh_values()
    assert set(keys(finder)) == {"widget/speedometer/opacity", "config/application/snap_gap"}
    assert all(row["modified"] for row in finder.model.rows)


def test_toggle_and_reset_saved_and_applied(finder, ui_env):
    finder.setSearch("minimize tray")
    key = finder.model.rows[0]["key"]
    before = cfg.user.config["application"]["minimize_to_tray"]
    finder.toggle(key)
    assert cfg.user.config["application"]["minimize_to_tray"] is (not before)
    assert ConfigType.CONFIG in ui_env and finder.applied  # saved, app reloaded once saved
    assert finder.model.rows[0]["modified"]
    finder.resetOption(key)
    assert cfg.user.config["application"]["minimize_to_tray"] is before
    finder.setSearch("minimize tray opacity")
    finder.toggle("config/application/snap_gap")  # not on / off: ignored
    assert cfg.user.config["application"]["snap_gap"] == cfg.default.config["application"]["snap_gap"]


def test_toggle_overlay_enable_uses_control(finder, monkeypatch):
    from tinypedal.ui.quick import finder_backend

    toggled = []
    monkeypatch.setattr(type(finder_backend.wctrl), "toggle", lambda self, name: toggled.append(name))
    finder.setSearch("speedometer enable")
    key = next(row["key"] for row in finder.model.rows if row["option"] == "enable")
    finder.toggle(key)
    assert toggled == ["speedometer"]


def test_open_option_and_copy_key(finder):
    from PySide6.QtGui import QGuiApplication

    finder.setSearch("snap gap")
    key = finder.model.rows[0]["key"]
    finder.openOption(key)
    assert finder.opened and finder.opened[0].key == "snap_gap"
    finder.copyKey(key)
    assert QGuiApplication.clipboard().text() == "snap_gap"
    finder.openOption("unknown/key")
    assert len(finder.opened) == 1


def test_global_option_opens_settings_page(ui_env, monkeypatch):
    from tinypedal.ui import app_settings, option_finder

    opened = []
    monkeypatch.setattr(app_settings, "open_app_settings", lambda *args: opened.append(args))
    entry = next(entry for entry in option_finder.build_index() if entry.key == "snap_gap")
    option_finder.open_option(None, entry)
    assert opened == [(None, "application", "snap_gap")]


def test_highlight_keeps_text():
    from tinypedal.ui.quick.finder_backend import highlight

    assert highlight("Font Color", ("color",)) == "Font <b>Color</b>"
    assert highlight("Opacité", ("opacite",)) == "<b>Opacité</b>"
    assert highlight("A<B", ()) == "A&lt;B"


def item_texts(view) -> set[str]:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def test_qml_page(ui_env):
    from tinypedal.ui.option_finder import OptionFinder

    page = OptionFinder(None)
    try:
        assert not page.view.errors(), [error.toString() for error in page.view.errors()]
        page.show()
        page.set_search("snap gap")
        for _ in range(20):
            QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Changed only" in texts and "Application" in texts and "Snap Gap" in page.backend.model.rows[0]["label"].replace(
            "<b>", "").replace("</b>", "")
    finally:
        page.close()
        flush()
