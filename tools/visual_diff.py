"""Compare widget renders of two folders (base & changed), for visual regression check in CI

Usage:
    python tools/visual_diff.py [--allow-changes] BASE_DIR NEW_DIR [DIFF_DIR]

Images with same name are compared pixel by pixel. A pixel is changed if any channel differs
by more than CHANNEL_TOLERANCE (antialiasing noise is ignored). An image is reported if more than
CHANGED_RATIO of its pixels changed, or if its size changed. Diff images (changed pixels in red
over a faded copy of new render) are written to DIFF_DIR. A markdown summary is printed, and
appended to $GITHUB_STEP_SUMMARY if set. Exit code 1 if any image changed, unless --allow-changes
(intended change: before / after image added in docs/changes, or "[visual]" in a commit message).
"""

from __future__ import annotations

import os
import sys
from typing import NamedTuple

CHANNEL_TOLERANCE = 24
CHANGED_RATIO = 0.002


class Difference(NamedTuple):
    name: str
    changed: int  # changed pixels, -1 if size changed
    total: int
    note: str


def compare_images(base_file: str, new_file: str, diff_file: str = "") -> Difference:
    """Compare two images, write diff image if changed"""
    from PySide6.QtGui import QColor, QImage

    name = os.path.basename(new_file)
    base = QImage(base_file).convertToFormat(QImage.Format.Format_ARGB32)
    new = QImage(new_file).convertToFormat(QImage.Format.Format_ARGB32)
    if base.size() != new.size():
        return Difference(name, -1, new.width() * new.height(),
                          f"size {base.width()}x{base.height()} -> {new.width()}x{new.height()}")
    width, height = new.width(), new.height()
    diff = QImage(new) if diff_file else None
    changed = 0
    for y in range(height):
        for x in range(width):
            a, b = base.pixelColor(x, y), new.pixelColor(x, y)
            if (abs(a.red() - b.red()) > CHANNEL_TOLERANCE or abs(a.green() - b.green()) > CHANNEL_TOLERANCE
                    or abs(a.blue() - b.blue()) > CHANNEL_TOLERANCE or abs(a.alpha() - b.alpha()) > CHANNEL_TOLERANCE):
                changed += 1
                if diff is not None:
                    diff.setPixelColor(x, y, QColor(255, 0, 0, 255))
            elif diff is not None:
                faded = QColor(b)
                faded.setAlpha(b.alpha() // 4)
                diff.setPixelColor(x, y, faded)
    total = max(width * height, 1)
    if diff is not None and changed / total > CHANGED_RATIO:
        diff.save(diff_file)
    return Difference(name, changed, total, "")


def compare_folders(base_dir: str, new_dir: str, diff_dir: str = "") -> tuple[list[Difference], list[str], list[str]]:
    """Changed images, images only in new folder, images only in base folder"""
    base_names = {name for name in os.listdir(base_dir) if name.endswith(".png")}
    new_names = {name for name in os.listdir(new_dir) if name.endswith(".png")}
    if diff_dir:
        os.makedirs(diff_dir, exist_ok=True)
    differences = []
    for name in sorted(base_names & new_names):
        diff_file = os.path.join(diff_dir, name) if diff_dir else ""
        result = compare_images(os.path.join(base_dir, name), os.path.join(new_dir, name), diff_file)
        if result.changed < 0 or result.changed / result.total > CHANGED_RATIO:
            differences.append(result)
    return differences, sorted(new_names - base_names), sorted(base_names - new_names)


def summary(differences: list[Difference], added: list[str], removed: list[str]) -> str:
    """Markdown report"""
    lines = ["## Widget visual changes", ""]
    if not (differences or added or removed):
        lines.append("No visual change.")
        return "\n".join(lines) + "\n"
    if differences:
        lines += ["| Render | Change |", "|---|---|"]
        for result in differences:
            change = result.note or f"{result.changed / result.total:.1%} of pixels"
            lines.append(f"| {result.name} | {change} |")
        lines.append("")
        lines.append("Diff images (changed pixels in red) are in the `widget-visual-diff` artifact.")
    if added:
        lines.append(f"New renders: {', '.join(added)}")
    if removed:
        lines.append(f"Removed renders: {', '.join(removed)}")
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    allow_changes = "--allow-changes" in args
    args = [arg for arg in args if arg != "--allow-changes"]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    from PySide6.QtGui import QGuiApplication

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication(sys.argv[:1])  # noqa: F841  # needed by QImage color conversion
    differences, added, removed = compare_folders(args[0], args[1], args[2] if len(args) > 2 else "")
    report = summary(differences, added, removed)
    if differences and allow_changes:
        report += "\nIntended visual change (before / after image in docs/changes or [visual] commit): not failing.\n"
    print(report)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as file:
            file.write(report)
    sys.exit(1 if differences and not allow_changes else 0)


if __name__ == "__main__":
    main()
