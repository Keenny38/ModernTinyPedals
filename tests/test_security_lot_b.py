"""Security audit 2026-10-29, lot B: imported presets & settings keep the receiver's local paths, game API address
and secrets; network paths never opened; pace note sound paths; preset package limits; user folders never files;
OpenXR layer copy folders restricted to the user"""

import json
import os
import sys
import zipfile

import pytest

from neopedal.userfile import preset_package
from neopedal.userfile import settings_import as si
from neopedal.userfile.private_option import is_receiver_option, keep_receiver_options
from neopedal.validator import image_exists, is_network_path

SHARED_PRESET = {
    "steering_wheel": {"enable": True, "custom_steering_wheel_image_file": "\\\\attacker\\s\\w.png"},
    "pace_notes_playback": {"pace_notes_sound_path": "//attacker/s/", "pace_notes_file_name": "\\\\attacker\\n.tppn",
                            "pace_notes_sound_volume": 30},
    "api_lmu": {"url_host": "attacker.example", "url_port": 80, "restapi_update_interval": 100},
    "plugin_unknown": {"logo_image_file": "C:\\x.png"},
}
RECEIVER = {
    "steering_wheel": {"enable": False, "custom_steering_wheel_image_file": "C:\\wheel.png"},
    "pace_notes_playback": {"pace_notes_sound_path": "sounds/", "pace_notes_file_name": "",
                            "pace_notes_sound_volume": 50},
    "api_lmu": {"url_host": "localhost", "url_port": 6397, "restapi_update_interval": 200},
}


def shared_preset():
    return json.loads(json.dumps(SHARED_PRESET))


# --- 3: network paths refused at point of use
@pytest.mark.parametrize("path", [
    "\\\\server\\share\\a.png", "//server/share/a.png", "\\/server/a.png", " \\\\server\\a",
    "\\\\?\\UNC\\server\\share\\a.png", "\\\\.\\pipe\\x", "\\??\\UNC\\server\\a", "file://server/a.png",
    "FILE:///C:/a.png", "smb://server/a", "http://server/a.png",
])
def test_network_paths_detected(path):
    assert is_network_path(path)


@pytest.mark.parametrize("path", ["C:\\images\\a.png", "Z:/share/a.png", "images/a.png", "/home/user/a.png", "",
                                  "a.png", "C:a.png"])
def test_local_paths_allowed(path):
    assert not is_network_path(path)
    assert not is_network_path(None)  # type: ignore[arg-type]


def test_image_exists_refuses_network_path(tmp_path, monkeypatch):
    image = tmp_path / "wheel.png"
    image.write_bytes(b"\x89PNG")
    assert image_exists(str(image))
    calls: list[str] = []

    def exists(path):
        calls.append(path)
        return True

    monkeypatch.setattr(os.path, "exists", exists)
    assert not image_exists("\\\\attacker\\s\\w.png")
    assert calls == []  # never touched (SMB connection)
    monkeypatch.setattr(os.path, "getsize", lambda path: 10)
    assert image_exists("\\\\nas\\logos\\brand.png", allow_network=True)  # listed from user's logo folder


def test_notes_file_on_network_path_not_opened(monkeypatch):
    from neopedal.module import module_notes
    from neopedal.userfile import track_notes

    opened: list[str] = []

    def getsize(path):
        opened.append(path)
        raise FileNotFoundError(path)  # never opened for real

    monkeypatch.setattr(os.path, "getsize", getsize)
    for filename in ("\\\\attacker\\s\\n.tppn", "//attacker/s/n.tppn"):
        config = {"enable_manual_file_selector": True, "pace_notes_file_name": filename}
        assert module_notes.load_pace_notes_file(
            config, "", "Le Mans", track_notes.HEADER_PACE_NOTES, track_notes.parse_csv_notes, ".tppn") is None
    assert opened == []
    # Notes folder of global settings (NAS folder) still read
    config = {"enable_manual_file_selector": False, "pace_notes_file_name": "\\\\attacker\\s\\n.tppn"}
    module_notes.load_pace_notes_file(
        config, "\\\\nas\\notes\\", "Le Mans", track_notes.HEADER_PACE_NOTES, track_notes.parse_csv_notes, ".tppn")
    assert opened == ["\\\\nas\\notes\\Le Mans.tppn"]


