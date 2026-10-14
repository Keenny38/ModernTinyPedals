"""VR overlay resource use: dirty rect writes for the OpenXR layer, SteamVR rate limit, updates paused with overlays,
process snapshot for the SteamVR check"""

import os
import struct
import sys

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import overlay_signal, realtime_state, vr_overlay, vr_shared
from neopedal.vr_overlay import VROverlay
from tests.test_vr_shared import FakeOverlayWindow, env, fake_openvr, make_widget  # noqa: F401


def dirty_fields(buffer):
    return struct.unpack_from("<6I", buffer, vr_shared.OFFSET_DIRTY)


def serial(buffer):
    return struct.unpack_from("<I", buffer, vr_shared.OFFSET_FRAME + 20)[0]


def pixel_rows(buffer, stride, rows):
    return bytes(buffer[vr_shared.DATA_OFFSET:vr_shared.DATA_OFFSET + stride * rows])


def test_writer_dirty_rect_copies_changed_rows_only():
    buffer = bytearray(vr_shared.MAPPING_SIZE)
    writer = vr_shared.SharedFrameWriter(buffer)
    assert writer.open()
    tiles = [vr_shared.Tile(0, 0, 4, 3, 0, 0)]
    first = bytes([1]) * 48  # 4 x 3, stride 16
    writer.write_tiles(first, 4, 3, 16, tiles, (4, 3), dirty=(1, 1, 2, 1))  # nothing written before: whole
    assert dirty_fields(buffer) == (0, 0, 0, 0, 0, 0) and pixel_rows(buffer, 16, 3) == first
    base = serial(buffer)
    second = bytes([2]) * 48
    writer.write_tiles(second, 4, 3, 16, tiles, (4, 3), dirty=(1, 1, 2, 1))
    assert dirty_fields(buffer) == (vr_shared.DIRTY_RECT, base, 1, 1, 2, 1) and serial(buffer) == base + 1
    assert pixel_rows(buffer, 16, 3) == bytes([1]) * 16 + bytes([2]) * 16 + bytes([1]) * 16  # row 1 only
    # Tiles moved only: empty rect, no pixel copied
    writer.write_tiles(bytes([3]) * 48, 4, 3, 16, tiles, (4, 3), dirty=(0, 0, 0, 0))
    assert dirty_fields(buffer) == (vr_shared.DIRTY_RECT, base + 1, 0, 0, 0, 0)
    assert pixel_rows(buffer, 16, 3) == bytes([1]) * 16 + bytes([2]) * 16 + bytes([1]) * 16
    # Other size, rect outside atlas, failed write: whole atlas
    writer.write_tiles(bytes([4]) * 64, 4, 4, 16, [vr_shared.Tile(0, 0, 4, 4, 0, 0)], (4, 4), dirty=(0, 0, 1, 1))
    assert dirty_fields(buffer)[0] == 0 and pixel_rows(buffer, 16, 4) == bytes([4]) * 64
    writer.write_tiles(bytes([5]) * 64, 4, 4, 16, [vr_shared.Tile(0, 0, 4, 4, 0, 0)], (4, 4), dirty=(3, 0, 2, 1))
    assert dirty_fields(buffer)[0] == 0 and pixel_rows(buffer, 16, 4) == bytes([5]) * 64
    with pytest.raises(ValueError):  # refused before any copy: memory still the last atlas
        writer.write_tiles(bytes(8), 4, 4, 16, [vr_shared.Tile(0, 0, 4, 4, 0, 0)], (4, 4), dirty=(0, 0, 1, 1))
    writer.write_tiles(bytes([6]) * 64, 4, 4, 16, [vr_shared.Tile(0, 0, 4, 4, 0, 0)], (4, 4), dirty=(0, 0, 1, 1))
    assert dirty_fields(buffer)[0] == vr_shared.DIRTY_RECT
    assert pixel_rows(buffer, 16, 4) == bytes([6]) * 16 + bytes([5]) * 48


def test_tile_composer_dirty_rect_of_changed_tile(ui_env):
    first, second = FakeOverlayWindow(), FakeOverlayWindow()
    try:
        for widget, x in ((first, 0), (second, 300)):
            widget.setGeometry(x, 0, 40, 20)
            widget.setStyleSheet("background: red;")
            widget.paint_serial = 1
            widget.show()
        QCoreApplication.processEvents()
        composer = vr_overlay.TileComposer()
        frame = composer.compose([first, second], 8, 32)
        assert frame is not None and frame.dirty is None and len(frame.tiles) == 2  # first atlas: whole
        second.setStyleSheet("background: blue;")
        second.paint_serial = 2
        QCoreApplication.processEvents()
        frame = composer.compose([first, second], 8, 32)
        tile = max(frame.tiles, key=lambda tile: tile.canvas_x)  # second widget's tile
        assert frame.dirty == (tile.atlas_x, tile.atlas_y, tile.width, tile.height)
    finally:
        first.close()
        second.close()


def test_steamvr_image_rate_limited(env, monkeypatch):  # noqa: F811
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    env.steamvr = True
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        control.update_overlay()
        assert log.count("setOverlayRaw") == 1
        widget.setStyleSheet("background: blue;")
        env.now += 10
        control.update_overlay()
        assert log.count("setOverlayRaw") == 1 and control._steamvr_dirty  # held back
        env.now += vr_overlay.STEAMVR_MIN_INTERVAL_MS
        control.update_overlay()
        assert log.count("setOverlayRaw") == 2 and not control._steamvr_dirty
        env.now += vr_overlay.STEAMVR_MIN_INTERVAL_MS
        control.update_overlay()
        assert log.count("setOverlayRaw") == 2  # unchanged image never sent again
    finally:
        widget.close()
        control.disable()


def test_updates_slowed_then_stopped_while_paused(env, monkeypatch):  # noqa: F811
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        assert control._timer.isActive() and control._timer.interval() == 50
        monkeypatch.setattr(realtime_state, "shown", False)  # not driving
        control.update_overlay()
        env.now += vr_overlay.PAUSED_GRACE_MS
        control.update_overlay()  # overlay still visible (auto hide off): slowed
        assert control._timer.isActive() and control._timer.interval() == vr_overlay.PAUSED_INTERVAL_MS
        widget.hide()
        env.now += vr_overlay.PAUSED_INTERVAL_MS
        control.update_overlay()  # nothing visible: stopped, OpenXR heartbeat kept
        assert not control._timer.isActive() and control._heartbeat_timer.isActive()
        monkeypatch.setattr(realtime_state, "shown", True)
        overlay_signal.paused.emit(False)  # driving again
        QCoreApplication.processEvents()
        assert control._timer.isActive() and control._timer.interval() == 50
    finally:
        widget.close()
        control.disable()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process snapshot")
def test_process_snapshot_lists_this_process():
    names = vr_overlay.process_names_windows()
    assert names is not None and os.path.basename(sys.executable).lower() in names


def test_steamvr_running_from_snapshot(monkeypatch):
    monkeypatch.setattr(vr_overlay, "process_names_windows", lambda: {"explorer.exe", "vrserver.exe"})
    assert vr_overlay.steamvr_running()
    monkeypatch.setattr(vr_overlay, "process_names_windows", lambda: {"explorer.exe"})
    assert not vr_overlay.steamvr_running()
