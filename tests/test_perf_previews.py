"""Overlay pictures served by the overlaypreview image provider (no PNG data URLs in models)"""

import gc
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QSize, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QColor, QImage

from tinypedal.ui.quick import preview_provider
from tinypedal.ui.quick.overlay_backend import OverlayModel, PreviewCache
from tinypedal.ui.quick.preview_provider import STORE, PreviewProvider, PreviewStore, fit_image, key_of


def solid(color: str, width: int = 40, height: int = 20) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_store_url_changes_only_with_picture():
    store = PreviewStore()
    first = store.put("a b/c", solid("#ff0000"))
    assert first.startswith("image://overlaypreview/a%20b%2Fc?v=")
    assert store.put("a b/c", solid("#ff0000")) == first  # same picture: same URL, QML cache kept
    second = store.put("a b/c", solid("#00ff00"))
    assert second != first
    assert key_of(second.removeprefix(preview_provider.URL_PREFIX)) == "a b/c"
    assert key_of("a b/c?v=3") == "a b/c"  # id given already decoded


def test_store_returns_copies_and_releases_owner():
    store = PreviewStore()
    prefix = store.new_prefix("test")
    image = solid("#123456")
    store.put(f"{prefix}x", image)
    image.fill(QColor("#ffffff"))  # caller painting again does not change the stored picture
    copy = store.get(f"{prefix}x")
    assert copy is not None and copy.pixelColor(1, 1) == QColor("#123456")
    copy.fill(QColor("#000000"))
    assert store.get(f"{prefix}x").pixelColor(1, 1) == QColor("#123456")
    store.put("other/x", image)
    store.release(prefix)
    assert store.get(f"{prefix}x") is None and store.get("other/x") is not None
    assert len(store) == 1


def test_store_thread_safe():
    store = PreviewStore()
    errors = []

    def reader():
        try:
            for _ in range(300):
                image = store.get("k")
                assert image is None or not image.isNull()
        except Exception as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    for index in range(300):
        store.put("k", solid("#ff0000" if index % 2 else "#0000ff"))
    for thread in threads:
        thread.join()
    assert not errors


def test_provider_scales_to_requested_size():
    store = PreviewStore()
    store.put("big", solid("#ff0000", 400, 200))
    provider = PreviewProvider(store)
    size = QSize()
    image = provider.requestImage("big?v=1", size, QSize(100, -1))
    assert (image.width(), image.height()) == (100, 50)
    assert provider.requestImage("big?v=1", QSize(), QSize()).width() == 400  # no sourceSize: full picture
    assert provider.requestImage("big?v=1", QSize(), QSize(800, 800)).width() == 400  # never scaled up
    assert provider.requestImage("missing?v=1", QSize(), QSize()).isNull()
    assert fit_image(solid("#ff0000", 10, 10), QSize(0, 0)).width() == 10


def test_preview_cache_pictures_released_with_cache():
    cache = PreviewCache(lambda name: solid("#ff0000"), lambda name: None)
    cache.render_now("gear")
    url = cache.role("gear", OverlayModel.PreviewRole)
    key = key_of(url.removeprefix(preview_provider.URL_PREFIX))
    assert STORE.get(key) is not None
    cache.stop()
    del cache
    gc.collect()
    assert STORE.get(key) is None  # no picture left behind in the shared store


@pytest.fixture
def qml_messages():
    messages = []

    def handler(mode, context, message):
        if mode != QtMsgType.QtDebugMsg:
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    yield messages
    qInstallMessageHandler(previous)


def test_overlays_page_shows_provider_pictures(ui_env, qml_messages):
    from tinypedal.ui.overlay_view import OverlayView

    view = OverlayView(None)
    view.resize(900, 640)
    view.show()
    try:
        images = []
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            stack = [view.view.rootObject()]
            images = []
            while stack:
                item = stack.pop()
                source = item.property("source")
                if (item.metaObject().className().startswith("QQuickImage")
                        and str(source.toString() if hasattr(source, "toString") else source).startswith(
                            "image://overlaypreview/")
                        and item.property("implicitWidth") > 0):
                    images.append(item)
                stack.extend(item.childItems())
            if images:
                break
            time.sleep(0.01)
        assert images, "no overlay picture loaded from the image provider"
        source_width = images[0].property("sourceSize").width()
        assert source_width == 0 or source_width % 32 == 0
        assert not [text for text in qml_messages if "qml" in text.lower() or "image" in text.lower()], qml_messages
    finally:
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, 0)