# --- 3: imported preset keeps receiver's local file & game connection options
def test_receiver_options():
    for key in ("url_host", "url_port", "pace_notes_sound_path", "pace_notes_file_name",
                "custom_steering_wheel_image_file"):
        assert is_receiver_option(key)
    assert not is_receiver_option("enable") and not is_receiver_option("restapi_update_interval")


def test_keep_receiver_options():
    preset = shared_preset()
    changed = keep_receiver_options(preset, RECEIVER)
    assert preset["steering_wheel"] == {"enable": True, "custom_steering_wheel_image_file": "C:\\wheel.png"}
    assert preset["pace_notes_playback"] == {"pace_notes_sound_path": "sounds/", "pace_notes_file_name": "",
                                             "pace_notes_sound_volume": 30}
    assert preset["api_lmu"] == {"url_host": "localhost", "url_port": 6397, "restapi_update_interval": 100}
    assert preset["plugin_unknown"] == {}  # receiver has none: removed, default used when loaded
    assert len(changed) == 6 and "api_lmu.url_host" in changed
    assert keep_receiver_options(preset, RECEIVER) == []  # same values: none listed
    no_receiver = shared_preset()
    keep_receiver_options(no_receiver)
    assert "url_host" not in no_receiver["api_lmu"] and no_receiver["api_lmu"]["restapi_update_interval"] == 100


def make_package(path, presets, extra=()):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps({"format": preset_package.PACKAGE_FORMAT, "version": 1}))
        for name, data in presets.items():
            package.writestr(f"presets/{name}", json.dumps(data))
        for name, data in extra:
            package.writestr(name, data)
    return str(path)


def test_package_import_keeps_receiver_options(tmp_path):
    target = tmp_path / "settings"
    target.mkdir()
    package = make_package(tmp_path / "shared.zip", {"shared.json": SHARED_PRESET, "own.json": {"relative": {}}})
    result = preset_package.import_preset_package(package, f"{target}/", receiver=RECEIVER)
    assert sorted(result.presets) == ["own.json", "shared.json"]
    data = json.loads((target / "shared.json").read_text(encoding="utf-8"))
    assert data["api_lmu"]["url_host"] == "localhost" and data["api_lmu"]["url_port"] == 6397
    assert data["steering_wheel"]["custom_steering_wheel_image_file"] == "C:\\wheel.png"
    assert data["pace_notes_playback"]["pace_notes_sound_path"] == "sounds/"
    assert len(result.kept) == 6 and all(line.startswith("shared: ") for line in result.kept)
    assert json.loads((target / "own.json").read_text(encoding="utf-8")) == {"relative": {}}  # unchanged


def test_dropped_preset_keeps_receiver_options(tmp_path):
    from neopedal.ui.file_drop import import_preset_file

    source = tmp_path / "shared.json"
    source.write_text(json.dumps({**shared_preset(), "relative": {"enable": True}}), encoding="utf-8")
    target = tmp_path / "settings"
    target.mkdir()
    name = import_preset_file(str(source), str(target), RECEIVER)
    data = json.loads((target / name).read_text(encoding="utf-8"))
    assert data["api_lmu"]["url_host"] == "localhost"
    assert data["pace_notes_playback"]["pace_notes_file_name"] == ""
    assert data["relative"] == {"enable": True}


# --- 12: preset package limits
def test_package_too_many_entries_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(preset_package, "MAX_ENTRIES", 5)
    target = tmp_path / "settings"
    target.mkdir()
    package = make_package(tmp_path / "many.zip", {}, [(f"tracknotes/{index}.tptn", "x") for index in range(6)])
    with pytest.raises(ValueError, match="too many files"):
        preset_package.import_preset_package(package, f"{target}/", notes_paths={"tracknotes": str(tmp_path)})
    assert os.listdir(target) == []


def test_package_too_many_presets_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(preset_package, "MAX_PRESETS", 2)
    target = tmp_path / "settings"
    target.mkdir()
    package = make_package(tmp_path / "many.zip", {f"p{index}.json": {"relative": {}} for index in range(3)})
    with pytest.raises(ValueError, match="too many presets"):
        preset_package.import_preset_package(package, f"{target}/")
    assert os.listdir(target) == []


