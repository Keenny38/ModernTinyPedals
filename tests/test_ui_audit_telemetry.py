"""UI/UX audit, telemetry zone (lap viewer, track maps): keyboard reach, loading states, contrast & colorblind
legend, responsive toolbars, confirmations & undo feedback"""

import os
import re

import pytest
from PySide6.QtCore import QObject, Qt

from neopedal.ui.quick import lap_map, qml_path
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import evaluate, find, key, named, opener, wait, warnings  # noqa: F401

ZONE = [
    "LapViewer", "SimpleView", "SessionView", "TraceChart", "XYView", "GCircle", "LapList", "LapFilter", "PlaybackBar",
    "ShowPicker", "MathChannels", "CornerList", "MapCanvas", "MapPanel", "RangeStats", "TrackMap", "TrackMapViewer",
    "TrackPicker", "RecentlyDeleted", "InfoCard", "LapChip", "ComparedLapPicker",
]
TIMES = chr(0xD7)  # speed button suffix (multiplication sign)


def source(name: str) -> str:
    with open(qml_path(name + ".qml"), encoding="utf-8") as file:
        return file.read()


# --- Static rules of zone pages
def test_controls_reached_with_tab():
    """Combos & sliders are Tp controls (Tab focus, click leaves keys to charts); no NoFocus control but the
    reference flag of lap rows (Enter on the row sets reference: no hidden focus stop)"""
    for name in ZONE:
        text = source(name)
        assert not re.search(r"^\s*(Slider|ComboBox|Popup) \{", text, re.M), name
        for line in text.split("\n"):
            if "focusPolicy: Qt.NoFocus" in line:
                assert name == "LapList" and "Enter on the lap row" in line, (name, line)


def test_no_hex_text_colors_and_button_sizes():
    for name in ZONE:
        text = source(name)
        assert not re.search(r'color: "#[0-9A-Fa-f]{6}"', text), name  # theme tokens (backend legend colors)
        assert "implicitHeight: theme.em * 1.8" not in text and "implicitHeight: theme.em * 1.9" not in text, name
        assert "opacity: 0.8\n" not in text or name != "TraceChart", name  # tick values without extra fading
    info = source("TrackMapViewer")
    assert '"#38BDF8"' not in info and '"#F97316" : page.current.slope' not in info


def test_loading_states_never_tell_not_recorded_while_reading():
    for name in ("TraceChart", "TrackMap", "GCircle", "CornerList", "XYView", "SimpleView", "SessionView", "LapList"):
        assert "TpStateView" in source(name) and "backend.loading" in source(name), name


# --- Map legend from backend: same colors as lines, colorblind palette for pedals
def test_map_legend_items_and_colorblind_pedals():
    pedals = {item["label"]: item["color"] for item in lap_map.legend_items("pedals")}
    assert len(pedals) == 4
    colorblind = lap_map.legend_items("pedals", True)
    assert colorblind[0]["color"] == lap_map.PEDAL_COLORS_COLORBLIND["throttle"].name()
    assert colorblind[1]["color"] == lap_map.PEDAL_COLORS_COLORBLIND["brake"].name()
    assert [item["label"] for item in lap_map.legend_items("gear")] == [str(gear) for gear in range(1, 9)]
    assert len(lap_map.legend_items("gain", True)) == 2 and lap_map.legend_items("laps") == []
    assert lap_map.zone_colors(True)["throttle"] == lap_map.PEDAL_COLORS_COLORBLIND["throttle"].name()
    for dark, light in lap_map.COLORBLIND_TEXT.values():
        assert dark != light


def test_backend_map_legend_carries_items_zones_tones(opener):  # noqa: F811
    backend = opener().backend
    backend.setMapMode("pedals")
    legend = backend.mapLegend
    assert len(legend["items"]) == 4 and set(legend["zones"]) == {"brake", "throttle"} and legend["tones"] == {}
    backend.setMapOption("colorblind", True)
    legend = backend.mapLegend
    assert legend["items"][0]["color"] == lap_map.PEDAL_COLORS_COLORBLIND["throttle"].name()
    assert set(legend["tones"]) == {"loss", "gain"} and len(legend["tones"]["loss"]) == 2
    backend.setMapOption("colorblind", False)


