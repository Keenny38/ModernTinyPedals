"""Option finder & preset comparison tests (headless), setup wizard tests: test_setup_wizard.py"""

import time

from PySide6.QtCore import QCoreApplication

from neopedal.setting import cfg


def test_option_finder(ui_env):
    from neopedal.i18n import set_language
    from neopedal.ui import option_finder

    entries = option_finder.build_index()
    assert len(entries) > 600
    # Modern design: only options it reads are found (no per cell colors)
    assert not option_finder.search_options(entries, "speedometer font color")
    assert option_finder.search_options(entries, "relative column time gap")
    cfg.user.setting["speedometer"]["enable_classic_layout"] = True  # classic layout: every option
    entries = option_finder.build_index()
    results = option_finder.search_options(entries, "speedometer font color")
    assert results and all(entry.section == "speedometer" for entry in results)
    set_language("Français")
    try:
        entries = option_finder.build_index()
        french = option_finder.search_options(entries, "couleur texte vitesse")
        assert any(entry.key == "font_color_speed" for entry in french)
    finally:
        set_language("English")
    dialog = option_finder.open_option(None, results[0])  # Overlay Options page, scrolled to option
    assert dialog is not None and dialog.backend.overlay == "speedometer" and dialog.backend.highlightKey
    dialog.close()
    finder = option_finder.OptionFinder(None)
    finder.set_search("opacity")
    assert finder.backend.model.rowCount() > 50
    finder.close()


def test_preset_diff_and_copy():
    from neopedal.userfile.preset_compare import copy_values, diff_presets

    preset_a = {"speed": {"enable": True, "position_x": 1, "font_size": 15}, "gear": {"enable": False}}
    preset_b = {"speed": {"enable": True, "position_x": 9, "font_size": 20}, "gear": {"enable": True}}
    keys = {(diff.section, diff.key) for diff in diff_presets(preset_a, preset_b)}
    assert keys == {("speed", "position_x"), ("speed", "font_size"), ("gear", "enable")}
    keys = {(diff.section, diff.key) for diff in diff_presets(preset_a, preset_b, ignore_position=True)}
    assert ("speed", "position_x") not in keys
    assert copy_values(preset_a, preset_b, [("speed", "font_size"), ("missing", "key")]) == 1
    assert preset_a["speed"]["font_size"] == 20


def test_preset_compare_dialog(ui_env, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.ui import preset_compare

    settings = cfg.path.settings
    other = dict(cfg.user.setting)
    other["speedometer"] = {**cfg.user.setting["speedometer"], "font_size": 99}
    import json

    with open(f"{settings}other.json", "w", encoding="utf-8") as file:
        json.dump(other, file)
    monkeypatch.setattr(type(cfg), "is_loaded", lambda self, name: False)
    dialog = preset_compare.PresetCompare(None, preset_a="default.json", preset_b="other.json")
    try:
        assert dialog.is_loading() and dialog.table.rowCount() == 0  # presets read in background
        deadline = time.monotonic() + 5
        while dialog.is_loading() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        rows = [dialog.table.item(row, 0).data(0x0100) for row in range(dialog.table.rowCount())]
        assert ("speedometer", "font_size") in rows
        row = rows.index(("speedometer", "font_size"))
        dialog.edit_filter.setText("zzzz")
        assert not dialog.table.isRowHidden(row)  # applied once typing pauses
        dialog.filter_now()
        assert dialog.table.isRowHidden(row)
        dialog.edit_filter.setText("speedometer FONT")
        dialog.filter_now()
        assert not dialog.table.isRowHidden(row)
        dialog.table.selectRow(row)
        dialog.copy_selected(to_a=True)
        assert dialog.presets["default.json"]["speedometer"]["font_size"] == 99
        assert dialog.table.rowCount() == len(rows) - 1
        dialog.saving()
        with open(f"{settings}default.json", encoding="utf-8") as file:
            assert json.load(file)["speedometer"]["font_size"] == 99
    finally:
        dialog.set_unmodified()
        dialog.close()
