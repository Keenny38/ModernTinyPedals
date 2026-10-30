"""What's new page: notes parsed in groups, cards & sub-bullets, versions skipped or since the last one run,
search, contents, version menu, option links, overlay actions, screenshots, install from it"""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QtMsgType, qInstallMessageHandler

NOTES = """Intro of the version.

### Nouveautés

#### Visionneuse de télémétrie (Telemetry)

- **Unités de tes réglages** : vitesse (km/h, mph), <b>pas du HTML</b>
  - sous-point avec `show_apex_speed`
    suite du sous-point
- **Axes gradués** : distance sous les courbes,
  valeurs haute et basse

### Corrections

- Plan d'arrêts

## Commits

### Added

- Add lap viewer analysis ([b31940e](https://github.com/Keenny38/ModernTinyPedals/commit/b31940e))

### Visuals

**Carte avant / après**

![Carte avant / après](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/abc123/docs/changes/map.png)

### SHA256

- `f2a9  NeoPedal-0.15.0-source.zip`
"""
SHOT = "https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-18-corner-coach.png"


@pytest.fixture
def update_repo(monkeypatch):
    """Update repository setting (app setting not loaded)"""
    from neopedal import update

    monkeypatch.setattr(update, "update_repository", lambda: "")


def test_split_notes_groups_cards_and_levels(update_repo):
    from neopedal.ui.release_notes import NotesItem, split_notes

    themes, details = split_notes(NOTES)
    assert [(section.group, section.title) for section in themes] == [
        ("", ""), ("Nouveautés", "Visionneuse de télémétrie (Telemetry)"), ("Corrections", "")]
    assert themes[0].items == [NotesItem("Intro of the version.", 0, False)]
    items = themes[1].items
    assert [item.level for item in items] == [0, 1, 0]  # sub-bullet kept under its bullet
    assert items[1].text == "sous-point avec `show_apex_speed` suite du sous-point"  # wrapped sub-bullet
    assert items[2].text.endswith("valeurs haute et basse")
    assert [section.group for section in details] == ["Added", "Visuals", "SHA256"]
    assert details[1].items[-1].text.startswith("![Carte")  # visuals screenshot (pinned commit) kept
    commits_only, none = split_notes("### Fixed\n\n- Fix replay")
    assert [section.group for section in commits_only] == ["Fixed"] and not none
    assert split_notes("") == ([], [])
    with_image = split_notes("### Carte\n\n- Nouvelle carte\n\n![Carte](https://example.com/map.png)\n")[0]
    assert with_image[0].items == [NotesItem("Nouvelle carte")]  # only changelog screenshots of app repository


def test_changelog_screenshots_kept_in_order(update_repo):
    from neopedal.ui.release_notes import notes_image, split_notes

    themes = split_notes(f"### Coach\n\n- Coaching\n  par virage\n  ![Coach]({SHOT})\n\n- Suite\n")[0]
    assert [item.text for item in themes[0].items] == ["Coaching par virage", f"![Coach]({SHOT})", "Suite"]
    assert notes_image(themes[0].items[1].text) == ("Coach", SHOT)
    assert notes_image("Coaching") is None
    other = SHOT.replace("Keenny38/ModernTinyPedals", "someone/else")
    assert notes_image(f"![x]({other})") is None  # other repository
    assert notes_image(f"![x]({SHOT.replace('docs/changes', 'images')})") is None
    assert notes_image(f"![x]({SHOT.replace('.png', '.svg')})") is None


