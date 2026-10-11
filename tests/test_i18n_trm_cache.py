"""Message translation cache (trm memoized, cleared when rules change)"""

import json

import pytest

from tinypedal import i18n

SAMPLES = (
    "Delete <b>race</b> preset permanently?<br><br>This cannot be undone!",
    "<b>Disable</b> all modules?",
    "UI: Legacy Light",
    "Saving section: 45%",
    "Replay recording stopped: [Errno 28] No space left on device",
    "Unknown message stays",
    "",
)


def _uncached(text: str) -> str:
    for pattern, replacement in i18n._message_rules:
        text = pattern.sub(replacement, text)
    return text


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


def test_trm_cached_same_output(french):
    for text in SAMPLES:
        expected = _uncached(text)
        assert i18n.trm(text) == expected
        assert i18n.trm(text) == expected  # cache hit
    assert i18n._translate_message.cache_info().hits >= len(SAMPLES)


def test_trm_non_str_unchanged(french):
    before = i18n._translate_message.cache_info().currsize
    for value in (None, 5, ["Saving section: 45%"]):
        assert i18n.trm(value) is value  # type: ignore[arg-type]
    assert i18n._translate_message.cache_info().currsize == before


def test_trm_cache_cleared_on_language_change(tmp_path):
    text = "Preset imported: <b>x</b>"
    pack = {
        "format": i18n.LANGUAGE_PACK_FORMAT, "code": "xy", "name": "Cachish",
        "messages": [["^Preset imported: ", "Preset importiert: "]],
    }
    (tmp_path / "xy.json").write_text(json.dumps(pack), encoding="utf-8")
    try:
        i18n.set_language("Français")
        french = i18n.trm(text)
        assert french != text
        assert i18n._translate_message.cache_info().currsize > 0
        i18n.set_language("English")
        assert i18n._translate_message.cache_info().currsize == 0
        assert i18n.trm(text) == text
        assert i18n.load_language_packs(str(tmp_path), str(tmp_path / "missing")) == ["Cachish"]
        i18n.set_language("Cachish")
        assert i18n.trm(text) == "Preset importiert: <b>x</b>"
        i18n.set_language("Français")
        assert i18n.trm(text) == french
    finally:
        i18n.set_language("English")
        i18n._LANGUAGES.pop("Cachish", None)
        i18n._packs.pop("xy", None)
        from tinypedal import regex_pattern

        regex_pattern.LANGUAGE_NAMES[:] = list(i18n.LANGUAGES)
