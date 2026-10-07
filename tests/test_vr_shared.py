"""OpenXR overlay layer, app side (no headset, no Windows needed)

Shared memory layout checked against the C header of the layer, registry with a fake winreg module,
VROverlay with the layer & SteamVR mocked: SteamVR started only once running, SteamVR overlay hidden
while the OpenXR layer draws the overlay.
"""

import json
import os
import re
import struct
import sys
import types

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from tinypedal import app_signal, vr_overlay, vr_shared
from tinypedal.setting import cfg
from tinypedal.vr_overlay import VROverlay, fit_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER_DIR = os.path.join(ROOT, "native", "openxr_layer")
HEADER = os.path.join(LAYER_DIR, "include", "tinypedal_vr_shared.h")


def c_header():
    """#define values, TpvrHeader & TpvrTile field offsets (from offset comments) of the layer header"""
    with open(HEADER, encoding="utf-8") as file:
        text = file.read()
    defines = {}
    for name, value in re.findall(r"^#define (TPVR_\w+) (.+?)(?:\s*/\*.*)?$", text, re.M):
        value = re.sub(r"(\d+)u\b", r"\1", value.strip())
        if value.startswith('"'):
            defines[name] = value.strip('"')
        else:
            defines[name] = eval(re.sub(r"TPVR_\w+", lambda m: str(defines[m[0]]), value))
    structs = {}
    for body, name in re.findall(r"^typedef struct \w+ \{(.*?)^\} (\w+);", text, re.M | re.S):
        structs[name] = {field: int(offset)
                         for field, offset in re.findall(r"^\s+\w+ (\w+)(?:\[\d+\])?;\s+/\* (\d+)", body, re.M)}
    return defines, structs["TpvrHeader"], structs["TpvrTile"]


def test_protocol_matches_layer_header():
    defines, fields, tile_fields = c_header()
    assert defines["TPVR_MAPPING_NAME"] == vr_shared.MAPPING_NAME
    assert defines["TPVR_MAGIC"] == vr_shared.MAGIC == struct.unpack("<I", b"TPVR")[0]
    for name in ("VERSION", "HEADER_SIZE", "DATA_OFFSET", "MAX_IMAGE_BYTES", "MAPPING_SIZE", "MAX_DIMENSION",
                 "APP_TIMEOUT_MS", "LAYER_TIMEOUT_MS", "FORMAT_RGBA8_STRAIGHT", "FORMAT_RGBA8_PREMULTIPLIED",
                 "FLAG_VISIBLE", "FLAG_ATTACH_TO_HEADSET", "LAYER_IDLE", "LAYER_ACTIVE", "LAYER_UNSUPPORTED",
                 "LAYER_FAILED", "LAYER_VERSION_MISMATCH", "TILE_OFFSET", "TILE_SIZE", "MAX_TILES", "MAX_CANVAS"):
        assert defines[f"TPVR_{name}"] == getattr(vr_shared, name), name
    assert fields["sequence"] == vr_shared.OFFSET_SEQUENCE
    assert fields["app_heartbeat_ms"] == vr_shared.OFFSET_APP_HEARTBEAT
    assert fields["width"] == vr_shared.OFFSET_FRAME
    assert fields["layer_heartbeat_ms"] == vr_shared.OFFSET_LAYER
    # Frame fields in the order written by the writer ("<6I4f3I" from OFFSET_FRAME)
    order = ["width", "height", "stride", "pixel_format", "flags", "image_serial", "width_meters",
             "distance_meters", "vertical_offset_meters", "horizontal_offset_meters", "data_offset",
             "data_capacity", "app_pid"]
    assert [fields[name] for name in order] == list(range(vr_shared.OFFSET_FRAME, vr_shared.OFFSET_FRAME + 52, 4))
    layer_offsets = [vr_shared.OFFSET_LAYER + offset for offset in (0, 8, 12, 16, 20, 24, 32)]
    assert [fields[name] for name in ("layer_heartbeat_ms", "layer_pid", "layer_state", "layer_graphics_api",
                                      "layer_last_result", "layer_frames_shown", "layer_version")] == layer_offsets
    assert struct.calcsize(vr_shared.LAYER_FORMAT) == 36
    # Version 2: canvas & tile table
    assert vr_shared.VERSION == 2
    assert [fields[name] for name in ("canvas_width", "canvas_height", "tile_count")] == [
        vr_shared.OFFSET_CANVAS, vr_shared.OFFSET_CANVAS + 4, vr_shared.OFFSET_CANVAS + 8]
    assert fields["reserved_app"] == vr_shared.OFFSET_CANVAS + 12 and fields["layer_heartbeat_ms"] == 128
    assert list(tile_fields) == ["atlas_x", "atlas_y", "width", "height", "canvas_x", "canvas_y", "reserved"]
    assert list(tile_fields.values()) == [0, 4, 8, 12, 16, 20, 24]
    assert struct.calcsize(vr_shared.TILE_FORMAT) == vr_shared.TILE_SIZE
    assert list(vr_shared.Tile._fields) == list(tile_fields)[:6]
    assert vr_shared.HEADER_SIZE <= vr_shared.TILE_OFFSET
    assert vr_shared.TILE_OFFSET + vr_shared.MAX_TILES * vr_shared.TILE_SIZE <= vr_shared.DATA_OFFSET


def test_layer_manifest():
    """Implicit layer manifest accepted by the OpenXR loader: required fields, DLL next to it"""
    with open(os.path.join(LAYER_DIR, "TinyPedalXrLayer.json"), encoding="utf-8") as file:
        manifest = json.load(file)
    layer = manifest["api_layer"]
    assert manifest["file_format_version"] == "1.0.0"
    assert layer["name"] == vr_shared.LAYER_NAME
    assert layer["disable_environment"] == vr_shared.DISABLE_ENVIRONMENT  # required for implicit layers
    assert layer["library_path"].replace("\\", "/") == f"./{vr_shared.LAYER_DLL}"  # relative to manifest
    assert re.fullmatch(r"1\.\d+", layer["api_version"]) and layer["implementation_version"]
    with open(os.path.join(LAYER_DIR, "src", "layer.cpp"), encoding="utf-8") as file:
        assert f'"{vr_shared.LAYER_NAME}"' in file.read()


# Shared memory writer


class SeqlockBuffer(bytearray):
    """Shared memory stand-in: checks pixels are written while sequence is odd"""

    def __init__(self):
        super().__init__(vr_shared.MAPPING_SIZE)
        self.pixel_writes = []

    def __setitem__(self, key, value):
        if isinstance(key, slice) and key.start == vr_shared.DATA_OFFSET:
            self.pixel_writes.append(struct.unpack_from("<Q", self, vr_shared.OFFSET_SEQUENCE)[0])
        super().__setitem__(key, value)


def frame_fields(buffer):
    return struct.unpack_from("<6I4f3I", buffer, vr_shared.OFFSET_FRAME)


def canvas_fields(buffer):
    """canvas width, height, tile count"""
    return struct.unpack_from("<3I", buffer, vr_shared.OFFSET_CANVAS)


def tile_table(buffer):
    count = canvas_fields(buffer)[2]
    return [vr_shared.Tile(*struct.unpack_from(vr_shared.TILE_FORMAT, buffer, vr_shared.TILE_OFFSET + index * 32))
            for index in range(count)]


def sequence(buffer):
    return struct.unpack_from("<Q", buffer, vr_shared.OFFSET_SEQUENCE)[0]