def test_package_too_large_refused_before_extracting(tmp_path, monkeypatch):
    monkeypatch.setattr(preset_package, "MAX_TOTAL_SIZE", 1000)
    target = tmp_path / "settings"
    target.mkdir()
    package = make_package(tmp_path / "bomb.zip", {"a.json": {"relative": {"text": "x" * 600}},
                                                   "b.json": {"relative": {"text": "y" * 600}}})
    read: list[str] = []
    real_read = preset_package.read_entry

    def read_entry(zip_file, info):
        if info.filename != "manifest.json":
            read.append(info.filename)
        return real_read(zip_file, info)

    monkeypatch.setattr(preset_package, "read_entry", read_entry)
    with pytest.raises(ValueError, match="too large"):
        preset_package.import_preset_package(package, f"{target}/")
    assert read == [] and os.listdir(target) == []


# --- 6: pace note sound file
@pytest.mark.parametrize("note", ["/attacker/s/x", "\\\\attacker\\s\\x", "..\\..\\Windows\\win", "../x", "C:x",
                                  "a:b", "", "  ", "a\x00b", "x*", None, 3])
def test_pace_note_unsafe_text_refused(tmp_path, note):
    from neopedal.userfile.track_notes import pace_note_sound_file

    assert pace_note_sound_file(f"{tmp_path}/", note, "wav") == ""


def test_pace_note_sound_file_inside_folder(tmp_path):
    from neopedal.userfile.track_notes import pace_note_sound_file

    folder = f"{tmp_path}/"
    sound = pace_note_sound_file(folder, "left 3", ".wav")
    assert sound == os.path.join(os.path.abspath(tmp_path), "left 3.wav")
    assert os.path.commonpath((os.path.abspath(tmp_path), sound)) == os.path.abspath(tmp_path)
    assert pace_note_sound_file(folder, "left", "wav/../../x") == ""  # format is an extension only
    assert pace_note_sound_file("//attacker/s/", "left", "wav") == ""  # network sound folder
    assert pace_note_sound_file("\\\\?\\UNC\\attacker\\s\\", "left", "wav") == ""
    assert pace_note_sound_file("/", "left", "mp3").endswith("left.mp3")  # default folder kept working


def test_pace_note_player_skips_unsafe_note(monkeypatch):
    pytest.importorskip("PySide6.QtMultimedia")
    from neopedal.ui import pace_notes_player

    sources = []

    class Player:
        mcfg = {"pace_notes_sound_path": "//attacker/s/", "pace_notes_sound_format": "wav"}
        _play_queue = ["x"]

        def setSource(self, url):
            sources.append(url)

    assert not pace_notes_player.PaceNotesPlayer.set_source(Player())  # type: ignore[arg-type]
    Player.mcfg = {"pace_notes_sound_path": "sounds/", "pace_notes_sound_format": "wav"}
    Player._play_queue = ["left"]
    assert pace_notes_player.PaceNotesPlayer.set_source(Player())  # type: ignore[arg-type]
    assert len(sources) == 1 and sources[0].toLocalFile().endswith("sounds/left.wav")


# --- 18: user folder never a file, Open Folder never runs a file
def test_user_path_existing_file_refused(tmp_path):
    from neopedal.userfile import set_user_data_path

    program = tmp_path / "evil.exe"
    program.write_bytes(b"MZ")
    assert set_user_data_path(str(program)) == ""
    folder = tmp_path / "data" / "new"
    assert set_user_data_path(str(folder)) == str(folder) and folder.is_dir()
    assert set_user_data_path(str(folder)) == str(folder)  # existing folder


