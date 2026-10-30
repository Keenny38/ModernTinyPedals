"""Security audit 2026-10-29, lot A: names & texts from the game, results, shared files & downloaded sheets shown as
plain text in QML pages (never rich text images, links, fonts), QML pages without network, page links opened by
scheme, values of Qt Widgets rich text messages escaped"""

import http.server
import re
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlImageProviderBase
from PySide6.QtQuick import QQuickImageProvider, QQuickItem
from PySide6.QtWidgets import QMessageBox, QWidget

from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401
from tests.test_qml_lint import blank, blocks, line_of, own_binding

QML_FOLDER = Path(__file__).resolve().parent.parent / "neopedal" / "ui" / "qml"
HOSTILE_HTTP = '<img src="http://203.0.113.5/a">'
HOSTILE_UNC = '<img src="file://203.0.113.5/a">'

# Text of a literal: "text", 'text', i18n.tr("text") (& joined with +): the app's own words
LITERAL = re.compile(
    r'\s*(?:(?:"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|(?:i18n\.tr|i18n\.trm|qsTr)\(\s*"(?:[^"\\\n]|\\.)*"\s*\))'
    r"\s*\+?\s*)+")
# Controls of the Basic style drawing their text with an IconLabel (AutoText, without QML context: an <img> in the
# text crashes the app): own contentItem needed for a text that is not a literal
ICON_LABEL_CONTROLS = ("Button", "ToolButton", "RoundButton", "DelayButton", "MenuItem", "ItemDelegate", "TabButton",
                       "CheckDelegate", "RadioDelegate", "SwitchDelegate", "SwipeDelegate", "MenuBarItem")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()  # made by conftest


def literal(value: str) -> bool:
    return bool(LITERAL.fullmatch(value)) and not value.rstrip().endswith("+")


def text_violations(text: str) -> list[tuple[int, str]]:
    """(line, value) of texts that QML could read as rich text without the page meaning it"""
    code = blank(text)
    found = []
    first_object = code.find("{")
    for kind in ("Text", "Label"):
        for start, end in blocks(code, kind):
            if own_binding(code, start, end, "textFormat") is not None:
                continue
            # Text made a component (inline or root of its file): text given by each use, its format said here
            if start - 1 == first_object or re.search(rf"\bcomponent\s+\w+\s*:\s*{kind}[ \t]*\{{$", code[:start]):
                found.append((line_of(text, start), f"{kind} component"))
                continue
            binding = own_binding(code, start, end, "text")
            if binding is None:  # text set through an alias (property alias text: label.text)
                ident = re.search(r"(?:^|[{;\s])id[ \t]*:[ \t]*(\w+)", code[start:end])
                if ident and re.search(rf"\b{ident.group(1)}\.text\b", code):
                    found.append((line_of(text, start), f"{kind} {ident.group(1)} (alias)"))
                continue
            value = text[binding[0]:binding[1]]
            if not literal(value):
                found.append((line_of(text, binding[0]), value.strip()))
    for kind in ICON_LABEL_CONTROLS:
        for start, end in blocks(code, kind):
            binding = own_binding(code, start, end, "text")
            if (binding and not literal(text[binding[0]:binding[1]])
                    and own_binding(code, start, end, "contentItem") is None):
                found.append((line_of(text, start), f"{kind} without contentItem"))
    for start, end in blocks(code, "ToolTip"):  # TpToolTip: plain text, or StyledText said explicitly
        if own_binding(code, start, end, "contentItem") is None:
            found.append((line_of(text, start), "ToolTip {} (TpToolTip)"))
    for start, end in blocks(code, "Menu"):  # Basic MenuItem delegates: IconLabel
        if own_binding(code, start, end, "delegate") is None:
            found.append((line_of(text, start), "Menu {} without delegate (TpMenu)"))
    return found


# Ratchet: every text bound to a value says its format
def test_qml_texts_of_values_have_explicit_format():
    unexpected = []
    for path in sorted(QML_FOLDER.rglob("*.qml")):
        for line, value in text_violations(path.read_text(encoding="utf-8")):
            unexpected.append(f"{path.name}:{line}: {value[:100]}")
    assert not unexpected, "textFormat: Text.PlainText (or escaped StyledText) needed:\n" + "\n".join(unexpected)


