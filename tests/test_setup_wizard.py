"""Setup wizard (Qt Quick page): steps, choices in wizard language, game detection, overlay previews in the
chosen style, preset name checked while typing, choices applied only when finished"""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, qInstallMessageHandler
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from tinypedal import i18n
from tinypedal.setting import cfg
from tinypedal.ui import setup_wizard
from tinypedal.ui.quick import setup_backend


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return condition()


def item_texts(view) -> set[str]:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


@pytest.fixture
def renders(monkeypatch):
    """Overlay pictures recorded (overlay, theme), small picture returned instead of real rendering"""
    calls = []

    def render(name, setting, style):
        calls.append((name, style["overlay_theme"]))
        image = QImage(40, 20, QImage.Format.Format_ARGB32)
        image.fill(0xFF336699)
        return image

    monkeypatch.setattr(setup_backend, "render_overlay", render)
    return calls


@pytest.fixture
def wizard(ui_env, renders):
    page = setup_wizard.SetupWizard(None, detect_games=False)
    yield page
    page.backend.stop_previews()
    page.deleteLater()
    flush()


def render_all(backend):
    assert wait_for(lambda: backend.pending() == 0)


def test_setup_choices_apply(ui_env, monkeypatch):
    reloads = []
    monkeypatch.setattr(setup_wizard.loader, "reload", lambda reload_preset=False: reloads.append(reload_preset))

    def create_preset(self, filename):
        with open(f"{cfg.path.settings}{filename}", "w", encoding="utf-8") as file:
            file.write("{}")

    monkeypatch.setattr(type(cfg), "create", create_preset)
    cfg.user.setting["relative"]["enable"] = False
    cfg.user.setting["radar"]["enable"] = True
    choices = setup_wizard.SetupChoices(
        language="Français", api_name="", window_theme="Modern Light", overlay_theme="Legacy Dark",
        modern_font=False, preset="", new_preset="my overlay", widgets=("relative",), colorblind=True,
        units="Imperial", disabled=("radar", "relative"),
    )
    try:
        setup_wizard.run_setup(choices)
        assert cfg.application["language"] == "Français"
        assert cfg.application["window_color_theme"] == "Modern Light"
        assert cfg.application["show_setup_wizard_at_startup"] is False
        style = cfg.user.config["overlay_style"]
        assert style["overlay_theme"] == "Legacy Dark" and style["enable_colorblind_colors"] is True
        assert cfg.user.setting["relative"]["enable"] is True  # checked wins over disabled
        assert cfg.user.setting["radar"]["enable"] is False
        assert cfg.user.setting["units"]["speed_unit"] == "MPH"
        assert cfg.user.setting["units"]["temperature_unit"] == "Fahrenheit"
        assert reloads == [True, False]  # load new preset, then restart with widgets
    finally:
        i18n.set_language("English")


def test_setup_keeps_mixed_units(ui_env, monkeypatch):
    monkeypatch.setattr(setup_wizard.loader, "reload", lambda reload_preset=False: None)
    cfg.user.setting["units"]["speed_unit"] = "MPH"  # metric otherwise
    assert setup_backend.unit_system(cfg.user.setting["units"]) == setup_wizard.UNITS_KEEP
    choices = setup_wizard.SetupChoices(
        language="English", api_name="", window_theme="Modern Dark", overlay_theme="Modern Dark",
        modern_font=True, preset="", new_preset="", widgets=())
    setup_wizard.run_setup(choices)
    assert cfg.user.setting["units"]["speed_unit"] == "MPH"
    assert cfg.user.setting["units"]["fuel_unit"] == "Liter"


def test_setup_language_set_before_overlays_reload(ui_env, monkeypatch):
    languages = []
    monkeypatch.setattr(setup_wizard.loader, "reload", lambda reload_preset=False: languages.append(
        i18n.current_language()))
    choices = setup_wizard.SetupChoices(
        language="Français", api_name="", window_theme="Modern Dark", overlay_theme="Modern Dark",
        modern_font=False, preset="", new_preset="", widgets=(),
    )
    try:
        setup_wizard.run_setup(choices)
        assert languages == ["fr"]  # overlays created with French labels
    finally:
        i18n.set_language("English")


def test_wizard_steps_without_qml_warnings(wizard):
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        wizard.resize(1100, 760)
        wizard.show()
        backend = wizard.backend
        QCoreApplication.processEvents()
        assert not wizard.view.errors()
        assert "Welcome to Modern Tiny Pedals" in item_texts(wizard.view)
        for step in range(1, backend.stepCount):
            backend.next()
            if step >= setup_backend.STEP_LOOK:
                render_all(backend)
            QCoreApplication.processEvents()
            assert backend.step == step
        assert "Ready to race" in item_texts(wizard.view)
        assert "Finish Setup" in item_texts(wizard.view)
        wizard.resize(620, 560)  # narrow: progress bar instead of steps
        for step in (3, 4, 0):
            backend.goTo(step)
            QCoreApplication.processEvents()
        assert not [text for text in messages if "qml" in text.lower() or "binding" in text.lower()], messages
    finally:
        qInstallMessageHandler(previous)
        wizard.hide()