def test_open_folder_never_starts_file(tmp_path, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.ui import menu

    program = tmp_path / "evil.exe"
    program.write_bytes(b"MZ")
    monkeypatch.setattr(cfg.path, "telemetry", str(program))
    started: list = []

    def open_url(url):
        started.append(url)
        return True

    monkeypatch.setattr(os, "startfile", lambda *args: started.append(args), raising=False)
    monkeypatch.setattr(menu.QDesktopServices, "openUrl", open_url)
    warnings: list = []
    monkeypatch.setattr(menu.QMessageBox, "warning", lambda *args: warnings.append(args))

    class Menu:
        _parent = None

    menu.ConfigMenu.open_folder(Menu(), True, "telemetry")  # type: ignore[arg-type]
    assert started == [] and len(warnings) == 1


# --- 8: settings import never takes update source, LAN access, secrets, plugin trust, network paths
def make_current(folder):
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({
        "web_dashboard": {"enable_lan_access": False, "access_code": "MYCODE123"},
        "stream_overlay": {"enable_lan_access": False, "access_token": "my-token-0123456789"},
    }), encoding="utf-8")
    (folder / si.PLUGIN_TRUST_FILE).write_text('{"plugin_mine": "abc"}', encoding="utf-8")
    return folder


def make_foreign_source(folder):
    (folder / "settings").mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({
        "application": {"update_repository": "attacker/fork", "language": "Deutsch"},
        "web_dashboard": {"enable_lan_access": True, "access_code": "THEIRCODE"},
        "stream_overlay": {"enable_lan_access": True, "access_token": "their-token-0123456789", "frame_rate": 60},
        "user_path": {"telemetry_path": "\\\\attacker\\s\\telemetry\\", "track_map_path": "D:/maps/"},
        "fuel_calculator": {"export_path": "//attacker/s/"},
    }), encoding="utf-8")
    (folder / si.PLUGIN_TRUST_FILE).write_text('{"plugin_evil": "def"}', encoding="utf-8")
    (folder / "settings" / "race.json").write_text(json.dumps({
        "api_lmu": {"url_host": "attacker.example", "url_port": 80, "access_mode": 1},
        "api_rf2": {"url_host": "127.0.0.1", "url_port": 5400},
    }), encoding="utf-8")
    (folder / "settings" / "local.json").write_text('{"api_lmu": {"url_host": "localhost"}}', encoding="utf-8")
    return folder


@pytest.fixture
def empty_report(monkeypatch):
    monkeypatch.setattr(si, "_report", [])


def test_settings_import_keeps_receiver_security_options(tmp_path, empty_report):
    from neopedal.template.setting_global import GLOBAL_DEFAULT as DEFAULT

    GLOBAL_DEFAULT: dict = DEFAULT

    current = make_current(tmp_path / "NeoPedal")
    source = make_foreign_source(tmp_path / "Other")
    assert si.request_import(str(current), str(source))
    assert si.apply_pending_import(str(current))
    config = json.loads((current / "config.json").read_text(encoding="utf-8"))
    assert config["application"] == {"update_repository": GLOBAL_DEFAULT["application"]["update_repository"],
                                     "language": "Deutsch"}  # other options imported
    assert config["web_dashboard"] == {"enable_lan_access": False, "access_code": "MYCODE123"}
    assert config["stream_overlay"] == {"enable_lan_access": False, "access_token": "my-token-0123456789",
                                        "frame_rate": 60}
    assert config["user_path"]["telemetry_path"] == GLOBAL_DEFAULT["user_path"]["telemetry_path"]
    assert config["user_path"]["track_map_path"] == "D:/maps/"  # local path kept
    assert config["fuel_calculator"]["export_path"] == GLOBAL_DEFAULT["fuel_calculator"]["export_path"]
    assert json.loads((current / si.PLUGIN_TRUST_FILE).read_text(encoding="utf-8")) == {"plugin_mine": "abc"}
    race = json.loads((current / "settings" / "race.json").read_text(encoding="utf-8"))
    assert race["api_lmu"] == {"url_host": "localhost", "url_port": 6397, "access_mode": 1}
    assert race["api_rf2"] == {"url_host": "127.0.0.1", "url_port": 5400}  # loopback kept
    assert (current / "settings" / "local.json").read_text(encoding="utf-8") == '{"api_lmu": {"url_host": "localhost"}}'
    report = "\n".join(message for _, message in si._report)
    assert "application.update_repository" in report and "trusted plugins not imported" in report
    assert "race: api_lmu" in report