def test_writer_header_and_frames():
    buffer = SeqlockBuffer()
    writer = vr_shared.SharedFrameWriter(buffer)
    assert writer.open() and writer.is_open
    assert struct.unpack_from("<4I", buffer, 0) == (vr_shared.MAGIC, vr_shared.VERSION, 256, vr_shared.MAPPING_SIZE)
    assert sequence(buffer) % 2 == 0
    fields = frame_fields(buffer)
    assert fields[10:12] == (vr_shared.DATA_OFFSET, vr_shared.MAX_IMAGE_BYTES) and fields[12] == os.getpid()
    assert fields[4] & vr_shared.FLAG_VISIBLE == 0  # nothing shown before first image

    writer.heartbeat(123456)
    assert struct.unpack_from("<Q", buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == 123456

    placement = vr_shared.Placement(0.6, 1.5, -0.3, 0.1, True)
    writer.set_placement(placement)
    before = sequence(buffer)
    pixels = bytes(range(256)) * 2  # 4 x 2 pixels, rows of 32 bytes (16 bytes padding)
    writer.write_image(pixels, 4, 2, 32)
    assert sequence(buffer) == before + 2 and buffer.pixel_writes == [before + 1]  # odd while copying
    width, height, stride, pixel_format, flags, serial, *rest = frame_fields(buffer)
    assert (width, height, stride, pixel_format) == (4, 2, 32, vr_shared.FORMAT_RGBA8_STRAIGHT)
    assert flags == vr_shared.FLAG_VISIBLE | vr_shared.FLAG_ATTACH_TO_HEADSET
    assert rest[:4] == pytest.approx([0.6, 1.5, -0.3, 0.1])
    assert bytes(buffer[vr_shared.DATA_OFFSET:vr_shared.DATA_OFFSET + 64]) == pixels[:64]
    assert canvas_fields(buffer) == (4, 2, 1)  # no crop: one tile, the whole canvas
    assert tile_table(buffer) == [vr_shared.Tile(0, 0, 4, 2, 0, 0)]

    writer.write_image(pixels, 4, 2, 32)
    assert frame_fields(buffer)[5] == serial + 1  # image serial changes with every image

    seq = sequence(buffer)
    writer.set_placement(placement)  # unchanged: nothing written
    assert sequence(buffer) == seq
    writer.set_placement(placement._replace(attach_to_headset=False, distance_meters=2.0))
    assert sequence(buffer) == seq + 2 and frame_fields(buffer)[5] == serial + 1  # placement only
    assert frame_fields(buffer)[4] == vr_shared.FLAG_VISIBLE and frame_fields(buffer)[7] == 2.0

    writer.hide()
    assert frame_fields(buffer)[4] == 0
    writer.close()
    assert not writer.is_open
    assert struct.unpack_from("<Q", buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == 0  # layer stops at once
    assert sequence(buffer) % 2 == 0


def test_writer_rejects_too_big_image():
    writer = vr_shared.SharedFrameWriter(bytearray(vr_shared.MAPPING_SIZE))
    writer.open()
    with pytest.raises(ValueError):
        writer.write_image(b"", 4097, 1, 4097 * 4)
    with pytest.raises(ValueError):
        writer.write_image(b"", 2048, 1024, 2048 * 4)  # 8 MB
    with pytest.raises(ValueError):
        writer.write_image(b"\0" * 8, 4, 4, 16)  # buffer smaller than size
    assert sequence(writer._buffer) % 2 == 0  # never left odd


@pytest.mark.parametrize("tiles, canvas", [
    ([], (10, 10)),  # no tile
    ([vr_shared.Tile(0, 0, 1, 1, 0, 0)] * (vr_shared.MAX_TILES + 1), (10, 10)),  # too many
    ([vr_shared.Tile(3, 0, 2, 2, 0, 0)], (10, 10)),  # outside atlas (4 x 4)
    ([vr_shared.Tile(0, 0, 4, 4, 7, 0)], (10, 10)),  # outside canvas
    ([vr_shared.Tile(0, 0, 0, 4, 0, 0)], (10, 10)),  # empty
    ([vr_shared.Tile(0, 0, 1, 1, -1, 0)], (10, 10)),  # negative
    ([vr_shared.Tile(0, 0, 1, 1, 0, 0)], (0, 10)),  # no canvas
    ([vr_shared.Tile(0, 0, 1, 1, 0, 0)], (vr_shared.MAX_CANVAS + 1, 10)),  # canvas too big
])
def test_writer_rejects_bad_tiles(tiles, canvas):
    buffer = bytearray(vr_shared.MAPPING_SIZE)
    writer = vr_shared.SharedFrameWriter(buffer)
    writer.open()
    seq = sequence(buffer)
    with pytest.raises(ValueError):
        writer.write_tiles(b"\0" * 64, 4, 4, 16, tiles, canvas)
    assert sequence(buffer) == seq  # nothing written


def test_writer_tile_table():
    """Atlas & tile table written in the seqlock, placement of the whole canvas (tiles placed by the layer)"""
    buffer = SeqlockBuffer()
    writer = vr_shared.SharedFrameWriter(buffer)
    writer.open()
    placement = vr_shared.Placement(1.0, 1.5, -0.2, 0.1, False)
    writer.set_placement(placement)
    tiles = [vr_shared.Tile(0, 0, 3, 2, 0, 0), vr_shared.Tile(4, 0, 2, 1, 90, 40), vr_shared.Tile(4, 2, 1, 1, 99, 49)]
    before = sequence(buffer)
    writer.write_tiles(bytes(range(96)), 6, 4, 24, tiles, (100, 50))
    assert sequence(buffer) == before + 2 and buffer.pixel_writes == [before + 1]
    width, height, stride, _format, flags, _serial, *rest = frame_fields(buffer)
    assert (width, height, stride, flags) == (6, 4, 24, vr_shared.FLAG_VISIBLE)
    assert rest[:4] == pytest.approx(list(placement[:4]))  # canvas placement, not cropped
    assert canvas_fields(buffer) == (100, 50, 3) and tile_table(buffer) == tiles
    # Placement change: table kept
    writer.set_placement(placement._replace(distance_meters=2.0))
    assert tile_table(buffer) == tiles and frame_fields(buffer)[7] == 2.0
    # Fewer tiles: count shrinks (stale entries beyond it ignored by the layer)
    writer.write_tiles(bytes(range(96)), 6, 4, 24, tiles[:1], (100, 50))
    assert canvas_fields(buffer) == (100, 50, 1) and tile_table(buffer) == tiles[:1]
    writer.hide()
    assert frame_fields(buffer)[4] == 0 and canvas_fields(buffer)[2] == 1


def test_tile_placement_matches_canvas():
    """Each tile shown where it is on the canvas placed by the settings (0.01 m per pixel here)"""
    placement = vr_shared.Placement(1.0, 1.5, -0.2, 0.1, True)
    whole = vr_shared.tile_placement(placement, (100, 50), vr_shared.Tile(7, 3, 100, 50, 0, 0))
    assert whole == placement  # atlas position irrelevant
    corner = vr_shared.tile_placement(placement, (100, 50), vr_shared.Tile(0, 0, 10, 10, 90, 40))
    assert corner[:4] == pytest.approx((0.1, 1.5, -0.2 - 0.2, 0.1 + 0.45)) and corner.attach_to_headset
    left = vr_shared.tile_placement(placement, (100, 50), vr_shared.Tile(0, 0, 20, 50, 0, 0))
    assert left[:4] == pytest.approx((0.2, 1.5, -0.2, 0.1 - 0.4))


def test_pack_atlas():
    positions, width, height = vr_shared.pack_atlas([(30, 12), (50, 20), (16, 8)])
    assert positions == [(51, 0), (0, 0), (82, 0)]  # tallest first, 1 pixel apart
    assert (width, height) == (98, 20)
    # Rows wrap at max width, never overlap
    sizes = [(40, 10), (40, 30), (40, 20), (40, 5)]
    positions, width, height = vr_shared.pack_atlas(sizes, max_width=100)
    assert positions == [(0, 31), (0, 0), (41, 0), (41, 31)] and (width, height) == (81, 41)
    boxes = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(positions, sizes)]
    for first in range(len(boxes)):
        for second in range(first + 1, len(boxes)):
            a, b = boxes[first], boxes[second]
            assert a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]  # at least 1 pixel apart
    assert vr_shared.pack_atlas([(101, 1)], max_width=100) is None
    assert vr_shared.pack_atlas(sizes, max_width=100, max_height=40) is None
    assert vr_shared.pack_atlas([]) == ([], 0, 0)


def test_cluster_rects():
    rects = [(0, 0, 100, 50), (110, 0, 50, 50), (1000, 800, 40, 40), (0, 900, 60, 20), (1050, 800, 10, 10)]
    assert vr_shared.cluster_rects(rects, 32, 8) == [[0, 1], [2, 4], [3]]  # near widgets share a tile
    assert vr_shared.cluster_rects(rects, 0, 8) == [[0], [1], [2], [3], [4]]
    two = vr_shared.cluster_rects(rects, 0, 2)
    assert len(two) == 2 and sorted(index for group in two for index in group) == [0, 1, 2, 3, 4]
    # Tile bounding boxes never overlap: overlapping widgets always in one tile
    overlapping = [(0, 0, 50, 50), (40, 40, 50, 50), (200, 0, 10, 10)]
    assert vr_shared.cluster_rects(overlapping, 0, 8) == [[0, 1], [2]]
    for count in range(1, 6):
        groups = vr_shared.cluster_rects(rects, 0, count)
        assert len(groups) <= count
        boxes = []
        for group in groups:
            box = rects[group[0]]
            for index in group[1:]:
                box = vr_shared.union_rect(box, rects[index])
            boxes.append(box)
        for first in range(len(boxes)):
            for second in range(first + 1, len(boxes)):
                assert not vr_shared._near(boxes[first], boxes[second], 0)
    assert vr_shared.cluster_rects([], 32, 8) == []


def test_writer_reopen_continues_sequence():
    """App started again while the game (layer) keeps the shared memory: sequence & serial continue"""
    buffer = bytearray(vr_shared.MAPPING_SIZE)
    writer = vr_shared.SharedFrameWriter(buffer)
    writer.open()
    writer.write_image(b"\1" * 16, 2, 2, 8)
    serial = frame_fields(buffer)[5]
    struct.pack_into("<Q", buffer, vr_shared.OFFSET_SEQUENCE, sequence(buffer) + 1)  # app killed while writing
    seq = sequence(buffer)
    again = vr_shared.SharedFrameWriter(buffer)
    again.open()
    assert sequence(buffer) > seq and sequence(buffer) % 2 == 0
    again.write_image(b"\2" * 16, 2, 2, 8)
    assert frame_fields(buffer)[5] == serial + 1  # layer sees a new image


def test_writer_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(vr_shared, "WINDOWS", False)
    writer = vr_shared.SharedFrameWriter()
    assert not writer.open() and not writer.is_open
    writer.heartbeat()  # no error when closed
    writer.hide()
    assert writer.layer_status() is None
    writer.close()


def write_layer_status(buffer, heartbeat, state=vr_shared.LAYER_ACTIVE, api=1, result=0, frames=9,
                       version=vr_shared.VERSION):
    struct.pack_into(vr_shared.LAYER_FORMAT, buffer, vr_shared.OFFSET_LAYER, heartbeat, 4321, state, api, result, frames,
                     version)


