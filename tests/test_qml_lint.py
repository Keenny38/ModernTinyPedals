"""Static checks of QML pages (performance patterns): derived models, busy indicators of hidden pages,
synchronous images, tooltip texts made while not hovered"""

import re
from pathlib import Path

QML_FOLDER = Path(__file__).resolve().parent.parent / "neopedal" / "ui" / "qml"

# Known exceptions: (file, rule) -> count (none: combos take object models with textRole)
ALLOWED: dict[tuple[str, str], int] = {}

STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
OPENERS, CLOSERS = "([{", ")]}"
CONTINUED_END = tuple("+-*/?:&|,([{.=<>!")
CONTINUED_START = tuple("+-*/?:&|.)]}=<>")
CHEAP_CALL = re.compile(r"(?:\bi18n\.tr|\bqsTr|\.arg|\bMath\.\w+|\.toFixed|\.replace|\.join|\bNumber|\bString)\s*\(")
HOVER_GUARD = re.compile(r"(?:\bhovered|\bcontainsMouse|\bToolTip\.visible)\s*\?")
CONSTANT_WORDS = frozenset(("true", "false", "null", "undefined"))


def blank(text: str) -> str:
    """Text with string contents & comments replaced by spaces (positions & lines kept)"""

    def spaces(match: re.Match) -> str:
        part = match.group(0)
        if part[0] in "\"'`":
            return part[0] + re.sub(r"[^\n]", " ", part[1:-1]) + part[-1]
        return re.sub(r"[^\n]", " ", part)

    return re.sub(f"{STRING.pattern}|{COMMENT.pattern}", spaces, text, flags=re.DOTALL)


def value_end(code: str, start: int) -> int:
    """End of binding value starting at start: brackets closed, line not continued, or ';'"""
    depth = 0
    index = start
    while index < len(code):
        char = code[index]
        if char in OPENERS:
            depth += 1
        elif char in CLOSERS:
            if depth == 0:
                return index
            depth -= 1
        elif char == ";" and depth == 0:
            return index
        elif char == "\n" and depth == 0:
            line = code[start:index].rstrip()
            rest = code[index:].lstrip()
            if line.endswith(CONTINUED_END) or rest.startswith(CONTINUED_START):
                index += 1
                continue
            return index
        index += 1
    return index


def bindings(code: str, name: str) -> list[tuple[int, int]]:
    """(start, end) of values of binding name anywhere in blanked code"""
    found = []
    for match in re.finditer(rf"(?:^|[{{;])[ \t]*{re.escape(name)}[ \t]*:(?!:)", code, re.MULTILINE):
        found.append((match.end(), value_end(code, match.end())))
    return found


def blocks(code: str, type_name: str) -> list[tuple[int, int]]:
    """(start, end) of contents of objects of type_name in blanked code"""
    found = []
    for match in re.finditer(rf"(?<![\w.]){type_name}[ \t]*\{{", code):
        depth, index = 1, match.end()
        while depth and index < len(code):
            depth += {"{": 1, "}": -1}.get(code[index], 0)
            index += 1
        found.append((match.end(), index - 1))
    return found


def own_binding(code: str, start: int, end: int, name: str) -> tuple[int, int] | None:
    """Value of binding name of the object itself (not of its child objects)"""
    for value_start, value_stop in bindings(code[:end], name):
        if value_start < start:
            continue
        depth = sum(code.count(char, start, value_start) for char in "{") - code.count("}", start, value_start)
        if depth == 0:
            return value_start, value_stop
    return None


def line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def bound_array(value: str, ids: set[str]) -> bool:
    """Array literal model with values that are not constants (strings, numbers, translated texts, ids, theme)"""
    code = COMMENT.sub(" ", STRING.sub("0", value)).strip()
    if not code.startswith("["):
        return False
    depth = 0
    for index, char in enumerate(code):  # literal itself (what is joined to it is not a literal)
        depth += (char in OPENERS) - (char in CLOSERS)
        if not depth:
            code = code[:index + 1]
            break
    code = re.sub(r"(?:\bi18n\.tr|\bqsTr)\(\s*0\s*\)", "0", code)
    for match in re.finditer(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", code):
        word = match.group(0)
        if (word in CONSTANT_WORDS or word in ids or word.startswith("theme.")
                or re.match(r"\s*:", code[match.end():])):
            continue
        return True
    return False


def violations(path: Path) -> list[tuple[str, int, str]]:
    """(rule, line, text) of performance patterns found in QML file"""
    text = path.read_text(encoding="utf-8")
    code = blank(text)
    ids = set(re.findall(r"\bid[ \t]*:[ \t]*(\w+)", code))
    found = []
    for start, end in bindings(code, "model"):
        value = text[start:end]
        if re.search(r"\.(?:filter|map)\s*\(", code[start:end]) or bound_array(value, ids):
            found.append(("model", line_of(text, start), value.strip()))
    for start, end in blocks(code, "BusyIndicator"):
        running = own_binding(code, start, end, "running")
        if running is None or "pageState.active" not in code[running[0]:running[1]]:
            found.append(("busy", line_of(text, start), "BusyIndicator"))
    for start, end in blocks(code, "Image"):
        source = own_binding(code, start, end, "source")
        source_text = text[source[0]:source[1]].strip() if source else ""
        constant = re.fullmatch(r'"(?:qrc:[^"]*|[^"]*\.(?:svg|png))"', source_text)
        if own_binding(code, start, end, "asynchronous") is None and not constant:
            found.append(("image", line_of(text, start), source_text))
    for start, end in bindings(code, "ToolTip.text"):
        value = code[start:end]
        calls = re.findall(r"[\w$.]+\(", CHEAP_CALL.sub("", value))
        if calls and not HOVER_GUARD.search(value):
            found.append(("tooltip", line_of(text, start), text[start:end].strip()))
    return found


def test_qml_performance_patterns():
    counts: dict[tuple[str, str], int] = {}
    unexpected = []
    for path in sorted(QML_FOLDER.glob("*.qml")):
        for rule, line, text in violations(path):
            key = (path.name, rule)
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > ALLOWED.get(key, 0):
                unexpected.append(f"{path.name}:{line} {rule}: {text[:100]}")
    assert not unexpected, "\n".join(unexpected)
    stale = {key: allowed for key, allowed in ALLOWED.items() if counts.get(key, 0) < allowed}
    assert not stale, f"fixed: lower or remove from ALLOWED {stale}"


def test_rules_catch_patterns(tmp_path):
    page = tmp_path / "Page.qml"
    page.write_text("""Item {
    Component { id: tab; Item {} }
    Repeater { model: backend.rows.filter(function(row) { return row.shown }) }
    Repeater { model: [1, 2, "a", i18n.tr("b"), tab] }  // constants & ids: fine
    Repeater {
        model: [
            { text: i18n.tr("Laps"), value: tab.life.laps },
        ]
    }
    Repeater { model: backend.rows }
    BusyIndicator { running: backend.busy }
    BusyIndicator { running: backend.busy && pageState.active }
    Image { source: "icons/flag.svg" }
    Image { source: backend.picture }
    Image { source: backend.picture; asynchronous: true }
    Item { ToolTip.text: page.describe(row) }
    Item { ToolTip.text: hovered ? page.describe(row) : "" }
    Item {
        ToolTip.text: i18n.tr("Lap %1").arg(row.lap)
                      + " " + i18n.tr("ok")
    }
}
""", encoding="utf-8")
    assert [(rule, line) for rule, line, _ in violations(page)] == [
        ("model", 3), ("model", 6), ("busy", 11), ("image", 14), ("tooltip", 16)]
