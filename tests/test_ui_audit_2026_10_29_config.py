"""UI/UX audit 2026-10-29, configuration lot: settings of the loaded preset in the Settings page (units, API options,
global font override B8, pace notes, module options in section mode), routes from menus / Modules / option search,
setup wizard (Streaming step, Finish shows the Overlays page & tests on screen), Ctrl+F page searches, vocabulary"""

import os
import re
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, qInstallMessageHandler

from neopedal import app_signal
from neopedal.setting import cfg
from tests import test_settings_page
from tests.test_settings_page import Host, flush

window = test_settings_page.window  # fixture: main window, reloads & restarts not run


class PresetHost(Host):
    """Settings host recording preset saves & toasts"""

    def __init__(self):
        super().__init__()
        self.preset_applied: list[tuple] = []
        self.toasts: list[str] = []
        self.sounds: list[dict] = []
        self.file = ""

    def applied_preset(self, sections, config_sections, font_sections, undo):
        self.preset_applied.append((sections, config_sections, font_sections, undo))

    def toast(self, text):
        self.toasts.append(text)

    def pick_file(self, filename, filter_name):
        return self.file

    def test_sound(self, values):
        self.sounds.append(values)
        return "played"


@pytest.fixture
def settings(ui_env):
    from neopedal.ui.quick.settings_backend import SettingsBackend

    host = PresetHost()
    backend = SettingsBackend(None, host)
    backend.host = host
    yield backend
    backend.deleteLater()
    flush()


def rows(backend) -> dict:
    return {row["key"]: row for row in backend.model.rows}


# Categories of the loaded preset
def test_preset_categories_listed_after_config_with_heading(settings):
    entries = settings.categories
    keys = [entry["key"] for entry in entries]
    assert keys[-4:] == ["units", "font", "pace_notes_playback", "api"]
    headings = [entry["heading"] for entry in entries if entry["heading"]]
    assert headings == ["In the loaded preset"] and entries[-4]["heading"] and entries[-4]["preset"]
    assert not any(entry["preset"] for entry in entries[:-4])


def test_units_edited_pending_then_saved_in_preset(settings, ui_env):
    settings.selectCategory("units")
    assert settings.categoryInfo["preset"] and settings.sectionState["preset"] == "default"
    shown = rows(settings)
    assert "preset:units/speed_unit" in shown and shown["preset:units/speed_unit"]["kind"] == "choice"
    choices = shown["preset:units/speed_unit"]["choices"]
    settings.setChoice("preset:units/speed_unit", choices.index("mph"))
    assert cfg.user.setting["units"]["speed_unit"] == "KPH" and settings.pendingCount == 1  # pending
    ui_env.clear()
    assert settings.apply()
    assert cfg.user.setting["units"]["speed_unit"] == "MPH" and "setting" in ui_env  # preset file saved
    assert settings.host.preset_applied[-1][0] == {"units"} and not settings.host.applied_sections
    settings.undo()  # undone past Apply: previous value pending again
    assert settings.pendingCount == 1 and rows(settings)["preset:units/speed_unit"]["text"] == "KPH"


def test_api_category_is_selected_api_section(settings):
    settings.selectCategory("api")
    keys = list(rows(settings))
    assert keys and all(key.startswith(f"preset:{cfg.api_key}/") for key in keys)


def test_preset_loaded_since_edit_asked_before_saving(settings, monkeypatch):
    settings.selectCategory("units")
    settings.setChoice("preset:units/speed_unit", rows(settings)["preset:units/speed_unit"]["choices"].index("mph"))
    monkeypatch.setattr(cfg.filename, "setting", "other.json")
    settings.host.answer = False
    assert not settings.apply() and "other" in settings.host.questions[-1]
    assert settings.pendingCount == 1 and cfg.user.setting["units"]["speed_unit"] == "KPH"
    settings.host.answer = True
    assert settings.apply() and cfg.user.setting["units"]["speed_unit"] == "MPH"