def test_changelog_image_file(tmp_path, monkeypatch, update_repo):
    from neopedal import update, userfile

    monkeypatch.setattr(userfile, "APP_ROOT", str(tmp_path / "app"))
    monkeypatch.setattr(update, "changelog_image_cache", lambda: str(tmp_path / "cache"))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    requests = []

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return self.data[:size]

    def urlopen(url, timeout):
        requests.append(url)
        return Response(served[0])

    served = [png]
    monkeypatch.setattr(update, "open_url", urlopen)
    path = update.changelog_image_file(SHOT)  # downloaded once, then kept
    assert path == str(tmp_path / "cache" / "2026-10-18-corner-coach.png")
    assert Path(path).read_bytes() == png
    assert update.changelog_image_file(SHOT) == path and len(requests) == 1
    shipped = tmp_path / "app" / "docs" / "changes" / "2026-10-18-corner-coach.png"
    shipped.parent.mkdir(parents=True)
    shipped.write_bytes(png)
    assert update.changelog_image_file(SHOT) == str(shipped)  # shipped with app first
    served[0] = b"<html>not found</html>"
    with pytest.raises(OSError):
        update.changelog_image_file(SHOT.replace("corner-coach", "other"))
    assert not (tmp_path / "cache" / "2026-10-18-other.png").exists()
    with pytest.raises(ValueError):
        update.changelog_image_file("https://example.com/docs/changes/x.png")
    assert len(requests) == 2


def test_inline_html():
    from neopedal.ui.release_notes import inline_html, plain_text

    assert inline_html("**Bold** & `code`") == "<b>Bold</b> &amp; <code>code</code>"
    assert inline_html("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"  # notes text never read as HTML
    assert inline_html("[abc](https://github.com/x)") == '<a href="https://github.com/x">abc</a>'
    assert inline_html("[bad](javascript:alert)") == "[bad](javascript:alert)"  # only web links
    assert 'href="https://x"' not in inline_html('[q](https://x"onclick=y)')  # never leaves the attribute
    assert inline_html("`show_apex_speed` & `T5`", {"show_apex_speed"}) == (
        '<a href="option:show_apex_speed"><code>show_apex_speed</code></a> &amp; <code>T5</code>')
    assert plain_text("**Next**: `T5` [link](https://x)") == "Next: T5 link"


def test_release_date_in_current_language():
    from neopedal import i18n
    from neopedal.ui.release_notes import format_release_date

    i18n.set_language("Français")
    try:
        assert format_release_date((2026, 10, 4)) == "4 octobre 2026"
    finally:
        i18n.set_language("English")
    assert format_release_date((2026, 10, 4)) == "4 October 2026"
    assert format_release_date((0, 0, 0)) == ""


CHANGELOG = """# Changelog

## 0.26.0 (2026-10-19)

### New

- Corner Coach

## 0.25.1 (2026-10-18)

- Fix

## 0.25.0 (2026-10-17)

- Ranks

## Unreleased

- Draft
"""


def test_changelog_entries_and_versions_between():
    from neopedal.update import changelog_entries, changelog_sections, entries_between

    entries = changelog_entries(CHANGELOG)
    assert [(entry.version, entry.date) for entry in entries] == [
        ("0.26.0", (2026, 10, 19)), ("0.25.1", (2026, 10, 18)), ("0.25.0", (2026, 10, 17)), ("Unreleased", (0, 0, 0))]
    assert changelog_sections(CHANGELOG)[0] == ("0.26.0", "### New\n\n- Corner Coach")
    between = entries_between(entries, (0, 25, 0), (0, 26, 0))
    assert [entry.version for entry in between] == ["0.26.0", "0.25.1"]  # newest first, installed one left out
    assert entries_between(entries, (0, 24, 0), (0, 26, 0), limit=1)[0].version == "0.26.0"
    assert entries_between(entries, (0, 26, 0), (0, 26, 0)) == []


@pytest.mark.parametrize("language", ["en", "fr"])
def test_update_check_lists_skipped_versions(monkeypatch, language):
    """Installed 0.24.0, latest 0.26.0: notes of 0.25.x follow the release notes (changelog fetched once a tag)"""
    import json

    from neopedal import update, version

    body = "### New\n\n- Corner Coach\n\n## Commits\n\n- Add x"
    response = b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps({
        "tag_name": "v0.26.0", "published_at": "2026-10-19T00:00:00Z", "body": body, "assets": []}).encode()
    fetched = []

    async def latest(repo):
        return response

    def fetch(repo, tag, code, timeout=5):
        fetched.append(code)
        return "" if code == "fr" else CHANGELOG  # not translated: English sections

    monkeypatch.setattr(update, "request_latest_release", latest)
    monkeypatch.setattr(update, "verified_release", lambda *args: None)  # signed manifest: test_signed_release.py
    monkeypatch.setattr(update, "fetch_changelog", fetch)
    monkeypatch.setattr(update, "current_language", lambda: language)
    monkeypatch.setattr(version, "__version__", "0.24.0")
    checker = update.UpdateChecker()
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert checker.is_updates() and checker.notes(language) == body
    assert [entry.version for entry in checker.earlier_notes(language)] == ["0.25.1", "0.25.0"]
    assert fetched == (["en"] if language == "en" else ["fr", "en"])
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert len(fetched) == (1 if language == "en" else 2)  # same release checked again: not fetched again
    monkeypatch.setattr(version, "__version__", "0.25.1")
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert checker.earlier_notes(language) == []  # previous release installed


def test_local_changelog_in_language(tmp_path):
    from neopedal.ui.home_view import local_changelog

    english = tmp_path / "CHANGELOG.md"
    english.write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "CHANGELOG.fr.md").write_text("## 0.26.0 (2026-10-19)\n\n- Coach de virages\n", encoding="utf-8")
    entries = local_changelog("fr", str(english))
    assert [entry.version for entry in entries][:3] == ["0.26.0", "0.25.1", "0.25.0"]
    assert entries[0].body == "- Coach de virages" and entries[1].body == "- Fix"  # English when not translated
    assert local_changelog("fr", str(tmp_path / "missing.md")) == []