def test_wizard_language_switches_texts_not_app(wizard):
    backend = wizard.backend
    wizard.show()
    QCoreApplication.processEvents()
    backend.setLanguage("Français")
    QCoreApplication.processEvents()
    try:
        assert i18n.current_language() == "en"  # app language changed only once finished
        assert wizard.windowTitle() == "Assistant de configuration"
        assert backend.steps[0]["title"] == "Bienvenue dans Modern Tiny Pedals"
        assert backend.newName == "mon overlay"
        assert "Bienvenue dans Modern Tiny Pedals" in item_texts(wizard.view)
        labels = {row["key"]: row["label"] for row in backend.tiles.rows}
        assert labels["relative"] != "Relative"  # French overlay names
        backend.setNewName("mine")
        backend.setLanguage("English")
        assert backend.newName == "mine"  # typed name kept
        assert backend.choices().language == "English"
    finally:
        wizard.hide()


def test_new_preset_name_checked_while_typing(wizard):
    backend = wizard.backend
    backend.goTo(setup_backend.STEP_OVERLAYS)
    changes = []
    backend.navigationChanged.connect(lambda: changes.append(backend.canGoNext))
    assert backend.newPreset and backend.nameError == ""
    backend.setNewName("Default")  # existing preset (case insensitive)
    assert not backend.canGoNext and not backend.canFinish
    assert backend.nameError == "A preset with this name already exists"
    backend.setNewName("backup copy")
    assert backend.nameError == "This name is reserved, choose another one"
    backend.setNewName("  ")
    assert backend.nameError == "Enter a preset name"
    backend.next()
    assert backend.step == setup_backend.STEP_OVERLAYS  # blocked
    backend.setNewName("new one.json")
    assert backend.canGoNext and changes[-1] is True
    assert backend.choices().new_preset == "new one"
    backend.setNewPreset(False)  # existing preset: no name needed
    backend.setNewName("default")
    assert backend.canFinish and backend.choices().new_preset == ""
    assert backend.choices().preset == "default.json"


def test_default_preset_name_not_used_yet(ui_env, renders):
    with open(f"{cfg.path.settings}my overlay.json", "w", encoding="utf-8") as file:
        file.write("{}")
    backend = setup_backend.SetupBackend(detect_games=False)
    assert backend.newName == "my overlay 2" and backend.nameError == ""


def test_overlay_checks_follow_preset_choice(ui_env, renders, monkeypatch):
    monkeypatch.setattr(cfg.filename, "setting", "default.json")  # loaded preset (left by other tests otherwise)
    backend = setup_backend.SetupBackend(detect_games=False)
    choices = backend.choices()
    assert set(choices.widgets) == set(setup_wizard.DEFAULT_STARTER)  # new preset: recommended
    assert "radar" in choices.disabled and "relative" not in choices.disabled
    backend.toggleOverlay("radar")
    assert backend.checkedCount == len(setup_wizard.DEFAULT_STARTER) + 1
    # Loaded preset: overlays already on are checked
    cfg.user.setting["standings"]["enable"] = True
    backend.setNewPreset(False)
    checked = {row["key"] for row in backend.tiles.rows if row["checked"]}
    assert "standings" in checked and "relative" not in checked
    backend.checkOverlays("none")
    assert backend.checkedCount == 0 and backend.choices().widgets == ()
    backend.checkOverlays("all")
    assert backend.checkedCount == backend.tileCount and backend.choices().disabled == ()
    backend.setNewPreset(True)  # choice of each preset kept
    assert "radar" in backend.choices().widgets


def test_other_preset_read_from_file(ui_env, renders):
    import json

    with open(f"{cfg.path.settings}race.json", "w", encoding="utf-8") as file:
        json.dump({"standings": {"enable": True}, "fuel": {"enable": False}}, file)
    backend = setup_backend.SetupBackend(detect_games=False)
    backend.setNewPreset(False)
    backend.setPresetIndex(backend.presets.index("race"))
    widgets = backend.choices().widgets
    assert "standings" in widgets and "fuel" not in widgets
    assert backend.choices().preset == "race.json"
    assert backend.widget_setting("standings", "race.json")["enable"] is True