# B8: global font override
def test_font_override_bounded_previewed_applied_once_and_undone(settings):
    cfg.user.setting["speedometer"]["font_size"] = 20
    settings.selectCategory("font")
    shown = rows(settings)
    assert set(shown) >= {"font:font_name", "font:font_size_addend", "font:font_weight",
                          "font:enable_auto_font_offset", "font:font_offset_vertical_addend"}
    assert shown["font:font_size_addend"]["minimum"] == -20 and shown["font:font_size_addend"]["maximum"] == 20
    settings.setNumber("font:font_size_addend", 999)
    assert settings.errorCount == 1 and not settings.apply()  # bounded: never +999
    settings.setNumber("font:font_size_addend", 2)
    preview = settings.fontPreview
    assert not preview["neutral"] and preview["sections"] > 0 and preview["options"] > 0
    assert float(preview["sizeAfter"][1]) == float(preview["sizeNow"][1]) + 2
    assert settings.apply()
    assert cfg.user.setting["speedometer"]["font_size"] == 22
    assert rows(settings)["font:font_size_addend"]["number"] == 0 and settings.fontPreview["neutral"]
    _, _, count, undo = settings.host.preset_applied[-1]
    assert count > 0 and callable(undo)
    settings.undo()  # applied once: Ctrl+Z never makes the addend pending again (would add it twice)
    assert "font:font_size_addend" not in settings._pending
    assert settings.apply() and cfg.user.setting["speedometer"]["font_size"] == 22
    assert undo() and cfg.user.setting["speedometer"]["font_size"] == 20  # toast Undo


def test_font_name_no_change_first_and_translated_choices(settings):
    settings.selectCategory("font")
    shown = rows(settings)
    assert shown["font:font_name"]["choices"][0] == "no change" and shown["font:font_name"]["choiceIndex"] == 0
    assert shown["font:enable_auto_font_offset"]["choices"] == ["no change", "enable", "disable"]
    settings.setChoice("font:enable_auto_font_offset", 2)
    assert settings.apply()
    assert all(not options["enable_auto_font_offset"] for options in cfg.user.setting.values()
               if isinstance(options, dict) and "enable_auto_font_offset" in options)


def test_font_undo_refused_once_another_preset_loaded(settings, monkeypatch):
    settings.selectCategory("font")
    settings.setNumber("font:font_size_addend", 1)
    assert settings.apply()
    undo = settings.host.preset_applied[-1][3]
    monkeypatch.setattr(cfg.filename, "setting", "other.json")
    assert not undo()


# Pace notes
def test_pace_notes_category_switch_at_once_and_test_sound(settings, ui_env):
    settings.selectCategory("pace_notes_playback")
    shown = rows(settings)
    assert "preset:pace_notes_playback/enable" not in shown  # header switch, not a pending row
    assert shown["preset:pace_notes_playback/pace_notes_file_name"]["kind"] == "file"
    assert shown["preset:pace_notes_playback/pace_notes_sound_path"]["kind"] == "path"
    assert shown["preset:pace_notes_playback/pace_notes_sound_volume"]["maximum"] == 100
    assert settings.sectionState["switchable"] and not settings.sectionState["enabled"]
    refreshed = []
    app_signal.refresh.connect(refreshed.append)
    try:
        settings.setSectionEnabled(True)
    finally:
        app_signal.refresh.disconnect(refreshed.append)
    assert cfg.user.setting["pace_notes_playback"]["enable"] is True and refreshed and settings.pendingCount == 0
    assert settings.sectionState["enabled"]
    settings.setNumber("preset:pace_notes_playback/pace_notes_sound_volume", 80)
    settings.testSound()  # pending volume played, not saved yet
    assert settings.host.sounds[-1]["pace_notes_sound_volume"] == 80 and settings.host.toasts[-1] == "played"


def test_pace_notes_file_checked_and_picked(settings, tmp_path):
    settings.selectCategory("pace_notes_playback")
    key = "preset:pace_notes_playback/pace_notes_file_name"
    settings.setText(key, str(tmp_path / "missing.tppn"))
    assert rows(settings)[key]["error"] == "File not found"
    notes = tmp_path / "track.tppn"
    notes.write_text("", encoding="utf-8")
    settings.host.file = str(notes)
    settings.browse(key)
    assert rows(settings)[key]["error"] == "" and settings._pending[key] == str(notes)


