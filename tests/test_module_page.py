"""Modules page: module specs, dependencies read from compiled code, backend filters & actions, Qt Quick page"""

import dis
import sys
from types import CodeType, MappingProxyType

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest

from tinypedal.setting import cfg
from tinypedal.template.setting_module import MODULE_DEFAULT
from tinypedal.template.setting_widget import WIDGET_FILENAME
from tinypedal.ui.quick import module_backend
from tinypedal.ui.quick.module_backend import (
    FILTER_ACTIVE,
    FILTER_INACTIVE,
    MODULE_PACKAGE,
    MODULE_SPECS,
    WIDGET_PACKAGE,
    CodeScan,
    Dependencies,
    ModuleBackend,
    find_dependencies,
    module_title,
    producers,
)

MODULES = ("module_delta", "module_fuel", "module_sectors", "module_stint", "module_recorder")
WIDGETS = ("deltabest", "fuel", "sectors", "stint_history")
DEPENDENCIES = Dependencies(
    overlays={"module_delta": ("deltabest",), "module_fuel": ("fuel",), "module_sectors": ("sectors",),
              "module_stint": ("stint_history",), "module_recorder": ()},
    modules={"module_delta": ("module_fuel", "module_stint"), "module_fuel": ("module_stint",), "module_sectors": (),
             "module_stint": (), "module_recorder": ()},
    needs={"module_delta": (), "module_fuel": ("module_delta",), "module_sectors": (),
           "module_stint": ("module_delta", "module_fuel"), "module_recorder": ()},
)


class FakeControl:
    """Module or widget control: toggles setting only, enabled ones running unless failing"""

    def __init__(self, names, type_id="module", failing=()):
        self._names = dict.fromkeys(names)
        self.type_id = type_id
        self.failing = set(failing)
        self.toggled: list[str] = []
        self.batch: list[str] = []
        self.reloaded: list[str] = []

    @property
    def names(self):
        return self._names.keys()

    @property
    def active_modules(self):
        return MappingProxyType({name: None for name in self._names
                                 if cfg.user.setting[name]["enable"] and name not in self.failing})

    def toggle(self, name):
        self.toggled.append(name)
        cfg.user.setting[name]["enable"] = not cfg.user.setting[name]["enable"]

    def enable_all(self):
        self.batch.append("enable")
        for name in self._names:
            cfg.user.setting[name]["enable"] = True

    def disable_all(self):
        self.batch.append("disable")
        for name in self._names:
            cfg.user.setting[name]["enable"] = False

    def reload(self, name=""):
        self.reloaded.append(name)


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def modules(ui_env):
    """Backend over 5 modules (sectors off, stint failing) & 4 overlays (deltabest & sectors on), answers yes"""
    for name in MODULES:
        cfg.user.setting[name]["enable"] = name != "module_sectors"
    for name in WIDGETS:
        cfg.user.setting[name]["enable"] = name in ("deltabest", "sectors")
    control = FakeControl(MODULES, failing=("module_stint",))
    widgets = FakeControl(WIDGETS, "widget")
    answers: list[str] = []
    configs: list[str] = []
    resets: list[str] = []
    backend = ModuleBackend(None, control, widgets, configs.append, lambda text: answers.append(text) or True,
                            reset_data=resets.append)
    backend.load_dependencies(DEPENDENCIES)
    backend.test = {"control": control, "widgets": widgets, "answers": answers, "configs": configs,  # type: ignore[attr-defined]
                    "resets": resets}
    yield backend
    backend.deleteLater()
    flush()


def shown(backend) -> list[str]:
    return [row["key"] for row in backend.rows_model.rows]