def test_game_detection_picks_running_game(ui_env, renders, monkeypatch):
    monkeypatch.setattr(setup_backend, "running_games", lambda: {"rFactor 2"})
    backend = setup_backend.SetupBackend()
    assert wait_for(lambda: any(game["running"] for game in backend.games))
    assert backend.game == "rFactor 2"
    running = [game["name"] for game in backend.games if game["running"]]
    assert running == ["rFactor 2"]
    # Choice of the driver wins over detection
    backend = setup_backend.SetupBackend(detect_games=False)
    backend.setGame(backend.games[0]["name"])
    backend._games_detected(["rFactor 2"])
    assert backend.game == backend.games[0]["name"]


def test_running_games_by_process_name(monkeypatch):
    import psutil

    class Process:
        def __init__(self, name):
            self.info = {"name": name}

    names = ["explorer.exe", "Le Mans Ultimate.exe", None]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [Process(name) for name in names])
    assert setup_backend.running_games() == {"Le Mans Ultimate", "Le Mans Ultimate (legacy)"}


def test_previews_rendered_in_chosen_style(wizard, renders):
    backend = wizard.backend
    QCoreApplication.processEvents()
    assert renders == []  # nothing rendered before Appearance step
    backend.goTo(setup_backend.STEP_LOOK)
    first = backend.pending()
    assert first > 0
    QCoreApplication.processEvents()
    assert renders[0][0] in (*setup_backend.STYLE_SAMPLES, setup_backend.THEME_SAMPLE)  # Appearance step first
    render_all(backend)
    assert all(row["previewState"] == setup_backend.PREVIEW_READY for row in backend.tiles.rows)
    assert all(row["previewState"] == setup_backend.PREVIEW_READY for row in backend.overlayThemes)
    count = len(renders)
    backend.setOverlayTheme("Legacy Light")
    render_all(backend)
    assert ("relative", "Legacy Light") in renders[count:]
    assert renders.count(("session", "Legacy Light")) == 1  # theme card picture reused by the tile
    count = len(renders)
    backend.setOverlayTheme("Modern Dark")  # pictures kept per style
    render_all(backend)
    assert len(renders) == count
    backend.setColorblind(True)
    assert backend.pending() > 0
    backend.skip()
    assert backend.pending() == 0  # closed: rendering stopped


def test_render_overlay_keeps_running_overlay_style(ui_env, bundled_fonts):
    from tinypedal.widget._painter import OverlayStyle

    OverlayStyle.corner_scale, OverlayStyle.depth_effects = 0.05, True
    style = {**cfg.user.config["overlay_style"], "overlay_theme": "Legacy Light"}
    image = setup_backend.render_overlay("deltabest", cfg.user.setting["deltabest"], style)
    assert image is not None and not image.isNull()
    assert image.width() <= setup_backend.PREVIEW_MAX.width() * image.devicePixelRatio()
    assert (OverlayStyle.corner_scale, OverlayStyle.depth_effects) == (0.05, True)


def test_summary_and_jump_back(wizard):
    backend = wizard.backend
    backend.setUnits("Imperial")
    backend.setWindowTheme("Legacy Light")
    backend.goTo(setup_backend.STEP_READY)
    rows = {row["label"]: row for row in backend.summary}
    assert rows["Units"]["value"].startswith("Imperial (mph")
    assert rows["Window theme"]["value"] == "Legacy Light"
    assert rows["Preset to use"]["value"] == "my overlay (new)"
    backend.goTo(rows["Units"]["step"])
    assert backend.step == setup_backend.STEP_UNITS


def test_finish_applies_choices_skip_does_not(ui_env, renders, monkeypatch):
    applied = []
    monkeypatch.setattr(setup_wizard, "run_setup", applied.append)
    wizard = setup_wizard.SetupWizard(None, detect_games=False)
    game = wizard.backend.games[-1]["name"]
    wizard.backend.setGame(game)
    wizard.backend.finish()
    assert applied == []  # once the click handler that asked is over
    QCoreApplication.processEvents()
    assert len(applied) == 1 and applied[0].api_name == game
    flush()
    cfg.application["show_setup_wizard_at_startup"] = True
    wizard = setup_wizard.SetupWizard(None, detect_games=False)
    wizard.backend.skip()
    QCoreApplication.processEvents()
    assert len(applied) == 1
    assert cfg.application["show_setup_wizard_at_startup"] is False
    flush()


def test_window_theme_cards_use_theme_palettes(ui_env, renders):
    backend = setup_backend.SetupBackend(detect_games=False)
    cards = {card["name"]: card for card in backend.windowThemes}
    assert list(cards) == list(setup_wizard.WINDOW_THEMES)
    assert cards["Modern Light"]["window"] != cards["Modern Dark"]["window"]
    assert cards["Legacy Dark"]["legacy"] and not cards["Modern Dark"]["legacy"]
    assert all(cards["Modern Dark"][part].startswith("#") for part in setup_backend.MOCKUP_ROLES)


