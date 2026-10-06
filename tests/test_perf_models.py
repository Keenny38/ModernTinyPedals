"""List models of QML views: sync with a key index (no quadratic scans), fewest moves (longest kept order),
reset when many rows moved, "anything changed" results, FoldedListModel change computed once per row"""

import random
from itertools import pairwise

import pytest
from PySide6.QtCore import QPersistentModelIndex, QtMsgType, qInstallMessageHandler

from tinypedal.ui.quick.models import DictListModel, FoldedListModel, longest_increasing, too_many_moves

try:
    from PySide6.QtTest import QAbstractItemModelTester
except ImportError:  # pragma: no cover
    QAbstractItemModelTester = None


@pytest.fixture
def qt_warnings():
    """Warnings of Qt (model tester failures in Warning mode) collected"""
    messages: list[str] = []

    def handler(kind, context, message):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    yield messages
    qInstallMessageHandler(previous)


def model_tester(model):
    if QAbstractItemModelTester is None:
        return None
    return QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)


def keys(model) -> list:
    return [row["key"] for row in model.rows]


def test_longest_increasing():
    assert longest_increasing([]) == []
    assert longest_increasing([3, 1, 2]) == [1, 2]
    values = [5, 1, 6, 2, 7, 3, 8]
    found = longest_increasing(values)
    assert len(found) == 4 and all(values[a] < values[b] for a, b in pairwise(found))
    rng = random.Random(3)
    for _ in range(200):
        values = rng.sample(range(50), rng.randint(0, 30))
        found = longest_increasing(values)
        assert found == sorted(found) and all(values[a] < values[b] for a, b in pairwise(found))
        best = [1] * len(values)  # O(n²) reference length
        for i in range(len(values)):
            for j in range(i):
                if values[j] < values[i]:
                    best[i] = max(best[i], best[j] + 1)
        assert len(found) == max(best, default=0)


def test_first_row_moved_to_end_is_one_move(qt_warnings):
    model = DictListModel(("key", "value"))
    tester = model_tester(model)
    model.sync([{"key": key, "value": 0} for key in "abcdefghij"])
    moved, resets = [], []
    model.rowsMoved.connect(lambda *args: moved.append(args[1:]))
    model.modelReset.connect(lambda: resets.append(True))
    assert model.sync([{"key": key, "value": 0} for key in "bcdefghija"])
    assert keys(model) == list("bcdefghija") and len(moved) == 1 and not resets
    assert not model.sync([{"key": key, "value": 0} for key in "bcdefghija"])  # nothing changed
    del tester
    assert not qt_warnings


def test_many_moves_reset():
    model = DictListModel(("key", "value"))
    model.sync([{"key": number, "value": 0} for number in range(100)])
    resets, moved = [], []
    model.modelReset.connect(lambda: resets.append(True))
    model.rowsMoved.connect(lambda *args: moved.append(True))
    model.sync([{"key": number, "value": 0} for number in reversed(range(100))])
    assert resets and not moved and keys(model) == list(reversed(range(100)))
    assert too_many_moves(26, 100) and not too_many_moves(25, 100) and not too_many_moves(8, 10)


def test_reset_if_mostly_new():
    model = DictListModel(("key",))
    model.sync([{"key": number} for number in range(10)])
    resets = []
    model.modelReset.connect(lambda: resets.append(True))
    model.sync([{"key": number} for number in range(5, 20)])
    assert not resets  # plain sync: in place
    model.sync([{"key": number} for number in range(15, 40)], reset_if_mostly_new=True)
    assert resets and keys(model) == list(range(15, 40))


def test_duplicate_keys():
    model = DictListModel(("key", "value"))
    model.sync([{"key": "a", "value": 1}, {"key": "a", "value": 2}, {"key": "b", "value": 3}])
    assert [(row["key"], row["value"]) for row in model.rows] == [("a", 1), ("a", 2), ("b", 3)]
    model.sync([{"key": "b", "value": 3}, {"key": "a", "value": 4}])
    assert [(row["key"], row["value"]) for row in model.rows] == [("b", 3), ("a", 4)]


def test_index_of_and_update_row():
    model = DictListModel(("key", "value"))
    model.sync([{"key": key, "value": 0} for key in "abc"])
    assert model.index_of("c") == 2 and model.index_of("z") == -1
    model.sync([{"key": key, "value": 0} for key in "cab"])
    assert model.index_of("c") == 0 and model.index_of("b") == 2  # stale cache rebuilt
    changes = []
    model.dataChanged.connect(lambda first, last, roles: changes.append((first.row(), list(roles))))
    assert model.update_row(1, {"value": 5}) and not model.update_row(1, {"value": 5})
    assert not model.update_row(9, {"value": 1})
    assert changes == [(1, [model._role_of["value"]])]


def random_rows(rng, pool: list, size: int) -> list[dict]:
    return [{"key": key, "value": rng.randint(0, 3), "text": str(rng.randint(0, 2))}
            for key in rng.sample(pool, min(size, len(pool)))]


def mutate(rng, rows: list[dict], pool: list) -> list[dict]:
    """Random inserts, removals, moves & value changes of rows"""
    rows = [dict(row) for row in rows]
    for _ in range(rng.randint(0, 6)):
        action = rng.choice(("insert", "remove", "move", "update", "update"))
        used = {row["key"] for row in rows}
        free = [key for key in pool if key not in used]
        if action == "insert" and free:
            rows.insert(rng.randint(0, len(rows)), {"key": rng.choice(free), "value": 0, "text": ""})
        elif action == "remove" and rows:
            del rows[rng.randrange(len(rows))]
        elif action == "move" and rows:
            row = rows.pop(rng.randrange(len(rows)))
            rows.insert(rng.randint(0, len(rows)), row)
        elif action == "update" and rows:
            rows[rng.randrange(len(rows))]["value"] = rng.randint(0, 9)
    if rng.random() < 0.05:
        rng.shuffle(rows)
    return rows


@pytest.mark.parametrize("seed", range(6))
def test_random_syncs_match_rows_and_notify_correctly(seed, qt_warnings):
    rng = random.Random(seed)
    pool = list(range(60))
    model = DictListModel(("key", "value", "text"))
    tester = model_tester(model)
    rows = random_rows(rng, pool, 20)
    model.sync(rows)
    resets = []
    model.modelReset.connect(lambda: resets.append(True))
    for _ in range(150):
        rows = mutate(rng, rows, pool)
        before = {row["key"]: QPersistentModelIndex(model.index(number, 0)) for number, row in enumerate(model.rows)}
        same = [dict(row) for row in model.rows] == rows
        resets.clear()
        changed = model.sync([dict(row) for row in rows])
        assert model.rows == rows
        assert changed != same
        if not resets:  # rows kept followed by their persistent index: moves notified right
            for key, index in before.items():
                if key in {row["key"] for row in rows}:
                    assert index.isValid() and model.rows[index.row()]["key"] == key
                else:
                    assert not index.isValid()
    del tester
    assert not qt_warnings


def test_folded_update_rows_computes_change_once():
    model = FoldedListModel(("key", "value"), "key")
    model.set_rows([{"key": key, "value": 0} for key in "abcd"], lambda row: row["key"] != "b")
    calls = []

    def change(row):
        calls.append(row["key"])
        return {"value": 1}

    assert model.update_rows(change)
    assert sorted(calls) == list("abcd")  # once per row, not again for shown copies
    assert [row["value"] for row in model.all_rows] == [1] * 4 and [row["value"] for row in model.rows] == [1] * 3
    assert not model.update_rows(lambda row: {"value": 1})
