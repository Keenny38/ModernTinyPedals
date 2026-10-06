"""Overlay Options page: one option edited updates its own rows only (row, section header, overlay in list),
same rows as a full rebuild, header info told once edits pause, overlay choice list not rebuilt on edits"""

import random

from PySide6.QtCore import QCoreApplication

from tests.test_overlay_options import options, row, set_classic  # noqa: F401
from tinypedal.setting import cfg


def spy(monkeypatch, backend, name: str) -> list:
    calls: list = []
    method = getattr(backend, name)

    def counted(*args, **kwargs):
        calls.append(args)
        return method(*args, **kwargs)

    monkeypatch.setattr(backend, name, counted)
    return calls


def same_as_full_rebuild(backend):
    shown = [dict(entry) for entry in backend.rows.rows]
    nav = [dict(entry) for entry in backend.nav.rows]
    backend.update_all()
    assert [dict(entry) for entry in backend.rows.rows] == shown
    assert [dict(entry) for entry in backend.nav.rows] == nav


def test_single_edit_updates_its_rows_only(options, monkeypatch):  # noqa: F811
    options.selectOverlay("speedometer")
    full_rows = spy(monkeypatch, options, "update_rows")
    full_nav = spy(monkeypatch, options, "update_nav")
    info, names = [], []
    options.infoChanged.connect(lambda: info.append(True))
    options.namesChanged.connect(lambda: names.append(True))
    changes = []
    options.rows.dataChanged.connect(lambda first, last, roles: changes.append((first.row(), last.row())))
    options.setNumber("speedometer/opacity", 0.55)
    assert not full_rows and not full_nav and not names
    edited = row(options, "speedometer/opacity")
    assert edited["changed"] and edited["modified"] and edited["number"] == 0.55
    header = row(options, "speedometer#layout")
    assert header["changedCount"] == 1 and header["customizedCount"] >= 1
    assert len(changes) == 2  # option row & its section header
    nav = options.nav.rows[options.navIndex("speedometer")]
    assert nav["changed"] == 1 and nav["customized"] >= 1  # overlay list at once
    assert not info and options.overlayInfo["customized"] >= 1  # read fresh, told once edits pause
    options._info_timer.timeout.emit()
    assert info
    options.setNumber("speedometer/opacity", 0.55)  # same value: nothing updated
    assert len(changes) == 2
    full_rows.clear()
    options.setText("speedometer/opacity", "abc")
    assert not full_rows and row(options, "speedometer/opacity")["error"]
    assert options.nav.rows[options.navIndex("speedometer")]["errors"] == 1
    same_as_full_rebuild(options)


def test_dependent_edits_rebuild_every_row(options, monkeypatch):  # noqa: F811
    set_classic("speedometer")
    options.refresh()
    options.selectOverlay("speedometer")
    full_rows = spy(monkeypatch, options, "update_rows")
    options.setBool("speedometer/show_speed_minimum", False)  # options of the item dimmed
    assert full_rows and row(options, "speedometer/font_color_speed_minimum")["dimmed"]
    full_rows.clear()
    options.selectOverlay("black_box")
    options.setAdvanced(True)
    full_rows.clear()
    choices = row(options, "black_box/display_profile")["choices"]
    options.setChoice("black_box/display_profile", choices.index("Minimal"))  # profile locks options
    assert full_rows and any(entry["locked"] for entry in options.rows.rows)
    full_rows.clear()
    options.setModifiedOnly(True)
    full_rows.clear()
    options.resetOption("black_box/display_profile")  # "Modified" filter: row may leave the list
    assert full_rows


def test_random_edits_match_full_rebuild(options):  # noqa: F811
    from tinypedal.ui.quick.option_kinds import KIND_BOOL, KIND_CHOICE, NUMBER_KINDS

    rng = random.Random(5)
    for name in ("speedometer", "black_box", "relative", "fuel"):
        options.selectOverlay(name)
        options.setAdvanced(True)
        for _ in range(25):
            entries = [entry for entry in options.rows.rows if entry["row"] == "option" and not entry["locked"]]
            entry = rng.choice(entries)
            oid, kind = entry["key"], entry["kind"]
            if kind == KIND_BOOL:
                options.setBool(oid, not entry["checked"])
            elif kind == KIND_CHOICE and entry["choices"]:
                options.setChoice(oid, rng.randrange(len(entry["choices"])))
            elif kind in NUMBER_KINDS:
                options.setNumber(oid, entry["minimum"] if rng.random() < 0.5 else entry["number"])
            elif rng.random() < 0.3:
                options.setText(oid, "")
            else:
                options.resetOption(oid)
            same_as_full_rebuild(options)
        options.discard()


def test_overlay_names_told_on_refresh_only(options):  # noqa: F811
    names = []
    options.namesChanged.connect(lambda: names.append(True))
    keys = options.overlayKeys
    assert keys == options.sorted_names() and len(options.overlayLabels) == len(keys)
    options.selectOverlay("fuel")
    options.setNumber("fuel/opacity", 0.4)
    assert not names
    cfg.user.setting["fuel"]["opacity"] = 0.4
    options.refresh()
    QCoreApplication.processEvents()
    assert names and options.overlayKeys == keys