def test_layer_status():
    buffer = bytearray(vr_shared.MAPPING_SIZE)
    writer = vr_shared.SharedFrameWriter(buffer)
    writer.open()
    status = writer.layer_status()
    assert not status.recent(1000) and not status.drawing(1000)
    write_layer_status(buffer, 5000)
    status = writer.layer_status()
    assert status.pid == 4321 and status.graphics_name == "D3D11" and status.frames_shown == 9
    assert status.drawing(5500) and not status.drawing(5000 + vr_shared.LAYER_TIMEOUT_MS + 1)
    write_layer_status(buffer, 5000, state=vr_shared.LAYER_UNSUPPORTED, api=4)
    status = writer.layer_status()
    assert status.recent(5000) and not status.drawing(5000) and status.graphics_name == "OpenGL"
    assert not status.version_mismatch
    # Game started with the layer of another app version: nothing drawn, mismatch reported
    write_layer_status(buffer, 5000, state=vr_shared.LAYER_VERSION_MISMATCH, version=3)
    status = writer.layer_status()
    assert status.version_mismatch and not status.drawing(5000) and status.version == 3


# Registry (winreg mocked)


class FakeWinreg(types.SimpleNamespace):
    """In-memory HKEY_CURRENT_USER"""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_DWORD = 4

    def __init__(self, values=None, key_exists=True):
        super().__init__()
        self.keys = {vr_shared.REGISTRY_KEY: dict(values or {})} if key_exists else {}

    def OpenKey(self, hive, path, reserved=0, access=0):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return path

    def CreateKeyEx(self, hive, path, reserved=0, access=0):
        self.keys.setdefault(path, {})
        return path

    def EnumValue(self, key, index):
        items = list(self.keys[key].items())
        if index >= len(items):
            raise OSError("no more data")
        name, value = items[index]
        return name, value, self.REG_DWORD

    def SetValueEx(self, key, name, reserved, kind, value):
        assert kind == self.REG_DWORD
        self.keys[key][name] = value

    def DeleteValue(self, key, name):
        del self.keys[key][name]

    def CloseKey(self, key):
        pass


OTHER_LAYER = r"C:\Program Files\OpenKneeboard\OpenKneeboard-OpenXR.json"


def test_register_layer(tmp_path):
    manifest = str(tmp_path / vr_shared.LAYER_MANIFEST)
    old = r"C:\Old\TinyPedal\lib\openxr_layer\TinyPedalXrLayer.json"
    reg = FakeWinreg({OTHER_LAYER: 0, old: 0})
    assert vr_shared.register_layer(manifest, reg)
    values = reg.keys[vr_shared.REGISTRY_KEY]
    assert values == {OTHER_LAYER: 0, os.path.abspath(manifest): 0}  # app moved: old entry replaced
    assert vr_shared.register_layer(manifest, reg)  # idempotent
    assert values == {OTHER_LAYER: 0, os.path.abspath(manifest): 0}
    assert vr_shared.registered_layers(reg) == {os.path.abspath(manifest): 0}
    assert vr_shared.unregister_layer(reg) == 1
    assert values == {OTHER_LAYER: 0}  # other layers untouched
    assert vr_shared.unregister_layer(reg) == 0


def test_register_respects_layer_disabled_by_user(tmp_path, caplog):
    """Disabled in an OpenXR layer tool (value 1): never enabled again, also when the app moved"""
    manifest = os.path.abspath(str(tmp_path / vr_shared.LAYER_MANIFEST))
    reg = FakeWinreg({OTHER_LAYER: 0, manifest: 1})
    with caplog.at_level("WARNING", logger="tinypedal.vr_shared"):
        assert vr_shared.register_layer(manifest, reg)
    assert reg.keys[vr_shared.REGISTRY_KEY] == {OTHER_LAYER: 0, manifest: 1}
    assert any("disabled by user" in record.getMessage() for record in caplog.records)
    moved = os.path.abspath(str(tmp_path / "new" / vr_shared.LAYER_MANIFEST))
    assert vr_shared.register_layer(moved, reg)
    assert reg.keys[vr_shared.REGISTRY_KEY] == {OTHER_LAYER: 0, moved: 1}


def test_register_adds_new_entry_before_removing_old(tmp_path):
    """Never a moment without a TinyPedal entry (game starting meanwhile keeps its overlay)"""
    manifest = os.path.abspath(str(tmp_path / vr_shared.LAYER_MANIFEST))
    old = r"C:\Old\openxr_layer\0123\TinyPedalXrLayer.json"
    reg = FakeWinreg({old: 0})
    calls = []
    set_value, delete_value = reg.SetValueEx, reg.DeleteValue
    reg.SetValueEx = lambda *args: calls.append("set") or set_value(*args)
    reg.DeleteValue = lambda *args: calls.append("delete") or delete_value(*args)
    assert vr_shared.register_layer(manifest, reg)
    assert calls == ["set", "delete"] and reg.keys[vr_shared.REGISTRY_KEY] == {manifest: 0}


def test_remove_missing_layers(tmp_path):
    """Entries of missing manifest or DLL make the OpenXR loader fail every OpenXR game: removed"""
    complete = make_layer(tmp_path / "complete")
    no_dll = make_layer(tmp_path / "no_dll")
    os.remove(os.path.join(os.path.dirname(no_dll), vr_shared.LAYER_DLL))
    gone = str(tmp_path / "gone" / vr_shared.LAYER_MANIFEST)
    disabled = str(tmp_path / "disabled" / vr_shared.LAYER_MANIFEST)  # skipped by loader, user choice kept
    reg = FakeWinreg({OTHER_LAYER: 0, complete: 0, no_dll: 0, gone: 0, disabled: 1})
    assert vr_shared.remove_missing_layers(reg) == 2
    assert reg.keys[vr_shared.REGISTRY_KEY] == {OTHER_LAYER: 0, complete: 0, disabled: 1}
    assert vr_shared.remove_missing_layers(reg) == 0
    assert vr_shared.remove_missing_layers(FakeWinreg(key_exists=False)) == 0


def test_loadable_manifest_ascii_path(tmp_path, monkeypatch):
    """OpenXR loader opens manifests with ANSI APIs: non-ASCII path registered as 8.3 path or ASCII copy"""
    ascii_manifest = make_layer(tmp_path / "layer")
    assert vr_shared.loadable_manifest(ascii_manifest) == os.path.abspath(ascii_manifest)
    manifest = make_layer(tmp_path / "Jérôme" / "openxr_layer")
    folder = os.path.dirname(manifest)
    # 8.3 short name of the folder, manifest file name kept (registry entry recognised by its name)
    short = str(tmp_path / "JRME~1" / "OPENXR~1")
    monkeypatch.setattr(vr_shared, "short_path", lambda path: short if path == folder else None)
    assert vr_shared.loadable_manifest(manifest) == os.path.join(short, vr_shared.LAYER_MANIFEST)
    # No 8.3 names (disabled on the volume): copied to the first writable ASCII folder
    monkeypatch.setattr(vr_shared, "short_path", lambda path: path)
    read_only = str(tmp_path / "read_only")
    writable = str(tmp_path / "ProgramData" / "ModernTinyPedals")
    real_mkdtemp = vr_shared.tempfile.mkdtemp

    def mkdtemp(prefix, dir):
        if dir.startswith(read_only):
            raise PermissionError("access denied")
        return real_mkdtemp(prefix=prefix, dir=dir)

    monkeypatch.setattr(vr_shared.tempfile, "mkdtemp", mkdtemp)
    copy = vr_shared.loadable_manifest(manifest, [str(tmp_path / "Jérôme" / "copies"), read_only, writable])
    assert copy is not None and copy.isascii() and copy.startswith(writable)
    assert os.path.basename(copy) == vr_shared.LAYER_MANIFEST
    with open(os.path.join(os.path.dirname(copy), vr_shared.LAYER_DLL), "rb") as file:
        assert file.read() == b"MZ v1"
    assert os.path.isfile(os.path.join(folder, vr_shared.LAYER_DLL))  # source kept
    assert not os.path.exists(tmp_path / "Jérôme" / "copies")  # non-ASCII folder never used
    # Nowhere to copy: None (reported by the app)
    assert vr_shared.loadable_manifest(manifest, [read_only]) is None
    # Default folders: ASCII only, one subfolder per Windows user
    monkeypatch.setenv("PROGRAMDATA", "C:\\ProgramData")
    monkeypatch.setenv("PUBLIC", "C:\\Users\\Públic")
    roots = vr_shared.ascii_layer_roots()
    assert roots and roots[0].startswith("C:\\ProgramData") and all(root.isascii() for root in roots)


def test_remove_old_copies_only_in_copy_folders(tmp_path):
    root = tmp_path / "copies"
    current = make_layer(root / "current")
    make_layer(root / "old")
    other = make_layer(tmp_path / "elsewhere" / "build")
    make_layer(tmp_path / "elsewhere" / "sibling")
    assert vr_shared.remove_old_copies(current, other, roots=[str(root)]) == 1
    assert sorted(entry.name for entry in root.iterdir()) == ["current"]
    assert (tmp_path / "elsewhere" / "sibling").is_dir()  # not a copy folder: untouched