def test_settings_import_first_start_no_previous(tmp_path, empty_report):
    current = tmp_path / "NeoPedal"
    source = make_foreign_source(tmp_path / "Other")
    current.mkdir()
    assert si.request_import(str(current), str(source))
    assert si.apply_pending_import(str(current))
    config = json.loads((current / "config.json").read_text(encoding="utf-8"))
    assert config["web_dashboard"] == {"enable_lan_access": False, "access_code": ""}  # new code made on use
    assert config["stream_overlay"]["access_token"] == ""
    assert not (current / si.PLUGIN_TRUST_FILE).exists()  # foreign trust removed


def test_own_backup_import_restores_settings(tmp_path, empty_report):
    current = make_current(tmp_path / "NeoPedal")
    backup = tmp_path / "Backup"
    backup.mkdir()
    own = {"application": {"language": "Français"},
           "web_dashboard": {"enable_lan_access": False, "access_code": "MYCODE123"},
           "user_path": {"track_map_path": "D:/maps/"}}
    (backup / "config.json").write_text(json.dumps(own), encoding="utf-8")
    (backup / si.PLUGIN_TRUST_FILE).write_text('{"plugin_mine": "abc"}', encoding="utf-8")
    assert si.request_import(str(current), str(backup))
    assert si.apply_pending_import(str(current))
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == own  # nothing changed
    assert all("not imported" not in message for _, message in si._report)


def test_trust_file_name_matches_plugin_loader():
    from neopedal import plugin_loader

    assert si.PLUGIN_TRUST_FILE == plugin_loader.TRUST_FILE


@pytest.mark.parametrize(("host", "local"), [("localhost", True), (" LOCALHOST ", True), ("127.0.0.1", True),
                                             ("127.5.5.5", True), ("::1", True), ("[::1]", True),
                                             ("192.168.1.2", False), ("attacker.example", False), (None, False)])
def test_loopback_host(host, local):
    assert si.is_loopback_host(host) is local


# --- 17: OpenXR layer copy folders made in a shared base restricted to the user, topmost first
def test_shared_root_restricts_every_made_folder(tmp_path, monkeypatch):
    from neopedal import vr_shared

    base = tmp_path / "base"
    base.mkdir()
    (base / "existing").mkdir()
    root = base / "existing" / "NeoPedal" / "openxr_layer" / "user"
    restricted: list[str] = []
    monkeypatch.setattr(vr_shared, "restrict_to_user", restricted.append)
    monkeypatch.setattr(vr_shared, "trusted_owner", lambda path: True)
    assert vr_shared.missing_folders(str(root)) == [
        str(base / "existing" / "NeoPedal"), str(base / "existing" / "NeoPedal" / "openxr_layer"), str(root)]
    vr_shared.secure_shared_root(str(root))
    assert restricted == [str(base / "existing" / "NeoPedal"), str(base / "existing" / "NeoPedal" / "openxr_layer"),
                          str(root)]
    restricted.clear()
    vr_shared.secure_shared_root(str(root))  # again: root only
    assert restricted == [str(root)]


def test_shared_root_folder_of_other_owner_refused(tmp_path, monkeypatch):
    from neopedal import vr_shared

    root = tmp_path / "NeoPedal" / "openxr_layer" / "user"
    middle = os.path.normcase(str(tmp_path / "NeoPedal" / "openxr_layer"))
    monkeypatch.setattr(vr_shared, "restrict_to_user", lambda folder: None)
    monkeypatch.setattr(vr_shared, "trusted_owner", lambda path: os.path.normcase(path) != middle)
    with pytest.raises(PermissionError):
        vr_shared.secure_shared_root(str(root))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access control")
def test_shared_root_made_folders_not_inherited_windows(tmp_path, monkeypatch):
    import subprocess

    from neopedal import vr_shared

    monkeypatch.setattr(vr_shared, "WINDOWS", True)
    top = tmp_path / "NeoPedal"
    root = top / "openxr_layer" / "user"
    vr_shared.secure_shared_root(str(root))
    for folder in (top, top / "openxr_layer", root):
        output = subprocess.run(["icacls", str(folder)], capture_output=True, text=True, check=True).stdout
        entries = [line for line in output.splitlines() if ":(" in line]
        assert len(entries) == 3, output  # user, SYSTEM & Administrators only: nothing of the shared base
        assert "(I)" not in output, output  # protected: nothing inherited
        assert vr_shared.trusted_owner(str(folder))
