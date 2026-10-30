"""UI/UX audit 2026-10-29, navigation lot: one page header in or out of the rail (N2), one name per page (N3),
breadcrumb from the real opener & help pages of every dialog page (N4), Preset Comparison as the compare panel of
the Presets page (N5), Pages section of the Tools page (N8), dialogs of the Tools page in the page (N9)"""

import os
import re

import pytest
from PySide6.QtWidgets import QMessageBox

from neopedal import i18n
from tests.test_ui_audit_2026_10_29_shell import flush, page_of, window  # noqa: F401

WIKI_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "wiki")


def wiki_anchors(page: str) -> set[str]:
    """GitHub anchors of a wiki page headings (lower case, punctuation dropped, spaces to hyphens)"""
    with open(os.path.join(WIKI_FOLDER, f"{page}.md"), encoding="utf-8") as file:
        headings = [line.lstrip("#").strip() for line in file if line.startswith("#")]
    return {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


# --- N4: help pages
def test_every_help_page_and_anchor_exists():
    from neopedal.template.page_registry import DIALOG_WIKI, PAGES

    links = {page.name: page.wiki for page in PAGES} | DIALOG_WIKI
    for name, link in links.items():
        page, _, anchor = link.partition("#")
        assert os.path.isfile(os.path.join(WIKI_FOLDER, f"{page}.md")), (name, link)
        assert not anchor or anchor in wiki_anchors(page), (name, link)


def test_dialog_pages_out_of_registry_have_help_page():
    from neopedal.template.page_registry import page_wiki

    for name in ("OverlayOptions", "OptionFinder", "ReleaseNotesDialog", "About", "LogInfo", "BugReport",
                 "RailEditor", "QuickAccessEditor"):
        assert page_wiki(name), name
    assert page_wiki("LapViewer") == "Telemetry-Viewer" and page_wiki("Bogus") == ""


# --- N3: one name per page
def test_short_label_is_short_form_of_label():
    from neopedal.template.page_registry import tool_pages

    for page in tool_pages():
        short = page.short_label.lower()
        if short:
            assert any(stem in page.label.lower() for stem in (short, short.removesuffix("s"), short.removesuffix("es"))), page.name


def test_tool_page_window_title_is_its_label():
    from neopedal.template.page_registry import tool_pages

    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "neopedal", "ui")
    for page in tool_pages():
        with open(os.path.join(folder, f"{page.name}.py"), encoding="utf-8") as file:
            assert f'"{page.label}"' in file.read(), page.name


def test_page_names(french):
    from neopedal.i18n import tr
    from neopedal.template.page_registry import page_spec

    i18n.set_language("English")
    assert page_spec("race_calculator").rail_label == "Calculator"
    assert page_spec("driver_stats_viewer").label == "Driver Stats"
    assert page_spec("preset_compare") is None  # panel of the Presets page (N5)
    i18n.set_language("Français")
    assert tr("What's New") == "Nouveautés" and tr("Calculator") == "Calculateur"
    assert tr("Keyboard Shortcuts") != tr("Hotkeys")  # Ctrl+/ sheet apart from the Hotkeys page
    assert "viewer" not in tr("Add to Viewer") and tr("Pacenotes").lower() in tr("Pace Notes Playback").lower()


# --- N2 & N4: header & breadcrumb
def test_breadcrumb_names_page_opened_from(window):  # noqa: F811
    from neopedal.ui.nav_rail import PAGE_INDEX
    from neopedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.select_page(PAGE_INDEX["home"])
    open_tool("brake_editor.BrakeEditor", window)  # Home quick access, palette...: Home, not Tools
    page = page_of(window, "BrakeEditor")
    assert page._button_crumb.text() == "Home" and page.crumb_target() == "home"
    view.select_page(PAGE_INDEX["widget"])
    open_tool("perf_view.PerformanceView", window)
    other = page_of(window, "PerformanceView")
    assert other._button_crumb.text() == "Overlays"
    other._button_crumb.click()
    assert view.current_index() == PAGE_INDEX["widget"]


def test_breadcrumb_of_page_opened_over_another_page(window):  # noqa: F811
    from neopedal.ui.tools_view import open_tool

    open_tool("race_calculator.RaceCalculator", window)  # navigation bar tool: kept open when left
    first = page_of(window, "RaceCalculator")
    open_tool("brake_editor.BrakeEditor", window)  # from the palette over the first page
    page = page_of(window, "BrakeEditor")
    assert page.origin is first and page._button_crumb.text() == first.title
    first.dialog.close()
    flush()
    assert page.origin is None and page._button_crumb.text() == "Tools"  # page gone: Tools page of the tool


# --- N5: Preset Comparison
def test_preset_comparison_opens_compare_panel(window):  # noqa: F811
    from neopedal.ui.command_palette import app_commands
    from neopedal.ui.nav_rail import PAGE_INDEX, parse_rail_items
    from neopedal.ui.preset_view import PresetList
    from neopedal.ui.tools_view import LISTED_TOOL_SECTIONS, open_tool

    assert "preset_compare.PresetCompare" not in [path for _, tools in LISTED_TOOL_SECTIONS for _, _, path in tools]
    assert parse_rail_items("preset_compare,home") == ["preset", "home"]  # saved bar entry: Presets page
    command = next(command for command in app_commands(window) if command.title == "Preset Comparison")
    window.show()
    requested = []
    page = open_tool("preset_compare.PresetCompare", window)
    assert isinstance(page, PresetList) and window.centralWidget().current_index() == PAGE_INDEX["preset"]
    page.backend.panelRequested.connect(lambda name, key: requested.append(name))
    flush()
    assert requested == ["compare"] and not window.centralWidget().dialog_pages()
    command.run()
    flush()
    assert requested == ["compare", "compare"]


# --- N8 & N9: Tools page
def test_tools_page_opens_pages_and_alerts_in_page(window, monkeypatch):  # noqa: F811
    from neopedal.ui import tools_view
    from neopedal.ui.nav_rail import PAGE_INDEX
    from neopedal.ui.quick import dialogs

    view = window.centralWidget()
    tools_view.open_page_or_tool("page:hotkey", window)
    assert view.current_index() == PAGE_INDEX["hotkey"]
    alerts = []
    monkeypatch.setattr(dialogs, "alert", lambda parent, title, text, *args, **kwargs: alerts.append(text))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("message box"))
    assert tools_view.open_tool("bogus_module.Bogus", window) is None
    assert alerts == ["Unable to open tool, see log for details."]
