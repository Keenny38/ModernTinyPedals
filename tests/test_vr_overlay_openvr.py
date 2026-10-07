"""VR overlay with a mocked "openvr" module (no SteamVR / headset required)

Regression: release build left out openvr's native library, "import openvr" raised OSError (not
ImportError), which escaped VROverlay.enable(): no overlay in headset, rest of loading stopped.
"""

import builtins
import ctypes
import os
import runpy
import sys
import types

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

from tinypedal import app_signal, vr_overlay, vr_shared
from tinypedal.setting import cfg
from tinypedal.vr_overlay import VROverlay

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeOverlayWindow(QWidget):
    widget_name = "fake"


class HmdMatrix34_t:
    def __init__(self):
        self.m = [[0.0] * 4 for _ in range(3)]


class FakeIVROverlay:
    def __init__(self, log):
        self.log = log

    def createOverlay(self, key, name):
        self.log.append(("createOverlay", key, name))
        return 42

    def setOverlayWidthInMeters(self, handle, width):
        self.log.append(("setOverlayWidthInMeters", handle, width))

    def setOverlayTransformAbsolute(self, handle, origin, matrix):
        self.log.append(("setOverlayTransformAbsolute", handle, origin, [list(row) for row in matrix.m]))

    def setOverlayTransformTrackedDeviceRelative(self, handle, device, matrix):
        self.log.append(("setOverlayTransformTrackedDeviceRelative", handle, device, [list(row) for row in matrix.m]))

    def showOverlay(self, handle):
        self.log.append(("showOverlay", handle))

    def hideOverlay(self, handle):
        self.log.append(("hideOverlay", handle))

    def setOverlayRaw(self, handle, buffer, width, height, bytes_per_pixel):
        assert isinstance(buffer, ctypes.Array)  # pyopenvr passes byref(buffer)
        self.log.append(("setOverlayRaw", handle, len(buffer), width, height, bytes_per_pixel))

    def destroyOverlay(self, handle):
        self.log.append(("destroyOverlay", handle))


def fake_openvr(log):
    module = types.ModuleType("openvr")
    module.VRApplication_Overlay = 2
    module.TrackingUniverseSeated = 0
    module.k_unTrackedDeviceIndex_Hmd = 0
    module.HmdMatrix34_t = HmdMatrix34_t
    module.init = lambda app_type: log.append(("init", app_type))
    module.shutdown = lambda: log.append(("shutdown",))
    module.IVROverlay = lambda: FakeIVROverlay(log)
    return module


@pytest.fixture
def vr_setting(ui_env, monkeypatch):
    monkeypatch.setattr(vr_overlay, "steamvr_running", lambda: True)  # overlay created at once

    class SyncCheck:  # process check done at once (background thread in app)
        running = True

        def done(self):
            return True

    monkeypatch.setattr(vr_overlay, "SteamVRCheck", SyncCheck)
    setting = cfg.user.config["vr_overlay"]
    setting.update(enable_vr_overlay=True, enable_vr_mirror_window=False)
    errors = []
    app_signal.error.connect(errors.append)
    yield setting, errors
    app_signal.error.disconnect(errors.append)
    QCoreApplication.processEvents()


def test_openvr_native_library_missing_fails_cleanly(vr_setting, monkeypatch):
    """Package found but its DLL not loadable: OSError reported, enable() does not raise"""
    _, errors = vr_setting
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "openvr":
            raise FileNotFoundError("Could not find module 'libopenvr_api_64'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr(builtins, "__import__", failing_import)
    control = VROverlay()
    control.enable()  # must not raise (loader goes on with stream overlay...)
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert not control.running and not control._timer.isActive()
    assert errors and "libopenvr_api_64" in errors[-1]


@pytest.mark.parametrize("attach", [False, True])
def test_enable_creates_shows_and_places_overlay(vr_setting, monkeypatch, attach):
    setting, errors = vr_setting
    setting.update(
        enable_attach_to_headset=attach, overlay_width_meters=0.6, distance_meters=1.5,
        vertical_offset_meters=-0.3, horizontal_offset_meters=0.1, update_interval=50)
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    control = VROverlay()
    try:
        control.enable()
        assert not errors and control.running and control._timer.isActive()
        names = [entry[0] for entry in log]
        assert names[:3] == ["init", "createOverlay", "setOverlayWidthInMeters"]
        assert log[0] == ("init", 2)  # VRApplication_Overlay
        assert log[2] == ("setOverlayWidthInMeters", 42, 0.6)
        placement = log[3]
        if attach:
            assert placement[:3] == ("setOverlayTransformTrackedDeviceRelative", 42, 0)
        else:
            assert placement[:3] == ("setOverlayTransformAbsolute", 42, 0)  # seated universe
        assert placement[3] == [[1.0, 0.0, 0.0, 0.1], [0.0, 1.0, 0.0, -0.3], [0.0, 0.0, 1.0, -1.5]]
        assert names[-1] == "showOverlay"
    finally:
        control.disable()
    assert log[-2:] == [("destroyOverlay", 42), ("shutdown",)]
    assert not control.running


def test_update_uploads_rgba_frame(vr_setting, monkeypatch):
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    widget = FakeOverlayWindow()
    widget.setGeometry(10, 10, 60, 30)
    widget.setStyleSheet("background: red;")
    widget.show()
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: [widget]))
    control = VROverlay()
    try:
        control.enable()
        log.clear()
        control.update_overlay()
        raw = [entry for entry in log if entry[0] == "setOverlayRaw"]
        assert len(raw) == 1
        _, handle, size, width, height, bpp = raw[0]
        assert handle == 42 and bpp == 4 and width >= 60 and height >= 30
        assert size == width * height * 4  # buffer matches size & bytes per pixel
        assert control._buffer is not None and len(control._buffer) == size  # kept alive
    finally:
        widget.close()
        control.disable()


