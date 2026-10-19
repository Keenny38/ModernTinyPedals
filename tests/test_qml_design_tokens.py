"""QML design system: theme tokens & contrast, pages built from tokens (no new hard-coded sizes or colors)"""

import os
import re

import pytest

from neopedal.ui.quick import qml_files as qml_paths
from neopedal.ui.quick import qml_folder_imports

PALETTES = ("Modern Dark", "Modern Light", "Legacy Dark", "Legacy Light")


def qml_files() -> dict[str, list[str]]:
    files = {}
    for path in qml_paths():
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
    assert len(found) <= 11, "\n".join(found)


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
{qml_folder_imports()}
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


# --- Design system rules of the 2026-10-18 audit (ratchets: lower a ceiling when removing raw values)
def element_blocks(element: str) -> list[tuple[str, int, str]]:
    """(file, line, own text) of every `element {` block: properties of the block itself, nested blocks dropped"""
    opening = re.compile(r"(?<![\w.])" + element + r"\s*\{")
    found = []
    for name, lines in qml_files().items():
        text = "\n".join(lines)
        for match in opening.finditer(text):
            depth, own = 0, []
            for char in text[match.end() - 1:]:
                if char == "{":
                    depth += 1
                    if depth == 1:
                        continue
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        break
                if depth == 1:
                    own.append(char)
            found.append((name, text.count("\n", 0, match.start()) + 1, "".join(own)))
    return found


def own_lines(own: str, prop: str) -> list[str]:
    """Lines of a block's own text setting a property (`prop:` at line start or after `;`)"""
    regex = re.compile(r"(?:^|;)\s*" + re.escape(prop) + r"\s*:")
    return [line for line in own.split("\n") if regex.search(line) and not line.strip().startswith("//")]


def test_icon_only_buttons_have_tooltip():
    """Icon only TpButton: tip names it (screen readers) and is shown instead of the glyph without icon font"""
    found = []
    for name, number, own in element_blocks("TpButton"):
        if not own_lines(own, "glyph"):
            continue
        texts = own_lines(own, "text")
        may_be_empty = not texts or any('""' in line for line in texts)
        if may_be_empty and not own_lines(own, "tip") and not own_lines(own, "fallback"):
            found.append(f"{name}:{number}")
    assert len(found) <= ICON_BUTTONS_WITHOUT_TIP, found


def test_clickable_areas_show_pointing_hand():
    """MouseArea handling clicks shows it (cursorShape); chart & drag areas set their own cursor too"""
    found = [f"{name}:{number}" for name, number, own in element_blocks("MouseArea")
             if (own_lines(own, "onClicked") or own_lines(own, "onDoubleClicked")) and not own_lines(own, "cursorShape")]
    assert len(found) <= CLICK_AREAS_WITHOUT_CURSOR, found


def test_text_never_faded_by_opacity():
    """Dim text is theme.dimText at full opacity: opacity under 1 drops text under 4.5:1 (disabled controls
    use theme.disabledOpacity on the whole control, hidden states use 0)"""
    number_regex = re.compile(r"(?<![\w.])0?\.\d+|(?<![\w.])0\.\d+")
    found = []
    for name, number, own in element_blocks("Text"):
        for line in own_lines(own, "opacity"):
            values = [float(value) for value in number_regex.findall(line.split("opacity", 1)[1])]
            if any(0 < value < 1 for value in values):
                found.append(f"{name}:{number}: {line.strip()}")
    assert len(found) <= FADED_TEXTS, found


def test_breakpoints_from_tokens():
    """Page modes switch at theme.bpCompact / bpNarrow / bpWide; content-tuned thresholds say so"""
    found = matches(r"width [<>]=? theme\.em \* \d", skip=lambda lines, index: "content-tuned" in lines[index])
    assert len(found) <= RAW_BREAKPOINTS, "\n".join(found)


def test_tints_from_tokens():
    """Tints come from theme.tint() / tintSubtle / tintSelected / tintStrong, not Qt.rgba with own alphas"""
    found = matches(r"Qt\.rgba\(")
    assert len(found) <= RAW_TINTS, "\n".join(found)


