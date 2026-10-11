"""Paint caches: pixmap alignment looked up once per painter & translation, value texts in their own cache"""

import pytest
from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QImage, QPainter, QPixmap


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 2.0])
def test_cached_alignment_same_as_device_transform(ratio):
    from tinypedal.widget._painter import pixel_aligned

    pixmap = QPixmap(round(200 * ratio), round(100 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    try:
        points = [QPointF(x / 7, y / 3) for x in range(0, 300, 13) for y in range(0, 90, 11)]
        for translation in ((0, 0), (0.5, 0.25), (3, 7), (-2.75, 1.5), (0, 0)):
            painter.save()
            painter.translate(*translation)
            world = painter.transform()
            for point in points:
                assert pixel_aligned(painter, point, world) == pixel_aligned(painter, point)
            painter.restore()
        painter.setViewport(QRect(0, 50, 100, -50))  # view transform: device transform read every time
        world = painter.transform()
        assert pixel_aligned(painter, points[5], world) == pixel_aligned(painter, points[5])
    finally:
        painter.end()


def test_alignment_cache_follows_painter():
    """A new painter (other device scale) never uses alignments of the previous one"""
    from tinypedal.widget._painter import pixel_aligned

    point = QPointF(10.3, 4.6)
    results = []
    for ratio in (2.0, 1.0):
        image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        painter = QPainter(image)
        results.append(pixel_aligned(painter, point, painter.transform()))
        assert results[-1] == pixel_aligned(painter, point)
        painter.end()
    assert results[0] != results[1]


def test_value_texts_never_push_out_labels(ui_env, bundled_fonts, monkeypatch):
    from importlib import import_module

    from tinypedal.setting import cfg
    from tinypedal.widget._modern import base

    widget = import_module("tinypedal.widget._modern.speedometer").Realtime(cfg, "speedometer")
    try:
        monkeypatch.setattr(base, "VALUE_CACHE_MIN", 4)
        widget._text_cache.clear()
        widget._value_cache.clear()
        widget.static_text("label", "Top speed")
        for value in range(100):  # timer, delta: a new value every update
            widget.static_text("value", f"{value * 0.013:.3f}")
        assert ("label", "Top speed") in widget._text_cache
        assert len(widget._value_cache) == 4 and len(widget._text_cache) == 1
        static = widget.static_text("value", "1.287")  # drawn again: from cache
        assert widget.static_text("value", "1.287") is static
        widget._last_values_drawn = 10_000
        assert widget.value_cache_size() == base.TEXT_CACHE_SIZE  # bounded
        widget.state = None
        widget.resize(100, 50)
        widget.grab()  # paint counts values drawn
        assert widget._last_values_drawn == widget._values_drawn
    finally:
        widget.deleteLater()
