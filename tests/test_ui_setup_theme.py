"""Setup wizard & theme editor tests (headless)"""

import json

from tinypedal.setting import cfg
from tinypedal.widget import _style


def test_setup_choices_apply(ui_env, monkeypatch):
    from tinypedal.ui import setup_wizard

    reloads = []
    monkeypatch.setattr(setup_wizard.loader, "reload", lambda reload_preset=False: reloads.append(reload_preset))
    def create_preset(self, filename):
        with open(f"{cfg.path.settings}{filename}", "w", encoding="utf-8") as file:
            file.write("{}")

    monkeypatch.setattr(type(cfg), "create", create_preset)
    cfg.user.setting["relative"]["enable"] = False
    choices = setup_wizard.SetupChoices(
        language="Français", api_name="", window_theme="Light", overlay_theme="High Contrast",
        modern_font=False, preset="", new_preset="my overlay", widgets=("relative",),
    )
    setup_wizard.run_setup(choices)
    assert cfg.application["language"] == "Français"
    assert cfg.application["window_color_theme"] == "Light"
    assert cfg.application["show_setup_wizard_at_startup"] is False
    assert cfg.user.config["overlay_style"]["overlay_theme"] == "High Contrast"
    assert cfg.user.setting["relative"]["enable"] is True
    assert reloads == [True, False]  # load new preset, then restart with widgets
    from tinypedal.i18n import set_language

    set_language("English")


def test_setup_wizard_dialog(ui_env):
    from tinypedal.ui.setup_wizard import SetupWizard

    wizard = SetupWizard(None)
    choices = wizard.choices()
    assert choices.language in ("English", "Français")
    assert "relative" in choices.widgets
    wizard.page_preset.preset.setCurrentIndex(0)  # create new preset
    wizard.page_preset.new_name.setText("default")  # existing preset name refused
    assert not wizard.page_preset.isComplete()
    wizard.page_preset.new_name.setText("new one")
    assert wizard.page_preset.isComplete()
    wizard.deleteLater()


def test_custom_theme_palette(tmp_path):
    from tinypedal.userfile.overlay_theme import load_custom_themes, save_custom_themes

    themes = {"Mine": {"base": "Colorblind Safe", "colors": {"ff2200": "123456", "BAD": "000000"}}}
    assert save_custom_themes(f"{tmp_path}/", themes)
    loaded = load_custom_themes(f"{tmp_path}/", _style.BUILTIN_THEMES)
    assert loaded == {"Mine": {"base": "Colorblind Safe", "colors": {"FF2200": "123456"}}}
    _style.set_custom_themes(loaded)
    try:
        assert "Mine" in _style.overlay_theme_names()
        palette = _style.theme_palette("Mine")
        assert palette["FF2200"] == "123456"  # custom color
        assert palette["009900"] == _style.COLORBLIND_PALETTE["009900"]  # from base
        assert _style.theme_palette("Deleted theme") is _style.MODERN_PALETTE
    finally:
        _style.set_custom_themes({})


def test_invalid_theme_file(tmp_path):
    from tinypedal.userfile.overlay_theme import FILENAME, load_custom_themes

    (tmp_path / FILENAME).write_text("{not json", encoding="utf-8")
    assert load_custom_themes(f"{tmp_path}/", _style.BUILTIN_THEMES) == {}
    (tmp_path / FILENAME).write_text(json.dumps({"Classic": {"colors": {}}}), encoding="utf-8")
    assert load_custom_themes(f"{tmp_path}/", _style.BUILTIN_THEMES) == {}  # built-in name refused


def test_widget_theme_override():
    default = {"font_color": "#FF2200", "widget_theme": "Global"}
    style = {"overlay_theme": "Modern Dark", "enable_modern_font": False, "minimum_bar_gap": 0}
    assert _style.modern_overrides(default, default, style)["font_color"] == "#FF4D4F"
    classic = {**default, "widget_theme": "Classic"}
    assert "font_color" not in _style.modern_overrides(classic, classic, style)
    colorblind = {**default, "widget_theme": "Colorblind Safe"}
    assert _style.modern_overrides(colorblind, colorblind, style)["font_color"] == "#D55E00"