def test_button_heights_from_size():
    """TpButton heights: size "sm" / "xs" (theme.controlHeight*), not own implicitHeight in em"""
    found = [f"{name}:{number}" for name, number, own in element_blocks("TpButton")
             if any("theme.em" in line for line in own_lines(own, "implicitHeight"))]
    assert len(found) <= BUTTON_HEIGHT_OVERRIDES, found


def test_text_sizes_from_font_scale():
    """Text sizes are font tokens (point sizes), not pixel sizes made from em"""
    found = matches(r"font\.pixelSize: (Math\.round\()?theme\.em")
    assert len(found) <= PIXEL_FONT_SIZES, "\n".join(found)


def test_spacing_from_tokens_does_not_grow():
    """Spacing, margins & paddings: theme.space1..6 / padPage / padCard / padPopup; em multiples left only
    where a size is tuned to content. Lower the ceiling when converting some."""
    found = matches(r"\b(spacing|[a-zA-Z]*[mM]argins?|[a-zA-Z]*[pP]adding): theme\.em \*")
    assert len(found) <= EM_SPACINGS, len(found)


def test_every_qml_text_translated():
    """Every i18n.tr("...") text of every QML file has a French translation (comment lines skipped)"""
    from neopedal.i18n.fr import TRANSLATION

    pattern = re.compile(r'i18n\.tr\("((?:[^"\\]|\\.)*)"\)')
    missing = set()
    for name, lines in qml_files().items():
        for line in lines:
            if not line.strip().startswith("//"):
                missing.update(f"{name}: {text}" for text in pattern.findall(line) if text not in TRANSLATION)
    assert not missing, sorted(missing)


ICON_BUTTONS_WITHOUT_TIP = 0
CLICK_AREAS_WITHOUT_CURSOR = 0
FADED_TEXTS = 0
RAW_BREAKPOINTS = 0
RAW_TINTS = 53
BUTTON_HEIGHT_OVERRIDES = 0
PIXEL_FONT_SIZES = 0
EM_SPACINGS = 278


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("colorblind", (False, True))
def test_theme_contrast_on_states(themed, palette, colorblind):
    """Dim text & accent text stay 4.5:1 on hovered, raised & selected rows; status colors 3:1 on cards
    (graphics, bold figures), colorblind variants too"""
    from PySide6.QtGui import QColor

    from neopedal.ui import set_colorblind
    from neopedal.ui.quick import Theme, blended, contrast_ratio

    themed(palette)
    set_colorblind(colorblind)
    try:
        theme = Theme()
        selected = [blended(theme.accent, surface, theme.tintSelected * 4 / 3) for surface in (theme.base, theme.window)]
        for surface in (theme.window, theme.base, theme.raised, theme.hover, *selected):
            assert contrast_ratio(theme.dimText, surface) >= 4.5, surface.name()
        for surface in (theme.window, theme.base, theme.raised):
            assert contrast_ratio(theme.accent, surface) >= 4.5, surface.name()
        assert contrast_ratio(QColor("white"), theme.accentFill.darker(107)) >= 4.5  # accent button hovered
        for color in (theme.gain, theme.loss, theme.warning, theme.purple, theme.gold, theme.live):
            assert contrast_ratio(color, theme.base) >= 3, color.name()
        tinted = blended(theme.loss, theme.base, 0.16)  # "on air" row
        assert contrast_ratio(theme.dimOn(tinted), tinted) >= 4.5
        assert contrast_ratio(theme.stageText, theme.stageTop) >= 4.5
        assert theme.colorblind == colorblind
        if colorblind:
            assert theme.gain.hue() != theme.loss.hue() and abs(theme.gain.hue() - 120) > 40  # not green
    finally:
        set_colorblind(False)


def test_colorblind_option_updates_pages(ui_env):
    """App refresh reads the overlay style option: theme status colors change & notify"""
    from neopedal.ui import colorblind_state, set_colorblind
    from neopedal.ui.quick import Theme

    theme = Theme()
    calls = []
    theme.changed.connect(lambda: calls.append(1))
    normal = theme.gain
    set_colorblind(True)
    try:
        assert calls and theme.gain != normal and colorblind_state().enabled
    finally:
        set_colorblind(False)
    assert theme.gain == normal


