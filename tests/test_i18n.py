"""Translation tests"""

import pytest

from tinypedal import i18n
from tinypedal.i18n.fr import TRANSLATION


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


def test_translations_unique():
    """Reverse lookup (menu action dispatch) requires unique translations"""
    values = list(TRANSLATION.values())
    duplicated = {value for value in values if values.count(value) > 1}
    assert not duplicated


def test_english_is_identity():
    i18n.set_language("English")
    assert i18n.tr("Duplicate") == "Duplicate"
    assert i18n.trm("This cannot be undone!") == "This cannot be undone!"


def test_french_roundtrip(french):
    for original, translated in TRANSLATION.items():
        assert i18n.tr(original) == translated
        assert i18n.untr(translated) == original


def test_french_messages(french):
    assert i18n.trm("Delete <b>race</b> preset permanently?<br><br>This cannot be undone!") == (
        "Supprimer définitivement le preset <b>race</b> ?<br><br>Cette action est irréversible !"
    )
    assert i18n.trm("<b>Disable</b> all modules?") == "<b>Désactiver</b> tous les modules ?"
    assert i18n.trm("UI: Dark") == "Thème : sombre"
    assert i18n.trm("Unknown message stays") == "Unknown message stays"


def test_language_pack(tmp_path):
    import json

    from tinypedal import regex_pattern
    from tinypedal.i18n import LANGUAGE_PACK_FORMAT, LANGUAGES, load_language_packs
    from tinypedal.i18n.options import option_label

    pack = {
        "format": LANGUAGE_PACK_FORMAT, "code": "xx", "name": "Testish",
        "ui": {"Config": "Konfig", "Help": ""},
        "messages": [["^Preset imported: ", "Preset importiert: "], ["(", "invalid regex skipped"]],
        "options": {"font_size": "Schriftgrösse"},
    }
    (tmp_path / "xx.json").write_text(json.dumps(pack), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    (tmp_path / "fr.json").write_text(json.dumps({**pack, "code": "fr", "name": "Fake"}), encoding="utf-8")
    try:
        assert load_language_packs(str(tmp_path), str(tmp_path / "missing")) == ["Testish"]
        assert LANGUAGES["Testish"] == "xx" and "Fake" not in LANGUAGES
        assert "Testish" in regex_pattern.LANGUAGE_NAMES  # shown in Language option
        i18n.set_language("Testish")
        assert i18n.tr("Config") == "Konfig"
        assert i18n.tr("Help") == "Help"  # empty translation: English
        assert i18n.trm("Preset imported: <b>x</b>") == "Preset importiert: <b>x</b>"
        assert option_label("font_size") == "Schriftgrösse"
    finally:
        i18n.set_language("English")
        i18n._LANGUAGES.pop("Testish", None)
        i18n._packs.pop("xx", None)
        regex_pattern.LANGUAGE_NAMES[:] = list(LANGUAGES)


def test_language_template_covers_french():
    import sys

    sys.path.insert(0, "tools")
    from make_language_template import build_template

    template = build_template("de", "Deutsch")
    assert set(template["ui"]) == set(TRANSLATION)
    assert template["options"] and all(value == "" for value in template["options"].values())