def test_pace_notes_sound_folder_never_created_and_root_default_kept(settings, tmp_path):
    settings.selectCategory("pace_notes_playback")
    key = "preset:pace_notes_playback/pace_notes_sound_path"
    folder = tmp_path / "sounds"
    settings.setText(key, str(folder))
    assert settings.apply() and not folder.exists()
    settings.resetOption(key)  # default "/" (root) is a valid sound folder here
    assert settings.apply() and cfg.user.setting["pace_notes_playback"]["pace_notes_sound_path"] == "/"


def test_test_sound_file_of_sound_folder(tmp_path):
    from neopedal.ui.pace_notes_view import test_sound_file

    (tmp_path / "b.wav").write_bytes(b"")
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "c.WAV").write_bytes(b"")
    folder = f"{tmp_path.as_posix()}/"
    assert os.path.basename(test_sound_file(folder, "wav")) == "b.wav"
    assert os.path.basename(test_sound_file(folder, ".mp3")) == "a.mp3"
    assert test_sound_file(folder, "aac") == ""
    assert test_sound_file(f"{(tmp_path / 'none').as_posix()}/", "wav") == ""


# Module options: section mode
def test_module_section_opened_as_extra_category_with_switch(settings, monkeypatch):
    from neopedal.module_control import mctrl

    toggled = []
    monkeypatch.setattr(type(mctrl), "toggle", lambda self, name, wait=None: toggled.append(name))
    assert settings.open_section("module_delta")
    assert settings.category == "module_delta" and settings.categories[-1]["key"] == "module_delta"
    shown = rows(settings)
    assert shown and all(key.startswith("preset:module_delta/") for key in shown)
    assert "preset:module_delta/enable" not in shown
    assert settings.sectionState["switchable"]
    settings.setSectionEnabled(not cfg.user.setting["module_delta"]["enable"])
    assert toggled == ["module_delta"]  # started / stopped & saved by module control, at once
    settings.open_section("module_fuel")
    assert [entry["key"] for entry in settings.categories][-2:] == ["module_delta", "module_fuel"]  # kept
    assert not settings.open_section("speedometer") and not settings.open_section("preset")  # overlays: own page


def test_module_category_named_in_app_language(settings):
    from neopedal import i18n
    from neopedal.ui.quick.module_backend import module_title

    settings.open_section("module_delta")
    english = settings.categoryInfo["label"]
    i18n.set_language("Français")
    try:
        assert settings.categoryInfo["label"] == module_title("module_delta")
        assert settings.categories[-1]["label"] == module_title("module_delta")
        assert settings.categoryInfo["description"].startswith("Temps au tour")
    finally:
        i18n.set_language("English")
    assert settings.categoryInfo["label"] == english


def test_module_option_saved_and_module_restarted(settings):
    settings.open_section("module_delta")
    key = "preset:module_delta/update_interval"
    settings.setNumber(key, rows(settings)[key]["number"] + 5)
    assert settings.apply()
    assert settings.host.preset_applied[-1][0] == {"module_delta"}


def test_focus_option_of_preset_section(settings):
    flashed = []
    settings.highlightChanged.connect(lambda: flashed.append(settings.highlightKey))
    settings.focus_option("units", "fuel_unit")
    assert settings.category == "units" and flashed[-1] == "preset:units/fuel_unit"
    settings.focus_option(cfg.api_key, "url_port")
    assert settings.category == "api" and flashed[-1] == f"preset:{cfg.api_key}/url_port"
    settings.focus_option("module_fuel", "update_interval")  # module: opened as extra category
    assert settings.category == "module_fuel" and flashed[-1] == "preset:module_fuel/update_interval"


def test_single_category_page_no_search(ui_env):
    from neopedal.ui.quick.settings_backend import SettingsBackend

    backend = SettingsBackend(None, PresetHost(), only="pace_notes_playback")
    try:
        assert backend.singleCategory and [entry["key"] for entry in backend.categories] == ["pace_notes_playback"]
        backend.setSearch("volume")
        assert not backend.searching and backend.category == "pace_notes_playback"
        assert not backend.open_section("module_delta")
    finally:
        backend.deleteLater()


