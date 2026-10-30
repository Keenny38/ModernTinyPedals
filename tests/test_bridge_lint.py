"""Static checks of Python backends read by QML pages: property getters return stored values (computed when the
data changes, not at each read of each binding), one notify signal never shared by many properties (any emit
evaluates every binding of every property again)"""

import ast
from pathlib import Path

BACKEND_FOLDER = Path(__file__).resolve().parent.parent / "neopedal" / "ui" / "quick"

MAX_SHARED_NOTIFY = 6  # properties a notify signal may cover
COMPUTING_CALLS = frozenset(("sorted", "any", "all", "sum", "min", "max", "filter", "map"))
LOOPS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.For, ast.While)

# Known exceptions (ratchets, lower when fixing): getters computing at each read, mostly read once into a QML
# readonly property, or small lists
ALLOWED_COMPUTING: dict[str, int] = {
    "director_backend.py": 2,
    "director_camera.py": 2,
    "director_graphics.py": 4,
    "director_timing.py": 2,
    "finder_backend.py": 1,
    "lap_backend.py": 8,
    "lap_charts.py": 1,
    "lap_conditions.py": 1,
    "lap_corners.py": 2,
    "lap_dashboard.py": 1,
    "overlay_backend.py": 1,
    "overlay_options_backend.py": 4,
    "preset_backend.py": 2,
    "race_backend.py": 7,
    "replays_backend.py": 12,
    "settings_backend.py": 3,
    "setup_backend.py": 8,
    "stats_backend.py": 3,
    "stream_backend.py": 3,
    "track_map_backend.py": 5,
}
# Parts (mixins) of a backend: counted with it (a signal of StatsCore notifies properties of every part)
BACKEND_PARTS = {f"stats_{part}.py": "stats_backend.py"
                 for part in ("core", "table", "overview", "selection", "edits", "sharing")}
BACKEND_PARTS.update({f"replays_{part}.py": "replays_backend.py"
                      for part in ("list", "folder", "playback", "incidents", "standings", "map")})
# Notify signals covering more than MAX_SHARED_NOTIFY properties: values changed together (theme, options of a page)
ALLOWED_SHARED: dict[tuple[str, str], int] = {
    # Theme tokens (palette, status & series colors, surfaces, strokes, shadow, legacy look, chart & map colors) of
    # the one Theme object: changed together, only by a theme or colorblind switch; pages read the QML theme copy
    # (theme_copy), which this signal refreshes
    ("__init__.py", "changed"): 48,
    ("director_backend.py", "settingsChanged"): 8,
    ("lap_backend.py", "chartChanged"): 11,
    ("lap_backend.py", "mapChanged"): 9,
    ("lap_backend.py", "optionsChanged"): 13,
    ("lap_corners.py", "changed"): 10,
    ("overlay_options_backend.py", "filterChanged"): 9,
    ("overlay_options_backend.py", "previewChanged"): 9,
    ("overlay_options_backend.py", "stateChanged"): 8,
    ("results_backend.py", "selectionChanged"): 7,
    ("stream_backend.py", "serverChanged"): 9,
    ("track_map_backend.py", "mapChanged"): 7,
}


def properties(tree: ast.AST):
    """(getter, notify signal name or "") of every Property decorated getter"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "") == "Property":
                notify = next((keyword.value for keyword in decorator.keywords if keyword.arg == "notify"), None)
                # notify=StatsCore.tracksChanged (signal of another part of the backend): its name
                yield node, ast.unparse(notify).rpartition(".")[2] if notify is not None else ""


def computing(getter: ast.FunctionDef) -> bool:
    """Getter looping over data or sorting / reducing it at each read"""
    return any(isinstance(node, LOOPS) or (isinstance(node, ast.Call)
                                           and getattr(node.func, "id", "") in COMPUTING_CALLS)
               for statement in getter.body for node in ast.walk(statement))


def scan(source: str) -> tuple[int, dict[str, int]]:
    """Computing getters & properties per notify signal of a backend source"""
    count, shared = 0, {}
    for getter, notify in properties(ast.parse(source)):
        count += computing(getter)
        if notify:
            shared[notify] = shared.get(notify, 0) + 1
    return count, shared


def test_backend_properties():
    unexpected, stale = [], []
    backends: dict[str, tuple[int, dict[str, int]]] = {}
    for path in sorted(BACKEND_FOLDER.glob("*.py")):
        count, shared = scan(path.read_text(encoding="utf-8"))
        name = BACKEND_PARTS.get(path.name, path.name)
        total_count, total_shared = backends.get(name, (0, {}))
        for notify, total in shared.items():
            total_shared[notify] = total_shared.get(notify, 0) + total
        backends[name] = (total_count + count, total_shared)
    for name, (count, shared) in sorted(backends.items()):
        allowed = ALLOWED_COMPUTING.get(name, 0)
        if count > allowed:
            unexpected.append(f"{name}: {count} computing getters (allowed {allowed}): store the value instead")
        elif count < allowed:
            stale.append(f"ALLOWED_COMPUTING {name}: {count}")
        for notify, total in shared.items():
            allowed = ALLOWED_SHARED.get((name, notify), MAX_SHARED_NOTIFY)
            if total > allowed:
                unexpected.append(f"{name}: {notify} notifies {total} properties (allowed {allowed}): split it")
            elif total < allowed and (name, notify) in ALLOWED_SHARED:
                stale.append(f"ALLOWED_SHARED {name} {notify}: {total}")
    assert not unexpected, "\n".join(unexpected)
    assert not stale, "fixed: lower or remove " + ", ".join(stale)


def test_rules_catch_patterns():
    count, shared = scan('''
class Backend(QObject):
    @Property(int, notify=rowsChanged)
    def stored(self):
        """Docstring"""
        return self._count

    @Property(bool, notify=rowsChanged)
    def anyShown(self):
        return any(row["shown"] for row in self.rows)

    @Property(list, notify=otherChanged)
    def names(self):
        return sorted(self._names)

    @Property(str, constant=True)
    def title(self):
        return self._title
''')
    assert count == 2 and shared == {"rowsChanged": 2, "otherChanged": 1}
