"""Audit H lot C4: lap viewer page composed of parts (child QObjects with their own state & slots, QML
backend.<part>.<member>) instead of a god class of mixins: QML names resolve, parts are children of the page
reached through explicit hosts, released with it"""

import functools
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaMethod, QObject

from neopedal.ui.quick import qml_path
from tests.test_lap_viewer_quick import backend  # noqa: F401

# QML files of lap viewer page (backend context property is LapViewerBackend)
LAP_VIEWER_QML = (
    "LapViewer", "CornerList", "GCircle", "LapFilter", "LapList", "MathChannels", "PlaybackBar", "RangeStats",
    "SessionView", "SetupDiff", "ShowPicker", "SimpleView", "TraceChart", "XYView", "TrackMap", "RecentlyDeleted",
)


def part_classes() -> dict:
    """Part property of page: class of part"""
    from neopedal.ui.quick.lap_charts import ChartTools, MathChannels
    from neopedal.ui.quick.lap_conditions import LapConditions
    from neopedal.ui.quick.lap_corners import CornerTable
    from neopedal.ui.quick.lap_dashboard import DashboardTab
    from neopedal.ui.quick.lap_export import LapExports
    from neopedal.ui.quick.lap_session import SessionTab

    return {"conditions": LapConditions, "dashboard": DashboardTab, "session": SessionTab,
            "math": MathChannels, "charts": ChartTools, "exports": LapExports,
            "cornerTable": CornerTable}


def meta_names(cls) -> set[str]:
    """Properties, slots & signals QML can read on class"""
    meta = cls.staticMetaObject
    names = {meta.property(index).name() for index in range(meta.propertyCount())}
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType() in (QMetaMethod.MethodType.Slot, QMetaMethod.MethodType.Signal,
                                   QMetaMethod.MethodType.Method):
            names.add(bytes(method.name().data()).decode())
    return names


def test_qml_backend_names_resolve():
    """Every backend.<name> & backend.<part>.<name> of lap viewer QML is a property, slot or signal (moved members
    never left behind in QML: undefined at run time only when that code path runs)"""
    from neopedal.ui.quick.lap_backend import LapViewerBackend

    root = meta_names(LapViewerBackend)
    parts = {name: meta_names(cls) for name, cls in part_classes().items()}
    missing = []
    for name in LAP_VIEWER_QML:
        text = Path(qml_path(f"{name}.qml")).read_text(encoding="utf-8")
        for match in re.finditer(r"\bbackend\.(\w+)(?:\.(\w+))?", text):
            member, sub = match.groups()
            if member not in root:
                missing.append(f"{name}.qml: backend.{member}")
            elif member in parts and sub is not None and sub not in parts[member]:
                missing.append(f"{name}.qml: backend.{member}.{sub}")
    assert not missing, missing


def test_parts_are_page_children(backend):  # noqa: F811
    """Parts: constant QObject properties, children of page (deleted with it), one object for the page life"""
    for name in part_classes():
        part = getattr(backend, name)
        assert isinstance(part, QObject) and part.parent() is backend
        assert getattr(backend, name) is part
        index = backend.metaObject().indexOfProperty(name)
        assert index >= 0 and backend.metaObject().property(index).isConstant()


def test_conditions_part(backend):  # noqa: F811
    """Similar conditions tolerance kept by its part: saved, told by its own signal (also on unit changes)"""
    from neopedal.ui.lap_viewer import load_viewer_setting

    conditions = backend.conditions
    told = []
    conditions.toleranceChanged.connect(lambda: told.append(True))
    conditions.setSimilarTolerance(8)
    assert conditions.similarTolerance == 8 and told == [True]
    assert load_viewer_setting(backend.folder)["similar_tolerance"] == 8
    conditions.setSimilarTolerance(4)  # not a choice: kept
    assert conditions.similarTolerance == 8 and len(told) == 1
    backend.optionsChanged.emit()  # units changed: temperature texts
    assert len(told) == 2
    assert not hasattr(backend, "compareSimilarConditions") and not hasattr(backend, "_similar_tolerance")


def test_parts_told_by_page_signals(backend):  # noqa: F811
    """Part signals follow page changes: shown laps (dashboard, session), corners (corner table, alignment),
    math channels & channel menu (math)"""
    told: dict[str, int] = {}

    def count(name: str):
        return lambda: told.__setitem__(name, told.get(name, 0) + 1)

    for name, signal in (("dashboard", backend.dashboard.changed), ("session", backend.session.changed),
                         ("corners", backend.cornerTable.changed), ("alignment", backend.charts.alignmentChanged),
                         ("math", backend.math.changed), ("inputs", backend.math.inputsChanged)):
        signal.connect(count(name))
    state = backend.session.state
    backend.chartChanged.emit()  # laps shown: also corners
    assert told.get("dashboard") == 1 and told.get("corners") == 1 and told.get("alignment") == 1
    assert backend.session.state is not state  # built again on next read (lap colors)
    backend.mathChanged.emit()
    backend.channelsChanged.emit()
    assert told.get("math") == 1 and told.get("inputs") == 1 and told.get("dashboard") == 2
    assert "session" not in told  # session tab told only by its own changes


def test_parts_released_with_page(ui_env):
    """Page release releases its parts (results kept per lap forgotten), page jobs owned by page only"""
    from PySide6.QtWidgets import QWidget

    from neopedal.setting import cfg
    from neopedal.ui.quick.lap_backend import LapViewerBackend
    from neopedal.ui.quick.lap_base import PagePart

    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    released = []
    for part in page.parts():
        assert isinstance(part, PagePart) and part.parent() is page
        part.release = functools.partial(released.append, type(part).__name__)  # type: ignore[method-assign]
    page.release()
    assert len(released) == len(page.parts()) == len(part_classes())
    page.release()  # once only
    assert len(released) == len(part_classes())
    parent.deleteLater()


def test_dashboard_part_cursor(backend):  # noqa: F811
    """Simple view values read at cursor from its part, page cursor state built from it while simple view shown"""
    backend.setSimpleView(True)
    assert backend.dashboard.opened and backend.dashboard.layout
    state = backend.cursorState(500.0)
    assert state["dashboard"] == backend.dashboard.cursor_values(500.0)
    assert [lap["lap"] for lap in state["inputs"]] == [lap.key for lap in backend.data.laps]
    backend.dashboard.release()
    assert backend.dashboard.items == []


def test_corner_table_part(backend):  # noqa: F811
    """Corner table part: rows of reference lap, sort & sensitivity saved, page delegates read the same rows"""
    from neopedal.ui.lap_viewer import load_viewer_setting

    table = backend.cornerTable
    assert backend.corner_rows() is table.rows and table.count == len(table.rows)
    assert table.model.rowCount() == len(table.items)
    table.setSort("loss")
    assert table.sort == "loss" and load_viewer_setting(backend.folder)["corner_sort"] == "loss"
    table.setHysteresis(table.hysteresis + 1)
    assert load_viewer_setting(backend.folder)["corner_hysteresis"] == table.hysteresis
    assert table.ranges == [table.range(index) for index in range(table.count)]
    table.release()
    assert table.rows == [] and table.items == [] and table.key == ()


@pytest.mark.parametrize("value, expected", [(True, 3), (5.0, 5), ("8", 3), (None, 3), (2, 2)])
def test_int_setting(value, expected):
    from neopedal.ui.quick.lap_base import int_setting

    assert int_setting({"x": value}, "x", 3) == expected