@pytest.mark.parametrize("palette", ("Modern Dark", "Legacy Light"))
def test_new_theme_functions_same_in_qml_and_python(themed, palette):
    """tint / dimOn / tone / sessionColor: JavaScript of the theme copy gives the Python slot results"""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick import Theme, create_quick_view

    themed(palette)
    parent = QWidget()
    try:
        view = create_quick_view(parent, "Card.qml", {})
        tones = ("loss", "gain", "fastest", "yellow", "live", "dim", "nothing", "")
        sessions = ("R", "RACE", "q", "PRACTICE", "W", "")
        body = ["import QtQuick", "QtObject {",
                '    property color t0: theme.tint(theme.accent, "selected")',
                '    property color t1: theme.tint(theme.loss, 0.3)',
                '    property color t2: theme.tint(theme.gain, "strong")',
                '    property color d0: theme.dimOn(theme.hover)',
                '    property color d1: theme.dimOn(theme.tint(theme.loss, 0.16))',
                '    property color d2: theme.dimOn(theme.accentFill)']
        body += [f'    property color o{i}: theme.tone("{name}")' for i, name in enumerate(tones)]
        body += [f'    property color s{i}: theme.sessionColor("{code}")' for i, code in enumerate(sessions)]
        body.append("}")
        component = QQmlComponent(view.engine())
        component.setData("\n".join(body).encode(), QUrl("functions.qml"))
        item = component.create(view.rootContext())
        assert item is not None, component.errorString()
        theme = Theme()
        python = {"t0": theme.tint(theme.accent, "selected"), "t1": theme.tint(theme.loss, 0.3),
                  "t2": theme.tint(theme.gain, "strong"), "d0": theme.dimOn(theme.hover),
                  "d1": theme.dimOn(theme.tint(theme.loss, 0.16)), "d2": theme.dimOn(theme.accentFill)}
        python.update({f"o{i}": theme.tone(name) for i, name in enumerate(tones)})
        python.update({f"s{i}": theme.sessionColor(code) for i, code in enumerate(sessions)})
        for key, expected in python.items():
            got = item.property(key)
            assert abs(got.redF() - expected.redF()) < 0.01 and abs(got.greenF() - expected.greenF()) < 0.01, key
            assert abs(got.blueF() - expected.blueF()) < 0.01 and abs(got.alphaF() - expected.alphaF()) < 0.01, key
        assert theme.sessionColor("RACE") == theme.warning and theme.tone("fastest") == theme.purple
    finally:
        parent.deleteLater()


def test_controls_without_icon_font(ui_env, monkeypatch, tmp_path):
    """No icon font (Linux...): icon only buttons show their fallback or tooltip text, menus their ✓"""
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui import app
    from neopedal.ui.quick import Theme, Translator, register_types, theme_copy

    monkeypatch.setattr(app, "icon_font_family", lambda: "")
    register_types()
    wrapper = tmp_path / "noicons.qml"
    wrapper.write_text(f'''import QtQuick
import QtQuick.Controls.Basic
{qml_folder_imports()}
Column {{
    width: 400; height: 300
    TpButton {{ objectName: "plus"; glyph: "\\uE710"; fallback: "+"; tip: "Add lap" }}
    TpButton {{ objectName: "tipped"; glyph: "\\uE710"; tip: "Add lap" }}
    TpButton {{ objectName: "texted"; glyph: "\\uE710"; text: "Add" }}
    Icon {{ objectName: "check"; glyph: "\\uE73E"; fallback: "✓" }}
    Icon {{ objectName: "gone"; glyph: "\\uE73E" }}
}}
''', encoding="utf-8")
    view = QQuickWidget()
    context = view.rootContext()
    context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
    context.setContextProperty("i18n", Translator(view))
    view.setSource(QUrl.fromLocalFile(str(wrapper)))
    try:
        assert not view.errors(), [error.toString() for error in view.errors()]
        root = view.rootObject()
        shown = {name: root.findChild(object, name) for name in ("plus", "tipped", "texted", "check", "gone")}
        assert shown["plus"].property("shownText") == "+"
        assert shown["tipped"].property("shownText") == "Add lap"
        assert shown["texted"].property("shownText") == "Add"
        assert shown["check"].property("text") == "✓" and shown["check"].property("visible")
        assert not shown["gone"].property("visible")
    finally:
        view.setSource(QUrl())
        view.deleteLater()