@pytest.fixture
def changelog_here(tmp_path, monkeypatch):
    """Local changelog of these tests, running version 0.26.0"""
    from neopedal.ui import home_view

    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    real = home_view.local_changelog
    monkeypatch.setattr(home_view, "local_changelog",
                        lambda language="en", filename="": real(language, str(tmp_path / "CHANGELOG.md")))
    monkeypatch.setattr(home_view, "VERSION", "0.26.0")
    monkeypatch.setattr(home_view.base_version, "__defaults__", ("0.26.0",))


def test_notes_after_update(ui_env, changelog_here):
    from neopedal.setting import cfg
    from neopedal.ui.release_notes import notes_after_update, remember_version_run

    entry, earlier = notes_after_update("0.25.0")
    assert entry.version == "0.26.0" and entry.date == (2026, 10, 19) and [e.version for e in earlier] == ["0.25.1"]
    assert notes_after_update("0.26.0") is None  # same version started again
    assert notes_after_update("") is None  # none recorded: first start (setup wizard) or of this feature
    assert notes_after_update("0.27.0") is None  # older copy started
    cfg.application["last_run_version"] = "0.25.0"
    assert remember_version_run() == "0.25.0" and cfg.application["last_run_version"] == "0.26.0"
    cfg.application["last_run_version"] = "0.27.0"  # source checkout newer than installed app
    assert remember_version_run() == "0.27.0" and cfg.application["last_run_version"] == "0.27.0"  # newest kept


@pytest.fixture
def qml_warnings():
    """QML warnings & errors printed while the test runs"""
    found = []

    def handler(kind, context, message):
        if kind != QtMsgType.QtDebugMsg and "/home/Release" in f"{context.file} {message}":
            found.append(message)  # this page only (other pages deleted meanwhile warn on their own)

    previous = qInstallMessageHandler(handler)
    yield found
    qInstallMessageHandler(previous)


@pytest.fixture
def notes_page(ui_env, monkeypatch, qml_warnings):
    from neopedal.ui import release_notes
    from neopedal.ui.quick import release_backend
    from neopedal.ui.release_notes import ReleaseNotesDialog

    monkeypatch.setattr(release_backend, "app_version", "0.10.0")  # source checkout reports its last release
    monkeypatch.setattr(release_notes, "app_version", "0.10.0")

    def offline(url, timeout=10):
        raise OSError("offline")

    monkeypatch.setattr(release_backend, "changelog_image_file", offline)
    pages = []

    def make(notes=NOTES, **kwargs):
        dialog = ReleaseNotesDialog(None, notes, (0, 15, 0), (2026, 10, 4), **kwargs)
        pages.append(dialog)
        return dialog

    yield make
    for dialog in pages:
        dialog.close()
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not qml_warnings, qml_warnings


def rows(backend):
    return [(row["kind"], row["title"]) for row in backend.model.rows]