def test_text_rule_catches_patterns():
    page = """Item {
    Text { text: "Literal" }
    Text { text: i18n.tr("Lap") + " · " + i18n.tr("Time") }
    Text { text: row.driver }
    Text { text: row.driver; textFormat: Text.PlainText }
    Text {
        text: page.ready ? row.team
                         : i18n.tr("None")
    }
    Text {
        text: "<b>" + page.esc(row.name) + "</b>"
        textFormat: Text.StyledText
    }
    property alias label: shown.text
    Text { id: shown }
    Text { id: unused }
    Button { text: row.name }
    Button { text: i18n.tr("OK") }
    ItemDelegate { text: row.name; contentItem: Text { text: parent.text; textFormat: Text.PlainText } }
    ToolTip { text: "x" }
    Menu { Action { text: row.name } }
    Item { ToolTip.text: row.name }  // shared tooltip: plain text set by the engine (secure_engine)
    component Cell: Text { color: theme.text }
    component Note: Text { textFormat: Text.StyledText }
}
"""
    found = text_violations(page)
    assert sorted(line for line, _ in found) == [4, 7, 15, 17, 20, 21, 23], found
    assert text_violations("import QtQuick\n// Label of a section\nText { color: theme.text }\n") == \
        [(3, "Text component")]  # root of a component file
    assert text_violations("import QtQuick\nText { color: theme.text; textFormat: Text.PlainText }\n") == []


def test_every_qml_file_compiles(qapp):
    """textFormat lines added to ~540 texts: every file still compiles (a property of a wrong object fails)"""
    from neopedal.ui.quick import QML_FOLDER as FOLDER
    from neopedal.ui.quick import qml_files, register_types

    register_types()
    engine = QQmlEngine()
    engine.addImportPath(FOLDER)
    errors = []
    for path in qml_files():
        component = QQmlComponent(engine, QUrl.fromLocalFile(path))
        if component.isError():
            errors.append(f"{Path(path).name}: {component.errorString()[:300]}")
    broken = QQmlComponent(engine)
    broken.setData(b"import QtQuick\nItem { Item { textFormat: Text.PlainText } }\n", QUrl("broken.qml"))
    assert broken.isError()  # the check sees a property set on the wrong object
    assert not errors, "\n".join(errors)


# Pages of the app: engine without network, shared tooltip in plain text, texts never load images
class CanaryImages(QQuickImageProvider):
    """image://canary/<id>: ids asked (a rich text <img> loads its picture through it)"""

    def __init__(self):
        super().__init__(QQmlImageProviderBase.ImageType.Image)
        self.asked: list[str] = []

    def requestImage(self, image_id, size, requested_size):  # Qt override
        self.asked.append(image_id)
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(0)
        return image


