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
    "overlay_backend.py": 3,
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
# Notify signals covering more than MAX_SHARED_NOTIFY properties: values changed together (theme, options of a page)
ALLOWED_SHARED: dict[tuple[str, str], int] = {
    ("__init__.py", "changed"): 30,  # theme & translator copies: changed only by a theme or language switch
    ("director_backend.py", "settingsChanged"): 8,
    ("lap_backend.py", "chartChanged"): 11,
    ("lap_backend.py", "mapChanged"): 10,
    ("lap_backend.py", "optionsChanged"): 13,
    ("lap_corners.py", "changed"): 10,
    ("overlay_options_backend.py", "filterChanged"): 9,
    ("overlay_options_backend.py", "previewChanged"): 9,
    ("overlay_options_backend.py", "stateChanged"): 8,
    ("results_backend.py", "selectionChanged"): 7,
    ("settings_backend.py", "stateChanged"): 7,
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
                yield node, ast.unparse(notify) if notify is not None else ""


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
    for path in sorted(BACKEND_FOLDER.glob("*.py")):
        count, shared = scan(path.read_text(encoding="utf-8"))
        allowed = ALLOWED_COMPUTING.get(path.name, 0)
        if count > allowed:
            unexpected.append(f"{path.name}: {count} computing getters (allowed {allowed}): store the value instead")
        elif count < allowed:
            stale.append(f"ALLOWED_COMPUTING {path.name}: {count}")
        for notify, total in shared.items():
            allowed = ALLOWED_SHARED.get((path.name, notify), MAX_SHARED_NOTIFY)
            if total > allowed:
                unexpected.append(f"{path.name}: {notify} notifies {total} properties (allowed {allowed}): split it")
            elif total < allowed and (path.name, notify) in ALLOWED_SHARED:
                stale.append(f"ALLOWED_SHARED {path.name} {notify}: {total}")
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