def test_register_creates_missing_key(tmp_path):
    reg = FakeWinreg(key_exists=False)
    assert vr_shared.registered_layers(reg) == {}
    assert vr_shared.unregister_layer(reg) == 0
    manifest = str(tmp_path / vr_shared.LAYER_MANIFEST)
    assert vr_shared.register_layer(manifest, reg)
    assert reg.keys[vr_shared.REGISTRY_KEY] == {os.path.abspath(manifest): 0}


def test_register_failure_reported(tmp_path):
    reg = FakeWinreg()

    def denied(*args):
        raise PermissionError("access denied")

    reg.CreateKeyEx = denied
    assert not vr_shared.register_layer(str(tmp_path / vr_shared.LAYER_MANIFEST), reg)


def test_find_layer_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("TINYPEDAL_XR_LAYER_DIR", str(tmp_path))
    monkeypatch.setattr(os.path, "isfile", lambda path, isfile=os.path.isfile: isfile(path) and str(tmp_path) in path)
    assert vr_shared.find_layer_manifest() is None
    (tmp_path / vr_shared.LAYER_MANIFEST).write_text("{}")
    assert vr_shared.find_layer_manifest() is None  # manifest without DLL never registered
    (tmp_path / vr_shared.LAYER_DLL).write_bytes(b"MZ")
    assert vr_shared.find_layer_manifest() == str(tmp_path / vr_shared.LAYER_MANIFEST)
    # Release build: lib/openxr_layer_bundle (sys._MEIPASS)
    monkeypatch.delenv("TINYPEDAL_XR_LAYER_DIR")
    bundle = tmp_path / "lib"
    (bundle / vr_shared.LAYER_FOLDER).mkdir(parents=True)
    for name in (vr_shared.LAYER_MANIFEST, vr_shared.LAYER_DLL):
        (bundle / vr_shared.LAYER_FOLDER / name).write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert vr_shared.find_layer_manifest() == str(bundle / vr_shared.LAYER_FOLDER / vr_shared.LAYER_MANIFEST)


def make_layer(folder, dll=b"MZ v1"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / vr_shared.LAYER_DLL).write_bytes(dll)
    (folder / vr_shared.LAYER_MANIFEST).write_text('{"api_layer": {"library_path": ".\\\\TinyPedalXrLayer.dll"}}')
    return str(folder / vr_shared.LAYER_MANIFEST)


def test_install_layer_outside_bundle(tmp_path, monkeypatch):
    """Games load a copy outside lib (rewritten by each update), one folder per layer build"""
    bundle = make_layer(tmp_path / "lib" / vr_shared.LAYER_FOLDER)
    root = tmp_path / vr_shared.LAYER_INSTALL_FOLDER
    installed = vr_shared.install_layer(bundle, str(root))
    folder = os.path.dirname(installed)
    assert os.path.dirname(folder) == str(root) and os.path.basename(installed) == vr_shared.LAYER_MANIFEST
    assert (tmp_path / folder / vr_shared.LAYER_DLL).read_bytes() == b"MZ v1"
    assert (tmp_path / installed).read_text() == (tmp_path / bundle).read_text()  # DLL path relative to manifest
    assert [entry.name for entry in root.iterdir()] == [os.path.basename(folder)]  # no temporary folder left
    # Same build (app restarted, or updated with an unchanged layer): copy reused, never written again
    def no_write(*args, **kwargs):
        raise AssertionError("copy written again")

    with monkeypatch.context() as patch:
        patch.setattr(vr_shared.shutil, "copyfile", no_write)
        assert vr_shared.install_layer(bundle, str(root)) == installed
    # New build: new folder, previous one untouched (may still be loaded by a game)
    make_layer(tmp_path / "lib" / vr_shared.LAYER_FOLDER, dll=b"MZ v2")
    newer = vr_shared.install_layer(bundle, str(root))
    assert os.path.dirname(newer) != folder and os.path.isfile(installed)
    # Incomplete copy (DLL removed by hand): written again
    os.remove(os.path.join(os.path.dirname(newer), vr_shared.LAYER_DLL))
    assert vr_shared.install_layer(bundle, str(root)) == newer
    assert os.path.isfile(os.path.join(os.path.dirname(newer), vr_shared.LAYER_DLL))


def test_remove_old_layers_keeps_copy_in_use(tmp_path, monkeypatch):
    root = tmp_path / vr_shared.LAYER_INSTALL_FOLDER
    current = root / "current"
    old = root / "old"
    in_use = root / "in_use"
    for folder in (current, old, in_use):
        make_layer(folder)
    (root / ".tmp-crashed").mkdir()  # copy interrupted
    (root / "notes.txt").write_text("not a layer folder")
    locked = str(in_use / vr_shared.LAYER_DLL)
    real_remove = os.remove

    def remove(path):
        if os.path.abspath(path) == locked:
            raise PermissionError("loaded by a running game")
        real_remove(path)

    monkeypatch.setattr(os, "remove", remove)
    assert vr_shared.remove_old_layers(str(root), str(current)) == 2
    assert sorted(entry.name for entry in root.iterdir()) == ["current", "in_use", "notes.txt"]
    assert (in_use / vr_shared.LAYER_MANIFEST).is_file()  # manifest kept with its DLL
    assert vr_shared.remove_old_layers(str(tmp_path / "missing"), str(current)) == 0


def test_prepare_layer(tmp_path, monkeypatch):
    bundle = make_layer(tmp_path / "lib" / vr_shared.LAYER_FOLDER)
    # From source: build folder registered as is
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert vr_shared.layer_install_root() is None
    assert vr_shared.prepare_layer(bundle) == bundle
    # Release: copy next to executable, older copies removed
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "tinypedal.exe"))
    root = tmp_path / vr_shared.LAYER_INSTALL_FOLDER
    assert vr_shared.layer_install_root() == str(root)
    make_layer(root / "previous_build", dll=b"MZ v0")
    installed = vr_shared.prepare_layer(bundle)
    assert installed.startswith(str(root)) and installed != bundle
    # Older copy removed only once the new one is registered (remove_old_copies)
    assert (root / "previous_build" / vr_shared.LAYER_DLL).is_file()
    assert vr_shared.remove_old_copies(installed) == 1
    assert [entry.name for entry in root.iterdir()] == [os.path.basename(os.path.dirname(installed))]
    # Copy impossible (folder read only...): bundled layer registered, still works until next update
    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(vr_shared.tempfile, "mkdtemp", denied)
    assert vr_shared.prepare_layer(bundle, str(tmp_path / "other")) == bundle


def test_installer_never_closes_openxr_games():
    """Updates replace no file a game loads: Restart Manager limited to executables, copies removed on
    uninstall (registry entries too, by install folder)"""
    with open(os.path.join(ROOT, "installer", "tinypedal.iss"), encoding="utf-8") as file:
        script = file.read()
    assert re.search(r"^CloseApplicationsFilter=\*\.exe$", script, re.MULTILINE)
    assert f'Type: filesandordirs; Name: "{{app}}\\{vr_shared.LAYER_INSTALL_FOLDER}"' in script
    assert re.search(r"^\[UninstallDelete\]$", script, re.MULTILINE)
    assert "RegDeleteValue(HKCU, OpenXRLayersKey" in script
    # ASCII copies (non-ASCII app folder) removed too; entries of deleted files (8.3 paths) once files are gone
    assert f'Name: "{{commonappdata}}\\ModernTinyPedals\\{vr_shared.LAYER_INSTALL_FOLDER}"' in script
    assert "usPostUninstall" in script and "not FileExists(Names[I])" in script
    assert vr_shared.LAYER_INSTALL_FOLDER != "lib"


def test_is_layer_entry():
    assert vr_shared.is_layer_entry(r"C:\A\lib\openxr_layer\TinyPedalXrLayer.json")
    assert vr_shared.is_layer_entry(r"c:\a\tinypedalxrlayer.JSON")
    assert not vr_shared.is_layer_entry(OTHER_LAYER)


# VROverlay with OpenXR layer & SteamVR mocked


class FakeOverlayWindow(QWidget):
    widget_name = "fake"


class FakeIVROverlay:
    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        def call(*args):
            self.log.append(name)
            return 42 if name == "createOverlay" else None

        return call


class HmdMatrix34_t:
    def __init__(self):
        self.m = [[0.0] * 4 for _ in range(3)]


def fake_openvr(log):
    module = types.ModuleType("openvr")
    module.VRApplication_Overlay = 2
    module.TrackingUniverseSeated = 0
    module.k_unTrackedDeviceIndex_Hmd = 0
    module.HmdMatrix34_t = HmdMatrix34_t
    module.init = lambda app_type: log.append("init")
    module.shutdown = lambda: log.append("shutdown")
    module.IVROverlay = lambda: FakeIVROverlay(log)
    return module


STEAMVR_CHECK = vr_overlay.SteamVRCheck


class SyncSteamVRCheck:
    """SteamVR process check done at once (background thread in app)"""

    def __init__(self):
        self.running = vr_overlay.steamvr_running()

    def done(self):
        return True


