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
    """#define values & TpvrHeader field offsets (from offset comments) of the layer header"""
    with open(HEADER, encoding="utf-8") as file:
        text = file.read()
    defines = {}
    for name, value in re.findall(r"^#define (TPVR_\w+) (.+?)(?:\s*/\*.*)?$", text, re.M):
        value = re.sub(r"(\d+)u\b", r"\1", value.strip())
        if value.startswith('"'):
            defines[name] = value.strip('"')
        else:
            defines[name] = eval(re.sub(r"TPVR_\w+", lambda m: str(defines[m[0]]), value))
    fields = {name: int(offset) for name, offset in re.findall(r"^\s+\w+ (\w+)(?:\[\d+\])?;\s+/\* (\d+)", text, re.M)}
    return defines, fields


def test_protocol_matches_layer_header():
    defines, fields = c_header()
    assert defines["TPVR_MAPPING_NAME"] == vr_shared.MAPPING_NAME
    assert defines["TPVR_MAGIC"] == vr_shared.MAGIC == struct.unpack("<I", b"TPVR")[0]
    for name in ("VERSION", "HEADER_SIZE", "DATA_OFFSET", "MAX_IMAGE_BYTES", "MAPPING_SIZE", "MAX_DIMENSION",
                 "APP_TIMEOUT_MS", "LAYER_TIMEOUT_MS", "FORMAT_RGBA8_STRAIGHT", "FORMAT_RGBA8_PREMULTIPLIED",
                 "FLAG_VISIBLE", "FLAG_ATTACH_TO_HEADSET", "LAYER_IDLE", "LAYER_ACTIVE", "LAYER_UNSUPPORTED",
                 "LAYER_FAILED"):
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


def sequence(buffer):
    return struct.unpack_from("<Q", buffer, vr_shared.OFFSET_SEQUENCE)[0]


def test_writer_header_and_frames():
    buffer = SeqlockBuffer()
    writer = vr_shared.SharedFrameWriter(buffer)
    assert writer.open() and writer.is_open
    assert struct.unpack_from("<4I", buffer, 0) == (vr_shared.MAGIC, 1, 256, vr_shared.MAPPING_SIZE)
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


def write_layer_status(buffer, heartbeat, state=vr_shared.LAYER_ACTIVE, api=1, result=0, frames=9):
    struct.pack_into(vr_shared.LAYER_FORMAT, buffer, vr_shared.OFFSET_LAYER, heartbeat, 4321, state, api, result, frames, 1)


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
    values[os.path.abspath(manifest)] = 1  # disabled by user (OpenXR tools): enabled again
    vr_shared.register_layer(manifest, reg)
    assert values[os.path.abspath(manifest)] == 0
    assert vr_shared.registered_layers(reg) == {os.path.abspath(manifest): 0}
    assert vr_shared.unregister_layer(reg) == 1
    assert values == {OTHER_LAYER: 0}  # other layers untouched
    assert vr_shared.unregister_layer(reg) == 0


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
        monkeypatch.setattr(vr_shared, "tick_ms", lambda: self.now)
        monkeypatch.setattr(vr_overlay, "steamvr_running", lambda: self.steamvr)

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
        width, height, stride, _format, flags, _serial, width_m, distance, vertical, horizontal = env.frame()[:10]
        assert width >= 60 and height >= 30 and stride == width * 4 and flags & vr_shared.FLAG_VISIBLE
        assert (width_m, distance, vertical, horizontal) == pytest.approx((0.8, 1.0, -0.2, 0.0))
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
        assert "showOverlay" not in log  # new image uploaded, overlay stays hidden
        env.now += vr_shared.LAYER_TIMEOUT_MS + 1  # game closed: layer silent
        log.clear()
        control.update_overlay()
        assert log == ["showOverlay"] and control._visible
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
        assert log == ["showOverlay"] and control._visible
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


def test_release_build_bundles_layer_where_app_finds_it():
    with open(os.path.join(ROOT, "build_pyinstaller.py"), encoding="utf-8") as file:
        script = file.read()
    assert f'OPENXR_LAYER_FOLDER = "{vr_shared.LAYER_FOLDER}"' in script
    assert f'OPENXR_LAYER_FILES = ("{vr_shared.LAYER_DLL}", "{vr_shared.LAYER_MANIFEST}")' in script
    with open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8") as file:
        assert "--require-openxr-layer" in file.read()  # release never ships without the layer