def test_applied_preset_reloads_only_what_reads_it(ui_env, monkeypatch):
    """Units & fonts: overlays reloaded; API: API restarted; module: that module; nothing when the whole app
    reloads for config.json settings saved at the same time"""
    from neopedal.ui import menu, settings_host
    from neopedal.ui.settings_host import SettingsHostMixin

    calls = []
    monkeypatch.setattr(settings_host, "run_after_saving", lambda callback: calls.append(callback))
    monkeypatch.setattr(settings_host, "show_toast", lambda *args, **kwargs: calls.append("toast"))
    host = SettingsHostMixin()
    host.applied_preset({"units"}, set(), 0, None)
    assert menu.menu_reload_only in calls
    calls.clear()
    host.applied_preset({cfg.api_key}, set(), 0, None)
    assert calls == ["toast", menu.menu_restart_api]
    calls.clear()
    host.applied_preset({"units"}, {"application"}, 0, None)
    assert calls == []  # whole app reloaded by applied(), no second toast
    calls.clear()
    host.applied_preset({"module_delta"}, set(), 0, None)
    assert next(call.args for call in calls if hasattr(call, "args")) == ("module_delta",)


# Routes: menus, Modules page, option search, command palette
def test_menu_links_open_settings_categories(window):
    from neopedal.ui.menu import open_preset_config

    page = open_preset_config(window, "units")
    assert page.backend.category == "units"
    assert open_preset_config(window, "font") is page and page.backend.category == "font"
    assert open_preset_config(window, "api") is page and page.backend.category == "api"
    assert not page.view.errors()


def test_modules_gear_and_option_search_open_settings(window):
    from neopedal.module_control import mctrl
    from neopedal.ui.app_settings import AppSettings
    from neopedal.ui.module_view import ModuleList
    from neopedal.ui.option_finder import OptionEntry, open_option

    modules = ModuleList(window, mctrl)
    try:
        modules.open_config("module_delta")  # gear of a module card
        settings = next(page.dialog for page in window.centralWidget().dialog_pages()
                        if isinstance(page.dialog, AppSettings))
        assert settings.backend.category == "module_delta"
        assert open_option(window, OptionEntry("units", "speed_unit", "setting", "units speed")) is settings
        assert settings.backend.category == "units"
    finally:
        modules.deleteLater()


def test_preset_categories_load_without_qml_warnings(window):
    from neopedal.ui.menu import open_preset_config

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page = open_preset_config(window, "units")
        window.resize(1200, 800)
        window.show()
        for section in ("units", "font", "pace_notes_playback", "api", "module_delta", "application"):
            page.backend.open_section(section)
            for _ in range(3):
                QCoreApplication.processEvents()
        page.backend.selectCategory("font")
        page.backend.setNumber("font:font_size_addend", 3)  # preview card with sample texts
        for _ in range(3):
            QCoreApplication.processEvents()
        window.resize(700, 600)  # narrow: categories in a choice list
        for _ in range(3):
            QCoreApplication.processEvents()
        assert not page.view.errors()
        assert not [text for text in messages if "qml" in text.lower() or "binding" in text.lower()], messages
    finally:
        qInstallMessageHandler(previous)
        page.backend.discard()


def test_pace_notes_page_is_the_settings_category(window):
    from neopedal.ui.pace_notes_view import PaceNotesControl

    page = PaceNotesControl(window)
    try:
        page.resize(900, 700)
        page.ensure_view()  # page built when first shown (rail page)
        QCoreApplication.processEvents()
        assert page.view is not None and not page.view.errors()
        assert page.backend.singleCategory and page.backend.category == "pace_notes_playback"
    finally:
        page.close()
        page.deleteLater()
        flush()


# Setup wizard
def test_wizard_streaming_step_and_finish_choices(ui_env):
    from neopedal.ui.quick import setup_backend
    from neopedal.ui.quick.setup_backend import SetupBackend

    backend = SetupBackend(None, detect_games=False)
    try:
        assert backend.steps[setup_backend.STEP_STREAM]["key"] == "stream"
        assert not backend.stream and backend.openScreenView and backend.testOnScreen
        backend.setStream(True)
        backend.copyStreamUrl()
        assert "/layout?token=" in backend.streamUrl and "crop=16:9" in backend.streamUrl
        backend.setTestOnScreen(False)
        summary = {row["label"]: row for row in backend.summary}
        assert summary["Streaming"]["value"] == "On" and summary["Streaming"]["step"] == setup_backend.STEP_STREAM
        choices = backend.choices()
        assert choices.stream and choices.open_screen_view and not choices.test_on_screen
    finally:
        backend.stop_previews()
        backend.deleteLater()
        flush()