class Env:
    """OpenXR layer available (Windows mocked), shared memory in a bytearray, fake clock"""

    def __init__(self, monkeypatch, tmp_path):
        self.buffer = bytearray(vr_shared.MAPPING_SIZE)
        self.registered = []
        self.unregistered = []
        self.now = 1_000_000
        self.steamvr = False
        self.errors = []
        manifest = str(tmp_path / vr_shared.LAYER_MANIFEST)
        monkeypatch.setattr(vr_shared, "WINDOWS", True)
        monkeypatch.setattr(vr_shared, "find_layer_manifest", lambda: manifest)
        monkeypatch.setattr(vr_shared, "register_layer", lambda path: self.registered.append(path) or True)
        monkeypatch.setattr(vr_shared, "unregister_layer", lambda: self.unregistered.append(1) or 0)
        self.cleaned = []
        monkeypatch.setattr(vr_shared, "remove_missing_layers", lambda: self.cleaned.append(1) or 0)
        monkeypatch.setattr(vr_shared, "tick_ms", lambda: self.now)
        monkeypatch.setattr(vr_overlay, "steamvr_running", lambda: self.steamvr)
        monkeypatch.setattr(vr_overlay, "SteamVRCheck", SyncSteamVRCheck)

    def frame(self):
        return frame_fields(self.buffer)


@pytest.fixture
def env(ui_env, monkeypatch, tmp_path):
    original = vr_shared.SharedFrameWriter
    environment = Env(monkeypatch, tmp_path)
    monkeypatch.setattr(vr_shared, "SharedFrameWriter", lambda: original(environment.buffer))
    setting = cfg.user.config["vr_overlay"]
    setting.update(enable_vr_overlay=True, enable_vr_mirror_window=False, update_interval=50)
    app_signal.error.connect(environment.errors.append)
    yield environment
    app_signal.error.disconnect(environment.errors.append)
    QCoreApplication.processEvents()


def make_widget(monkeypatch):
    widget = FakeOverlayWindow()
    widget.setGeometry(10, 10, 60, 30)
    widget.setStyleSheet("background: red;")
    widget.show()
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: [widget] if widget.isVisible() else []))
    return widget


def test_release_registers_layer_copy_outside_lib(env, tmp_path, monkeypatch):
    """Release: layer registered from its copy next to executable, never from lib (deleted by updates)"""
    bundle = make_layer(tmp_path / "lib" / vr_shared.LAYER_FOLDER)
    monkeypatch.setattr(vr_shared, "find_layer_manifest", lambda: bundle)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "tinypedal.exe"))
    control = VROverlay()
    try:
        control.enable()
        assert control.openxr_active and len(env.registered) == 1
        registered = env.registered[0]
        assert registered.startswith(str(tmp_path / "app" / vr_shared.LAYER_INSTALL_FOLDER))
        assert os.path.isfile(os.path.join(os.path.dirname(registered), vr_shared.LAYER_DLL))
    finally:
        control.disable()