# Specs & dependencies from code
def test_every_module_has_spec_and_french_description():
    from tinypedal.i18n.fr import TRANSLATION

    assert set(MODULE_SPECS) == set(MODULE_DEFAULT)  # new module: add its spec (glyph, data, description)
    for name, spec in MODULE_SPECS.items():
        assert spec.glyph and spec.description in TRANSLATION, name
        for data_name, method in spec.resets:
            from tinypedal.ui.menu import ResetDataMenu

            assert callable(getattr(ResetDataMenu, method)) and data_name in TRANSLATION, (name, method)


def test_module_title_without_module_prefix():
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        assert module_title("module_mapping") == "Cartographie"  # label "Module : cartographie"
        assert module_title("module_fuel") == "Carburant"
    finally:
        i18n.set_language("English")
    assert module_title("module_mapping") == "Mapping"


_reference: dict[str, tuple[set[str], set[str]]] = {}


def reference_scan(name: str) -> tuple[set[str], set[str]]:
    """Fields read & modules imported by module name, with dis.get_instructions (slow but plain), cached"""
    if name in _reference:
        return _reference[name]
    fields: set[str] = set()
    imports: set[str] = set()
    code, is_package = module_backend.module_code(name)
    stack = [code] if code is not None else []
    while stack:
        current = stack.pop()
        previous = None
        consts: list = []
        for instruction in dis.get_instructions(current):
            if (instruction.opname == "LOAD_ATTR" and previous is not None and previous.argval == "minfo"
                    and previous.opname in ("LOAD_GLOBAL", "LOAD_NAME")):
                fields.add(instruction.argval)
            elif instruction.opname in ("LOAD_CONST", "LOAD_SMALL_INT"):
                consts.append(instruction.argval)
            elif instruction.opname == "IMPORT_NAME" and len(consts) >= 2 and isinstance(consts[-2], int):
                imports |= module_backend.resolve_import(name, is_package, instruction.argval, consts[-2], consts[-1])
            if instruction.opname != "CACHE":
                previous = instruction
        stack.extend(const for const in current.co_consts if isinstance(const, CodeType))
    _reference[name] = fields, imports
    return fields, imports


def reference_fields(name: str, package: str) -> set[str]:
    """Fields read by module name & package modules it imports (any depth), see reference_scan"""
    found: set[str] = set()
    pending, seen = [name], set()
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            fields, imports = reference_scan(current)
            found |= fields
            pending.extend(imported for imported in imports if imported.startswith(f"{package}."))
    return found


def test_fast_scan_matches_disassembly():
    """Own bytecode decoding finds what dis finds (every Python version of CI), for every overlay & module"""
    scan = CodeScan()
    for widget in WIDGET_FILENAME:
        for name in (f"{WIDGET_PACKAGE}.{widget}", f"{WIDGET_PACKAGE}._modern.{widget}"):
            assert scan.fields_of(name, WIDGET_PACKAGE) == reference_fields(name, WIDGET_PACKAGE), name
    for module in MODULE_DEFAULT:
        name = f"{MODULE_PACKAGE}.{module}"
        assert scan.fields_of(name, MODULE_PACKAGE) == reference_fields(name, MODULE_PACKAGE), name


def test_overlay_data_all_filled_by_modules():
    """Every module_info field an overlay reads comes from a module (new module data: update MODULE_SPECS)"""
    scan = CodeScan()
    filled = producers(MODULE_DEFAULT)
    read: set[str] = set()
    for widget in WIDGET_FILENAME:
        read |= scan.fields_of(f"{WIDGET_PACKAGE}.{widget}", WIDGET_PACKAGE)
        read |= scan.fields_of(f"{WIDGET_PACKAGE}._modern.{widget}", WIDGET_PACKAGE)
    assert read and read <= set(filled), read - set(filled)
    for module, spec in MODULE_SPECS.items():  # each module touches the data it is said to fill
        assert set(spec.fields) <= scan.fields_of(f"{MODULE_PACKAGE}.{module}", MODULE_PACKAGE), module