def test_wizard_global_choices_stream_and_screen_view(ui_env, monkeypatch):
    from neopedal.ui import setup_wizard

    choices = setup_wizard.SetupChoices(
        language="English", api_name="", window_theme="Modern Dark", overlay_theme="Modern Dark",
        modern_font=True, preset="", new_preset="", widgets=(), stream=True, open_screen_view=True)
    setup_wizard.apply_global_choices(choices)
    assert cfg.user.config["stream_overlay"]["enable_stream_overlay"] is True
    assert cfg.application["show_overlay_screen_view"] is True


def test_wizard_finish_runs_test_once_reloaded(ui_env, monkeypatch):
    from neopedal import loader
    from neopedal.ui import setup_wizard

    after = []
    monkeypatch.setattr(loader, "reload", lambda **kwargs: None)
    monkeypatch.setattr(loader, "after_reload", after.append)
    done = []
    choices = setup_wizard.SetupChoices(
        language="English", api_name="", window_theme="Modern Dark", overlay_theme="Modern Dark",
        modern_font=True, preset="", new_preset="", widgets=())
    setup_wizard.run_setup(choices, lambda: done.append(1))
    after.pop(0)()  # preset loaded: preset choices applied, reloaded
    assert not done
    after.pop(0)()  # overlays running with the choices
    assert done == [1]


def test_ready_step_text_up_to_date():
    from neopedal.ui.quick import qml_path

    with open(qml_path("SetupReady.qml"), encoding="utf-8") as file:
        text = file.read()
    assert "Lock Overlay" not in text and "Screen view" in text and "testOnScreen" in text


# Ctrl+F, vocabulary, translations
@pytest.mark.parametrize("name", ["Settings", "OptionFinder", "Modules", "Presets", "Hotkeys"])
def test_ctrl_f_searches_the_page(name):
    from neopedal.ui.quick import qml_path

    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        text = file.read()
    assert re.search(r"StandardKey\.Find|Qt\.Key_F", text), name
    assert "Ctrl+F" in text  # told in the search field


def test_plural_titles_and_options_wording():
    from neopedal.ui.quick import qml_path

    with open(qml_path("Modules.qml"), encoding="utf-8") as file:
        modules = file.read()
    with open(qml_path("ModuleCard.qml"), encoding="utf-8") as file:
        card = file.read()
    assert 'title: i18n.tr("Modules")' in modules and 'i18n.tr("Config")' not in modules + card
    assert 'i18n.tr("Options…")' in modules


def test_french_overlay_vocabulary_and_new_texts_translated():
    from neopedal.i18n.fr import TRANSLATION
    from neopedal.ui.quick.settings_backend import FONT_HELP, FONT_LABELS, PRESET_CATEGORIES

    renamed = ("Overlay Performance", "Overlay Times", "No widget enabled.", "Search pages, tools, commands, settings, presets, options…",
               "Ignore overlay positions")
    assert not [key for key in renamed if re.search(r"\bwidgets?\b", TRANSLATION[key])]  # C5: overlay in French
    texts = [*FONT_LABELS.values(), *FONT_HELP.values(), "In the loaded preset", "Modules", "Hotkeys", "Presets"]
    for category in PRESET_CATEGORIES:
        texts += [category.label, category.description, *(title for title, _ in category.groups)]
    assert not [text for text in texts if text not in TRANSLATION]


def test_pace_notes_page_module_light_at_startup():
    """Main window imports the Pace Notes page module: no Qt Quick until the page is shown"""
    import subprocess
    import sys

    code = ("import sys; import neopedal.ui.pace_notes_view; "
            "print([m for m in sys.modules if m.startswith('PySide6.QtQuick')])")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_dead_option_section_removed():
    from neopedal.ui import _option, config

    assert not hasattr(_option, "OptionSection") and not hasattr(config, "FontConfig")


def test_theme_and_dpi_in_settings_application_interface(settings):
    settings.selectCategory("application")
    shown = rows(settings)
    assert shown["application/window_color_theme"]["kind"] == "choice"
    assert shown["application/enable_high_dpi_scaling"]["applies"] == "restart"  # restart notice
    assert shown["application/window_color_theme"]["group"] == shown["application/enable_high_dpi_scaling"]["group"]