def test_page_rows_folds_and_header(notes_page, update_repo):
    dialog = notes_page()
    backend = dialog.backend
    assert dialog.view.rootObject() is not None and not dialog.view.errors()
    assert rows(backend) == [
        ("card", ""), ("group", "Nouveautés"), ("card", "Visionneuse de télémétrie (Telemetry)"),
        ("group", "Corrections"), ("card", ""), ("fold", "Before / After"), ("fold", "Technical Details")]
    assert [row["count"] for row in backend.model.rows[-2:]] == [1, 2]  # 1 screenshot, 2 technical cards
    assert [chip["label"] for chip in backend.contents] == ["Nouveautés", "Corrections"]
    assert backend.title == "Version 0.15.0" and backend.chip == "New Version"
    assert "4 October 2026" in backend.detail and backend.installVisible
    backend.toggleFold("0:details")
    assert rows(backend)[-5:] == [("fold", "Technical Details"), ("group", "Added"), ("card", ""),
                                  ("group", "SHA256"), ("card", "")]
    card = backend.model.rows[2]
    assert [item["level"] for item in card["items"]] == [0, 1, 0]
    assert '<a href="option:show_apex_speed">' in card["items"][1]["html"]  # option key of an overlay
    backend.toggleFold("0:visuals")
    assert backend.imageList == [{
        "url": "https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/abc123/docs/changes/map.png",
        "caption": "Carte avant / après"}]


def test_page_search(notes_page):
    backend = notes_page().backend
    backend.setSearch("axes")
    assert rows(backend) == [("group", "Nouveautés"), ("card", "Visionneuse de télémétrie (Telemetry)")]
    assert backend.foundCount == 1 and backend.searching
    backend.setSearch("b31940e")  # technical details searched too, fold opened
    assert rows(backend)[-1] == ("card", "") and rows(backend)[0] == ("fold", "Technical Details")
    backend.setSearch("téléMETRIE")  # case & accents folded
    assert backend.foundCount == 1
    backend.setSearch("nothing here")
    assert rows(backend) == [] and backend.foundCount == 0
    backend.setSearch("")
    assert len(rows(backend)) == 7


def test_several_versions_and_version_menu(notes_page, changelog_here):
    from neopedal.update import ChangelogEntry

    earlier = [ChangelogEntry("0.14.1", (2026, 10, 3), "- Fix"), ChangelogEntry("0.14.0", (0, 0, 0), "- Old")]
    backend = notes_page(earlier=earlier).backend
    versions = [row for row in backend.model.rows if row["kind"] == "version"]
    assert [row["title"] for row in versions] == ["Version 0.15.0", "Version 0.14.1", "Version 0.14.0"]
    assert versions[1]["subtitle"] == "3 October 2026"
    assert [chip["label"] for chip in backend.contents] == ["0.15.0", "0.14.1", "0.14.0"]
    assert "3 versions" in backend.detail
    menu = backend.versions
    assert menu[0] == {"key": "", "label": "0.14.0 → 0.15.0"}
    assert [choice["key"] for choice in menu[1:]] == ["0.26.0", "0.25.1", "0.25.0"]  # local changelog
    backend.showVersion("0.25.1")
    assert backend.title == "Version 0.25.1" and backend.chip == "" and rows(backend) == [("card", "")]
    assert "18 October 2026" in backend.detail
    backend.showVersion("")
    assert backend.chip == "New Version" and len([row for row in backend.model.rows if row["kind"] == "version"]) == 3


def test_overlays_named_by_card_titles(notes_page, monkeypatch):
    from neopedal.module_control import wctrl
    from neopedal.setting import cfg
    from neopedal.ui.quick.release_backend import overlay_labels, overlays_named

    labels = overlay_labels()
    assert overlays_named("Relative Finish Order and Standings", labels) == ["relative_finish_order", "standings"]
    assert overlays_named("Darker panels and opacity of all overlays", labels) == []
    assert overlays_named("Flag: new alerts", labels) == ["flag"]
    notes = "### New\n\n#### Flag: new alerts\n\n- Penalty chip (`show_penalty`)\n"
    cfg.user.setting["flag"]["enable"] = False
    backend = notes_page(notes=notes).backend
    card = backend.model.rows[-1]
    assert card["overlays"] == ["flag"] and backend.enabledOverlays == []
    turned_on = []
    monkeypatch.setattr(type(wctrl), "set_enabled", lambda self, names, enable: turned_on.append((list(names), enable))
                        or cfg.user.setting["flag"].update(enable=enable))
    backend.tryOverlay("flag")
    assert turned_on == [(["flag"], True)] and backend.enabledOverlays == ["flag"]


