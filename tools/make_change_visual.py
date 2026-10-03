"""
Render a before / after visual of overlay changes: docs/changes/<date>-<slug>.png

Each widget is rendered twice on the same simulated race data as the README preview
(tools/make_readme_preview.py): with the code of a base revision (default HEAD, so the
last commit) and with the working tree. Both renders are placed side by side, base on
the left. Commit the image with the change: release notes (tools/gen_release_notes.py)
show every image added under docs/changes in their Visuals section, captioned by --title
(stored in the image).

Run from project root, before committing the overlay change:
    python tools/make_change_visual.py black_box
    python tools/make_change_visual.py black_box --set black_box.show_motor_map=true --slug motor-map
    python tools/make_change_visual.py relative standings --base HEAD~2

--set overrides a widget option in both renders (JSON value, plain text if not JSON),
to show an option that is off by default. Unknown options are ignored by older code.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUTPUT_DIR = os.path.join("docs", "changes")
MARGIN = 24
GAP = 48
LABEL_HEIGHT = 34

# Runs inside a source tree (base worktree or working tree), with that tree's code:
# same setup as README preview main(), then renders the asked widgets as PNG files.
RENDER_SCRIPT = r'''
import json, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
import tools.make_readme_preview as preview
from PySide6.QtCore import Qt, QTimerEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget
from importlib import import_module

names, overrides, output = json.loads(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3]
preview.load_bundled_fonts()
preview.cfg.default.set_default()
for slot in preview.cfg.user.__slots__:
    setattr(preview.cfg.user, slot, preview.copy_setting(getattr(preview.cfg.default, slot)))
for name, options in overrides.items():
    preview.cfg.user.setting[name].update(options)
sim, data = preview.lmu_api()
preview.api._api, preview.api.read = sim, sim.reader()
preview.set_telemetry(sim, data)
preview.set_vehicles()
preview.set_modules()
for name in names:
    widget = import_module(f"tinypedal.widget.{name}").Realtime(preview.cfg, name)
    widget.adjustSize()
    for _ in range(3):
        widget.timerEvent(QTimerEvent(0))
    widget.adjustSize()
    pixmap = QPixmap(widget.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
    pixmap.save(os.path.join(output, f"{name}.png"))
    widget.deleteLater()
'''


def parse_overrides(values: list[str]) -> dict[str, dict]:
    """--set widget.option=value, value as JSON (plain text if not JSON)"""
    overrides: dict[str, dict] = {}
    for item in values:
        key, _, raw = item.partition("=")
        widget, _, option = key.partition(".")
        if not (widget and option and raw):
            raise SystemExit(f"invalid --set {item!r}, expected widget.option=value")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        overrides.setdefault(widget, {})[option] = value
    return overrides


def render_tree(tree: str, names: list[str], overrides: dict, output: str):
    """Render widgets with the code of one source tree"""
    os.makedirs(output, exist_ok=True)
    subprocess.run(
        [sys.executable, "-c", RENDER_SCRIPT, json.dumps(names), json.dumps(overrides), output],
        cwd=tree, check=True,
    )


def compose(names: list[str], before_dir: str, after_dir: str, title: str, output: str):
    """Before / after pairs, one row per widget"""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    from tinypedal.main import load_bundled_fonts
    from tools.make_readme_preview import BACKGROUND

    _app = QApplication.instance() or QApplication(sys.argv)
    load_bundled_fonts()
    rows = []
    for name in names:
        before = QPixmap(os.path.join(before_dir, f"{name}.png"))  # null if widget is new
        after = QPixmap(os.path.join(after_dir, f"{name}.png"))
        rows.append((before, after))
    column = max(max(before.width(), after.width()) for before, after in rows)
    width = MARGIN * 2 + column * 2 + GAP
    height = MARGIN * 2 + LABEL_HEIGHT * 2 + sum(
        max(before.height(), after.height()) + LABEL_HEIGHT for before, after in rows)
    image = QPixmap(width, height)
    image.fill(BACKGROUND)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(QFont("JetBrains Mono", 14, QFont.Weight.Bold))
    painter.setPen(QColor(255, 255, 255, 220))
    painter.drawText(QRectF(MARGIN, MARGIN, width - MARGIN * 2, LABEL_HEIGHT),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
    top = MARGIN + LABEL_HEIGHT * 2
    painter.setFont(QFont("JetBrains Mono", 12))
    for name, (before, after) in zip(names, rows):
        for index, (label, pixmap) in enumerate((("Avant", before), ("Après", after))):
            left = MARGIN + index * (column + GAP)
            painter.setPen(QColor(255, 255, 255, 150))
            painter.drawText(QRectF(left, top - LABEL_HEIGHT, column, LABEL_HEIGHT),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{label} · {name}")
            if pixmap.isNull():
                painter.drawText(QRectF(left, top, column, LABEL_HEIGHT), Qt.AlignmentFlag.AlignLeft, "(nouveau)")
            else:
                painter.drawPixmap(int(left), int(top), pixmap)
        top += max(before.height(), after.height()) + LABEL_HEIGHT
    painter.end()
    picture = image.toImage()
    picture.setText("Title", title)  # caption of the image in release notes
    picture.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("widgets", nargs="+", help="widget names, for example black_box")
    parser.add_argument("--base", default="HEAD", help="revision rendered as before (default HEAD)")
    parser.add_argument("--set", action="append", default=[], metavar="WIDGET.OPTION=VALUE",
                        help="option override in both renders (repeatable)")
    parser.add_argument("--slug", default="", help="file name part (default: widget names)")
    parser.add_argument("--title", default="", help="caption on top (default: widget names)")
    args = parser.parse_args()
    overrides = parse_overrides(args.set)
    slug = args.slug or "-".join(name.replace("_", "-") for name in args.widgets)
    output = os.path.join(OUTPUT_DIR, f"{datetime.date.today().isoformat()}-{slug}.png")

    with tempfile.TemporaryDirectory() as temp:
        base_tree = os.path.join(temp, "base")
        subprocess.run(["git", "worktree", "add", "--detach", "--quiet", base_tree, args.base], cwd=ROOT, check=True)
        try:
            render_tree(base_tree, args.widgets, overrides, os.path.join(temp, "before"))
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", base_tree], cwd=ROOT, check=False)
        render_tree(ROOT, args.widgets, overrides, os.path.join(temp, "after"))
        os.makedirs(os.path.join(ROOT, OUTPUT_DIR), exist_ok=True)
        compose(args.widgets, os.path.join(temp, "before"), os.path.join(temp, "after"),
                args.title or ", ".join(args.widgets), os.path.join(ROOT, output))
    print(f"saved {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