def test_dependencies_found_without_importing():
    before = {name for name in sys.modules if name.startswith(f"{WIDGET_PACKAGE}.")}
    module_backend._found_dependencies.clear()
    dependencies = find_dependencies(WIDGET_FILENAME, MODULE_DEFAULT)
    assert {name for name in sys.modules if name.startswith(f"{WIDGET_PACKAGE}.")} == before  # nothing run
    assert "fuel" in dependencies.overlays["module_fuel"]
    assert {"relative", "standings"} <= set(dependencies.overlays["module_relative"])
    assert "relative" in dependencies.overlays["module_vehicles"]
    assert dependencies.overlays["module_sectors"] == ("sectors",)
    assert dependencies.overlays["module_recorder"] == ()  # telemetry for the viewer, no overlay
    assert "module_delta" in dependencies.needs["module_stint"]
    assert "module_stint" in dependencies.modules["module_delta"]
    assert "module_hybrid" not in dependencies.needs["module_fuel"]  # fuel writes hybrid ratio, never reads it
    assert find_dependencies(WIDGET_FILENAME, MODULE_DEFAULT) is dependencies  # read once


# Backend
def test_rows_states_and_users(modules):
    rows = {row["key"]: row for row in modules.rows_model.rows}
    assert shown(modules) == sorted(MODULES, key=lambda name: module_title(name).casefold())
    assert rows["module_delta"]["running"] and rows["module_delta"]["users"] == ["Deltabest"]
    assert rows["module_delta"]["moduleUsers"] == ["Fuel", "Stint"]
    assert rows["module_fuel"]["userCount"] == 0 and rows["module_fuel"]["userTotal"] == 1  # Fuel overlay off
    assert rows["module_stint"]["failed"] and modules.failedCount == 1
    assert rows["module_sectors"]["needed"] and modules.neededNames == ["Sectors"]  # off, Sectors overlay on
    assert rows["module_recorder"]["glyph"] and rows["module_recorder"]["userTotal"] == 0
    assert rows["module_delta"]["resets"] == [{"key": "reset_deltabest", "label": "Delta Best"}]
    assert rows["module_delta"]["interval"] == cfg.user.setting["module_delta"]["update_interval"]
    assert modules.activeCount == 4 and modules.totalCount == 5


def test_needs_shown_when_needed_module_off(modules):
    cfg.user.setting["module_delta"]["enable"] = False
    modules.refresh()
    rows = {row["key"]: row for row in modules.rows_model.rows}
    assert rows["module_fuel"]["needs"] == ["Delta"]  # fuel on, its delta off
    assert rows["module_delta"]["needed"] and "Delta" in modules.neededNames


def test_search_and_state_filter(modules):
    modules.setSearch("sector")
    assert shown(modules) == ["module_sectors"] and modules.filtered
    modules.setSearch("theoretical best")  # description words, any order
    assert shown(modules) == ["module_sectors"]
    modules.setSearch("")
    modules.setStateFilter(FILTER_INACTIVE)
    assert shown(modules) == ["module_sectors"]
    modules.setStateFilter(FILTER_ACTIVE)
    assert "module_sectors" not in shown(modules) and len(shown(modules)) == 4
    assert modules.stateCounts == [5, 4, 1]
    modules.clearFilters()
    assert len(shown(modules)) == 5 and not modules.filtered


def test_search_in_french(modules):
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        modules.refresh()
        modules.setSearch("meilleur tour theorique")  # accents left out
        assert shown(modules) == ["module_sectors"]
    finally:
        i18n.set_language("English")


def test_toggle_and_enable_needed(modules):
    control = modules.test["control"]
    modules.toggle("module_sectors")
    assert control.toggled == ["module_sectors"] and not modules.neededNames
    modules.toggle("unknown")
    assert control.toggled == ["module_sectors"]
    modules.toggle("module_sectors")  # off again
    modules.enableNeeded()
    assert control.toggled[-1] == "module_sectors" and cfg.user.setting["module_sectors"]["enable"]


