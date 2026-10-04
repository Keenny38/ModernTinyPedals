"""What's new page: release notes split in themes & technical details, install from it"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

NOTES = """### Visionneuse de télémétrie (Telemetry)

- **Unités de tes réglages** : vitesse (km/h, mph), <b>pas du HTML</b>
- **Axes gradués** : distance sous les courbes,
  valeurs haute et basse

### Calculateur

- Plan d'arrêts

## Commits

### Added

- Add lap viewer analysis ([b31940e](https://github.com/Keenny38/ModernTinyPedals/commit/b31940e))

### SHA256

- `f2a9  ModernTinyPedals-0.15.0-source.zip`
"""


def test_split_notes_themes_and_details():
    from tinypedal.ui.release_notes import split_notes

    themes, details = split_notes(NOTES)
    assert [section.title for section in themes] == ["Visionneuse de télémétrie (Telemetry)", "Calculateur"]
    assert len(themes[0].items) == 2 and themes[0].items[1].endswith("valeurs haute et basse")  # wrapped bullet
    assert [section.title for section in details] == ["Added", "SHA256"]
    commits_only, none = split_notes("### Fixed\n\n- Fix replay")
    assert [section.title for section in commits_only] == ["Fixed"] and not none
    assert split_notes("") == ([], [])


def test_inline_html():
    from tinypedal.ui.release_notes import inline_html

    assert inline_html("**Bold** & `code`") == "<b>Bold</b> &amp; <code>code</code>"
    assert inline_html("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"  # notes text never read as HTML
    assert inline_html("[abc](https://github.com/x)") == '<a href="https://github.com/x">abc</a>'
    assert inline_html("[bad](javascript:alert)") == "[bad](javascript:alert)"  # only web links


def test_release_date_in_current_language():
    from tinypedal import i18n
    from tinypedal.ui.release_notes import format_release_date

    i18n.set_language("Français")
    try:
        assert format_release_date((2026, 10, 4)) == "4 octobre 2026"
    finally:
        i18n.set_language("English")
    assert format_release_date((2026, 10, 4)) == "4 October 2026"
    assert format_release_date((0, 0, 0)) == ""


@pytest.fixture
def notes_page(ui_env):
    from tinypedal.ui.release_notes import ReleaseNotesDialog

    pages = []

    def make(**kwargs):
        dialog = ReleaseNotesDialog(None, NOTES, (0, 15, 0), (2026, 10, 4), **kwargs)
        pages.append(dialog)
        return dialog

    yield make
    for dialog in pages:
        dialog.close()
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_page_cards_and_details(notes_page):
    from tinypedal.ui.release_notes import NotesCard

    dialog = notes_page()
    cards = dialog.findChildren(NotesCard)
    assert len(cards) == 4  # 2 themes, commits, checksums
    assert dialog.details_box.isHidden()  # technical details folded
    dialog.button_details.setChecked(True)
    assert not dialog.details_box.isHidden()
    label = type(dialog.label_detail)
    assert "0.15.0" in dialog.findChild(label, "notesTitle").text()
    assert dialog.findChild(label, "notesChip").text() == "New Version"  # newer than installed version
    assert dialog.button_install.isVisibleTo(dialog)  # always offered: browser download when app cannot install
    assert "4 October 2026" in dialog.label_detail.text()


def test_prompt_install(notes_page):
    from tinypedal.i18n import tr

    dialog = notes_page(can_install=True, prompt=True)
    asked = []
    dialog.install_requested.connect(lambda: asked.append(1))
    assert dialog.button_install.isVisibleTo(dialog) and dialog.button_install.text() == tr("Install Now")
    assert dialog.button_close.text() == tr("Later")
    dialog.button_install.click()
    assert asked


def test_update_messages_translated():
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("New Updates: v0.15.0 (2026-10-4)") == "Nouvelle version : v0.15.0 (2026-10-4)"
        assert i18n.trm("No Updates Available") == "Aucune mise à jour disponible"
    finally:
        i18n.set_language("English")


def test_notify_button_opens_notes(ui_env, monkeypatch):
    from tinypedal.ui import notification
    from tinypedal.ui.release_notes import ReleaseNotesDialog
    from tinypedal.update import update_checker

    monkeypatch.setattr(update_checker, "release_notes", NOTES)
    opened = []
    monkeypatch.setattr(ReleaseNotesDialog, "open", lambda self: opened.append(self))
    button = notification.UpdatesNotifyButton("v0.15.0")
    try:
        button.show_release_notes()
        assert opened and opened[0].themes
        installs = []
        monkeypatch.setattr(button, "download_update", lambda: installs.append(button._auto_install))
        opened[0].install_requested.emit()
        assert installs == [True]  # install asked from notes: no second question
    finally:
        for dialog in opened:
            dialog.deleteLater()
        button.deleteLater()


def test_shown_as_page(ui_env, monkeypatch):
    """Inside the app: page title & Close button of page only, readable column on a wide page"""
    from PySide6.QtWidgets import QApplication

    from tinypedal.setting import cfg
    from tinypedal.ui import app as app_module
    from tinypedal.ui.release_notes import ReleaseNotesDialog

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    window = app_module.AppWindow()
    try:
        window.resize(1800, 900)
        window.show()
        dialog = ReleaseNotesDialog(window, NOTES, (0, 15, 0), (2026, 10, 4))
        dialog.open()
        QApplication.processEvents()
        assert dialog.in_app_page and dialog.button_close.isHidden()  # page has its own Close
        from tinypedal.ui.release_notes import NotesCard
        card = dialog.findChildren(NotesCard)[0]
        assert card.width() > dialog.width() * 0.8  # notes fill the page width
        dialog.close()
    finally:
        window.hide()
        window.deleteLater()


def test_download_in_browser_when_app_cannot_install(notes_page, monkeypatch):
    from tinypedal.ui import release_notes

    opened = []
    monkeypatch.setattr(release_notes.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    dialog = notes_page(download_url="https://github.com/x/releases/download/v0.15.0/Setup.exe")
    asked = []
    dialog.install_requested.connect(lambda: asked.append(1))
    dialog.button_install.click()
    assert opened == ["https://github.com/x/releases/download/v0.15.0/Setup.exe"] and not asked
    other = notes_page()  # no installer: release page
    other.button_install.click()
    assert opened[-1].endswith("/releases")