class Hits(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # http.server name
        Hits.hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def web_server():
    """Local web server: base address, paths asked"""
    Hits.hits = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hits)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", Hits.hits
    server.shutdown()
    server.server_close()


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def wait_until(condition, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return True


@pytest.fixture
def make_page(qapp, tmp_path, monkeypatch):
    """QML page of the app (create_quick_view) from QML text of the test, every page folder imported"""
    from neopedal.ui import quick

    made = []

    def make(body: str):
        path = tmp_path / f"Page{len(made)}.qml"
        path.write_text(f"import QtQuick\nimport QtQuick.Controls.Basic\n{quick.qml_folder_imports()}\n{body}\n",
                        encoding="utf-8")
        index = quick.qml_path
        monkeypatch.setattr(quick, "qml_path", lambda name: str(path) if name == path.name else index(name))
        parent = QWidget()
        parent.resize(500, 300)
        view = quick.create_quick_view(parent, path.name, {})
        view.resize(500, 300)
        parent.show()
        made.append(parent)
        assert not view.errors(), [error.toString() for error in view.errors()]
        return view

    yield make
    for parent in made:
        parent.hide()
        parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def tooltip_format(engine: QQmlEngine) -> int:
    component = QQmlComponent(engine)
    component.setData(b"import QtQuick\nimport QtQuick.Controls.Basic\n"
                      b"Item { readonly property int format: ToolTip.toolTip.contentItem.textFormat }\n", QUrl("f.qml"))
    probe = component.create()
    try:
        return int(probe.property("format"))
    finally:
        probe.deleteLater()


def test_page_engines_show_shared_tooltip_as_plain_text(make_page):
    first, second = make_page("Item { ToolTip.text: 'x' }"), make_page("Item {}")
    plain = 0  # Text.PlainText
    assert tooltip_format(first.engine()) == plain and tooltip_format(second.engine()) == plain
    assert tooltip_format(QQmlEngine()) != plain  # Basic style default: AutoText (what secure_engine changes)


def test_page_engine_loads_nothing_from_network(make_page, web_server):
    """A rich text <img> of a page asks no web server (address leak, tracking), unlike a plain engine"""
    from PySide6.QtQuickWidgets import QQuickWidget

    base, hits = web_server
    body = f'Item {{ Text {{ text: "<img src=\\"{base}/page.png\\"> x"; textFormat: Text.StyledText }} }}'
    make_page(body)
    process_events(1.0)
    assert hits == []
    # Same text in an engine of its own (no secure_engine): the server is asked, so the check above can fail
    parent = QWidget()
    plain = QQuickWidget(parent)
    plain.engine().addImportPath(str(QML_FOLDER))
    component = QQmlComponent(plain.engine())
    component.setData(f"import QtQuick\n{body.replace('page.png', 'plain.png')}\n".encode(), QUrl("plain.qml"))
    item = component.create()
    try:
        assert wait_until(lambda: hits == ["/plain.png"])
    finally:
        item.deleteLater()
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_offline_network_refuses_any_host_at_once(qapp, web_server):
    from neopedal.ui.quick import OfflineNetworkFactory

    base, hits = web_server
    parent = QWidget()
    manager = OfflineNetworkFactory().create(parent)
    replies = [manager.get(QNetworkRequest(QUrl(url))) for url in ("http://203.0.113.5/a", "https://203.0.113.5/a",
                                                                   f"{base}/local.png")]
    started = time.monotonic()
    assert wait_until(lambda: all(reply.isFinished() for reply in replies), 5.0)
    assert time.monotonic() - started < 3.0  # refused without trying the host (no connection timeout)
    assert all(reply.error() != QNetworkReply.NetworkError.NoError for reply in replies)
    assert hits == []
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_plain_texts_of_components_never_load_images(make_page):
    """Shared components showing names (notice, toast, confirm, tooltip, chips): an <img> stays text"""
    view = make_page("""Item {
    property string name: ""
    TpNotice { objectName: "notice"; text: parent.name }
    TpToast { objectName: "toast"; text: parent.name }
    TpToolTip { objectName: "tip"; visible: true; text: parent.name }
    TpChip { objectName: "chip"; text: parent.name }
    Text { objectName: "styled"; text: ""; textFormat: Text.StyledText }
}""")
    canary = CanaryImages()
    view.engine().addImageProvider("canary", canary)
    root = view.rootObject()
    texts = [item for item in root.findChildren(QQuickItem) if item.metaObject().className().startswith("QQuickText")]
    root.setProperty("name", '<img src="image://canary/name"> Driver')
    process_events(0.5)
    assert canary.asked == []
    shown = [item.property("text") for item in texts]
    assert shown.count('<img src="image://canary/name"> Driver') >= 3  # notice, toast, chip: the name itself
    # Control: the same <img> in a styled text is loaded through the canary
    root.findChild(QQuickItem, "styled").setProperty("text", '<img src="image://canary/control"> x')
    assert wait_until(lambda: canary.asked == ["control"])


def test_hostile_names_stay_text_in_the_page(make_page):
    """Names with an <img> of a web or file share address: shown as text, nothing loaded"""
    view = make_page("""Item {
    property string name: ""
    readonly property bool plain: nameText.textFormat === Text.PlainText
    Text { id: nameText; objectName: "name"; text: parent.name; textFormat: Text.PlainText }
}""")
    item = view.rootObject().findChild(QQuickItem, "name")
    assert view.rootObject().property("plain")  # checked before a file share address is shown
    view.rootObject().setProperty("name", "x")
    process_events(0.05)
    width_one = item.property("implicitWidth")
    for name in (HOSTILE_HTTP, HOSTILE_UNC):
        view.rootObject().setProperty("name", name)
        process_events(0.05)
        assert item.property("text") == name
        assert item.property("implicitWidth") > width_one * 10  # tag drawn as characters, not an image


def visual_items(root: QQuickItem) -> list[QQuickItem]:
    """Items drawn under root (delegates of lists included)"""
    found, todo = [], [root]
    while todo:
        item = todo.pop()
        found.append(item)
        todo.extend(item.childItems())
    return found


def test_director_page_shows_hostile_driver_names_as_text(director_page):  # noqa: F811
    page = director_page
    canary = CanaryImages()
    engine = page.view.engine()
    engine.addImageProvider("canary", canary)
    hostile = '<img src="image://canary/driver">'
    team = '<img src="image://canary/team"><font size=7>'
    poll(page, race_answers(100.0, car(1, 1, driver=hostile, team=team), car(2, 2, distance=900.0)))
    page.resize(1400, 900)
    page.show()  # car list, standings & desk drawn
    process_events(0.5)
    rows = [page.backend.carRows.rows[index] for index in range(page.backend.carRows.rowCount())]
    assert any(row["driver"] == hostile for row in rows)
    shown = [item for item in visual_items(page.view.rootObject()) if item.property("text") == hostile]
    assert shown  # driver name drawn by the page
    assert canary.asked == []
    # Control: the canary is asked by a styled text of the same engine
    component = QQmlComponent(engine)
    component.setData(b'import QtQuick\nText { text: "<img src=\\"image://canary/control\\"> x"; '
                      b"textFormat: Text.StyledText }\n", QUrl("control.qml"))
    control = component.create()
    try:
        assert wait_until(lambda: "control" in canary.asked)
        assert "driver" not in canary.asked and "team" not in canary.asked
    finally:
        control.deleteLater()


# Links of pages
@pytest.fixture
def opened(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


def test_web_links_open_only_web_schemes(qapp, opened):
    from neopedal.ui.quick import open_web_link

    refused = ("search-ms:query=x&crumb=location:\\\\evil\\s", "file:///C:/Windows/System32/calc.exe",
               "file://203.0.113.5/s/a.exe", "ms-settings:privacy", "javascript:alert(1)", "\\\\evil\\s\\a.exe",
               "https://", "", "option:show_speed")
    for link in refused:
        assert not open_web_link(link), link
    assert not open_web_link("http://example.com/a")  # https only by default
    assert open_web_link(" https://www.youtube.com/@ohne_speed ")
    assert open_web_link("http://example.com/a", ("https", "http"))
    assert opened == ["https://www.youtube.com/@ohne_speed", "http://example.com/a"]


def test_release_notes_links_web_or_option_only(qapp, opened, monkeypatch):
    from neopedal.ui.quick.release_backend import ReleaseNotesBackend

    options = []
    monkeypatch.setattr(ReleaseNotesBackend, "open_option", lambda self, key, overlays: options.append(key))
    backend = ReleaseNotesBackend.__new__(ReleaseNotesBackend)  # links only: no page state needed
    for link in ("search-ms:query=x", "file:///C:/a.exe", "https://github.com/a", "http://example.com/b",
                 "option:show_speed"):
        ReleaseNotesBackend.openLink(backend, link, "")
    assert opened == ["https://github.com/a", "http://example.com/b"] and options == ["show_speed"]


class SheetStub:
    """What StatsCore.referenceText reads"""

    def __init__(self, updated: str):
        from types import SimpleNamespace

        self.references = SimpleNamespace(entries=[1], updated=updated)
        self._downloading = False
        self.reference_error = ""

    @staticmethod
    def viewer_config():
        return {"enable_lap_reference": True}


def test_community_sheet_date_is_text_and_its_links_https_only(qapp, opened):
    from neopedal.ui.quick.stats_core import StatsCore

    hostile = "<a href='search-ms:query=x&crumb=location:\\\\evil\\s'>2026-10-29</a><img src='//evil/a'>"
    text = StatsCore.referenceText.fget(SheetStub(hostile))
    assert "<img" not in text and text.count("<a ") == 1  # only the source link of the app
    assert "&lt;img src=" in text and "&lt;a href=" in text  # the sheet's cell shown as text
    StatsCore.openLink(None, "search-ms:query=x&crumb=location:\\\\evil\\s")
    StatsCore.openLink(None, "https://www.youtube.com/@ohne_speed")
    assert opened == ["https://www.youtube.com/@ohne_speed"]


def test_driver_stats_page_opens_links_through_backend():
    page = (QML_FOLDER / "analysis" / "DriverStats.qml").read_text(encoding="utf-8")
    assert "openUrlExternally" not in page and "backend.openLink(link)" in page
    for path in QML_FOLDER.rglob("*.qml"):  # links of rich texts go to a backend slot checking the scheme
        for handler in re.findall(r"onLinkActivated:[^\n]*", path.read_text(encoding="utf-8")):
            assert "openUrlExternally" not in handler, path.name


# Rich text messages of Qt Widgets & status lines
def test_safe_markup_keeps_only_style_tags():
    from neopedal.ui import message_text, safe_markup

    assert safe_markup("Exported <b>a.csv</b><br>to <i>x</i> <code>1f</code>") == \
        "Exported <b>a.csv</b><br>to <i>x</i> <code>1f</code>"
    shown = safe_markup(f"Unable to import package:<br>{HOSTILE_UNC} <font size=7>x</font> <a href='file:x'>y</a>")
    assert "<img" not in shown and "<font" not in shown and "<a " not in shown
    assert shown.startswith("Unable to import package:<br>&lt;img src=")
    assert safe_markup("Tom &amp; Jerry & <b>Co</b>") == "Tom &amp; Jerry &amp; <b>Co</b>"  # escaped once
    assert safe_markup(safe_markup(HOSTILE_HTTP)) == safe_markup(HOSTILE_HTTP)
    assert message_text("Plain text: a < b & c") == "Plain text: a < b & c"  # plain message as is
    assert message_text(f"Unable to rename: {HOSTILE_HTTP}") == f"Unable to rename: {safe_markup(HOSTILE_HTTP)}"


def test_confirm_box_and_toast_escape_values(qapp):
    from PySide6.QtWidgets import QLabel

    from neopedal.ui._common import confirm_box
    from neopedal.ui.toast import show_toast

    box, _ = confirm_box(None, "Confirm", f"Move replay <b>{HOSTILE_UNC}</b> to the recycle bin?", "Move")
    assert "<img" not in box.text() and "<b>&lt;img" in box.text()
    box.deleteLater()
    window = QWidget()
    toast = show_toast(window, f"Exported: <b>{HOSTILE_HTTP}</b>")
    assert isinstance(toast, QLabel) and "<img" not in toast.text() and toast.text().startswith("Exported: <b>&lt;img")
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_lap_viewer_status_escapes_values(qapp):
    from neopedal.ui.quick.lap_backend import LapViewerBackend

    status = LapViewerBackend.__new__(LapViewerBackend)

    class Timer:
        def start(self):
            pass

        stop = start

    status._status_timer = Timer()
    status.notify_status = lambda: None
    LapViewerBackend.set_status(status, f"MoTeC log imported: <b>{HOSTILE_UNC}.ld</b>")
    assert status._status == f"MoTeC log imported: <b>{safe(HOSTILE_UNC)}.ld</b>"


def safe(text: str) -> str:
    from neopedal.ui import safe_markup

    return safe_markup(text)


def test_preset_package_import_error_escaped(ui_env, monkeypatch):
    """Finding 7: names of ZIP entries in the error (rich text message) are text"""
    from PySide6.QtWidgets import QFileDialog

    from neopedal.ui import preset_view

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: shown.append(args[2])))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: ("pack.zip", "")))

    def refused(*args, **kwargs):
        raise ValueError(f"not allowed entry: {HOSTILE_UNC}.json")

    monkeypatch.setattr(preset_view, "import_preset_package", refused)
    monkeypatch.setattr(preset_view.PresetList, "refresh", lambda self, *args: None)
    widget = preset_view.PresetList.__new__(preset_view.PresetList)
    QWidget.__init__(widget)
    try:
        preset_view.PresetList.import_package(widget)
    finally:
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(shown) == 1 and "<img" not in shown[0] and "&lt;img src=" in shown[0]


def test_plugin_install_error_escaped(ui_env, monkeypatch):
    """Finding 7: invalid plugin name of a package (rich text message) is text"""
    from neopedal.ui import plugin_manager

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: shown.append(args[2])))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))

    def invalid(filename):
        raise ValueError(f"invalid plugin name: {HOSTILE_HTTP}")

    monkeypatch.setattr(plugin_manager, "install_plugin_package", invalid)
    manager = plugin_manager.PluginManager(None)
    try:
        manager.install_file("plugin.zip")
    finally:
        manager.close()
        manager.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(shown) == 1 and "<img" not in shown[0] and "invalid plugin name: &lt;img src=" in shown[0]