def test_batch_toggle_shown_only(modules, monkeypatch):
    control = modules.test["control"]
    modules.setSearch("sector")
    modules.enableShown()
    assert control.toggled == ["module_sectors"] and not control.batch
    assert "1 shown modules" in modules.test["answers"][0]
    modules.clearFilters()
    modules.disableShown()
    assert control.batch == ["disable"] and "all modules" in modules.test["answers"][1]
    monkeypatch.setitem(cfg.application, "show_confirmation_for_batch_toggle", False)
    modules.enableShown()
    assert control.batch == ["disable", "enable"] and len(modules.test["answers"]) == 2


def test_batch_toggle_declined(ui_env):
    control = FakeControl(("module_delta", "module_fuel"))
    for name in control.names:
        cfg.user.setting[name]["enable"] = False
    backend = ModuleBackend(None, control, FakeControl((), "widget"), lambda name: None, lambda text: False)
    backend.enableShown()
    assert not control.batch and not control.toggled
    backend.deleteLater()


def test_config_and_reset_data(modules):
    modules.openConfig("module_fuel")
    modules.openConfig("unknown")
    assert modules.test["configs"] == ["module_fuel"]
    modules.resetData("module_fuel", "reset_fueldelta")
    modules.resetData("module_fuel", "reset_deltabest")  # not data of this module: ignored
    modules.resetData("module_fuel", "deleteLater")
    assert modules.test["resets"] == ["reset_fueldelta"]


def test_dependencies_loaded_later(ui_env, monkeypatch):
    calls = []
    monkeypatch.setattr(module_backend, "find_dependencies", lambda *args: calls.append(args) or DEPENDENCIES)
    control = FakeControl(MODULES)
    for name in MODULES:
        cfg.user.setting[name]["enable"] = True
    backend = ModuleBackend(None, control, FakeControl(WIDGETS, "widget"), lambda name: None, lambda text: True)
    try:
        assert not backend.dependenciesReady and backend.rows_model.rows[0]["userTotal"] == 0
        backend.loadDependenciesLater()
        flush()
        assert backend.dependenciesReady and len(calls) == 1
        backend.loadDependenciesLater()
        flush()
        assert len(calls) == 1
    finally:
        backend.deleteLater()
        flush()


# Page
@pytest.fixture
def page(modules):
    from tinypedal.ui.module_view import ModuleList

    view = ModuleList(None, modules.test["control"], modules.test["widgets"])
    view.backend.load_dependencies(DEPENDENCIES)
    view.resize(900, 700)
    yield view
    view.close()
    view.deleteLater()
    flush()


def item_texts(view) -> set[str]:
    texts = set()
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def settle(count: int = 20):
    for _ in range(count):
        QCoreApplication.processEvents()


def test_qml_page_created_when_shown(page):
    assert page.view is None  # nothing loaded until shown
    page.show()
    assert page.view is not None and page.layout().count() == 1
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]
    settle()
    texts = item_texts(page.view)
    assert {"Module", "Delta", "Sectors", "Running", "Error", "Disabled", "Enable All"} <= texts
    assert "Needed by 1 enabled overlay" in texts and "1 module could not start, see log." in texts
    assert not page.view.grabFramebuffer().isNull()


def test_qml_page_keyboard(page, monkeypatch):
    """Grid keys: Space switches current module, Enter opens its config, letters go to search"""
    configs = []
    monkeypatch.setattr(page.backend, "_open_config", configs.append)
    page.show()
    settle()
    grid = next(item for item in _items(page.view.rootObject()) if item.metaObject().className().startswith("QQuickGridView"))
    grid.forceActiveFocus()
    settle()
    first = page.backend.rows_model.rows[0]["key"]
    QTest.keyClick(page.view, Qt.Key.Key_Space)
    QTest.keyClick(page.view, Qt.Key.Key_Return)
    settle()
    assert page.module_control.toggled == [first] and configs == [first]
    QTest.keyClicks(page.view, "sect")
    settle()
    assert page.backend.searchText == "sect"
    assert [row["key"] for row in page.backend.rows_model.rows] == ["module_sectors"]


