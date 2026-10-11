"""VR overlay composition: canvas composed at the size sent, compared with the previous algorithm (full size
canvas of backing store copies, then scaled down), kept here as reference"""

import ctypes
import math
import random
import zlib

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QWidget

from tinypedal import vr_overlay, vr_shared
from tinypedal.vr_overlay import MAX_PIXELS, CanvasComposer, canvas_size, compose_tiles, content_rect, image_frame

# Reference: previous algorithm


def old_window_image(widget):
    if getattr(widget, "paint_serial", None) is not None:
        store = widget.backingStore()
        device = store.paintDevice() if store is not None else None
        if isinstance(device, QImage) and not device.isNull():
            ratio = device.devicePixelRatio()
            width, height = round(widget.width() * ratio), round(widget.height() * ratio)
            if 0 < width <= device.width() and 0 < height <= device.height():
                return device.copy(0, 0, width, height)
    pixmap = widget.grab()
    return pixmap.toImage() if not pixmap.isNull() else None


def old_compose_group(widgets, origin, size):
    image = QImage(size[0], size[1], QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    for widget in widgets:
        window = old_window_image(widget)
        if window is not None:
            painter.setOpacity(widget.windowOpacity())
            painter.drawImage(widget.frameGeometry().topLeft() - origin, window)
    painter.end()
    return image


def old_compose_widgets(widgets):
    visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
    if not visible:
        return None
    bounds = QRect()
    for widget in visible:
        bounds = bounds.united(widget.frameGeometry())
    image = old_compose_group(visible, bounds.topLeft(), (bounds.width(), bounds.height()))
    pixels = image.width() * image.height()
    if pixels > MAX_PIXELS:
        scale = (MAX_PIXELS / pixels) ** 0.5
        image = image.scaled(max(int(image.width() * scale), 1), max(int(image.height() * scale), 1),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return image


def old_row_span(image):
    bits = memoryview(image.constBits())[:image.sizeInBytes()]
    stride, width, height = image.bytesPerLine(), image.width(), image.height()
    zero = bytes(width)
    first = 0
    while first < height and bits[first * stride:first * stride + width] == zero:
        first += 1
    if first == height:
        return None
    last = height - 1
    while bits[last * stride:last * stride + width] == zero:
        last -= 1
    return first, last


def old_content_rect(image):
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    rows = old_row_span(alpha)
    if rows is None:
        return QRect()
    top, bottom = rows
    band = alpha.copy(0, top, alpha.width(), bottom - top + 1)
    columns = old_row_span(band.transformed(QTransform().rotate(90)))
    if columns is None:
        return QRect()
    left, right = columns
    return QRect(left, top, right - left + 1, bottom - top + 1)


def old_cluster_rects(rects, gap, max_count):
    """cluster_rects before its O(n²) rewrite (merge loop restarted after each merge)"""
    union_rect, near = vr_shared.union_rect, vr_shared._near
    groups = [([index], rect) for index, rect in enumerate(rects)]

    def merge(first, second):
        indexes = sorted(groups[first][0] + groups[second][0])
        groups[first] = (indexes, union_rect(groups[first][1], groups[second][1]))
        del groups[second]

    def merge_near(distance):
        merged = True
        while merged:
            merged = False
            for first in range(len(groups)):
                for second in range(first + 1, len(groups)):
                    if near(groups[first][1], groups[second][1], distance):
                        merge(first, second)
                        merged = True
                        break
                if merged:
                    break

    merge_near(gap)
    while len(groups) > max(max_count, 1):
        best = None
        for first in range(len(groups)):
            for second in range(first + 1, len(groups)):
                union = union_rect(groups[first][1], groups[second][1])
                growth = union[2] * union[3] - sum(group[1][2] * group[1][3] for group in (groups[first], groups[second]))
                if best is None or growth < best[0]:
                    best = (growth, first, second)
        merge(best[1], best[2])
        merge_near(0)
    return sorted((group[0] for group in groups), key=lambda indexes: indexes[0])


def previous_compose_tiles(widgets, max_tiles=vr_overlay.OPENXR_MAX_TILES, gap=vr_overlay.OPENXR_TILE_GAP):
    """compose_tiles before TileComposer: everything composed again on each call, checksum of whole atlas"""
    visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
    if not visible:
        return None
    geometries = [widget.frameGeometry() for widget in visible]
    bounds = QRect()
    for geometry in geometries:
        bounds = bounds.united(geometry)
    rects = [(rect.x() - bounds.x(), rect.y() - bounds.y(), rect.width(), rect.height()) for rect in geometries]
    parts = []
    for group in old_cluster_rects(rects, gap, min(max_tiles, vr_shared.MAX_TILES)):
        box = rects[group[0]]
        for index in group[1:]:
            box = vr_shared.union_rect(box, rects[index])
        image = vr_overlay.compose_group([visible[index] for index in group],
                                         bounds.topLeft() + QPoint(box[0], box[1]), (box[2], box[3]))
        rect = content_rect(image)
        if not rect.isEmpty():
            parts.append((image, rect, box[0] + rect.x(), box[1] + rect.y()))
    if not parts:
        return None
    area = sum(rect.width() * rect.height() for _, rect, _, _ in parts)
    scale = min(1.0, math.sqrt(MAX_PIXELS / area), vr_shared.MAX_CANVAS / max(bounds.width(), bounds.height()))
    while True:
        sizes = [(max(round(rect.width() * scale), 1), max(round(rect.height() * scale), 1)) for _, rect, _, _ in parts]
        packed = vr_shared.pack_atlas(sizes)
        if packed is not None and packed[1] * packed[2] * 4 <= vr_shared.MAX_IMAGE_BYTES:
            break
        scale *= 0.9
    positions, atlas_width, atlas_height = packed
    canvas = (min(max(round(bounds.width() * scale), 1), vr_shared.MAX_CANVAS),
              min(max(round(bounds.height() * scale), 1), vr_shared.MAX_CANVAS))
    atlas = QImage(atlas_width, atlas_height, QImage.Format.Format_RGBA8888)
    atlas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(atlas)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    tiles = []
    for (image, rect, x, y), (width, height), (atlas_x, atlas_y) in zip(parts, sizes, positions):
        if (width, height) != (rect.width(), rect.height()):
            painter.drawImage(atlas_x, atlas_y, image.copy(rect).scaled(
                width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            painter.drawImage(QPoint(atlas_x, atlas_y), image, rect)
        canvas_x = min(round(x * scale), canvas[0] - width)
        canvas_y = min(round(y * scale), canvas[1] - height)
        tiles.append(vr_shared.Tile(atlas_x, atlas_y, width, height, max(canvas_x, 0), max(canvas_y, 0)))
    painter.end()
    layout = repr((tiles, canvas)).encode()
    checksum = zlib.crc32(memoryview(atlas.constBits())[:atlas.sizeInBytes()], zlib.crc32(layout))
    return vr_overlay.TileFrame(atlas, tuple(tiles), canvas, checksum)


def old_compose_tiles(widgets, max_tiles=vr_overlay.OPENXR_MAX_TILES, gap=vr_overlay.OPENXR_TILE_GAP):
    visible = [widget for widget in widgets if widget.isVisible() and widget.width() > 0]
    if not visible:
        return None
    geometries = [widget.frameGeometry() for widget in visible]
    bounds = QRect()
    for geometry in geometries:
        bounds = bounds.united(geometry)
    rects = [(rect.x() - bounds.x(), rect.y() - bounds.y(), rect.width(), rect.height()) for rect in geometries]
    parts = []
    for group in old_cluster_rects(rects, gap, min(max_tiles, vr_shared.MAX_TILES)):
        box = rects[group[0]]
        for index in group[1:]:
            box = vr_shared.union_rect(box, rects[index])
        image = old_compose_group([visible[index] for index in group],
                                  bounds.topLeft() + QPoint(box[0], box[1]), (box[2], box[3]))
        rect = old_content_rect(image)
        if rect.isEmpty():
            continue
        if rect != image.rect():
            image = image.copy(rect)
        parts.append((image, box[0] + rect.x(), box[1] + rect.y()))
    if not parts:
        return None
    area = sum(image.width() * image.height() for image, _, _ in parts)
    scale = min(1.0, math.sqrt(MAX_PIXELS / area), vr_shared.MAX_CANVAS / max(bounds.width(), bounds.height()))
    while True:
        sizes = [(max(round(image.width() * scale), 1), max(round(image.height() * scale), 1)) for image, _, _ in parts]
        packed = vr_shared.pack_atlas(sizes)
        if packed is not None and packed[1] * packed[2] * 4 <= vr_shared.MAX_IMAGE_BYTES:
            break
        scale *= 0.9
    positions, atlas_width, atlas_height = packed
    canvas = (min(max(round(bounds.width() * scale), 1), vr_shared.MAX_CANVAS),
              min(max(round(bounds.height() * scale), 1), vr_shared.MAX_CANVAS))
    atlas = QImage(atlas_width, atlas_height, QImage.Format.Format_RGBA8888)
    atlas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(atlas)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    tiles = []
    for (image, x, y), (width, height), (atlas_x, atlas_y) in zip(parts, sizes, positions):
        if (width, height) != (image.width(), image.height()):
            image = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(atlas_x, atlas_y, image)
        canvas_x = min(round(x * scale), canvas[0] - width)
        canvas_y = min(round(y * scale), canvas[1] - height)
        tiles.append(vr_shared.Tile(atlas_x, atlas_y, width, height, max(canvas_x, 0), max(canvas_y, 0)))
    painter.end()
    layout = repr((tiles, canvas)).encode()
    checksum = zlib.crc32(memoryview(atlas.constBits())[:atlas.sizeInBytes()], zlib.crc32(layout))
    return vr_overlay.TileFrame(atlas, tuple(tiles), canvas, checksum)


# Fake overlay windows: frameless, translucent, painted like overlays (text, thin lines, gradient, bars)


class SceneWindow(QWidget):
    widget_name = "scene"

    def __init__(self, seed: int):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.seed = seed

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 180 + self.seed % 60))
        painter.drawRoundedRect(QRectF(0, 0, width, height), 6, 6)
        gradient = QLinearGradient(0, 0, width, 0)
        gradient.setColorAt(0, QColor(255, 40 * (self.seed % 6), 0))
        gradient.setColorAt(1, QColor(0, 200, 255, 200))
        painter.setBrush(gradient)
        painter.drawRect(QRectF(4, height - 14, (width - 8) * ((self.seed * 37) % 100) / 100, 10))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        for index in range(0, width, 7):
            painter.drawLine(index, 2, index, 6)
        font = QFont()
        font.setPixelSize(max(height // 5, 9))
        painter.setFont(font)
        painter.drawText(QRectF(6, 8, width - 12, height - 24), Qt.AlignmentFlag.AlignLeft,
                         f"Lap {self.seed} 1:23.{self.seed:03d} P{self.seed % 20}")
        painter.end()


def process_events(rounds=4):
    for _ in range(rounds):
        QCoreApplication.processEvents()


SERIAL = [0]


def counted(widget):
    """Window painted: paint serial as widget._base gives it"""
    SERIAL[0] += 1
    widget.paint_serial = SERIAL[0]


def make_scene(rects, opacities=None):
    windows = []
    for index, (x, y, width, height) in enumerate(rects):
        window = SceneWindow(index + 1)
        window.setGeometry(x, y, width, height)
        if opacities and index in opacities:
            window.setWindowOpacity(opacities[index])
        window.show()
        windows.append(window)
    process_events()
    for window in windows:
        counted(window)
    return windows


def close_all(windows):
    for window in windows:
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def repaint(window, seed):
    window.seed = seed
    window.repaint()
    process_events()
    counted(window)


# 10 windows over a 2560 x 1440 canvas (2 overlapping, 2 faded)
SCENE_1440P = [(0, 0, 420, 160), (300, 100, 300, 120), (2140, 0, 420, 200), (1100, 600, 360, 240),
               (0, 1240, 520, 200), (2260, 1240, 300, 200), (800, 20, 240, 90), (1600, 1000, 300, 140),
               (40, 500, 200, 400), (1900, 400, 320, 180)]
FADED = {3: 0.5, 7: 0.8}


def raw(image):
    return memoryview(image.constBits())[:image.sizeInBytes()].tobytes()


def pixel_diff(first, second):
    """Max & mean absolute byte difference, share of bytes differing by more than 32"""
    data_first, data_second = raw(first), raw(second)
    total = largest = over = 0
    for one, two in zip(data_first, data_second):
        diff = one - two if one > two else two - one
        total += diff
        over += diff > 32
        if diff > largest:
            largest = diff
    return largest, total / len(data_first), over / len(data_first)


def premultiplied_diff(first, second):
    """Max & mean difference of premultiplied pixels (color of transparent pixels ignored)"""
    return pixel_diff(first.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied),
                      second.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied))


@pytest.fixture(autouse=True)
def fresh_composer():
    vr_overlay._composer.reset()
    vr_overlay._tile_composer.reset()
    yield
    vr_overlay._composer.reset()
    vr_overlay._tile_composer.reset()


def test_canvas_size_matches_qimage_scaled():
    for width, height in ((1024, 1024), (1025, 1024), (2560, 1440), (1530, 910), (3000, 1300), (7680, 1440),
                          (5000, 30), (30, 5000), (1, 1048577), (1448, 725)):
        image = QImage(width, height, QImage.Format.Format_Alpha8)
        if width * height > MAX_PIXELS:
            scale = (MAX_PIXELS / (width * height)) ** 0.5
            image = image.scaled(max(int(width * scale), 1), max(int(height * scale), 1),
                                 Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        assert canvas_size(width, height) == (image.width(), image.height()), (width, height)


def test_unscaled_canvas_identical_to_previous():
    windows = make_scene([(10, 10, 300, 120), (200, 90, 260, 150), (700, 500, 200, 80)], {1: 0.6})
    try:
        old = old_compose_widgets(windows)
        new = CanvasComposer().compose(windows)
        assert new.format() == old.format() == QImage.Format.Format_RGBA8888
        assert new.size() == old.size() and new.width() * new.height() <= MAX_PIXELS
        assert raw(new) == raw(old)
    finally:
        close_all(windows)


def test_scaled_canvas_close_to_previous(capsys):
    windows = make_scene(SCENE_1440P, FADED)
    try:
        old = old_compose_widgets(windows)
        new = CanvasComposer().compose(windows)
        assert new.format() == old.format() == QImage.Format.Format_RGBA8888
        assert (new.width(), new.height()) == (old.width(), old.height()) == (1365, 768)
        largest, mean, _ = pixel_diff(new, old)
        largest_pm, mean_pm, over_pm = premultiplied_diff(new, old)
        with capsys.disabled():
            print(f"\n1440p scaled: max {largest} mean {mean:.3f} (premultiplied: max {largest_pm} "
                  f"mean {mean_pm:.3f}, {over_pm:.2%} bytes off by more than 32)")
        # Each window scaled (area average, as before) at its rounded place: up to half a pixel shift at edges
        assert mean_pm < 2.0 and over_pm < 0.01
    finally:
        close_all(windows)


def test_partial_redraw_same_as_full():
    windows = make_scene(SCENE_1440P, FADED)
    composer = CanvasComposer()
    try:
        first = composer.compose(windows)
        assert composer.compose(windows) is first  # nothing painted: unchanged
        for changed in ((1,), (0, 9), (3,), (8, 2, 5)):  # overlapping, faded, several
            for index in changed:
                repaint(windows[index], 30 + index * 3 + len(changed))
            image = composer.compose(windows)
            assert image is first  # updated in place
            assert raw(image) == raw(CanvasComposer().compose(windows)), changed
        windows[4].setWindowOpacity(0.3)  # layout changed: whole image drawn again
        process_events()
        assert raw(composer.compose(windows)) == raw(CanvasComposer().compose(windows))
        windows[6].move(900, 30)
        process_events()
        counted(windows[6])
        assert raw(composer.compose(windows)) == raw(CanvasComposer().compose(windows))
        windows[2].hide()  # canvas smaller: new image size
        assert raw(composer.compose(windows)) == raw(CanvasComposer().compose(windows))
    finally:
        close_all(windows)


def test_window_not_counted_always_drawn():
    windows = make_scene([(0, 0, 200, 100), (300, 0, 200, 100)])
    composer = CanvasComposer()
    try:
        del windows[1].paint_serial  # grabbed each time (window not counted)
        composer.compose(windows)
        windows[1].seed = 77
        windows[1].update()
        process_events()
        assert raw(composer.compose(windows)) == raw(old_compose_widgets(windows))
    finally:
        close_all(windows)


def test_backing_store_same_as_grab():
    """Window drawn from its backing store (no copy) gives the same image as rendering it again (grab)"""
    windows = make_scene([(0, 0, 300, 120), (250, 60, 200, 100)], {1: 0.7})
    try:
        for window in windows:
            del window.paint_serial
        grabbed = vr_overlay.compose_widgets(windows).copy()  # shared image, updated by next call
        for window in windows:
            counted(window)
        assert raw(vr_overlay.compose_widgets(windows)) == raw(grabbed)
    finally:
        close_all(windows)


def test_new_window_same_place_drawn_again():
    """Window closed & another opened at the same place with the same serial: never taken for the closed one"""
    composer = CanvasComposer()
    windows = make_scene([(0, 0, 200, 100)])
    serial = windows[0].paint_serial
    composer.compose(windows)
    close_all(windows)
    windows = make_scene([(0, 0, 200, 100)])
    try:
        windows[0].seed = 9
        windows[0].repaint()
        process_events()
        windows[0].paint_serial = serial
        assert raw(composer.compose(windows)) == raw(old_compose_widgets(windows))
    finally:
        close_all(windows)


def test_nothing_visible_releases_image():
    composer = CanvasComposer()
    windows = make_scene([(0, 0, 200, 100)])
    try:
        assert composer.compose(windows) is not None
        windows[0].hide()
        assert composer.compose(windows) is None and composer.image is None
    finally:
        close_all(windows)


def test_high_dpi_backing_store_drawn_at_window_size():
    windows = make_scene([(0, 0, 100, 50)])
    store = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    store.fill(QColor(0, 0, 255))
    store.setDevicePixelRatio(2.0)

    class Store:
        @staticmethod
        def paintDevice():
            return store

    windows[0].backingStore = lambda: Store()
    try:
        image, source = vr_overlay.window_source(windows[0])
        assert image is store and source == QRect(0, 0, 200, 100)  # backing store itself, device pixels
        composed = CanvasComposer().compose(windows)
        assert (composed.width(), composed.height()) == (100, 50)  # window size, whole store drawn in it
        assert composed.pixelColor(0, 0).getRgb() == composed.pixelColor(99, 49).getRgb() == (0, 0, 255, 255)
    finally:
        close_all(windows)


def test_backing_store_bigger_than_window_read_in_place():
    """Window part (top left) of a bigger backing store scaled without copy, same as scaling a copy of it"""
    windows = make_scene([(0, 0, 100, 50)])
    store = QImage(260, 140, QImage.Format.Format_ARGB32_Premultiplied)
    store.fill(QColor(255, 0, 0))  # outside the window: never drawn
    painter = QPainter(store)
    gradient = QLinearGradient(0, 0, 200, 100)
    gradient.setColorAt(0, QColor(0, 0, 255, 120))
    gradient.setColorAt(1, QColor(0, 255, 0))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.fillRect(0, 0, 200, 100, gradient)
    painter.end()
    store.setDevicePixelRatio(2.0)

    class Store:
        @staticmethod
        def paintDevice():
            return store

    windows[0].backingStore = lambda: Store()
    try:
        composed = CanvasComposer().compose(windows)
        expected = QImage(100, 50, QImage.Format.Format_RGBA8888)
        expected.fill(Qt.GlobalColor.transparent)
        painter = QPainter(expected)
        scaled = store.copy(0, 0, 200, 100).scaled(100, 50, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(QRect(0, 0, 100, 50), scaled, scaled.rect())
        painter.end()
        assert raw(composed) == raw(expected)
        assert all(composed.pixelColor(99, y).red() == 0 for y in range(50))
    finally:
        close_all(windows)


def test_image_frame_no_copy():
    image = QImage(64, 32, QImage.Format.Format_RGBA8888)
    image.fill(QColor(10, 20, 30, 40))
    frame = image_frame(image)
    assert len(frame.buffer) == 64 * 32 * 4 and frame.image is image
    assert bytes(frame.buffer) == raw(image) and frame.checksum == vr_overlay.image_checksum(image)
    address = ctypes.addressof(ctypes.c_char.from_buffer(memoryview(image.bits())))
    assert ctypes.addressof(frame.buffer) == address  # image pixels, not a copy


def test_content_rect_same_as_previous():
    image = QImage(301, 97, QImage.Format.Format_RGBA8888)
    image.fill(0)
    checks = [image.copy()]
    for x, y in ((7, 5), (290, 96), (0, 40), (300, 0), (150, 50)):
        image.setPixelColor(x, y, QColor(1, 2, 3, 1))
        checks.append(image.copy())
    image.fill(QColor(1, 2, 3, 200))
    checks.append(image.copy())
    checks.append(image.convertToFormat(QImage.Format.Format_ARGB32))  # other format (converted)
    odd = QImage(13, 7, QImage.Format.Format_ARGB32_Premultiplied)
    odd.fill(0)
    odd.setPixelColor(12, 3, QColor(255, 0, 0, 255))
    checks.append(odd)
    checks.append(QImage(5, 3, QImage.Format.Format_RGB32))  # opaque: whole image
    for check in checks:
        assert content_rect(check) == old_content_rect(check)


def test_compose_tiles_same_as_previous():
    for rects in ([(10, 10, 60, 30), (1500, 900, 40, 20), (100, 10, 20, 20)], SCENE_1440P,
                  [(index % 4 * 300, index // 4 * 200, 50, 40) for index in range(12)] + [(0, 700, 3000, 600)]):
        windows = make_scene(rects, FADED)
        try:
            new, old, previous = compose_tiles(windows), old_compose_tiles(windows), previous_compose_tiles(windows)
            assert (new.tiles, new.canvas) == (old.tiles, old.canvas) == (previous.tiles, previous.canvas)
            assert raw(new.atlas) == raw(old.atlas) == raw(previous.atlas)
            assert old.checksum == previous.checksum
            assert compose_tiles(windows).checksum == new.checksum  # unchanged
        finally:
            close_all(windows)


# 20 windows over 2560 x 1440: SCENE_1440P & 10 small ones (groups of several windows, far apart ones)
SCENE_20 = [*SCENE_1440P, (460, 300, 120, 50), (600, 300, 90, 50), (1250, 80, 150, 60), (1700, 700, 200, 90),
            (2000, 900, 160, 80), (300, 900, 200, 120), (520, 1000, 110, 60), (1500, 1300, 180, 100),
            (2400, 600, 150, 70), (1000, 1200, 240, 100)]


@pytest.fixture
def draw_count(monkeypatch):
    """Windows drawn (draw_window calls)"""
    calls = []
    original = vr_overlay.draw_window
    monkeypatch.setattr(vr_overlay, "draw_window", lambda *args: calls.append(args[1]) or original(*args))
    return calls


def test_tile_composer_updates_same_as_full(draw_count):
    """Tiles kept between updates (groups, group images, atlas): same output as composing everything again,
    checksum the same exactly when atlas & tiles are"""
    windows = make_scene(SCENE_20, FADED)
    composer = vr_overlay.TileComposer()
    last = []

    def check(label, max_tiles=vr_overlay.OPENXR_MAX_TILES, gap=vr_overlay.OPENXR_TILE_GAP):
        draw_count.clear()
        frame = composer.compose(windows, max_tiles, gap)
        drawn = len(draw_count)
        reference = previous_compose_tiles(windows, max_tiles, gap)
        assert (frame.tiles, frame.canvas) == (reference.tiles, reference.canvas), label
        assert raw(frame.atlas) == raw(reference.atlas), label
        state = (frame.tiles, frame.canvas, raw(frame.atlas))
        if last:
            assert (frame.checksum == last[0][0]) == (state == last[0][1]), label
        last[:] = [(frame.checksum, state)]
        return frame, drawn

    try:
        frame, drawn = check("first")
        assert drawn == len(windows)
        assert composer.compose(windows, vr_overlay.OPENXR_MAX_TILES, vr_overlay.OPENXR_TILE_GAP) is frame
        repaint(windows[1], 31)  # overlapping window 0
        assert check("one painted")[1] == 2  # its group only, windows in its rect
        checksum = last[0][0]
        counted(windows[1])  # painted the same
        assert check("painted the same")[0].checksum == checksum
        for changed in ((0, 9), (3,), (8, 2, 5), (12, 13), (19,)):
            for index in changed:
                repaint(windows[index], 40 + index * 3 + len(changed))
            assert check(f"painted {changed}")[1] < len(windows)
        windows[4].setWindowOpacity(0.3)  # group drawn again
        process_events()
        check("opacity")
        windows[6].move(900, 30)
        process_events()
        counted(windows[6])
        check("moved")
        windows[2].hide()  # canvas smaller
        check("hidden")
        windows[2].show()
        process_events()
        counted(windows[2])
        check("shown")
        check("one tile", max_tiles=1)
        check("no gap", gap=0)
        check("gap again")
    finally:
        close_all(windows)


def test_tile_composer_scaled_atlas_updates(draw_count):
    """Atlas scaled down to fit shared memory: changed tiles scaled & drawn again, same as everything again"""
    windows = make_scene([(index % 4 * 300, index // 4 * 200, 50, 40) for index in range(12)] + [(0, 700, 3000, 600)])
    composer = vr_overlay.TileComposer()
    try:
        first = composer.compose(windows, vr_overlay.OPENXR_MAX_TILES, vr_overlay.OPENXR_TILE_GAP)
        checksum = first.checksum
        assert first.canvas[0] < 3000  # scaled
        for index, seed in ((12, 70), (3, 71), (12, 72)):
            repaint(windows[index], seed)
            frame = composer.compose(windows, vr_overlay.OPENXR_MAX_TILES, vr_overlay.OPENXR_TILE_GAP)
            reference = previous_compose_tiles(windows)
            assert (frame.tiles, frame.canvas) == (reference.tiles, reference.canvas)
            assert raw(frame.atlas) == raw(reference.atlas)
            assert frame.checksum != checksum
            checksum = frame.checksum
    finally:
        close_all(windows)


def test_tile_composer_released_when_nothing_visible():
    windows = make_scene([(0, 0, 200, 100)])
    composer = vr_overlay.TileComposer()
    try:
        assert composer.compose(windows, 8, 32) is not None and composer._groups
        windows[0].hide()
        assert composer.compose(windows, 8, 32) is None
        assert composer._atlas is None and not composer._groups and composer._frame is None
    finally:
        close_all(windows)


def random_rects(rng, count, mode):
    if mode == 0:  # spread
        return [(rng.randint(0, 2400), rng.randint(0, 1300), rng.randint(0, 300), rng.randint(0, 200))
                for _ in range(count)]
    if mode == 1:  # grid, equal sizes: equal growths, first pair in index order wins
        step = rng.choice((50, 64, 100))
        return [(rng.randint(0, 20) * step, rng.randint(0, 12) * step, step // 2, step // 2) for _ in range(count)]
    if mode == 2:  # small widgets over a 2560 x 1440 screen
        return [(rng.randint(0, 2500), rng.randint(0, 1400), rng.randint(1, 60), rng.randint(1, 60))
                for _ in range(count)]
    return [(rng.randint(0, 300), rng.randint(0, 300), rng.randint(0, 80), rng.randint(0, 80))  # overlapping
            for _ in range(count)]


def test_cluster_rects_same_as_previous():
    rng = random.Random(7)
    for trial in range(3000):
        rects = random_rects(rng, rng.randint(0, 36), trial % 4)
        gap = rng.choice((-20, -1, 0, 1, 8, 32, 100))
        max_count = rng.choice((-1, 0, 1, 2, 3, 8, 16, 50))
        assert vr_shared.cluster_rects(rects, gap, max_count) == old_cluster_rects(rects, gap, max_count), (
            rects, gap, max_count)


def test_canvas_checksum_read_only_where_drawn(monkeypatch):
    """Checksum kept per band of rows: same as reading the whole image, rows outside drawn windows not read"""
    windows = make_scene(SCENE_1440P, FADED)
    composer = CanvasComposer()

    def full(image):
        return vr_overlay.RowChecksum().value(image, image.width() << 16 | image.height())

    try:
        image = composer.compose(windows)
        checksum = composer.checksum()
        assert checksum == full(image) and composer.dirty.boundingRect() == image.rect()
        read = []
        original = zlib.crc32
        repaint(windows[6], 7)  # painted the same (small window at the top)
        monkeypatch.setattr(vr_overlay.zlib, "crc32", lambda data, *seed: read.append(len(data)) or original(data, *seed))
        composer.compose(windows)
        assert composer.checksum() == checksum
        target = CanvasComposer.target(windows[6].frameGeometry(), windows[6], QRect(0, 0, 2560, 1440), image)
        assert composer.dirty.boundingRect() == target
        bands = -(-(target.bottom() + 1) // 16) - target.top() // 16
        assert sum(read[:-1]) == bands * 16 * image.bytesPerLine()  # its rows (bands), then the band checksums
        monkeypatch.setattr(vr_overlay.zlib, "crc32", original)
        repaint(windows[6], 60)
        composer.compose(windows)
        assert composer.checksum() != checksum and composer.checksum() == full(image)
        windows[2].hide()  # new image size: read whole
        image = composer.compose(windows)
        assert composer.checksum() == full(image)
        composer.reset()
        assert composer.checksum() is None
    finally:
        close_all(windows)


def canvas_bounds(windows):
    bounds = QRect()
    for window in windows:
        if window.isVisible():
            bounds = bounds.united(window.frameGeometry())
    return bounds


def backing_image(window):
    device = window.backingStore().paintDevice()
    return device.copy(0, 0, window.width(), window.height()).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)


def mirror_reference(image, size, background):
    """Mirror window as before: background, then composed image converted to a pixmap"""
    reference = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(reference)
    painter.fillRect(reference.rect(), background)
    painter.drawPixmap(0, 0, QPixmap.fromImage(image))
    painter.end()
    return reference


class PaintRects(QObject):
    def __init__(self):
        super().__init__()
        self.rects = []

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.rects.append(event.rect())
        return False


def test_mirror_window_repaints_changed_part_only(ui_env, monkeypatch):
    """Mirror window draws the composed image itself (no pixmap per update), only the part drawn since, same
    pixels as before; unchanged image not shown again"""
    windows = make_scene([*SCENE_1440P[:4], (1500, 700, 300, 140)])
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: windows))
    control = vr_overlay.VROverlay()
    control._mirror = mirror = vr_overlay.MirrorWindow("#203040", lambda: None)
    mirror.show()
    paints = PaintRects()
    mirror.installEventFilter(paints)
    shown = []
    original = mirror.set_image
    monkeypatch.setattr(mirror, "set_image", lambda *args: shown.append(args) or original(*args))
    try:
        control.update_overlay()
        process_events()
        image = vr_overlay._composer.image
        assert mirror.image is image and mirror.size() == image.size()
        assert raw(backing_image(mirror)) == raw(mirror_reference(image, mirror.size(), mirror.background))
        paints.rects.clear()
        repaint(windows[1], 77)
        control.update_overlay()
        process_events()
        target = CanvasComposer.target(windows[1].frameGeometry(), windows[1], canvas_bounds(windows), image)
        assert shown[-1][1].boundingRect() == target and paints.rects and all(
            target.contains(rect) for rect in paints.rects)
        assert raw(backing_image(mirror)) == raw(mirror_reference(image, mirror.size(), mirror.background))
        count = len(shown)
        counted(windows[1])  # painted the same: not shown again
        control.update_overlay()
        assert len(shown) == count
        repaint(windows[4], 78)
        control.update_overlay()
        process_events()
        assert len(shown) == count + 1
        assert raw(backing_image(mirror)) == raw(mirror_reference(image, mirror.size(), mirror.background))
        windows[0].hide()  # new canvas: whole window
        counted(windows[0])  # hidden (paint serial as widget._base gives it)
        control.update_overlay()
        process_events()
        assert shown[-1][1] is None or mirror.image is not image
        assert raw(backing_image(mirror)) == raw(mirror_reference(
            vr_overlay._composer.image, mirror.size(), mirror.background))
    finally:
        mirror.removeEventFilter(paints)
        control._mirror = None
        mirror.hide()
        mirror.deleteLater()
        control.disable()
        close_all(windows)


def test_update_sends_composed_image_without_copy(monkeypatch):
    """SteamVR gets the composed image pixels (same size & format as before), kept until next frame"""
    windows = make_scene(SCENE_1440P[:4])
    sent = []

    class Overlay:
        def setOverlayRaw(self, handle, buffer, width, height, bytes_per_pixel):
            sent.append((ctypes.addressof(buffer), len(buffer), width, height, bytes_per_pixel, bytes(buffer)))

        def showOverlay(self, handle):
            pass

        def hideOverlay(self, handle):
            pass

    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: windows))
    control = vr_overlay.VROverlay()
    control._overlay, control._handle, control._visible = Overlay(), 1, True
    try:
        expected = old_compose_widgets(windows)
        control.update_overlay()
        assert len(sent) == 1
        address, size, width, height, bpp, data = sent[0]
        assert (size, width, height, bpp) == (expected.sizeInBytes(), expected.width(), expected.height(), 4)
        assert premultiplied_diff(control._buffer_image, expected)[1] < 2.0
        assert address == ctypes.addressof(ctypes.c_char.from_buffer(memoryview(control._buffer_image.bits())))
        repaint(windows[1], 50)
        control.update_overlay()
        assert len(sent) == 2 and sent[1][0] == address and sent[1][5] != data  # same canvas, updated in place
        counted(windows[1])  # painted the same: not sent again
        control.update_overlay()
        assert len(sent) == 2
    finally:
        control._overlay = control._handle = None
        control.disable()
        close_all(windows)


def test_image_part_read_in_place():
    """Part of an image read without copy: same pixels & same scaled image as a copy of it"""
    image = QImage(301, 97, QImage.Format.Format_RGBA8888)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 301, 97)
    gradient.setColorAt(0, QColor(255, 0, 0, 40))
    gradient.setColorAt(1, QColor(0, 255, 200, 255))
    painter.fillRect(20, 5, 250, 80, gradient)
    painter.end()
    assert vr_overlay.image_part(image, image.rect()) is image
    for rect in (QRect(0, 0, 301, 1), QRect(17, 3, 200, 61), QRect(299, 95, 2, 2), QRect(5, 40, 296, 57)):
        part = vr_overlay.image_part(image, rect)
        assert raw(part.copy()) == raw(image.copy(rect))
        size = (max(rect.width() // 3, 1), max(rect.height() // 2, 1))  # smaller (only scaled then)
        assert raw(part.scaled(*size, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)) == raw(image.copy(rect).scaled(
            *size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))


def test_tile_group_visible_part_same_as_content_rect():
    """Visible part of a group found per band of rows, only drawn bands read again: same as content_rect"""
    image = QImage(130, 70, QImage.Format.Format_RGBA8888)
    image.fill(0)
    group = vr_overlay.TileGroup((), image, [])
    assert group.rect.isEmpty() and len(group.bands) == 5
    for x, y, alpha in ((7, 5, 1), (129, 69, 255), (0, 40, 9), (60, 16, 3), (7, 5, 0), (129, 69, 0), (0, 40, 0),
                        (60, 16, 0)):
        image.setPixelColor(x, y, QColor(1, 2, 3, alpha))
        group.drawn(y, y + 1)
        assert group.rect == content_rect(image), (x, y, alpha)