def test_option_links_open_the_option(notes_page, monkeypatch):
    from neopedal.ui import option_finder

    backend = notes_page().backend
    opened = []
    monkeypatch.setattr(option_finder, "open_option", lambda parent, entry: opened.append((entry.section, entry.key)))
    backend.openLink("option:show_apex_speed", "")  # one overlay has it
    assert opened == [("corner_coach", "show_apex_speed")]
    searched = []

    class Finder:
        def __init__(self, parent):
            pass

        def show(self):
            pass

        def shown_dialog(self):
            return self

        def set_search(self, text):
            searched.append(text)

    monkeypatch.setattr(option_finder, "OptionFinder", Finder)
    key = "show_background"
    owners = [entry.section for entry in backend.option_entries(key)]
    assert len(owners) > 1
    backend.openLink(f"option:{key}", "")  # several overlays have it: Find Option
    assert searched == [key]
    backend.openLink(f"option:{key}", f"other,{owners[1]}")  # card of an overlay having it: its option
    assert opened[-1] == (owners[1], key) and searched == [key]
    assert "Open option" in backend.optionTip(f"option:{key}")


def test_screenshots_loaded_in_turn(notes_page, monkeypatch, tmp_path):
    from PySide6.QtGui import QImage

    from neopedal.ui.quick import release_backend

    image = QImage(400, 100, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    shot = tmp_path / "shot.png"
    image.save(str(shot))
    missing = SHOT.replace("corner-coach", "missing")
    asked = []

    def changelog_image_file(url):
        asked.append(url)
        if url == missing:
            raise OSError("offline")
        return str(shot)

    monkeypatch.setattr(release_backend, "changelog_image_file", changelog_image_file)
    backend = notes_page(notes=f"### Coach\n\n- Coaching\n\n![Coach]({SHOT})\n\n![Absente]({missing})\n\n"
                               f"![Later]({SHOT.replace('coach', 'later')})\n").backend
    for url in (SHOT, missing, SHOT.replace("coach", "later")):  # delegates built (list near the view)
        backend.requestImage(url)
    backend.requestImage(SHOT)  # asked again: loaded once
    backend.dropImage(SHOT.replace("coach", "later"))  # delegate gone before its turn: not loaded
    deadline = time.monotonic() + 10
    while backend.jobs.running or backend._image_queue:
        QCoreApplication.processEvents()
        assert time.monotonic() < deadline, "screenshots not loaded"
        time.sleep(0.01)
    QCoreApplication.processEvents()
    assert backend.images[SHOT]["status"] == "ready" and (backend.images[SHOT]["width"], backend.images[SHOT]["height"]) == (400, 100)
    assert backend.images[SHOT]["source"].endswith("shot.png")
    assert backend.images[missing] == {"status": "failed"}
    assert asked == [SHOT, missing]  # one at a time, in request order
    opened = []
    monkeypatch.setattr(release_backend.QDesktopServices, "openUrl", opened.append)
    backend.openImage(SHOT)
    backend.openImage(missing)
    assert opened[0].toLocalFile() == str(shot).replace("\\", "/") and opened[1].toString() == missing


def test_prompt_install(notes_page):
    from neopedal.i18n import tr

    dialog = notes_page(can_install=True, prompt=True)
    asked = []
    dialog.install_requested.connect(lambda: asked.append(1))
    backend = dialog.backend
    assert backend.installVisible and backend.installText == tr("Install Now") and backend.closeText == tr("Later")
    backend.install()
    assert not asked  # queued: runs once QML handled the click
    QCoreApplication.processEvents()
    assert asked


def test_running_version_has_nothing_to_install(notes_page, changelog_here):
    dialog = notes_page(current=True)
    backend = dialog.backend
    assert not backend.installVisible and not backend.skipVisible and backend.chip == ""
    assert "Installed version" not in backend.detail
    after_update = notes_page(current=True, since="0.14.0").backend
    assert "Updated from 0.14.0" in after_update.detail


def test_show_after_update_switch(notes_page):
    from neopedal.setting import cfg

    backend = notes_page().backend
    assert backend.showAfterUpdate
    backend.setShowAfterUpdate(False)
    assert not cfg.application["show_release_notes_after_update"] and not backend.showAfterUpdate


def test_update_messages_translated():
    from neopedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("New Updates: v0.15.0 (2026-10-4)") == "Nouvelle version : v0.15.0 (2026-10-4)"
        assert i18n.trm("No Updates Available") == "Aucune mise à jour disponible"
    finally:
        i18n.set_language("English")


def test_notify_button_opens_notes(ui_env, monkeypatch):
    from neopedal.ui import notification
    from neopedal.ui.release_notes import ReleaseNotesDialog
    from neopedal.update import ChangelogEntry, update_checker

    monkeypatch.setattr(update_checker, "release_notes", NOTES)
    monkeypatch.setattr(update_checker, "earlier_entries", {"en": [ChangelogEntry("0.14.0", (0, 0, 0), "- Old")]})
    opened = []
    monkeypatch.setattr(ReleaseNotesDialog, "open", lambda self: opened.append(self))
    button = notification.UpdatesNotifyButton("v0.15.0")
    try:
        button.show_release_notes()
        assert opened and len(opened[0].backend._releases) == 2  # skipped version follows
        installs = []
        monkeypatch.setattr(button, "download_update", lambda: installs.append(button._auto_install))
        opened[0].install_requested.emit()
        assert installs == [True]  # install asked from notes: no second question
    finally:
        for dialog in opened:
            dialog.close()
            dialog.deleteLater()
        button.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_shown_as_page(ui_env, monkeypatch):
    """Inside the app: page title & Close button of page only"""
    from PySide6.QtWidgets import QApplication

    from neopedal.setting import cfg
    from neopedal.ui import app as app_module
    from neopedal.ui.release_notes import ReleaseNotesDialog

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    window = app_module.AppWindow()
    try:
        window.resize(1800, 900)
        window.show()
        dialog = ReleaseNotesDialog(window, NOTES, (0, 15, 0), (2026, 10, 4))
        dialog.open()
        QApplication.processEvents()
        assert dialog.in_app_page and not dialog.backend.closeVisible  # page has its own Close
        assert dialog.backend.page_visible
        dialog.close()
    finally:
        window.hide()
        window.deleteLater()


def test_notes_shown_after_update(ui_env, changelog_here, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from neopedal.setting import cfg
    from neopedal.ui import app as app_module
    from neopedal.ui.release_notes import ReleaseNotesDialog

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    cfg.application["last_run_version"] = "0.25.0"
    window = app_module.AppWindow()
    try:
        window.show()
        window.first_launch_steps()
        QApplication.processEvents()
        dialog = window.findChild(ReleaseNotesDialog)
        assert dialog is not None and dialog.in_app_page
        assert [release.version for release in dialog.backend._releases] == [(0, 26, 0), (0, 25, 1)]
        assert "Updated from 0.25.0" in dialog.backend.detail and cfg.application["last_run_version"] == "0.26.0"
        dialog.close()
        QApplication.processEvents()
        window.first_launch_steps()  # started again: not shown again
        QApplication.processEvents()
        assert window.findChild(ReleaseNotesDialog) is None or not window.findChild(ReleaseNotesDialog).isVisible()
    finally:
        window.hide()
        window.deleteLater()


def test_download_in_browser_when_app_cannot_install(notes_page, monkeypatch):
    from neopedal.ui import release_notes

    opened = []
    monkeypatch.setattr(release_notes.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    dialog = notes_page(download_url="https://github.com/x/releases/download/v0.15.0/Setup.exe")
    asked = []
    dialog.install_requested.connect(lambda: asked.append(1))
    dialog.request_install()
    assert opened == ["https://github.com/x/releases/download/v0.15.0/Setup.exe"] and not asked
    other = notes_page()  # no installer: release page
    other.request_install()
    assert opened[-1].endswith("/releases")
