"""Stream capture checksum in place & cached overlay list, results server folder lookups cached,
replay frame XOR by slices"""

import os
import random
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from test_stream_overlay import FakeOverlay, process_events

from neopedal import replay, stream_overlay
from neopedal.process import results_file as rf
from neopedal.stream_overlay import FrameStore, OverlayCapture


# Replay XOR
def xor_reference(data: bytes, base: bytes) -> bytes:
    return (int.from_bytes(data, "little") ^ int.from_bytes(base, "little")).to_bytes(len(data), "little")


@pytest.mark.parametrize("size", [0, 1, 100, replay.XOR_BLOCK, replay.XOR_BLOCK * 3 + 17])
def test_xor_bytes_same_as_whole_frame_xor(size):
    rng = random.Random(size)
    base = rng.randbytes(size)
    changed = bytearray(base)
    for _ in range(5):  # few changed places (mostly unchanged frame)
        if size:
            changed[rng.randrange(size)] ^= 0xFF
    cases = [
        (bytes(changed), base),
        (rng.randbytes(size), base),  # every slice changed
        (base, base),
        (bytes(size), base),  # zero frame
        (base, bytes(size)),  # zero previous frame
    ]
    for data, previous in cases:
        result = replay.xor_bytes(data, previous)
        assert isinstance(result, bytes) and result == xor_reference(data, previous)
        assert replay.xor_bytes(result, previous) == data  # decoded back


def test_replay_round_trip(tmp_path):
    rng = random.Random(1)
    frames = [(bytes(range(256)) * 200)[:replay.XOR_BLOCK * 2 + 5]]  # compressible like game data
    for _ in range(5):
        frame = bytearray(frames[-1])
        frame[rng.randrange(len(frame))] ^= 0x55
        frames.append(bytes(frame))
    path = tmp_path / "test.tpreplay"
    with open(path, "wb") as file:
        writer = replay.ReplayWriter(file, len(frames[0]), 30)
        for index, frame in enumerate(frames):
            writer.write(index / 30, frame)
        writer.finish()
    loaded = replay.ReplayFile(str(path))
    try:
        assert [loaded.frame(index) for index in range(len(frames))] == frames
    finally:
        loaded.close()


# Stream capture
def close_overlays(*overlays):
    for overlay in overlays:
        overlay.close()
        overlay.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_backing_checksum_same_as_copy():
    overlay = FakeOverlay("gear", "Screen & Stream")
    try:
        overlay.move(10, 10)
        overlay.show()
        process_events(0.1)
        image = stream_overlay.window_image(overlay)
        assert image is not None
        assert stream_overlay.backing_checksum(overlay) == stream_overlay.image_checksum(image)
    finally:
        close_overlays(overlay)


class FakeStore:
    def __init__(self, image):
        self.image = image

    def paintDevice(self):
        return self.image


def test_backing_checksum_of_wider_store(monkeypatch):
    """Backing store wider than window (lines not contiguous): checksum of window part, same as its copy"""
    overlay = FakeOverlay("gear", "Screen & Stream")
    try:
        store = QImage(100, 50, QImage.Format.Format_ARGB32_Premultiplied)
        store.fill(QColor("#80112233"))
        for x in range(60, 100):  # outside window: never counted
            store.setPixelColor(x, 3, QColor("#ffffffff"))
        store.setPixelColor(5, 5, QColor("#ff00ff00"))
        monkeypatch.setattr(overlay, "backingStore", lambda: FakeStore(store))
        expected = stream_overlay.image_checksum(store.copy(0, 0, 60, 30))
        assert stream_overlay.backing_checksum(overlay) == expected
        assert stream_overlay.window_image(overlay).size() == store.copy(0, 0, 60, 30).size()
        # Not a 32 bit image: copied (window_image) instead
        monkeypatch.setattr(overlay, "backingStore", lambda: FakeStore(store.convertToFormat(QImage.Format.Format_RGB16)))
        assert stream_overlay.backing_checksum(overlay) is None
    finally:
        close_overlays(overlay)


def test_overlay_windows_listed_again_only_when_overlays_change(monkeypatch):
    gear = FakeOverlay("gear", "Screen & Stream")
    gear.move(10, 10)
    gear.show()
    process_events(0.1)
    listed = []
    original = QApplication.topLevelWidgets
    monkeypatch.setattr(stream_overlay.QApplication, "topLevelWidgets", lambda: listed.append(1) or original())
    key = [("a",)]
    monkeypatch.setattr(stream_overlay, "active_overlays_key", lambda: key[0])
    store = FrameStore()
    capture = OverlayCapture(store)
    hidden = FakeOverlay("radar", "Screen & Stream")
    fuel = None
    try:
        store.touch("layout")
        capture.capture()
        capture.capture()
        capture.capture()
        assert len(listed) == 1
        assert [name for name, _ in capture.overlays()] == ["gear"]
        gear.wcfg = {"stream_visibility": "Screen Only"}  # options & visibility checked every time
        assert capture.overlays() == []
        gear.wcfg = {"stream_visibility": "Screen & Stream"}
        hidden.move(150, 10)
        hidden.show()  # listed while hidden (visibility context): on stream at once when shown
        process_events(0.1)
        assert sorted(name for name, _ in capture.overlays()) == ["gear", "radar"]
        close_overlays(hidden)
        fuel = FakeOverlay("fuel", "Screen & Stream")
        fuel.move(80, 10)
        fuel.show()
        process_events(0.1)
        assert [name for name, _ in capture.overlays()] == ["gear"]  # new window not listed yet
        key[0] = ("a", "b")  # overlay started
        assert sorted(name for name, _ in capture.overlays()) == ["fuel", "gear"] and len(listed) == 2
        now = time.monotonic()
        monkeypatch.setattr(stream_overlay.time, "monotonic", lambda: now + stream_overlay.LIST_SECONDS + 1)
        capture.overlays()
        assert len(listed) == 3  # listed again now and then
        close_overlays(fuel)  # closed window: skipped
        assert [name for name, _ in capture.overlays()] == ["gear"]
    finally:
        capture.stop()
        close_overlays(gear)