def test_steamvr_keeps_whole_canvas_image_openxr_tiles_match(vr_setting, monkeypatch):
    """SteamVR overlay: one image of the whole canvas (as before). OpenXR tiles: same pixels, each placed
    where its part of that image is shown by the SteamVR overlay (same meters per pixel & center)"""
    setting, _ = vr_setting
    setting.update(overlay_width_meters=0.9, distance_meters=1.2, vertical_offset_meters=-0.1,
                   horizontal_offset_meters=0.05, enable_attach_to_headset=False)
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    widgets = []
    for x, y, color in ((10, 10, "red"), (700, 400, "blue")):
        widget = FakeOverlayWindow()
        widget.setGeometry(x, y, 60, 30)
        widget.setStyleSheet(f"background: {color};")
        widget.show()
        widgets.append(widget)
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: widgets))
    control = VROverlay()
    try:
        control.enable()
        log.clear()
        control.update_overlay()
        raw = [entry for entry in log if entry[0] == "setOverlayRaw"]
        assert len(raw) == 1
        image = vr_overlay.compose_widgets(widgets)
        assert (raw[0][3], raw[0][4]) == (image.width(), image.height())  # whole canvas, gap included
        assert image.width() > 750 and image.height() > 420
    finally:
        control.disable()
    frame = vr_overlay.compose_tiles(widgets)
    assert frame is not None and frame.canvas == (image.width(), image.height()) and len(frame.tiles) == 2
    placement = vr_overlay.placement_from(setting)
    meters_per_pixel = placement.width_meters / image.width()
    for tile in frame.tiles:
        assert frame.atlas.copy(tile.atlas_x, tile.atlas_y, tile.width, tile.height) == image.copy(
            tile.canvas_x, tile.canvas_y, tile.width, tile.height)  # same pixels as SteamVR image part
        quad = vr_shared.tile_placement(placement, frame.canvas, tile)
        # Center of the part in the SteamVR overlay (centered on its transform, y up)
        center_x = placement.horizontal_offset_meters + (
            tile.canvas_x + tile.width / 2 - image.width() / 2) * meters_per_pixel
        center_y = placement.vertical_offset_meters - (
            tile.canvas_y + tile.height / 2 - image.height() / 2) * meters_per_pixel
        assert quad.horizontal_offset_meters == pytest.approx(center_x)
        assert quad.vertical_offset_meters == pytest.approx(center_y)
        assert quad.width_meters == pytest.approx(tile.width * meters_per_pixel)
        assert quad.distance_meters == placement.distance_meters and not quad.attach_to_headset
    for widget in widgets:
        widget.close()


def test_reload_starts_overlay_again(vr_setting, monkeypatch):
    """Settings applied: app reload (disable then enable) creates overlay again with new placement"""
    setting, _ = vr_setting
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    control = VROverlay()
    try:
        control.enable()
        control.disable()
        setting["overlay_width_meters"] = 1.2
        log.clear()
        control.enable()
        assert ("init", 2) in log and ("setOverlayWidthInMeters", 42, 1.2) in log
        assert control.running
    finally:
        control.disable()


def test_pyinstaller_hook_bundles_openvr_library(monkeypatch):
    """Release build: openvr native library collected (ctypes load not detected by PyInstaller)"""
    calls = []
    hooks = types.ModuleType("PyInstaller.utils.hooks")

    def collect_dynamic_libs(package, destdir=None, search_patterns=None):
        calls.append((package, search_patterns))
        return [(f"site-packages/{package}/{search_patterns[0]}", package)]

    hooks.collect_dynamic_libs = collect_dynamic_libs
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    hook = runpy.run_path(os.path.join(ROOT, "tools", "pyinstaller_hooks", "hook-openvr.py"))
    assert calls and calls[0][0] == "openvr"
    assert hook["binaries"] and hook["binaries"][0][1] == "openvr"
    pattern = hook["library_pattern"]
    assert pattern("Windows", 64) == "libopenvr_api_64.dll"
    assert pattern("Linux", 64) == "libopenvr_api_64.so"
    assert pattern("Darwin", 64) == "libopenvr_api_32.dylib"
