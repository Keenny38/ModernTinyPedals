"""QML design system: theme tokens & contrast, pages built from tokens (no new hard-coded sizes or colors)"""

import glob
import os
import re

import pytest

from neopedal.ui.quick import QML_FOLDER

PALETTES = ("Modern Dark", "Modern Light", "Legacy Dark", "Legacy Light")


def qml_files() -> dict[str, list[str]]:
    files = {}
    for path in sorted(glob.glob(os.path.join(QML_FOLDER, "*.qml"))):
        with open(path, encoding="utf-8") as file:
            files[os.path.basename(path)] = file.read().split("\n")
    return files


def matches(pattern: str, skip=None) -> list[str]:
    """file:line of every QML line matching pattern"""
    regex = re.compile(pattern)
    found = []
    for name, lines in qml_files().items():
        for number, line in enumerate(lines, 1):
            if regex.search(line) and not (skip and skip(lines, number - 1)):
                found.append(f"{name}:{number}: {line.strip()}")
    return found


# --- Pages use the token scale
def test_font_sizes_from_scale():
    """theme.fontSmall... not theme.fontPoint * 0.83 (base size alone or scaled by a variable is fine)"""
    assert matches(r"theme\.fontPoint \* [\d(]") == []


def test_radius_from_scale():
    assert matches(r"\bradius: theme\.em \* \d") == []


def test_spacing_in_tenths_of_em():
    """Spacing & margins: multiples of 0.1 em"""
    assert matches(r"\b(spacing|margins|[a-zA-Z]*Margin): theme\.em \* \d+\.\d{2,}") == []


def test_tooltip_delay_and_disabled_opacity_tokens():
    assert matches(r"ToolTip\.delay: \d") == []
    assert matches(r"opacity: enabled \? 1 : \d") == []


def test_short_animations_use_motion_tokens():
    """UI transitions (up to 300 ms) follow theme.motion*: off with Windows animation effects off.
    Looping animations keep a fixed duration (never 0: busy loop), gated by theme.animate instead."""
    def in_loop(lines, index):
        return any("loops:" in line for line in lines[max(0, index - 8): index + 8])

    assert matches(r"\bduration: ([1-9]\d|[12]\d\d|300)\b", skip=in_loop) == []
    for found in matches(r"loops: (Animation\.Infinite|\d)"):
        name, number = found.split(":")[:2]
        lines = qml_files()[name]
        block = "\n".join(lines[max(0, int(number) - 6): int(number)])
        assert "theme.animate" in block or "RotationAnimation" in block, found  # spinners keep turning


def test_hard_coded_colors_do_not_grow():
    """Colors come from theme (semantic tokens: seriesFuel, compound(), inkOn()...). Left: track map
    drawing defaults (user colors), gear & pedal scales, preview backdrops. Lower the ceiling when removing some."""
    found = matches(r'"#[0-9A-Fa-f]{3,8}"')
    assert len(found) <= 55, "\n".join(found)


def test_compound_colors_not_redefined():
    assert matches(r'(Soft|Medium|Hard)\b.*"#[0-9A-Fa-f]{6}"') == []
    assert matches(r'letter === "S" \? "#') == []


def test_search_fields_shared():
    """Search boxes are TpSearchField (debounce, clear button, Esc), not restyled TextFields"""
    assert matches(r'placeholderText: i18n\.tr\("Search', skip=lambda lines, index: not any(
        "TextField {" in line and "Tp" not in line for line in lines[max(0, index - 8): index])) == []


def test_buttons_reachable_with_keyboard():
    files = qml_files()
    for name in ("TpButton.qml", "TpSwitch.qml"):
        text = "\n".join(files[name])
        assert "focusPolicy: Qt.TabFocus" in text and "FocusRing" in text, name
    assert "activeFocusOnTab: true" in "\n".join(files["TpSegmented.qml"])


# --- Theme values
@pytest.fixture
def themed(ui_env):
    from neopedal.ui import set_style_palette

    yield set_style_palette
    set_style_palette("Modern Dark")


@pytest.mark.parametrize("palette", PALETTES)
def test_theme_contrast(themed, palette):
    """Text on window & white text on fills reach WCAG AA (4.5:1), hover shows on buttons"""
    from PySide6.QtGui import QColor

    from neopedal.ui.quick import Theme, contrast_ratio

    themed(palette)
    theme = Theme()
    white = QColor("white")
    assert contrast_ratio(theme.text, theme.window) >= 7
    assert contrast_ratio(theme.dimText, theme.window) >= 4.5
    assert contrast_ratio(theme.dimText, theme.base) >= 4.5
    assert contrast_ratio(theme.accentFill, white) >= 4.5
    assert contrast_ratio(theme.lossFill, white) >= 4.5
    assert contrast_ratio(theme.hover, theme.raised) >= 1.19
    assert theme.accentFill.hue() == pytest.approx(theme.accent.hue(), abs=2)  # same color, darker