def test_wizard_opens_in_app_language_with_current_choices(ui_env, renders):
    cfg.application["window_color_theme"] = "Modern Light"
    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
    i18n.set_language("Français")
    cfg.application["language"] = "Français"
    try:
        wizard = setup_wizard.SetupWizard(None, detect_games=False)
        backend = wizard.backend
        assert wizard.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        assert wizard.windowTitle() == "Assistant de configuration"
        labels = {card["name"]: card["label"] for card in backend.windowThemes}
        assert labels["Modern Light"] == "Moderne clair" and labels["Legacy Dark"] == "Classique sombre"
        assert backend.newName == "mon overlay"
        choices = backend.choices()
        assert (choices.language, choices.window_theme, choices.overlay_theme) == (
            "Français", "Modern Light", "Legacy Dark")
        wizard.deleteLater()
        flush()
    finally:
        i18n.set_language("English")


def test_unit_systems_cover_preset_units():
    from tinypedal.regex_pattern import CHOICE_UNITS
    from tinypedal.template.setting_common import COMMON_DEFAULT

    assert setup_wizard.UNIT_SYSTEMS["Metric"] == COMMON_DEFAULT["units"]
    for units in setup_wizard.UNIT_SYSTEMS.values():
        assert set(units) == set(COMMON_DEFAULT["units"])
        assert all(value in CHOICE_UNITS[key] for key, value in units.items())


def click_text(view, text: str):
    """Mouse click on QML item showing text, also in popups (button handlers run like a real click)"""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtTest import QTest

    stack, found = [view.quickWindow().contentItem()], None
    while stack and found is None:
        item = stack.pop(0)
        if item.isVisible() and item.width() > 0 and item.property("text") == text:
            found = item
        stack.extend(item.childItems())
    assert found is not None, text
    point = found.mapToScene(QPointF(found.width() / 2, found.height() / 2))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(round(point.x()), round(point.y())))
    for _ in range(5):
        QCoreApplication.processEvents()


def wait_popup(view, opened: bool):
    """Confirmation box shown (or gone) once its fade is over"""
    def shown() -> bool:
        stack = [view.quickWindow().contentItem()]
        while stack:
            item = stack.pop()
            if item.isVisible() and item.property("text") == "Quit the setup wizard?":
                return True
            stack.extend(item.childItems())
        return False

    assert wait_for(lambda: shown() == opened), opened


def test_buttons_of_qml_page_close_and_jump_without_crash(ui_env, renders, monkeypatch):
    """Finish & Skip close the window (QML page deleted) after their click handler, Change replaces its own step,
    Esc & window close ask first"""
    applied = []
    monkeypatch.setattr(setup_wizard, "run_setup", applied.append)
    closed = []
    wizard = setup_wizard.SetupWizard(None, detect_games=False)
    wizard.finished.connect(closed.append)
    wizard.resize(1000, 700)
    wizard.show()
    backend = wizard.backend
    backend.goTo(setup_backend.STEP_READY)
    QCoreApplication.processEvents()
    click_text(wizard.view, "Change")  # first row: language
    assert backend.step == setup_backend.STEP_WELCOME
    backend.goTo(setup_backend.STEP_READY)
    QCoreApplication.processEvents()
    click_text(wizard.view, "Finish Setup")
    assert len(applied) == 1 and closed == [QDialog.DialogCode.Accepted]
    flush()
    cfg.application["show_setup_wizard_at_startup"] = True
    wizard = setup_wizard.SetupWizard(None, detect_games=False)
    wizard.finished.connect(closed.append)
    wizard.show()
    QCoreApplication.processEvents()
    QTest.keyClick(wizard.view, Qt.Key.Key_Escape)  # Esc asks first
    wait_popup(wizard.view, True)
    click_text(wizard.view, "Continue Setup")  # stays open, choices kept
    wait_popup(wizard.view, False)
    assert wizard.isVisible() and closed == [QDialog.DialogCode.Accepted]
    QTest.keyClick(wizard.view, Qt.Key.Key_Escape)
    wait_popup(wizard.view, True)
    QTest.keyClick(wizard.view, Qt.Key.Key_Escape)  # Esc closes the box only
    wait_popup(wizard.view, False)
    assert wizard.isVisible()
    wizard.close()  # window close button asks too
    wait_popup(wizard.view, True)
    assert wizard.isVisible()
    click_text(wizard.view, "Quit")
    assert closed[-1] == QDialog.DialogCode.Rejected and len(applied) == 1
    assert cfg.application["show_setup_wizard_at_startup"] is False
    flush()
