"""Release notes in app language: CHANGELOG.md (English, GitHub release notes) & CHANGELOG.<code>.md"""

import io
import json
import os

import pytest

from tinypedal import update
from tinypedal.ui import home_view

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENGLISH = """# Changelog

Intro.

## 0.20.0 (2026-10-05)

### Overlays

- **Delta graph** added.

## 0.19.1 (2026-10-05)

- Windows build fixed.
"""

FRENCH = """# Journal

## 0.20.0 (2026-10-05)

### Overlays

- **Graphique de delta** ajouté.
"""


def test_changelog_sections():
    assert [name for name, _ in update.changelog_sections(ENGLISH)] == ["0.20.0", "0.19.1"]
    assert update.changelog_section(ENGLISH, "0.19.1") == "- Windows build fixed."
    assert update.changelog_section(ENGLISH, "0.18.0") == ""
    assert update.changelog_sections("no section") == []


def test_localized_changelog_name():
    assert update.localized_changelog_name("fr") == "CHANGELOG.fr.md"
    assert update.localized_changelog_name("pt_BR", "docs/CHANGELOG.md") == "docs/CHANGELOG.pt_BR.md"
    assert update.localized_changelog_name("en") == "CHANGELOG.md"
    assert update.localized_changelog_name("../x") == "CHANGELOG.md"  # never a path


def test_localize_release_notes():
    notes = "### Overlays\n\n- **Delta graph** added.\n\n## Commits\n\n### Added\n\n- Add delta graph (abc)\n\n### SHA256"
    french = update.localize_release_notes(notes, "### Overlays\n\n- **Graphique de delta** ajouté.\n")
    assert french.startswith("### Overlays\n\n- **Graphique de delta** ajouté.\n\n## Commits\n\n### Added")
    assert "Delta graph" not in french and french.endswith("### SHA256")
    commits_only = "### Fixed\n\n- Fix text (abc)"  # no English changelog section
    assert update.localize_release_notes(commits_only, "- Texte corrigé.") == (
        "- Texte corrigé.\n\n## Commits\n\n### Fixed\n\n- Fix text (abc)")
    assert update.localize_release_notes("", "- Texte corrigé.") == "- Texte corrigé."
    assert update.localize_release_notes(notes, "  \n") == notes  # not translated: English


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_fetch_localized_summary(monkeypatch):
    urls = []

    def urlopen(url, timeout=0):
        urls.append(url)
        if url.endswith("CHANGELOG.fr.md"):
            return FakeResponse(FRENCH.encode())
        raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    summary = update.fetch_localized_summary("Keenny38/ModernTinyPedals", "v0.20.0", "fr")
    assert summary == "### Overlays\n\n- **Graphique de delta** ajouté."
    assert urls == ["https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/v0.20.0/CHANGELOG.fr.md"]
    assert update.fetch_localized_summary("Keenny38/ModernTinyPedals", "v0.19.1", "fr") == ""  # no section
    assert update.fetch_localized_summary("Keenny38/ModernTinyPedals", "v0.20.0", "de") == ""  # 404
    urls.clear()
    assert update.fetch_localized_summary("Keenny38/ModernTinyPedals", "v0.20.0", "en") == ""
    assert update.fetch_localized_summary("Keenny38/ModernTinyPedals", "", "fr") == ""
    assert update.fetch_localized_summary("not a repo", "v0.20.0", "fr") == ""
    assert urls == []  # nothing to fetch


def release_response(tag="v99.0.0", body="### Overlays\n\n- **Delta graph** added.\n\n## Commits\n\n- Add x"):
    return b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps({
        "tag_name": tag, "published_at": "2099-01-02T00:00:00Z", "body": body, "assets": [],
    }).encode()


def test_parse_release_tag():
    assert update.parse_release_tag(release_response("v0.20.0")) == "v0.20.0"
    assert update.parse_release_tag(release_response("../../x")) == ""
    assert update.parse_release_tag(b"") == ""