def test_fill_for_white_text_keeps_dark_enough_colors():
    from PySide6.QtGui import QColor

    from neopedal.ui.quick import fill_for_white_text

    assert fill_for_white_text(QColor("#1F2328")).name() == "#1f2328"
    assert fill_for_white_text(QColor("#F87171")).name() != "#f87171"


def test_theme_tokens_copied_to_qml(ui_env):
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick import FONT_SCALE, MOTION, RADIUS_SCALE, Theme, create_quick_view

    parent = QWidget()
    try:
        view = create_quick_view(parent, "Card.qml", {})
        theme = view.rootContext().contextProperty("theme")
        original = Theme()
        assert not isinstance(theme, Theme)
        for name in (*FONT_SCALE, *RADIUS_SCALE, *MOTION, "bpWide", "tipDelay", "disabledOpacity", "tintSelected",
                     "monoFont", "animate", "accentFill", "lossFill", "seriesFuel", "silver", "live"):
            assert theme.property(name) == getattr(original, name), name
        assert theme.property("fontSmall") == pytest.approx(original.fontPoint * 0.85)
        assert theme.property("motionBase") in (0, 180)
    finally:
        parent.deleteLater()


@pytest.mark.parametrize("palette", ("Modern Dark", "Modern Light"))
def test_theme_functions_same_in_qml_and_python(themed, palette):
    """compound / inkOn / rowColor: JavaScript of the theme copy gives the Python slot results"""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick import Theme, create_quick_view

    themed(palette)
    parent = QWidget()
    try:
        view = create_quick_view(parent, "Card.qml", {})
        names = ("S", "Medium #2", "Q-Soft", "hard", "Wet", "Intermediate", "Ultrasoft", "??", "",
                 "Hyper - Soft", "Supersoft", "Bias Ply", "x")
        fills = ("#FFCC00", "#1F2328", "#4C8DFF", "#EDEDED")
        rows = ((False, False), (True, False), (False, True), (True, True))
        body = ["import QtQuick", "QtObject {"]
        body += [f'    property color c{i}: theme.compound("{name}")' for i, name in enumerate(names)]
        body += [f'    property string l{i}: theme.compoundLetter("{name}")' for i, name in enumerate(names)]
        body += [f'    property color i{i}: theme.inkOn("{fill}")' for i, fill in enumerate(fills)]
        body += [f"    property color r{i}: theme.rowColor({str(h).lower()}, {str(s).lower()})" for i, (h, s) in enumerate(rows)]
        body.append("}")
        component = QQmlComponent(view.engine())
        component.setData("\n".join(body).encode(), QUrl("functions.qml"))
        item = component.create(view.rootContext())
        assert item is not None, component.errorString()
        theme = Theme()
        for i, name in enumerate(names):
            assert item.property(f"c{i}") == theme.compound(name), name
            assert item.property(f"l{i}") == theme.compoundLetter(name), name
        for i, fill in enumerate(fills):
            assert item.property(f"i{i}") == theme.inkOn(QColor(fill)), fill
        for i, (hovered, selected) in enumerate(rows):
            js, py = item.property(f"r{i}"), theme.rowColor(hovered, selected)
            assert js.rgb() == py.rgb() and js.alphaF() == pytest.approx(py.alphaF(), abs=0.01), (hovered, selected)
    finally:
        parent.deleteLater()


def test_compound_letters_and_light_variants(themed):
    from neopedal.ui.quick import Theme

    themed("Modern Dark")
    theme = Theme()
    assert theme.compound("S").name() == "#ededed" and theme.compound("Soft") == theme.compound("S")
    assert theme.compound("H").name() == "#e5484d" and theme.compound("M").name() == "#f5c518"
    themed("Modern Light")
    assert theme.compound("S").name() == "#777777"  # white soft: gray, else white on white
    assert theme.compound("Unknown") == theme.dimText