def test_settings_host_without_optional_methods(ui_env):
    """Hosts of older pages (no toast, preset or file dialogs): actions still safe"""
    from neopedal.ui.quick.settings_backend import SettingsBackend

    backend = SettingsBackend(None, SimpleNamespace(
        confirm=lambda text: True, applied=lambda sections, restart: None))
    try:
        backend.selectCategory("units")
        key = next(iter(rows(backend)))
        backend.resetOption(key)
        backend.selectCategory("pace_notes_playback")
        backend.testSound()
        backend.browse("preset:pace_notes_playback/pace_notes_file_name")
        backend.setNumber("preset:pace_notes_playback/pace_notes_sound_volume", 10)
        assert backend.apply()
    finally:
        backend.deleteLater()


# Wave 2: dialogs over the page (answers by callback), page toasts, tokens
def test_reset_section_asked_over_the_page(settings):
    asked = []
    settings.host.ask = lambda text, action, on_result: asked.append((text, action, on_result))
    settings.selectCategory("units")
    key = "preset:units/speed_unit"
    settings.setChoice(key, rows(settings)[key]["choices"].index("mph"))
    settings.apply()
    settings.resetCategory()
    assert asked and asked[0][1] == "Reset Section" and not settings._pending  # nothing until answered
    asked[0][2](False)
    assert not settings._pending
    asked[0][2](True)
    assert settings._pending[key] == "KPH"


def test_preset_lock_and_repair_answered_by_callback(ui_env, monkeypatch):
    from neopedal.ui.quick.preset_backend import PresetBackend

    monkeypatch.setattr(cfg.user, "filelock", {})
    asked = []
    host = SimpleNamespace(ask=lambda title, message, on_result: asked.append((title, on_result)),
                           page_toast=lambda text, error, undo: None)
    backend = PresetBackend(None, host)
    try:
        backend._times["race.json"] = (0.0, 0)  # known preset
        backend.toggleLock("race.json")
        assert asked[-1][0] == "Lock Preset" and "race.json" not in cfg.user.filelock
        asked[-1][1](True)
        assert "race.json" in cfg.user.filelock
        backend.toggleLock("race.json")
        asked[-1][1](False)  # unlock declined
        assert "race.json" in cfg.user.filelock
    finally:
        backend.deleteLater()


def test_module_batch_switch_at_once_with_undo(ui_env):
    """Modules page Enable / Disable (n): at once like the Overlays page (2026-10-29 audit E5), never asked"""
    from neopedal.ui.quick.module_backend import ModuleBackend
    from tests.test_module_page import DEPENDENCIES, MODULES, WIDGETS, FakeControl

    for name in MODULES:
        cfg.user.setting[name]["enable"] = True
    asked = []
    control = FakeControl(MODULES)
    backend = ModuleBackend(None, control, FakeControl(WIDGETS, "widget"), lambda name: None,
                            lambda text: pytest.fail("sync confirm"), ask=lambda text, on_result: asked.append(on_result))
    try:
        backend.load_dependencies(DEPENDENCIES)
        backend.disableShown()
        assert not asked and not any(cfg.user.setting[name]["enable"] for name in MODULES)
        backend.undoBulk()
        assert all(cfg.user.setting[name]["enable"] for name in MODULES)
    finally:
        backend.deleteLater()


def test_notice_previews_readable(settings):
    cfg.user.config["notification"]["font_color_locked_preset"] = "#777777"
    cfg.user.config["notification"]["background_color_locked_preset"] = "#808080"
    preview = settings.previews["Preset Locked"]
    from PySide6.QtGui import QColor

    from neopedal.ui.notification import MIN_CONTRAST, contrast

    assert contrast(QColor(preview["color"]), QColor(preview["background"])) >= MIN_CONTRAST


@pytest.mark.parametrize("name", ["Settings", "OptionFinder", "Presets", "Modules", "Hotkeys", "SetupWizard"])
def test_pages_host_backend_dialogs_and_toasts(name):
    from neopedal.ui.quick import qml_path

    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        text = file.read()
    assert "TpDialogHost {}" in text and "TpToast {" not in text  # one toast: the page's


def test_settings_page_owns_its_title():
    from neopedal.ui.app_settings import AppSettings

    assert AppSettings.OWNS_TITLE is True