def test_canvas_kept_while_overlays_unchanged(monkeypatch):
    gear = FakeOverlay("gear", "Screen & Stream")
    gear.move(10, 10)
    gear.show()
    process_events(0.1)
    gear.paint_serial = 1
    capture = OverlayCapture(FrameStore())
    geometry = []
    original = gear.geometry
    monkeypatch.setattr(gear, "geometry", lambda: geometry.append(1) or original())
    screens = []
    original_screens = stream_overlay.screens_key
    monkeypatch.setattr(stream_overlay, "screens_key", lambda: screens.append(1) or original_screens())
    try:
        first = capture.canvas([gear])
        count = len(geometry)
        assert capture.canvas([gear]) == first and capture.canvas([gear]) == first
        assert len(geometry) == count and len(screens) == 1  # nothing painted or moved: places not looked at
        gear.paint_serial = 2
        capture.canvas([gear])
        assert len(geometry) == count + 1  # looked at, same places: canvas kept
        now = time.monotonic()
        monkeypatch.setattr(stream_overlay.time, "monotonic", lambda: now + stream_overlay.LIST_SECONDS + 1)
        capture.canvas([gear])
        assert len(screens) == 2
    finally:
        close_overlays(gear)


# Results folder lookups
def settle(path, age: float = 10.0):
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


def test_results_listing_cached_while_folder_unchanged(tmp_path, monkeypatch):
    rf.forget_lookups()
    (tmp_path / "2026_10_05_22_34_33-70R1.xml").write_text("<x/>", encoding="utf-8")
    settle(tmp_path, 20)
    scans = []
    original = os.scandir
    monkeypatch.setattr(rf.os, "scandir", lambda path: scans.append(path) or original(path))
    first = rf.results_files(str(tmp_path))
    assert rf.results_files(str(tmp_path)) == first and len(scans) == 1
    first.append("changed")  # copy returned
    assert len(rf.results_files(str(tmp_path))) == 1
    (tmp_path / "2026_10_06_22_34_33-70Q1.xml").write_text("<x/>", encoding="utf-8")
    settle(tmp_path, 10)  # new file: folder modified time changed
    assert [os.path.basename(path) for path in rf.results_files(str(tmp_path))] == [
        "2026_10_06_22_34_33-70Q1.xml", "2026_10_05_22_34_33-70R1.xml"]
    assert len(scans) == 2
    # Folder changed moments ago (time stamp granularity): listed every time
    (tmp_path / "2026_10_07_22_34_33-70R1.xml").write_text("<x/>", encoding="utf-8")
    assert len(rf.results_files(str(tmp_path))) == 3
    rf.results_files(str(tmp_path))
    assert len(scans) == 4
    # Listed again at least every LISTING_MAX_AGE
    settle(tmp_path, 10)
    rf.results_files(str(tmp_path))
    count = len(scans)
    now = time.monotonic()
    monkeypatch.setattr(rf.time, "monotonic", lambda: now + rf.LISTING_MAX_AGE + 1)
    rf.results_files(str(tmp_path))
    assert len(scans) == count + 1
    assert rf.results_files(str(tmp_path / "missing")) == []
    rf.forget_lookups()


def test_chosen_folder_read_again_only_when_changed(tmp_path, monkeypatch):
    rf.forget_lookups()
    settings = tmp_path / rf.PAGE_SETTINGS_FILE
    settings.write_text('{"folder": "C:/one"}', encoding="utf-8")
    settle(settings)
    opened = []
    original = open

    def counted(path, *args, **kwargs):
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", counted)
    assert rf.chosen_results_folder(str(tmp_path)) == "C:/one"
    assert rf.chosen_results_folder(str(tmp_path)) == "C:/one" and len(opened) == 1
    settings.write_text('{"folder": "C:/other"}', encoding="utf-8")
    assert rf.chosen_results_folder(str(tmp_path)) == "C:/other"  # just written: read
    settle(settings, 5)
    assert rf.chosen_results_folder(str(tmp_path)) == "C:/other"
    assert rf.chosen_results_folder(str(tmp_path)) == "C:/other" and len(opened) == 3
    settings.unlink()
    assert rf.chosen_results_folder(str(tmp_path)) == ""
    rf.forget_lookups()


def test_steam_game_folders_looked_up_again_after_a_while(tmp_path, monkeypatch):
    rf.forget_lookups()
    lookups = []
    monkeypatch.setattr(rf, "steam_folder", lambda: lookups.append(1) or str(tmp_path))
    assert rf.find_results_folders() == {}
    assert rf.find_results_folders() == {} and len(lookups) == 1
    now = time.monotonic()
    monkeypatch.setattr(rf.time, "monotonic", lambda: now + rf.STEAM_CACHE_SECONDS + 1)
    rf.find_results_folders()
    assert len(lookups) == 2
    rf.forget_lookups()