def _items(root):
    stack = [root]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.childItems())


def test_qml_page_translated(modules):
    from tinypedal import i18n
    from tinypedal.ui.module_view import ModuleList

    i18n.set_language("Français")
    try:
        view = ModuleList(None, modules.test["control"], modules.test["widgets"])
        view.backend.load_dependencies(DEPENDENCIES)
        view.resize(900, 700)  # every card shown (grid makes cards of visible rows only)
        view.show()
        settle(10)
        texts = item_texts(view.view)
        assert "Tout activer" in texts and "Enable All" not in texts
        assert {"Modules", "4 / 5 activés", "Secteurs", "Nécessaire à 1 overlay activé"} <= texts
        view.close()
        view.deleteLater()
        flush()
    finally:
        i18n.set_language("English")


def test_page_reset_data_uses_reset_menu(page, monkeypatch):
    from tinypedal.ui import menu

    called = []
    monkeypatch.setattr(menu.ResetDataMenu, "reset_sectorbest", lambda self: called.append(self.title()))
    page.reset_data("reset_sectorbest")
    assert called == ["Reset Data"]


def test_page_config_saved_restarts_module(page):
    page.reload_module("module_fuel")
    assert page.module_control.reloaded == ["module_fuel"]


def test_qml_imports_bundled_modules():
    """Release build bundles only QML_MODULES: page files import nothing else (checked statically)"""
    import re

    from tinypedal.ui.quick import QML_FOLDER
    from tinypedal.ui.quick.qml_modules import QML_MODULES

    for name in ("Modules.qml", "ModuleCard.qml"):
        with open(f"{QML_FOLDER}/{name}", encoding="utf-8") as file:
            imported = re.findall(r"^import ([A-Za-z.]+)", file.read(), flags=re.MULTILINE)
        assert imported and all(module.replace(".", "/") in QML_MODULES for module in imported), (name, imported)


def test_french_page_messages():
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("<b>Enable</b> 2 shown modules?") == "<b>Activer</b> les 2 modules affichés ?"
        assert i18n.trm("<b>Disable</b> all modules?") == "<b>Désactiver</b> tous les modules ?"
        assert i18n.trm("<b>Enable</b> 3 shown overlays?") == "<b>Activer</b> les 3 overlays affichés ?"
        assert i18n.trm("3 of 13 modules shown") == "3 modules affichés sur 13"
        assert i18n.trm("2 modules could not start, see log.") == "2 modules n'ont pas pu démarrer, voir le journal."
        assert i18n.trm("Needed by 4 enabled overlays") == "Nécessaire à 4 overlays activés"
        assert i18n.trm("Needs Delta, Carburant (off)") == "A besoin de : Delta, Carburant (désactivé)"
        assert i18n.trm("6 enabled overlays use it") == "6 overlays activés l'utilisent"
        assert i18n.trm("Used by 3 overlays, none enabled") == "Utilisé par 3 overlays, aucun activé"
        assert i18n.trm("Updated every 10 ms (400 ms when not driving)") == (
            "Mis à jour toutes les 10 ms (400 ms hors conduite)")
        assert i18n.trm("Off but needed by enabled overlays or modules: Secteurs") == (
            "Désactivés mais nécessaires à des overlays ou modules activés : Secteurs")
    finally:
        i18n.set_language("English")


def test_main_window_uses_module_page(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui import app as app_module
    from tinypedal.ui.module_view import ModuleList

    host = QWidget()
    try:
        page = app_module.build_page("module", host, view=None, window=host, icon_family="")  # type: ignore[arg-type]
        assert isinstance(page, ModuleList) and page.view is None  # QML page made when first shown
    finally:
        host.deleteLater()
        flush()