def test_button_width_same_inside_hidden_parent(ui_env, tmp_path):
    """TpButton size comes from its texts, not from visibility: hidden probe buttons (race calculator header
    levels) measure the same widths as shown ones, else the header level flips forever (page hang)"""
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.quick import Theme, Translator, register_types, theme_copy

    register_types()
    wrapper = tmp_path / "probes.qml"
    wrapper.write_text(f'''import QtQuick
{qml_folder_imports()}
Row {{
    width: 600; height: 60
    TpButton {{ objectName: "shown"; glyph: "x"; text: "Load Live" }}
    Item {{ visible: false; TpButton {{ objectName: "probe"; glyph: "x"; text: "Load Live" }} }}
    TpHeaderCell {{ objectName: "cell"; text: "Laps"; sorted: true }}
    Item {{ visible: false; TpHeaderCell {{ objectName: "hiddenCell"; text: "Laps"; sorted: true }} }}
}}
''', encoding="utf-8")
    view = QQuickWidget()
    context = view.rootContext()
    context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
    context.setContextProperty("i18n", Translator(view))
    view.setSource(QUrl.fromLocalFile(str(wrapper)))
    try:
        assert not view.errors(), [error.toString() for error in view.errors()]
        root = view.rootObject()
        widths = {name: root.findChild(object, name).property("implicitWidth") for name in ("shown", "probe", "cell", "hiddenCell")}
        assert widths["shown"] == widths["probe"] > widths["shown"] / 2
        assert widths["cell"] == widths["hiddenCell"]
    finally:
        view.setSource(QUrl())
        view.deleteLater()


def test_toolbar_texts_then_icons_then_menu(ui_env, tmp_path):
    """TpToolbar: every action with its text when it fits, least important ones icon only, then in the "⋯"
    menu (pinned ones never), back to texts when wide again"""
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.quick import PageState, Theme, Translator, register_types, theme_copy

    register_types()
    wrapper = tmp_path / "toolbar.qml"
    wrapper.write_text(f'''import QtQuick
import QtQuick.Layouts
{qml_folder_imports()}
Item {{
    width: 900; height: 60
    RowLayout {{
        anchors.fill: parent
        TpToolbar {{
            objectName: "bar"
            Layout.fillWidth: true
            TpAction {{ name: "imp"; text: "Import laps"; glyph: "x"; priority: 2 }}
            TpAction {{ name: "exp"; text: "Export"; glyph: "y"; priority: 1 }}
            TpAction {{ name: "live"; text: "Live"; glyph: "z"; checkable: true; priority: 0 }}
            TpAction {{ name: "show"; text: "Show channels"; glyph: "w"; priority: 3; pinned: true }}
        }}
    }}
}}
''', encoding="utf-8")
    view = QQuickWidget()
    view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    context = view.rootContext()
    context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
    context.setContextProperty("i18n", Translator(view))
    context.setContextProperty("pageState", PageState(view))
    view.setSource(QUrl.fromLocalFile(str(wrapper)))
    try:
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.move(-6000, -6000)
        view.show()
        bar = view.rootObject().findChild(object, "bar")

        def modes_at(width):
            view.resize(width, 60)
            for _ in range(5):
                QCoreApplication.processEvents()
            return list(bar.property("modes").toVariant()) if hasattr(bar.property("modes"), "toVariant") else list(bar.property("modes"))

        full = bar.property("fullWidth")
        assert full > 0
        assert modes_at(round(full) + 40) == [0, 0, 0, 0]
        narrow = modes_at(round(full * 0.7))
        # Lowest priority changed first (icon only, or in the menu when icons save little: no icon font)
        assert narrow[2] != 0 and narrow[3] != 2 and all(mode <= narrow[2] for mode in narrow)
        tiny = modes_at(round(full * 0.3))
        assert tiny[3] != 2 and 2 in tiny  # pinned stays, others in the menu
        assert modes_at(round(full) + 40) == [0, 0, 0, 0]
    finally:
        view.setSource(QUrl())
        view.deleteLater()