# --- Page behaviour
def test_track_picker_reached_with_tab_and_lap_list_keys(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    track_box = named(view, "trackBox")
    assert track_box.property("focusPolicy") == Qt.FocusPolicy.TabFocus.value
    assert track_box.metaObject().className().startswith("TrackPicker")
    rows = named(view, "lapRows")
    path = evaluate(view, rows, "(function() { for (var i = 0; i < count; i++) { currentIndex = i;"
                                " if (currentItem && currentItem.kind !== 'session') return currentItem.path } return '' })()")
    assert path
    shown = backend.isCompared(path)
    rows.forceActiveFocus()
    wait(0.1)
    key(view, Qt.Key.Key_Space)  # focused list: Space shows / hides the lap under keyboard
    wait(0.3)
    assert backend.isCompared(path) is not shown
    key(view, Qt.Key.Key_Escape)  # keys back to charts
    assert view.quickWindow().activeFocusItem() is not rows


def test_trashed_lap_named_in_toast_with_undo(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    toast = named(view, "lapToast")
    rows = [entry.file.path for entry in backend.entries]
    trashed = []
    backend.lapsTrashed.connect(lambda count, label: trashed.append((count, label)))
    backend.deleteLap(rows[0])
    wait(0.3)
    assert trashed and trashed[0][0] == 1 and trashed[0][1] != ""
    assert toast.property("shown") and trashed[0][1] in toast.property("text")
    assert toast.property("actionText") != ""  # Undo at hand
    backend.undoDelete()
    wait(0.3)
    assert os.path.exists(rows[0])


def test_delete_key_takes_clicked_chip_lap_only(opener, warnings):  # noqa: F811
    """Delete removes the lap of a clicked (pinned) chip, a chip only hovered never decides it"""
    assert "root.chart.pinnedKey" in source("LapList") and "root.chart.highlightKey" not in source("LapList")
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = find(view, lambda item: item.property("lodTier") is not None)[0]
    lap_list = named(view, "lapList")
    keys = [item["key"] for item in backend.legend]
    assert len(keys) > 1
    chart.setProperty("hoverKey", keys[0])
    chart.setProperty("pinnedKey", keys[1])
    wait(0.1)
    evaluate(view, lap_list, "deleteLaps()")
    wait(0.3)
    assert not os.path.exists(keys[1]) and os.path.exists(keys[0])


def test_math_editor_keeps_typed_changes(opener, warnings):  # noqa: F811
    dialog = opener()
    view = dialog.view
    editor = view.rootObject().findChild(QObject, "mathEditor")
    evaluate(view, editor, "open()")
    wait(0.4)
    assert not editor.property("dirty")
    view.rootObject().findChild(QObject, "mathNameField").setProperty("text", "Typed")
    assert editor.property("dirty")
    assert evaluate(view, editor, "closePolicy === 0")  # Popup.NoAutoClose: a click beside keeps typed text
    evaluate(view, editor, "requestClose()")
    wait(0.4)
    discard = view.rootObject().findChild(QObject, "mathDiscardDialog")
    assert discard.property("visible") and editor.property("visible")
    evaluate(view, discard, "accept()")
    wait(0.4)
    assert not editor.property("visible")


def test_show_reset_asks_first(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    shown = list(backend.dashboard.shownChannels)
    backend.setChannelVisible(next(item["key"] for group in backend.dashboard.catalog for item in group["items"]
                                   if not item["shown"] and not item["detail"]), True)
    changed = list(backend.dashboard.shownChannels)
    assert changed != shown
    reset = view.rootObject().findChild(QObject, "showResetDialog")
    evaluate(view, reset, "open()")
    wait(0.3)
    assert list(backend.dashboard.shownChannels) == changed  # nothing reset until accepted
    evaluate(view, reset, "accept()")
    wait(0.3)
    assert list(backend.dashboard.shownChannels) != changed


@pytest.mark.parametrize("speed", [0.5, 1.5])
def test_playback_speed_decimal_separator(opener, warnings, speed):  # noqa: F811
    dialog = opener()
    view = dialog.view
    chart = find(view, lambda item: item.property("lodTier") is not None)[0]
    chart.setProperty("playSpeed", speed)
    wait(0.1)
    point = evaluate(view, chart, "theme.decimalPoint")
    texts = [item.property("text") for item in find(view, lambda item: str(item.property("text") or "").endswith(TIMES))]
    assert f"{int(speed)}{point}5{TIMES}" in texts


# --- Laps told apart without color: same number on lap chips & before each chart value
def test_lap_marks_on_chips_and_values(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = find(view, lambda item: item.property("lodTier") is not None)[0]
    keys = [item["key"] for item in backend.legend]
    assert len(keys) > 1
    assert [evaluate(view, chart, f"lapMark({key!r})") for key in keys] == [str(i + 1) for i in range(len(keys))]
    chips = [item for item in find(view, lambda item: item.property("mark") is not None and item.property("lapColor") is not None)
             if item.isVisible()]
    assert sorted(chip.property("mark") for chip in chips if chip.property("mark")) == sorted(
        str(i + 1) for i in range(len(keys)))
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.3)
    marks = {item.property("text") for item in find(view, lambda item: item.property("text") in [str(i + 1) for i in range(len(keys))]
                                                    and item.isVisible())}
    assert marks  # bubble rows show the lap marks
    assert evaluate(view, chart, "markWidth") > 0


# --- Toolbar fitted to the window: actions into "⋯" instead of disappearing, Show always a button
def test_lap_toolbar_overflows_into_menu(opener, warnings):  # noqa: F811
    dialog = opener()
    view = dialog.view
    dialog.resize(2200, 800)
    wait(0.5)
    more = named(view, "toolbarMore")
    assert not more.isVisible() and named(view, "importButton").isVisible()
    dialog.resize(700, 800)  # page minimum width wins: overflow depends on fonts (bundled fonts loaded or not)
    wait(0.5)
    toolbar = named(view, "lapToolbar")
    assert named(view, "showButton").isVisible()  # pinned
    # Overflows into "⋯" exactly when the full row does not fit (TpToolbar widths themselves: design tokens tests).
    # Modes may come back as QJSValue (Linux): converted. Labels dropped to icons (1) first, then "⋯" (2)
    modes = toolbar.property("modes")
    modes = list(modes.toVariant() if hasattr(modes, "toVariant") else modes)
    assert more.isVisible() == (2 in modes)
    assert more.isVisible() or 1 in modes or toolbar.property("fullWidth") <= toolbar.width() + 0.5