def test_theme_editor(ui_env, monkeypatch):
    from tinypedal.ui import theme_editor

    monkeypatch.setattr(theme_editor.loader, "reload", lambda reload_preset=False: None)
    monkeypatch.setattr(theme_editor.QInputDialog, "getText", staticmethod(lambda *args: ("Night", True)))
    editor = theme_editor.ThemeEditor(None)
    try:
        editor.new_theme()
        assert editor.theme_list.currentText() == "Night"
        row = editor.classic_colors.index("FF2200")
        editor.set_theme_color(row, "00FF00")
        assert editor.themes["Night"]["colors"]["FF2200"] == "00FF00"
        assert editor.label_preview.pixmap() is not None and not editor.label_preview.pixmap().isNull()
        editor.undo()
        assert "FF2200" not in editor.themes["Night"]["colors"]
        editor.redo()
        assert editor.save_themes()
        assert "Night" in _style.overlay_theme_names()
    finally:
        _style.set_custom_themes({})
        editor.set_unmodified()
        editor.close()


def test_option_finder(ui_env):
    from tinypedal.i18n import set_language
    from tinypedal.ui import option_finder

    entries = option_finder.build_index()
    assert len(entries) > 1500
    results = option_finder.search_options(entries, "speedometer font color")
    assert results and all(entry.section == "speedometer" for entry in results)
    set_language("Français")
    try:
        entries = option_finder.build_index()
        french = option_finder.search_options(entries, "couleur texte vitesse")
        assert any(entry.key == "font_color_speed" for entry in french)
    finally:
        set_language("English")
    dialog = option_finder.open_option(None, results[0])
    assert dialog.edit_search.text() == results[0].key
    visible = [key for key, editor in dialog.option_edit.items() if not editor.isHidden()]
    assert results[0].key in visible and len(visible) < len(dialog.option_edit)
    dialog.close()
    finder = option_finder.OptionFinder(None)
    finder.edit_search.setText("opacity")
    assert finder.list_results.count() > 50
    finder.close()


def test_preset_diff_and_copy():
    from tinypedal.userfile.preset_compare import copy_values, diff_presets

    preset_a = {"speed": {"enable": True, "position_x": 1, "font_size": 15}, "gear": {"enable": False}}
    preset_b = {"speed": {"enable": True, "position_x": 9, "font_size": 20}, "gear": {"enable": True}}
    keys = {(diff.section, diff.key) for diff in diff_presets(preset_a, preset_b)}
    assert keys == {("speed", "position_x"), ("speed", "font_size"), ("gear", "enable")}
    keys = {(diff.section, diff.key) for diff in diff_presets(preset_a, preset_b, ignore_position=True)}
    assert ("speed", "position_x") not in keys
    assert copy_values(preset_a, preset_b, [("speed", "font_size"), ("missing", "key")]) == 1
    assert preset_a["speed"]["font_size"] == 20


def test_preset_compare_dialog(ui_env, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui import preset_compare

    settings = cfg.path.settings
    other = dict(cfg.user.setting)
    other["speedometer"] = {**cfg.user.setting["speedometer"], "font_size": 99}
    import json

    with open(f"{settings}other.json", "w", encoding="utf-8") as file:
        json.dump(other, file)
    monkeypatch.setattr(type(cfg), "is_loaded", lambda self, name: False)
    dialog = preset_compare.PresetCompare(None, preset_a="default.json", preset_b="other.json")
    try:
        rows = [dialog.table.item(row, 0).data(0x0100) for row in range(dialog.table.rowCount())]
        assert ("speedometer", "font_size") in rows
        row = rows.index(("speedometer", "font_size"))
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


def test_theme_export_import(tmp_path):
    import pytest

    from tinypedal.userfile.overlay_theme import export_theme, import_themes, unique_theme_name

    builtin = ("Modern Dark", "Modern Light")
    filename = str(tmp_path / "mine.json")
    theme = {"base": "Modern Dark", "colors": {"FF2200": "CC0000"}}
    assert export_theme(filename, "Mine", theme)
    assert import_themes(filename, builtin) == {"Mine": theme}
    (tmp_path / "bad.json").write_text('{"x": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        import_themes(str(tmp_path / "bad.json"), builtin)
    assert unique_theme_name("Mine", {"Mine", "Mine (2)"}) == "Mine (3)"