def test_openxr_layer_receives_frames(env, monkeypatch):
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        assert env.registered and control.openxr_active and control.running and control._timer.isActive()
        assert not env.errors  # openvr missing is not an error: OpenXR layer shows the overlay
        assert struct.unpack_from("<I", env.buffer, 0)[0] == vr_shared.MAGIC
        env.now += 50
        control.update_overlay()
        assert env.frame()[:2] == (0, 0)  # no OpenXR game (layer silent): nothing composed nor written
        write_layer_status(env.buffer, env.now)  # OpenXR game started
        env.now += 10
        control.update_overlay()  # written at once
        width, height, stride, _format, flags, _serial, width_m, distance, vertical, horizontal = env.frame()[:10]
        assert (width, height) == (60, 30) and stride == width * 4 and flags & vr_shared.FLAG_VISIBLE  # widget only
        canvas = vr_overlay.compose_widgets([widget])  # window frame size, transparent around widget
        rect = vr_overlay.content_rect(canvas)
        assert (rect.width(), rect.height()) == (60, 30) and canvas.width() > 60
        placement = vr_shared.Placement(0.8, 1.0, -0.2, 0.0, False)
        assert (width_m, distance, vertical, horizontal) == pytest.approx(placement[:4])  # whole canvas
        assert canvas_fields(env.buffer) == (canvas.width(), canvas.height(), 1)
        tiles = tile_table(env.buffer)
        assert tiles == [vr_shared.Tile(0, 0, 60, 30, rect.x(), rect.y())]
        # Shown by the layer where the widget is on the canvas, same scale as before
        expected = vr_shared.tile_placement(placement, (canvas.width(), canvas.height()), tiles[0])
        assert expected.width_meters == pytest.approx(0.8 * 60 / canvas.width())
        pixel = env.buffer[vr_shared.DATA_OFFSET + (15 * width + 30) * 4:][:4]  # inside the red widget
        assert pixel[0] == 255 and pixel[3] == 255
        assert struct.unpack_from("<Q", env.buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == env.now
        seq = sequence(env.buffer)
        env.now += 50
        control.update_overlay()  # unchanged image: heartbeat only
        assert sequence(env.buffer) == seq
        assert struct.unpack_from("<Q", env.buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == env.now
        widget.hide()
        control.update_overlay()
        assert env.frame()[4] & vr_shared.FLAG_VISIBLE == 0  # all overlays hidden
    finally:
        widget.close()
        control.disable()
    assert not control.running
    assert struct.unpack_from("<Q", env.buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == 0  # app gone for layer


def _no_openvr_import():
    import builtins

    real_import = builtins.__import__

    def importer(name, *args, **kwargs):
        if name == "openvr":
            raise ImportError("No module named 'openvr'")
        return real_import(name, *args, **kwargs)

    return importer


def test_option_off_unregisters_layer(env):
    cfg.user.config["vr_overlay"]["enable_vr_overlay"] = False
    control = VROverlay()
    control.enable()
    assert env.unregistered and not env.registered and not control.running


def test_steamvr_started_only_once_running(env, monkeypatch):
    """SteamVR never launched by the app (Meta users): overlay created once SteamVR runs"""
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        assert "init" not in log and control.running and not env.errors
        env.now += 1000
        control.update_overlay()
        assert "init" not in log  # not running, next check later
        env.steamvr = True
        control.update_overlay()
        assert "init" not in log  # checked every STEAMVR_RETRY_MS only
        env.now += vr_overlay.STEAMVR_RETRY_MS
        control.update_overlay()
        assert log[:3] == ["init", "createOverlay", "setOverlayWidthInMeters"]
        assert "setOverlayRaw" in log  # image sent at once
    finally:
        widget.close()
        control.disable()
    assert log[-2:] == ["destroyOverlay", "shutdown"]


def test_steamvr_overlay_hidden_while_openxr_layer_draws(env, monkeypatch):
    """OpenXR game on SteamVR runtime: layer draws the overlay, no second image from SteamVR overlay"""
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    env.steamvr = True
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        control.update_overlay()
        assert control._visible
        log.clear()
        write_layer_status(env.buffer, env.now, frames=9)  # OpenXR game frames drawn by layer
        control.update_overlay()
        write_layer_status(env.buffer, env.now, frames=12)
        env.now += 50
        control.update_overlay()
        assert log == ["hideOverlay"] and not control._visible
        widget.setStyleSheet("background: blue;")
        env.now += 50
        write_layer_status(env.buffer, env.now, frames=15)
        control.update_overlay()
        assert "showOverlay" not in log and "setOverlayRaw" not in log  # hidden: image not even sent
        env.now += vr_shared.LAYER_TIMEOUT_MS + 1  # game closed: layer silent
        log.clear()
        control.update_overlay()
        assert log == ["setOverlayRaw", "showOverlay"] and control._visible  # newest image sent, then shown
        # OpenGL game: layer cannot draw, SteamVR overlay kept
        write_layer_status(env.buffer, env.now, state=vr_shared.LAYER_UNSUPPORTED, api=4)
        log.clear()
        control.update_overlay()
        assert "hideOverlay" not in log and control._visible
    finally:
        widget.close()
        control.disable()


def test_steamvr_overlay_kept_while_openxr_layer_draws_nothing(env, monkeypatch):
    """Layer ACTIVE but no quad submitted (no layer slot left, image lost or refused): SteamVR overlay kept"""
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    env.steamvr = True
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        control.update_overlay()
        assert control._visible
        log.clear()
        for _ in range(5):  # heartbeat written every game frame, frames_shown never grows
            write_layer_status(env.buffer, env.now, frames=9)
            env.now += 50
            control.update_overlay()
        assert "hideOverlay" not in log and control._visible
        write_layer_status(env.buffer, env.now, frames=10)  # layer starts drawing
        env.now += 50
        control.update_overlay()
        assert log == ["hideOverlay"] and not control._visible
        log.clear()
        for _ in range(vr_shared.LAYER_TIMEOUT_MS // 100 + 2):  # stops drawing, game still running
            write_layer_status(env.buffer, env.now, frames=10)
            env.now += 100
            control.update_overlay()
        assert log == ["setOverlayRaw", "showOverlay"] and control._visible
    finally:
        widget.close()
        control.disable()


def test_steamvr_closed_then_restarted(env, monkeypatch):
    log = []
    module = fake_openvr(log)
    monkeypatch.setitem(sys.modules, "openvr", module)
    env.steamvr = True
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        control.update_overlay()

        def closed(*args):
            raise RuntimeError("SteamVR closed")

        control._overlay.setOverlayRaw = closed
        widget.setStyleSheet("background: blue;")
        control.update_overlay()
        assert control._overlay is None and control.running and control._timer.isActive()  # OpenXR kept
        assert not env.errors  # closing SteamVR is not an error
        log.clear()
        env.now += vr_overlay.STEAMVR_RETRY_MS
        control.update_overlay()
        assert "init" in log and control._overlay is not None
    finally:
        widget.close()
        control.disable()


def test_steamvr_process_checked_in_background(env, monkeypatch):
    """Process scan (tens of ms) never on GUI thread, none while the OpenXR layer draws the overlay"""
    import threading

    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    monkeypatch.setattr(vr_overlay, "SteamVRCheck", STEAMVR_CHECK)  # background thread, as in app
    threads = []
    release = threading.Event()

    def scan():
        threads.append(threading.current_thread())
        assert release.wait(5)
        return env.steamvr

    monkeypatch.setattr(vr_overlay, "steamvr_running", scan)
    env.steamvr = True
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()  # check started, GUI thread not blocked
        assert threads and threads[0] is not threading.main_thread()
        control.update_overlay()
        assert "init" not in log  # result not known yet
        release.set()
        control._steamvr_check._thread.join(5)
        control.update_overlay()
        assert "init" in log and control._overlay is not None
        # SteamVR closed while the OpenXR layer draws: no process scan until it stops drawing
        control._overlay.setOverlayRaw = None  # raises TypeError: SteamVR overlay stopped
        widget.setStyleSheet("background: blue;")
        write_layer_status(env.buffer, env.now, frames=9)
        control.update_overlay()
        write_layer_status(env.buffer, env.now, frames=12)
        env.now += 50
        control.update_overlay()
        assert control._overlay is None and control._xr_drawing
        threads.clear()
        for _ in range(3):
            env.now += vr_overlay.STEAMVR_RETRY_MS
            write_layer_status(env.buffer, env.now, frames=12 + env.now)
            control.update_overlay()
        assert not threads and control._steamvr_check is None
        env.now += vr_shared.LAYER_TIMEOUT_MS + 1  # game closed: layer silent, SteamVR checked again
        control.update_overlay()
        assert threads and (control._steamvr_check is not None or control._overlay is not None)
    finally:
        release.set()
        widget.close()
        control.disable()


def test_openxr_image_rate_limited_and_cropped(env, monkeypatch):
    """Layer copies the image in the game frame: written at most every OPENXR_MIN_INTERVAL_MS (last image
    written later even without new paint), transparent margins cropped, same place in VR"""
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    control = VROverlay()
    widget = make_widget(monkeypatch)
    other = FakeOverlayWindow()
    other.setGeometry(310, 210, 40, 20)
    other.setStyleSheet("background: green;")
    other.show()
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: [widget, other]))
    try:
        control.enable()
        write_layer_status(env.buffer, env.now)  # OpenXR game running
        control.update_overlay()
        serial = env.frame()[5]
        width, height = env.frame()[:2]
        assert (width, height) == (101, 30)  # one tile per widget (far apart), 1 pixel apart in the atlas
        tiles = tile_table(env.buffer)
        assert [(tile.width, tile.height) for tile in tiles] == [(60, 30), (40, 20)]
        assert tiles[1].atlas_x == 61 and tiles[1].canvas_x - tiles[0].canvas_x == 300  # desktop layout kept
        assert tiles[1].canvas_y - tiles[0].canvas_y == 200
        widget.setStyleSheet("background: blue;")
        env.now += 20
        control.update_overlay()
        assert env.frame()[5] == serial  # too soon: kept for later
        env.now += vr_overlay.OPENXR_MIN_INTERVAL_MS
        control.update_overlay()  # nothing painted since: kept image written now
        assert env.frame()[5] == serial + 1
        pixel = env.buffer[vr_shared.DATA_OFFSET + (15 * width + 30) * 4:][:4]
        assert pixel[2] == 255 and pixel[3] == 255  # blue
        other.hide()
        env.now += 20
        control.update_overlay()
        assert env.frame()[:2] == (101, 30)  # rate limited
        env.now += vr_overlay.OPENXR_MIN_INTERVAL_MS
        control.update_overlay()
        assert env.frame()[:2] == (60, 30)  # widget only
        widget.hide()
        env.now += 1
        control.update_overlay()
        assert env.frame()[4] & vr_shared.FLAG_VISIBLE == 0  # all hidden: at once
    finally:
        widget.close()
        other.close()
        control.disable()


def test_cropped_placement_keeps_position_in_vr():
    placement = vr_shared.Placement(1.0, 1.5, -0.2, 0.1, False)
    assert vr_shared.cropped_placement(placement, None, 50, 25) == placement
    assert vr_shared.cropped_placement(placement, (0, 0, 100, 50), 100, 50) == placement
    top_left = vr_shared.cropped_placement(placement, (0, 0, 100, 50), 50, 25)  # meters: 0.01 per pixel
    assert top_left[:4] == pytest.approx((0.5, 1.5, -0.2 + 0.125, 0.1 - 0.25))
    bottom_right = vr_shared.cropped_placement(placement, (90, 40, 100, 50), 10, 10)
    assert bottom_right[:4] == pytest.approx((0.1, 1.5, -0.2 - 0.2, 0.1 + 0.45))
    assert bottom_right.attach_to_headset is False


def test_content_rect():
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor

    image = QImage(301, 97, QImage.Format.Format_RGBA8888)
    image.fill(0)
    assert vr_overlay.content_rect(image).isEmpty()
    image.setPixelColor(7, 5, QColor(0, 0, 0, 1))
    assert vr_overlay.content_rect(image) == QRect(7, 5, 1, 1)
    image.setPixelColor(290, 96, QColor(255, 0, 0, 255))
    assert vr_overlay.content_rect(image) == QRect(7, 5, 284, 92)
    image.fill(QColor(1, 2, 3, 200))
    assert vr_overlay.content_rect(image) == QRect(0, 0, 301, 97)


def test_enable_never_raises(env, monkeypatch):
    def broken():
        raise RuntimeError("registry broken")

    monkeypatch.setattr(vr_shared, "find_layer_manifest", broken)
    control = VROverlay()
    control.enable()  # must not raise (loader goes on)
    assert env.errors and "registry broken" in env.errors[-1]
    control.disable()


def test_no_layer_no_openvr_reports_error(env, monkeypatch):
    monkeypatch.setattr(vr_shared, "find_layer_manifest", lambda: None)
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    control = VROverlay()
    control.enable()
    assert not control.running and env.errors and "openvr" in env.errors[-1]


def test_steamvr_running(monkeypatch):
    class Process:
        def __init__(self, name):
            self.info = {"name": name}

    psutil = types.ModuleType("psutil")
    psutil.process_iter = lambda attrs: [Process("explorer.exe"), Process("vrserver.exe")]
    monkeypatch.setitem(sys.modules, "psutil", psutil)
    assert vr_overlay.steamvr_running()
    psutil.process_iter = lambda attrs: [Process("explorer.exe"), Process(None)]
    assert not vr_overlay.steamvr_running()

    def failing(attrs):
        raise OSError("access denied")

    psutil.process_iter = failing
    assert not vr_overlay.steamvr_running()


def make_colored(x, y, width, height, color):
    widget = FakeOverlayWindow()
    widget.setGeometry(x, y, width, height)
    widget.setStyleSheet(f"background: {color};")
    widget.show()
    return widget


def atlas_pixel(frame, x, y):
    return frame.atlas.pixelColor(x, y).getRgb()


def test_compose_tiles_one_tile_per_widget_group():
    widgets = [make_colored(10, 10, 60, 30, "red"), make_colored(1500, 900, 40, 20, "blue"),
               make_colored(100, 10, 20, 20, "green")]  # 30 px from the red one: same tile
    try:
        frame = vr_overlay.compose_tiles(widgets)
        assert frame is not None and len(frame.tiles) == 2
        canvas = vr_overlay.compose_widgets(widgets)  # same canvas as the SteamVR image (before its scaling)
        bounds = widgets[0].frameGeometry().united(widgets[1].frameGeometry())
        assert frame.canvas == (bounds.width(), bounds.height())
        assert canvas is not None
        red_green, blue = sorted(frame.tiles, key=lambda tile: tile.canvas_x)
        assert (red_green.width, red_green.height) == (110, 30)  # cropped to visible pixels of both widgets
        assert (blue.width, blue.height) == (40, 20)
        assert blue.canvas_x - red_green.canvas_x == 1490 and blue.canvas_y - red_green.canvas_y == 890
        assert frame.atlas.width() * frame.atlas.height() < 200 * 40  # not the 1530 x 910 canvas
        # Tile pixels: widget colors at their place, transparent gap between red & green
        assert atlas_pixel(frame, red_green.atlas_x + 5, red_green.atlas_y + 5) == (255, 0, 0, 255)
        assert atlas_pixel(frame, red_green.atlas_x + 100, red_green.atlas_y + 5)[1] > 100  # green
        assert atlas_pixel(frame, red_green.atlas_x + 75, red_green.atlas_y + 5)[3] == 0
        assert atlas_pixel(frame, blue.atlas_x + 5, blue.atlas_y + 5) == (0, 0, 255, 255)
        for tile in frame.tiles:  # 1 transparent pixel around each tile in the atlas
            if tile.atlas_x + tile.width < frame.atlas.width():
                assert atlas_pixel(frame, tile.atlas_x + tile.width, tile.atlas_y)[3] == 0
        assert vr_overlay.compose_tiles(widgets).checksum == frame.checksum  # unchanged
        widgets[1].setStyleSheet("background: yellow;")
        assert vr_overlay.compose_tiles(widgets).checksum != frame.checksum
        assert len(vr_overlay.compose_tiles(widgets, max_tiles=1).tiles) == 1
    finally:
        for widget in widgets:
            widget.close()
    assert vr_overlay.compose_tiles(widgets) is None  # nothing visible


def test_compose_tiles_bounded_and_scaled():
    widgets = [make_colored(index % 4 * 300, index // 4 * 200, 50, 40, "red") for index in range(12)]
    big = make_colored(0, 700, 3000, 600, "blue")  # 1.8 M pixels: scaled down to fit shared memory
    try:
        frame = vr_overlay.compose_tiles(widgets)
        assert frame is not None and len(frame.tiles) == vr_overlay.OPENXR_MAX_TILES  # 12 widgets, 8 tiles
        frame = vr_overlay.compose_tiles([*widgets, big])
        atlas = frame.atlas
        assert atlas.bytesPerLine() * atlas.height() <= vr_shared.MAX_IMAGE_BYTES
        assert max(atlas.width(), atlas.height()) <= vr_shared.MAX_DIMENSION
        bounds = big.frameGeometry()
        for widget in widgets:
            bounds = bounds.united(widget.frameGeometry())
        scale = frame.canvas[0] / bounds.width()
        assert scale < 0.8 and frame.canvas[1] == pytest.approx(bounds.height() * scale, abs=1)
        for tile in frame.tiles:  # layer limits: within atlas & canvas
            assert tile.atlas_x + tile.width <= atlas.width() and tile.atlas_y + tile.height <= atlas.height()
            assert tile.canvas_x + tile.width <= frame.canvas[0] and tile.canvas_y + tile.height <= frame.canvas[1]
        writer = vr_shared.SharedFrameWriter(bytearray(vr_shared.MAPPING_SIZE))
        writer.open()
        view = memoryview(atlas.constBits())[:atlas.sizeInBytes()]
        writer.write_tiles(view, atlas.width(), atlas.height(), atlas.bytesPerLine(), frame.tiles, frame.canvas)
    finally:
        for widget in [*widgets, big]:
            widget.close()


def test_layer_version_mismatch_reported(env, monkeypatch, caplog):
    """Game started with the layer of an older app: nothing drawn by it, user told to restart the game,
    SteamVR overlay kept"""
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        control.update_overlay()
        write_layer_status(env.buffer, env.now, state=vr_shared.LAYER_VERSION_MISMATCH, frames=0, version=3)
        with caplog.at_level("WARNING", logger="tinypedal.vr_overlay"):
            control.update_overlay()
        assert any("restart the game" in record.getMessage() for record in caplog.records)
        assert not control._xr_drawing
        assert len(env.errors) == 1 and "restart the VR game" in env.errors[0]  # user told, once
        env.now += 50
        write_layer_status(env.buffer, env.now, state=vr_shared.LAYER_UNSUPPORTED, frames=0, version=3)
        control.update_overlay()
        env.now += 50
        write_layer_status(env.buffer, env.now, state=vr_shared.LAYER_VERSION_MISMATCH, frames=0, version=3)
        control.update_overlay()
        assert len(env.errors) == 1  # same game process: not again
    finally:
        widget.close()
        control.disable()


def _count_calls(monkeypatch, name):
    calls = []
    original = getattr(vr_overlay, name)
    monkeypatch.setattr(vr_overlay, name, lambda *args, **kwargs: calls.append(1) or original(*args, **kwargs))
    return calls


def test_openxr_tiles_only_while_layer_runs(env, monkeypatch):
    """No OpenXR game: tiles neither composed nor written (app heartbeat kept); written at once when a layer
    appears, hidden when it goes (next game never shows an outdated image)"""
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    composed = _count_calls(monkeypatch, "compose_tiles")
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        for _ in range(3):
            widget.setStyleSheet(f"background: rgb({len(composed) * 10}, 0, 0);")
            env.now += 100
            control.update_overlay()
        assert not composed and env.frame()[:2] == (0, 0)
        assert struct.unpack_from("<Q", env.buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == env.now
        # Game starts: written on the next heartbeat tick, rate limit ignored
        write_layer_status(env.buffer, env.now)
        control._heartbeat_timer.timeout.emit()
        assert len(composed) == 1 and env.frame()[:2] == (60, 30) and env.frame()[4] & vr_shared.FLAG_VISIBLE
        # Game closed: hidden, nothing composed any more
        env.now += vr_shared.LAYER_TIMEOUT_MS + 1
        control.update_overlay()
        assert env.frame()[4] & vr_shared.FLAG_VISIBLE == 0
        widget.setStyleSheet("background: blue;")
        env.now += 100
        control.update_overlay()
        assert len(composed) == 1
        # Next game: newest image written at once
        write_layer_status(env.buffer, env.now)
        control.update_overlay()
        assert len(composed) == 2 and env.frame()[4] & vr_shared.FLAG_VISIBLE
        width = env.frame()[0]
        pixel = env.buffer[vr_shared.DATA_OFFSET + (15 * width + 30) * 4:][:4]
        assert pixel[2] == 255 and pixel[0] == 0  # blue
    finally:
        widget.close()
        control.disable()


def test_heartbeat_independent_of_update_interval(env, monkeypatch):
    """Update interval up to 60 s, layer drops the overlay 2 s after the last heartbeat: heartbeat timer"""
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    cfg.user.config["vr_overlay"]["update_interval"] = 60000
    control = VROverlay()
    try:
        control.enable()
        assert control._timer.interval() == 60000
        assert control._heartbeat_timer.isActive()
        assert control._heartbeat_timer.interval() < vr_shared.APP_TIMEOUT_MS / 2
        env.now += 1500
        control._heartbeat_timer.timeout.emit()
        assert struct.unpack_from("<Q", env.buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == env.now
    finally:
        control.disable()
    assert not control._heartbeat_timer.isActive()
    assert struct.unpack_from("<Q", env.buffer, vr_shared.OFFSET_APP_HEARTBEAT)[0] == 0


def test_steamvr_image_not_composed_while_hidden_for_openxr(env, monkeypatch):
    """SteamVR overlay hidden (OpenXR layer draws), no mirror: whole canvas neither composed nor sent"""
    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    env.steamvr = True
    composed = _count_calls(monkeypatch, "compose_widgets")
    control = VROverlay()
    widget = make_widget(monkeypatch)
    try:
        control.enable()
        control.update_overlay()
        write_layer_status(env.buffer, env.now, frames=9)
        control.update_overlay()
        write_layer_status(env.buffer, env.now, frames=12)
        env.now += 50
        control.update_overlay()
        assert not control._visible
        log.clear()
        composed.clear()
        for frames in (15, 18, 21):
            widget.setStyleSheet(f"background: rgb(0, 0, {frames * 10});")
            env.now += 100
            write_layer_status(env.buffer, env.now, frames=frames)
            control.update_overlay()
        assert not composed and "setOverlayRaw" not in log
        assert control._checksum is None  # sent again once shown
    finally:
        widget.close()
        control.disable()


def test_layer_cleanup_and_ascii_path_errors(env, monkeypatch, tmp_path):
    """Registry entries of missing files removed even without layer; no ASCII path: reported once"""
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    monkeypatch.setattr(vr_shared, "find_layer_manifest", lambda: None)
    control = VROverlay()
    control.enable()
    assert env.cleaned and not env.registered and not control.openxr_active
    control.disable()
    manifest = make_layer(tmp_path / "Jérôme")
    monkeypatch.setattr(vr_shared, "find_layer_manifest", lambda: manifest)
    monkeypatch.setattr(vr_shared, "loadable_manifest", lambda path: None)
    env.errors.clear()
    for _ in range(2):  # reload
        control.enable()
        control.disable()
    assert not env.registered and not control.openxr_active
    assert len([error for error in env.errors if "ASCII" in error]) == 1


def test_old_copies_removed_after_registration(env, monkeypatch, tmp_path):
    """Old layer copy (maybe loaded by games) removed only once the new one is registered"""
    bundle = make_layer(tmp_path / "lib" / vr_shared.LAYER_FOLDER)
    monkeypatch.setattr(vr_shared, "find_layer_manifest", lambda: bundle)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "tinypedal.exe"))
    old = tmp_path / "app" / vr_shared.LAYER_INSTALL_FOLDER / "old_build"
    make_layer(old, dll=b"MZ v0")
    monkeypatch.setattr(vr_shared, "register_layer", lambda path: False)  # registry denied
    control = VROverlay()
    control.enable()
    control.disable()
    assert (old / vr_shared.LAYER_DLL).is_file()  # still registered: kept
    monkeypatch.setattr(vr_shared, "register_layer", lambda path: env.registered.append(path) or True)
    control.enable()
    control.disable()
    assert env.registered and not old.exists()


class FakeMapping(bytearray):
    def close(self):
        pass


def test_shared_memory_created_for_non_elevated_games(monkeypatch):
    """Mapping created with an explicit DACL (current user, medium integrity) then mapped by name; default
    security if impossible, with a warning when elevated (non elevated games could not open it)"""
    import mmap

    calls = []
    monkeypatch.setattr(vr_shared, "WINDOWS", True)
    monkeypatch.setattr(mmap, "mmap", lambda fileno, size, tagname=None: calls.append(("mmap", tagname))
                        or FakeMapping(size))
    monkeypatch.setattr(vr_shared, "create_mapping", lambda name, size: calls.append(("create", name, size)) or 77)
    monkeypatch.setattr(vr_shared, "close_handle", lambda handle: calls.append(("close", handle)))
    monkeypatch.setattr(vr_shared, "is_elevated", lambda: True)
    monkeypatch.setattr(vr_shared, "tick_ms", lambda: 1000)
    writer = vr_shared.SharedFrameWriter()
    assert writer.open() and writer.warning is None
    assert calls == [("create", vr_shared.MAPPING_NAME, vr_shared.MAPPING_SIZE), ("mmap", vr_shared.MAPPING_NAME),
                     ("close", 77)]  # handle closed once mapped (mapping kept by the mmap)
    writer.close()
    assert "(ML;;NW;;;ME)" in vr_shared.MAPPING_SDDL and "{user}" in vr_shared.MAPPING_SDDL

    def failing(name, size):
        raise OSError("ConvertStringSecurityDescriptorToSecurityDescriptorW failed")

    monkeypatch.setattr(vr_shared, "create_mapping", failing)
    calls.clear()
    writer = vr_shared.SharedFrameWriter()
    assert writer.open() and calls == [("mmap", vr_shared.MAPPING_NAME)]  # default security fallback
    assert writer.warning and "administrator" in writer.warning
    writer.close()
    monkeypatch.setattr(vr_shared, "is_elevated", lambda: False)
    writer = vr_shared.SharedFrameWriter()
    assert writer.open() and writer.warning is None  # not elevated: default security works
    writer.close()


def test_elevated_warning_reported(env, monkeypatch):
    original = type(vr_shared.SharedFrameWriter())  # class (fixture replaced it by a factory)

    def writer():
        instance = original(env.buffer)
        instance.warning = "VR overlay: app runs as administrator"
        return instance

    monkeypatch.setattr(vr_shared, "SharedFrameWriter", writer)
    monkeypatch.delitem(sys.modules, "openvr", raising=False)
    monkeypatch.setattr("builtins.__import__", _no_openvr_import())
    control = VROverlay()
    for _ in range(2):
        control.enable()
        control.disable()
    assert env.errors == ["VR overlay: app runs as administrator"]


def test_fit_image():
    image = QImage(5000, 100, QImage.Format.Format_RGBA8888)
    fitted = fit_image(image, 4096)
    assert fitted.width() == 4096 and fitted.height() <= 100
    small = QImage(100, 50, QImage.Format.Format_RGBA8888)
    assert fit_image(small, 4096) is small


READER_MAIN = r"""
#include <cstdio>
#include <vector>
#include "shared_frame.h"
int main(int argc, char** argv) {
    std::FILE* file = std::fopen(argv[1], "rb");
    std::vector<uint64_t> words(TPVR_MAPPING_SIZE / 8);
    size_t size = std::fread(words.data(), 1, TPVR_MAPPING_SIZE, file);
    std::fclose(file);
    const uint8_t* base = reinterpret_cast<const uint8_t*>(words.data());
    tpvr::FrameReader reader;
    int result = static_cast<int>(reader.read(base, size, std::strtoull(argv[2], nullptr, 10)));
    const tpvr::FrameInfo& info = reader.info();
    unsigned long sum = 0;
    for (uint8_t value : reader.pixels()) sum += value;
    std::printf("%d %d %u %u %u %d %.3f %.3f %.3f %.3f %lu\n", result, reader.drawable() ? 1 : 0, info.width,
                info.height, info.pixel_format, info.attach_to_headset ? 1 : 0, info.width_meters, info.distance_meters,
                info.vertical_offset_meters, info.horizontal_offset_meters, sum);
    // Quads the layer submits with argv[3] layer slots: image rect, canvas position, pose & size (meters)
    const uint32_t slots = argc > 3 ? static_cast<uint32_t>(std::strtoul(argv[3], nullptr, 10)) : 16u;
    const tpvr::TileLayout layout = tpvr::plan_layout(info, slots, 4096, 4096);
    std::printf("%u %u %u %d\n", info.canvas_width, info.canvas_height, info.tile_count, layout.merged ? 1 : 0);
    for (const tpvr::LayoutQuad& quad : layout.quads) {
        const tpvr::QuadPlacement placement = tpvr::quad_placement(info, layout.canvas_width, layout.canvas_height, quad);
        std::printf("%u %u %u %u %u %u %.6f %.6f %.6f %.6f %.6f\n", quad.image.x, quad.image.y, quad.image.width,
                    quad.image.height, quad.canvas_x, quad.canvas_y, placement.x, placement.y, placement.z,
                    placement.width, placement.height);
    }
    return 0;
}
"""


def test_cpp_reader_reads_python_frames(tmp_path):
    """Frame written by the app read by the layer's reader (compiled when a C++ compiler is available)"""
    import shutil
    import subprocess

    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None or sys.platform == "win32":  # Windows: built & tested by the "OpenXR layer" CI job
        pytest.skip("no C++ compiler")
    source = tmp_path / "reader.cpp"
    source.write_text(READER_MAIN.replace("#include <cstdio>", "#include <cstdio>\n#include <cstdlib>"))
    program = tmp_path / "reader"
    subprocess.run(
        [compiler, "-std=c++17", "-O1", "-I", os.path.join(LAYER_DIR, "include"), "-I", os.path.join(LAYER_DIR, "src"),
         str(source), os.path.join(LAYER_DIR, "src", "shared_frame.cpp"), "-o", str(program)],
        check=True, timeout=120)
    buffer = bytearray(vr_shared.MAPPING_SIZE)
    writer = vr_shared.SharedFrameWriter(buffer)
    writer.open()
    writer.set_placement(vr_shared.Placement(0.5, 1.25, -0.25, 0.125, True))
    image = QImage(30, 12, QImage.Format.Format_RGBA8888)
    image.fill(0x80402010)  # ARGB
    view = memoryview(image.constBits())[:image.sizeInBytes()]
    writer.write_image(view, image.width(), image.height(), image.bytesPerLine())
    writer.heartbeat(5000)
    dump = tmp_path / "frame.bin"
    dump.write_bytes(bytes(buffer))
    output = subprocess.run([str(program), str(dump), "5100"], capture_output=True, text=True, check=True, timeout=30)
    fields = output.stdout.split()
    assert fields[:6] == ["0", "1", "30", "12", "1", "1"]  # Updated, drawable, size, straight RGBA, attached
    assert [float(value) for value in fields[6:10]] == [0.5, 1.25, -0.25, 0.125]
    assert int(fields[10]) == 30 * 12 * (0x40 + 0x20 + 0x10 + 0x80)
    stale = subprocess.run([str(program), str(dump), str(5000 + vr_shared.APP_TIMEOUT_MS + 1)],
                           capture_output=True, text=True, check=True, timeout=30)
    assert stale.stdout.split()[:2] == ["4", "0"]  # AppGone: nothing drawn

    # Tiles: each quad where Python places the tile (tile_placement), merged when slots are missing
    placement = vr_shared.Placement(0.6, 1.25, -0.25, 0.125, False)
    writer.set_placement(placement)
    tiles = [vr_shared.Tile(0, 0, 30, 12, 0, 0), vr_shared.Tile(31, 0, 20, 10, 280, 190),
             vr_shared.Tile(52, 0, 8, 6, 140, 60)]
    atlas = bytes([0x40, 0x20, 0x10, 0x80]) * (60 * 12)
    writer.write_tiles(atlas, 60, 12, 240, tiles, (300, 200))
    writer.heartbeat(5000)
    dump.write_bytes(bytes(buffer))
    lines = subprocess.run([str(program), str(dump), "5100"], capture_output=True, text=True, check=True,
                           timeout=30).stdout.splitlines()
    assert lines[0].split()[:6] == ["0", "1", "60", "12", "1", "0"]
    assert lines[1].split() == ["300", "200", "3", "0"]  # canvas, tiles, not merged
    assert len(lines) == 2 + len(tiles)
    for tile, line in zip(tiles, lines[2:]):
        values = line.split()
        assert [int(value) for value in values[:6]] == [tile.atlas_x, tile.atlas_y, tile.width, tile.height,
                                                        tile.canvas_x, tile.canvas_y]  # imageRect = atlas rect
        expected = vr_shared.tile_placement(placement, (300, 200), tile)
        x, y, z, width, height = (float(value) for value in values[6:])
        assert (x, y, z) == pytest.approx((expected.horizontal_offset_meters, expected.vertical_offset_meters,
                                           -expected.distance_meters), abs=1e-5)
        assert (width, height) == pytest.approx((expected.width_meters, expected.width_meters * tile.height / tile.width),
                                                abs=1e-5)
    merged = subprocess.run([str(program), str(dump), "5100", "2"], capture_output=True, text=True, check=True,
                            timeout=30).stdout.splitlines()
    assert merged[1].split() == ["300", "200", "3", "1"] and len(merged) == 4  # 2 quads for 3 tiles


def test_release_build_bundles_layer_where_app_finds_it():
    with open(os.path.join(ROOT, "build_pyinstaller.py"), encoding="utf-8") as file:
        script = file.read()
    assert f'OPENXR_LAYER_FOLDER = "{vr_shared.LAYER_FOLDER}"' in script
    assert f'OPENXR_LAYER_FILES = ("{vr_shared.LAYER_DLL}", "{vr_shared.LAYER_MANIFEST}")' in script
    with open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8") as file:
        assert "--require-openxr-layer" in file.read()  # release never ships without the layer
