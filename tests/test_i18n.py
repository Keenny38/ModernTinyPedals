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
