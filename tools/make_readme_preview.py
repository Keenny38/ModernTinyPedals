"""
Render README preview image from real widgets: images/readme_preview.png

Every widget is built with default modern settings on simulated LMU data: a GT3 car at
speed mid race at Road Atlanta, in a 20 car multi-class field. Data modules do not run
here, so their outputs (minfo) are filled directly. Widgets are then packed on a neutral
background, largest first.

The simulated race (neopedal/demo_data.py) is the one overlay pictures of the app show.

Run from project root after visual changes to widgets:
    python tools/make_readme_preview.py
"""

from __future__ import annotations

import math
import os
import pkgutil
import sys
from importlib import import_module

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF, Qt, QTimerEvent
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication(sys.argv)

from neopedal import demo_data
from neopedal.api_control import api
from neopedal.demo_data import HISTORY_WIDGETS, lmu_api, set_telemetry
from neopedal.main import load_bundled_fonts
from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.userfile.json_setting import copy_setting
from neopedal.widget._modern import create_widget

OUTPUT = os.path.join("images", "readme_preview.png")
WIDTH = 1920
MARGIN = 24
SPACING = 14
BACKGROUND = QColor(28, 31, 36)

__all__ = ("HISTORY_WIDGETS", "api", "copy_setting", "lmu_api", "load_bundled_fonts", "set_telemetry")


def set_vehicles():
    """Vehicles and relative module outputs (see neopedal.demo_data)"""
    demo_data.set_vehicles(minfo, cfg.user.setting["standings"], api.read)
    sample_driver_ranks()


def sample_driver_ranks():
    """Driver & Safety Rank of simulated drivers (rank column & field level, when switched on), as overlay
    pictures of the app: nothing read from the game folder nor online"""
    from neopedal import rank_info
    from neopedal.process import driver_ranks as dr
    from neopedal.process import field_ranks as fr
    from neopedal.userfile.badge_icons import icons
    from neopedal.widget._modern.drivers import SAMPLE_RANKS

    rank_info.ranks.poll = lambda: None
    rank_info.field.poll = lambda names: None
    icons.request = lambda key: None  # badge icons never downloaded (dots of badge colors)
    rank_info.field._ranks = {
        fr.driver_key(veh.driverName): dr.DriverRanks(
            veh.driverName, "", "", "", dr.Rank(*sample[:2], 50), dr.Rank(*sample[2:4], 50), sample[4])
        for veh in minfo.vehicles.dataSet if veh.driverName
        for sample in (SAMPLE_RANKS[veh.positionOverall % len(SAMPLE_RANKS)],)
    }


def set_modules():
    """Data module outputs the widgets read (see neopedal.demo_data)"""
    demo_data.set_modules(minfo)


def pack(sizes: dict[str, tuple[int, int]], width: int) -> tuple[dict[str, tuple[int, int]], int]:
    """Pack rectangles (largest first) into a fixed width, using skyline bottom-left placement"""
    skyline = [(0, width, 0)]  # segments: x, width, top y
    positions = {}
    for name, (w, h) in sorted(sizes.items(), key=lambda item: (-item[1][1], -item[1][0])):
        best = None
        for start, (seg_x, _, _) in enumerate(skyline):
            if seg_x + w > width:
                break
            # Lowest y where the rect fits starting at this segment
            top, span, index = 0, 0, start
            while span < w and index < len(skyline):
                top = max(top, skyline[index][2])
                span = skyline[index][0] + skyline[index][1] - seg_x
                index += 1
            if span < w:
                continue
            if best is None or top < best[1] or (top == best[1] and seg_x < best[0]):
                best = (seg_x, top)
        x, y = best
        positions[name] = (x, y)
        # Update skyline
        new_skyline = []
        for seg_x, seg_w, seg_y in skyline:
            seg_end = seg_x + seg_w
            if seg_end <= x or seg_x >= x + w:
                new_skyline.append((seg_x, seg_w, seg_y))
                continue
            if seg_x < x:
                new_skyline.append((seg_x, x - seg_x, seg_y))
            if seg_end > x + w:
                new_skyline.append((x + w, seg_end - x - w, seg_y))
        new_skyline.append((x, w, y + h))
        new_skyline.sort()
        skyline = new_skyline
    return positions, max(y + sizes[name][1] for name, (_, y) in positions.items())


def replay_history(widget, data):
    """Feed a widget drawing input history a corner, ending at the simulated state"""
    demo_data.replay_history(widget, data, minfo)


def without_game_pictures():
    """No car brand logo nor picture of the game (trademarks never published in repo images): empty
    brand logo & game picture folders (user's own logos left out), never fetched from a running game"""
    import tempfile

    from neopedal.userfile import game_images

    cfg.path.game_image = tempfile.mkdtemp(prefix="preview_pictures_")
    cfg.path.brand_logo = tempfile.mkdtemp(prefix="preview_logos_") + os.sep
    game_images.fetch_from_game = lambda *args, **kwargs: (0, b"")


def render_widgets(data) -> dict[str, QPixmap]:
    names = sorted(
        module.name
        for module in pkgutil.iter_modules(import_module("neopedal.widget").__path__)
        if not module.name.startswith("_")
    )
    pixmaps = {}
    for name in names:
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        widget.adjustSize()
        if name in HISTORY_WIDGETS:
            replay_history(widget, data)
        for _ in range(3):  # a few updates, so smoothed values settle
            widget.timerEvent(QTimerEvent(0))
        widget.adjustSize()  # rows shown on update (standings, relative) change the size
        # Render on transparent pixmap: grab() fills translucent areas with an opaque background
        pixmap = QPixmap(widget.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
        pixmaps[name] = pixmap
        widget.deleteLater()
    return pixmaps


def main():
    load_bundled_fonts()
    cfg.default.set_default()
    for name in cfg.user.__slots__:
        setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)))
    without_game_pictures()
    sim, data = lmu_api()
    api._api, api.read = sim, sim.reader()
    set_telemetry(sim, data)
    set_vehicles()
    set_modules()

    pixmaps = render_widgets(data)
    sizes = {name: (pixmap.width() + SPACING, pixmap.height() + SPACING) for name, pixmap in pixmaps.items()}
    positions, height = pack(sizes, WIDTH - MARGIN * 2 + SPACING)

    caption_height = 40
    image = QPixmap(WIDTH, height - SPACING + MARGIN * 2 + caption_height)
    image.fill(BACKGROUND)
    painter = QPainter(image)
    for name, (x, y) in positions.items():
        painter.drawPixmap(MARGIN + x, MARGIN + y, pixmaps[name])
    painter.setFont(QFont("JetBrains Mono", 13))
    painter.setPen(QColor(255, 255, 255, 140))
    painter.drawText(
        QRectF(MARGIN, image.height() - MARGIN - 24, WIDTH - MARGIN * 2, 24),
        Qt.AlignmentFlag.AlignRight,
        f"NeoPedal · all {len(pixmaps)} widgets · simulated data",
    )
    painter.end()
    image.save(OUTPUT)
    print(f"saved {OUTPUT} {image.width()}x{image.height()} ({math.floor(os.path.getsize(OUTPUT) / 1024)} KB)")


if __name__ == "__main__":
    main()