def test_compound_badges_same_as_overlays():
    """Tyre compound badges of app pages, Broadcast Director & its stream graphics: letters of overlays'
    default compound symbols, colors of overlays (soft white, hard red), filled squares (no rings, no dots)"""
    from neopedal.stream_director import DIRECTOR_HTML, tyre_badges
    from neopedal.template.setting_compounds import compound_letter, name_color
    from neopedal.ui.quick.director_shared import tyre_letter
    from neopedal.userfile.heatmap import set_predefined_compound_symbol

    for name in ("Soft", "Medium", "Hard", "Wet", "Intermediate", "Supersoft", "Hypersoft", "Bias Ply", "Dry"):
        assert compound_letter(name) == set_predefined_compound_symbol(name) == tyre_letter(name), name
    assert compound_letter("Medium #2") == "M" and compound_letter("Hyper - Soft") == "S" and compound_letter("") == ""
    badges = tyre_badges()
    assert badges["S"][0] == name_color("Soft") == "#EDEDED" and badges["H"][0] == name_color("Hard") == "#E5484D"
    assert badges["S"][1] == "#0E1116" and badges["W"][1] == "#F4F6F9"  # readable letter
    assert "@@tyres@@" in DIRECTOR_HTML and "border-radius:50%;border:" not in DIRECTOR_HTML
    for name in ("DirectorCars.qml", "DirectorTiming.qml", "RaceTyreCell.qml", "RaceTyreTab.qml"):
        assert "compoundColor" not in "\n".join(qml_files()[name]) and "tyreColor(" not in "\n".join(qml_files()[name])
    users = [name for name, lines in qml_files().items() if any("TpCompound" in line for line in lines)]
    assert {"DirectorCars.qml", "DirectorTiming.qml", "DirectorSheet.qml", "RaceTyreCell.qml", "RaceTyreTab.qml",
            "TpCombo.qml", "DriverStats.qml", "ResultsLaps.qml", "RaceLiveTab.qml"} <= set(users)


# --- Keyboard: Tab reaches buttons & switches (ring shown), Enter / Space press, arrows choose a segment
def test_keyboard_focus_and_press(ui_env, tmp_path):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from neopedal.ui.quick import Theme, Translator, register_types, theme_copy

    register_types()
    wrapper = tmp_path / "keys.qml"
    wrapper.write_text(f'''import QtQuick
import "{QUrl.fromLocalFile(QML_FOLDER).toString()}"
Row {{
    property int clicks: 0
    property int chosen: -1
    width: 600; height: 60
    TpButton {{ objectName: "first"; text: "First"; onClicked: parent.clicks++ }}
    TpSwitch {{ objectName: "switch"; text: "Switch" }}
    TpSegmented {{ objectName: "segments"; options: ["A", "B", "C"]; currentIndex: Math.max(parent.chosen, 0); onActivated: function(index) {{ parent.chosen = index }} }}
}}
''', encoding="utf-8")
    view = QQuickWidget()
    view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    context = view.rootContext()
    context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
    context.setContextProperty("i18n", Translator(view))
    view.setSource(QUrl.fromLocalFile(str(wrapper)))
    assert not view.errors(), [error.toString() for error in view.errors()]
    view.resize(600, 60)
    view.show()
    view.activateWindow()
    view.setFocus()
    try:
        root = view.rootObject()
        first, switch, segments = (root.findChild(object, name) for name in ("first", "switch", "segments"))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=first.mapToScene(first.boundingRect().center()).toPoint())
        QApplication.processEvents()
        assert root.property("clicks") == 1 and not first.property("activeFocus")  # click leaves focus alone
        QTest.keyClick(view, Qt.Key.Key_Tab)
        QApplication.processEvents()
        assert first.property("activeFocus") and first.property("visualFocus")
        QTest.keyClick(view, Qt.Key.Key_Return)
        QTest.qWait(200)  # animateClick
        assert root.property("clicks") == 2
        QTest.keyClick(view, Qt.Key.Key_Tab)
        QTest.keyClick(view, Qt.Key.Key_Space)
        QApplication.processEvents()
        assert switch.property("activeFocus") and switch.property("checked")
        QTest.keyClick(view, Qt.Key.Key_Tab)
        QTest.keyClick(view, Qt.Key.Key_Right)
        QTest.keyClick(view, Qt.Key.Key_Right)
        QTest.keyClick(view, Qt.Key.Key_Right)  # past the end: stays on last
        QApplication.processEvents()
        assert segments.property("activeFocus") and segments.property("currentIndex") == 2 and root.property("chosen") == 2
        QTest.keyClick(view, Qt.Key.Key_Home)
        assert segments.property("currentIndex") == 0
    finally:
        view.close()
        view.setSource(QUrl())
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