@pytest.mark.parametrize("language", ["fr", "en"])
def test_update_check_fetches_notes_in_app_language(monkeypatch, language):
    checker = update.UpdateChecker()
    fetched = []

    async def latest(repo):
        return release_response()

    def fetch(repo, tag, code):
        fetched.append((repo, tag, code))
        return "### Overlays\n\n- **Graphique de delta** ajouté."

    monkeypatch.setattr(update, "request_latest_release", latest)
    monkeypatch.setattr(update, "fetch_localized_summary", fetch)
    monkeypatch.setattr(update, "current_language", lambda: language)
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert checker.is_updates() and "Delta graph" in checker.release_notes
    assert checker.notes("en") == checker.release_notes
    if language == "fr":
        assert fetched == [("Keenny38/ModernTinyPedals", "v99.0.0", "fr")]
        assert checker.notes("fr").startswith("### Overlays\n\n- **Graphique de delta** ajouté.\n\n## Commits")
    else:
        assert not fetched and checker.notes("fr") == checker.release_notes  # English for every language


def test_update_check_state_kept_consistent_on_notes_error(monkeypatch):
    """Connection cut while fetching translated notes (HTTPException, not OSError): update still
    notified in English; unexpected error later: no half updated state (update without version)"""
    import http.client

    checker = update.UpdateChecker()

    async def latest(repo):
        return release_response()

    def urlopen(url, timeout=0):
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(update, "request_latest_release", latest)
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(update, "current_language", lambda: "fr")
    assert update.fetch_localized_summary("Keenny38/ModernTinyPedals", "v99.0.0", "fr") == ""
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert checker.is_updates() and checker.latest_version() == (99, 0, 0)
    assert checker.notes("fr") == checker.release_notes

    checker = update.UpdateChecker()

    def fetch(*args):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(update, "fetch_localized_summary", fetch)
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert not checker.is_updates() and checker.release_notes == "" and checker.installer is None
    assert checker.message() == "Unable To Find Updates"


def test_no_update_fetches_nothing(monkeypatch):
    checker = update.UpdateChecker()

    async def latest(repo):
        return release_response(tag="v0.0.1")

    monkeypatch.setattr(update, "request_latest_release", latest)
    monkeypatch.setattr(update, "fetch_localized_summary", lambda *args: pytest.fail("notes not shown"))
    monkeypatch.setattr(update, "current_language", lambda: "fr")
    checker._UpdateChecker__checking("Keenny38/ModernTinyPedals")
    assert not checker.is_updates() and checker.localized_notes == {}


def test_running_version_notes_in_app_language(tmp_path):
    english = tmp_path / "CHANGELOG.md"
    english.write_text(ENGLISH, encoding="utf-8")
    (tmp_path / "CHANGELOG.fr.md").write_text(FRENCH, encoding="utf-8")
    notes = home_view.current_release_notes(str(english), "0.20.0", "fr")
    assert notes == "### Overlays\n\n- **Graphique de delta** ajouté."
    assert home_view.current_release_notes(str(english), "0.20.0", "en").endswith("**Delta graph** added.")
    # Not translated yet: English section of that version, not another French one
    assert home_view.current_release_notes(str(english), "0.19.1", "fr") == "- Windows build fixed."
    # Development version: newest section, in app language
    assert "Graphique de delta" in home_view.current_release_notes(str(english), "0.21.0+2.gabc", "fr")
    # Language without changelog: English
    assert home_view.current_release_notes(str(english), "0.20.0", "de").endswith("**Delta graph** added.")
    assert home_view.current_release_notes(str(tmp_path / "missing.md"), "0.20.0", "fr") == ""


def test_changelog_translations_have_same_versions():
    """Every version of CHANGELOG.md is translated in CHANGELOG.fr.md (and nothing more)"""
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as file:
        english = [name for name, _ in update.changelog_sections(file.read())]
    with open(os.path.join(ROOT, "CHANGELOG.fr.md"), encoding="utf-8") as file:
        french = [name for name, _ in update.changelog_sections(file.read())]
    assert english and english == french
