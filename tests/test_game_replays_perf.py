"""Game Replays page work: panels built when first shown, hidden map not updated nor animated, timeline span
steady while playhead moves, list rows reused with hover-only buttons made on demand"""

from PySide6.QtCore import QCoreApplication

from tests.test_game_info import GAME_ANSWERS, answered, replays_page, wait_requests  # noqa: F401


def items_of(root):
    found, todo = [], [root]
    while todo:
        item = todo.pop()
        found.append(item)
        todo.extend(item.childItems())
    return found


def has_property(view, name) -> list:
    return [item for item in items_of(view.rootObject()) if item.metaObject().indexOfProperty(name) >= 0]


def pump(count=10):
    for _ in range(count):
        QCoreApplication.processEvents()


def test_panels_built_when_shown(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    replays_page.resize(1400, 860)
    replays_page.show()
    pump()
    view = replays_page.view
    assert backend.panelIndex == 0
    assert not has_property(view, "flipY")  # map panel not built
    assert not backend.mapCars.rows  # nor updated while hidden
    backend.setPanel(1)
    pump()
    assert not has_property(view, "flipY") and not backend.mapCars.rows
    backend.setPanel(2)  # shown: map cars at once, then followed
    pump()
    assert len(has_property(view, "flipY")) == 1 and backend.mapCars.rows
    maps = has_property(view, "gliding")
    assert maps and maps[0].property("gliding")
    backend.setPanel(0)
    pump()
    assert len(has_property(view, "flipY")) == 1  # kept once built
    assert not maps[0].property("gliding")  # hidden: no car animation


def test_timeline_end_steady_without_session_length(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    backend.session_end = -1.0
    ends = set()
    for replay_time in range(1700, 1760, 7):
        backend.replay_time = float(replay_time)
        ends.add(backend.timeline["end"])
    assert len(ends) <= 2 and all(end % 60 == 0 for end in ends)
    backend.session_end = 3600.0
    assert backend.timeline["end"] == 3600.0


def test_lists_reuse_rows(replays_page):  # noqa: F811
    from PySide6.QtCore import qInstallMessageHandler

    def buttons(**wanted):
        return [item for item in items_of(replays_page.view.rootObject())
                if item.metaObject().className().startswith("TpButton")
                and all(item.property(name) == value for name, value in wanted.items())]

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        backend = answered(replays_page, GAME_ANSWERS)
        replays_page.resize(1400, 860)
        replays_page.show()
        pump(20)
        # Jump button made for the selected incident row only (none hovered)
        jumps = len(buttons(flat=False, accent=True))
        backend.selectIncident(backend.incidentRows.rows[0]["key"])
        pump()
        assert len(buttons(flat=False, accent=True)) == jumps + 1
        backend.setPanel(1)
        pump(20)
        lists = [item for item in items_of(replays_page.view.rootObject())
                 if item.metaObject().className().startswith("QQuickListView") and item.property("reuseItems")]
        assert len(lists) == 3  # replays, incidents, standings
        assert len(buttons(text="Watch")) == 1  # selected replay row only
    finally:
        qInstallMessageHandler(previous)
    qml = [text for text in messages if ".qml" in text]
    assert not qml, qml


def test_timeline_ticks_fixed(replays_page):  # noqa: F811
    answered(replays_page, GAME_ANSWERS)
    replays_page.resize(1400, 860)
    replays_page.show()
    pump(20)
    timelines = has_property(replays_page.view, "firstTick")
    assert len(timelines) == 1
    timeline = timelines[0]
    ticks = [item for item in items_of(timeline) if item.metaObject().indexOfProperty("value") >= 0]
    assert len(ticks) == 40 and any(tick.isVisible() for tick in ticks)
    timeline.zoomAt(0.3, 200.0)
    pump()
    after = [item for item in items_of(timeline) if item.metaObject().indexOfProperty("value") >= 0]
    assert after == ticks  # same items, values moved
    shown = [tick.property("value") for tick in after if tick.isVisible()]
    assert shown and min(shown) >= timeline.property("viewStart")
