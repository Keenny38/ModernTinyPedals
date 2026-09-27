"""VR overlay tests (no headset required)"""

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

from tinypedal import app_signal
from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting
from tinypedal.vr_overlay import MAX_PIXELS, VROverlay, compose_widgets, image_frame, overlay_transform


class FakeOverlay(QWidget):
    widget_name = "fake"


def make_widget(x, y, width, height):
    widget = FakeOverlay()
    widget.setGeometry(x, y, width, height)
    widget.setStyleSheet("background: red;")
    widget.show()
    return widget


def test_compose_keeps_layout():
    widgets = [make_widget(100, 100, 50, 20), make_widget(300, 200, 40, 40)]
    image = compose_widgets(widgets)
    # Bounding box of both widgets (frame geometry may add window frame on some platforms)
    assert image.width() >= 240 and image.height() >= 140
    for widget in widgets:
        widget.close()


def test_compose_scaled_down():
    widget = make_widget(0, 0, 2000, 1000)
    image = compose_widgets([widget])
    assert image.width() * image.height() <= MAX_PIXELS
    widget.close()


def test_compose_nothing_visible():
    assert compose_widgets([]) is None


def test_transform():
    matrix = overlay_transform(1.0, -0.2, 0.1)
    assert matrix[0][3] == 0.1 and matrix[1][3] == -0.2 and matrix[2][3] == -1.0


def test_enable_without_steamvr_fails_cleanly(monkeypatch):
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    config["vr_overlay"]["enable_vr_overlay"] = True
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    errors = []
    app_signal.error.connect(errors.append)
    control = VROverlay()
    control.enable()  # no SteamVR (or no openvr package): must not raise
    QCoreApplication.processEvents()
    assert not control.running
    assert errors  # user is notified
    app_signal.error.disconnect(errors.append)


def test_image_frame_checksum():
    widget = make_widget(0, 0, 60, 30)
    image = compose_widgets([widget])
    frame = image_frame(image)
    assert len(frame.buffer) == frame.width * frame.height * 4
    assert image_frame(image).checksum == frame.checksum  # unchanged image, same checksum
    widget.setStyleSheet("background: blue;")
    assert image_frame(compose_widgets([widget])).checksum != frame.checksum
    widget.close()


class FakeVR:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append(name)


def test_update_hides_and_skips_unchanged(monkeypatch):
    control = VROverlay()
    fake = FakeVR()
    control._overlay, control._handle, control._visible = fake, 1, True
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(list))
    control.update_overlay()
    assert fake.calls == ["hideOverlay"] and not control._visible
    widget = make_widget(0, 0, 60, 30)
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: [widget]))
    control.update_overlay()
    control.update_overlay()  # unchanged: no new upload
    assert fake.calls == ["hideOverlay", "setOverlayRaw", "showOverlay"]
    widget.close()
    control._overlay = control._handle = None
