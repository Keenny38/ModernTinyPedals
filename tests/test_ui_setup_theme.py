"""Option finder & preset comparison tests (headless), setup wizard tests: test_setup_wizard.py"""

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

