"""Security audit 2026-10-29, findings 13, 14, 15, 19, 26, 28, 29: hostile input, language packs, plugin
trust digest, bug report redaction, reserved file names, Linux instance lock"""

import base64
import json
import os
import struct
import sys
import zlib

import pytest

from neopedal import plugin_loader
from neopedal.validator import (
    WINDOWS_RESERVED_NAMES,
    avoid_reserved_filename,
    is_reserved_filename,
    load_json_strict,
)

DEEP = "[" * 100_000 + "]" * 100_000  # refused by check_json_nesting (json.loads raised RecursionError itself before 3.14)


# Finding 14: deeply nested JSON & numbers out of range
def test_json_nesting_checked_before_parsing():
    from neopedal.validator import MAX_JSON_DEPTH, check_json_nesting, json_loads_checked

    check_json_nesting("[" * MAX_JSON_DEPTH + "]" * MAX_JSON_DEPTH)  # at the limit
    check_json_nesting('{"a": "' + "[" * (MAX_JSON_DEPTH + 1) + '"}')  # brackets inside strings never count
    check_json_nesting(b'["\\"", "]]]]", {"\\\\": [[]]}]')  # escaped quotes & backslashes
    with pytest.raises(RecursionError):
        check_json_nesting("[" * (MAX_JSON_DEPTH + 1) + "]" * (MAX_JSON_DEPTH + 1))
    with pytest.raises(RecursionError):
        check_json_nesting(b'{"a": [' + b"{" * MAX_JSON_DEPTH + b"}" * MAX_JSON_DEPTH + b"]}")
    with pytest.raises(RecursionError):
        json_loads_checked(DEEP.encode())
    assert json_loads_checked(b'[1, {"a": "]]]]"}]') == [1, {"a": "]]]]"}]


# CodeQL py/polynomial-redos: unterminated string of escaped quotes took quadratic time (41 s for 160 KB)
def test_json_nesting_unterminated_string_linear():
    import time

    from neopedal.validator import MAX_JSON_DEPTH, check_json_nesting

    hostile = "[" * (MAX_JSON_DEPTH + 1) + '"' + '\\"' * 80_000  # openers first: scan never skipped
    start = time.perf_counter()
    with pytest.raises(RecursionError):  # brackets before the string still counted
        check_json_nesting(hostile)
    assert time.perf_counter() - start < 2
    check_json_nesting("[" * MAX_JSON_DEPTH + '"' + "[" * 10 + "]" * MAX_JSON_DEPTH)  # inside the open string


def test_load_json_strict_allow_nan_still_checks_nesting():
    assert load_json_strict('{"a": NaN}', allow_nan=True)["a"] != 0  # NaN kept
    with pytest.raises(ValueError):
        load_json_strict('{"a": NaN}')
    with pytest.raises(ValueError):
        load_json_strict(DEEP, allow_nan=True)


def make_pb_code(document) -> str:
    payload = json.dumps(document).encode("utf-8") if not isinstance(document, str) else document.encode("utf-8")
    return "NP1:pb:" + base64.urlsafe_b64encode(zlib.compress(payload, 9)).decode("ascii")


def test_pb_code_hostile_values():
    from neopedal.userfile import pb_code

    deep = "[" * 30_000 + "]" * 30_000  # within decompressed size read (64 KB)
    assert pb_code.decode(make_pb_code(deep)) is None  # nested too deeply: refused, no RecursionError
    data = {"track": "Spa", "vehicle": "Car", "laptime": 120.5}
    for when in (1e308, 10 ** 400, -5, pb_code.MAX_TIME + 1):  # date overflowing date formatting: unknown date
        best = pb_code.decode(make_pb_code({"d": {**data, "time": when}}))
        assert best is not None and best.time == 0
    assert pb_code.decode(make_pb_code({"d": {**data, "time": 1_700_000_000}})).time == 1_700_000_000
    assert pb_code.decode(make_pb_code({"d": {**data, "laptime": 10 ** 400}})) is None  # no OverflowError


def test_pb_code_max_date_formats(ui_env):
    from neopedal.ui.quick.formatting import format_date
    from neopedal.userfile.pb_code import MAX_TIME

    assert format_date(MAX_TIME) != "-"


def test_dropped_preset_nested_too_deeply(tmp_path):
    from neopedal.ui.file_drop import import_preset_file

    path = tmp_path / "deep.json"
    path.write_text(DEEP, encoding="utf-8")
    with pytest.raises(ValueError):
        import_preset_file(str(path), str(tmp_path / "settings"))


def test_lap_info_and_cache_nested_too_deeply(tmp_path):
    from neopedal.userfile import lap_cache, telemetry_lap

    assert telemetry_lap.parse_info(telemetry_lap.INFO_PREFIX + DEEP) == {}
    assert telemetry_lap.parse_info(telemetry_lap.INFO_PREFIX + '{"wetness": NaN}')  # own files may hold NaN
    header = DEEP.encode("utf-8")
    path = tmp_path / "lap.bin"
    path.write_bytes(lap_cache.ARRAYS_HEAD.pack(lap_cache.ARRAYS_MAGIC, lap_cache.ARRAYS_FORMAT, len(header)) + header)
    assert lap_cache.read_arrays_file(str(path)) is None
    assert lap_cache.read_cached_lap(str(path), (0, 0), "lap.csv") is None
    listed = b'{"values": [], "arrays": []}'  # values not a dict: no AttributeError
    path.write_bytes(lap_cache.ARRAYS_HEAD.pack(lap_cache.ARRAYS_MAGIC, lap_cache.ARRAYS_FORMAT, len(listed)) + listed)
    assert lap_cache.read_cached_lap(str(path), (0, 0), "lap.csv") is None


def test_replay_header_nested_too_deeply():
    import io

    from neopedal import replay

    with pytest.raises(ValueError, match="invalid replay header"):
        replay.read_header(io.BytesIO(replay.MAGIC + b"[" * 100_000 + b"\n"))


def test_untrusted_json_sweep_never_raises_recursion_error(tmp_path, monkeypatch):
    from neopedal.process import driver_ranks, raceos
    from neopedal.userfile import layout_profile, preset_check, tyre_strategy

    assert driver_ranks.parse_storage('{"driverRank": ' + DEEP + "}") == []
    assert not driver_ranks.valid_raw(b'{"driverRank": ' + DEEP.encode() + b"}")
    assert raceos._json(DEEP.encode()) is None
    path = tmp_path / "deep.json"
    path.write_text(DEEP, encoding="utf-8")
    assert layout_profile.load_profiles(str(path)) == {}
    with pytest.raises(ValueError):
        preset_check.check_preset_file("deep.json", f"{tmp_path}{os.sep}", {})
    (tmp_path / "deep.tyres").write_text(DEEP, encoding="utf-8")
    tyre_strategy.load_tyre_strategy_file("deep", f"{tmp_path}{os.sep}", ".tyres")  # no exception


def test_game_rest_cache_nested_too_deeply(monkeypatch):
    from types import SimpleNamespace

    from neopedal import game_rest_cache

    cache = game_rest_cache.rest_cache
    monkeypatch.setattr(cache, "answer", lambda *args, **kwargs: SimpleNamespace(ok=True, body=DEEP.encode()))
    assert cache.json("/rest/deep") is None


def test_appended_list_decoder_nested_too_deeply():
    from neopedal.adapter.restapi_connector import AppendedListDecoder

    decoder = AppendedListDecoder()
    assert decoder("[1, 2]") == [1, 2]
    with pytest.raises(RecursionError):  # caller (request task) catches it as invalid JSON
        decoder("[1, 2, " + DEEP + "]")


# Finding 13: lap file memory bounds
def write_lap(path, header, rows):
    path.write_text(",".join(header) + "\n" + "".join(",".join(row) + "\n" for row in rows), encoding="utf-8")


def test_lap_file_columns_values_characters_bounded(tmp_path, monkeypatch):
    from neopedal.module.module_recorder import CSV_HEADER
    from neopedal.userfile import telemetry_lap

    assert len(CSV_HEADER) * 3 < telemetry_lap.MAX_FILE_COLUMNS  # recorded laps never refused
    assert telemetry_lap.MAX_FILE_ROWS * 60 <= telemetry_lap.MAX_FILE_VALUES  # long imported laps neither
    path = tmp_path / "wide.csv"
    write_lap(path, ["distance", *(f"c{index}" for index in range(telemetry_lap.MAX_FILE_COLUMNS))], [])
    with pytest.raises(ValueError, match="columns"):
        telemetry_lap.load_lap(str(path))
    rows = [[str(index), "1", "2"] for index in range(20)]
    write_lap(path, ["distance", "a", "b"], rows)
    assert len(telemetry_lap.load_lap(str(path)).columns["distance"]) == 20
    monkeypatch.setattr(telemetry_lap, "MAX_FILE_VALUES", 30)  # 10 rows of 3 columns
    with pytest.raises(ValueError, match="more than 10 samples"):
        telemetry_lap.load_lap(str(path))
    monkeypatch.setattr(telemetry_lap, "MAX_FILE_VALUES", 64_000_000)
    monkeypatch.setattr(telemetry_lap, "MAX_FILE_CHARACTERS", 50)
    with pytest.raises(ValueError, match="characters"):
        telemetry_lap.load_lap(str(path))


# Finding 13 & 14: MoTeC .ld channels
def ld_file(tmp_path, channels):
    from neopedal.userfile.motec_ld import LdInfo, write_ld

    path = tmp_path / "log.ld"
    write_ld(str(path), channels, LdInfo(driver="Me", vehicle="Car", venue="Spa"))
    return path


def patch_channel(path, index, **fields):
    """Change fields of channel descriptor written by write_ld (descriptors one after another)"""
    from neopedal.userfile import motec_ld

    positions = {"data_ptr": 2, "count": 3, "dtype": 5, "size": 6, "frequency": 7, "decimals": 11, "name": 12}
    offset = motec_ld.HEAD.size + motec_ld.EVENT.size + motec_ld.VENUE.size + motec_ld.VEHICLE.size
    offset += index * motec_ld.CHANNEL.size
    data = bytearray(path.read_bytes())
    values = list(motec_ld.CHANNEL.unpack_from(data, offset))
    for name, value in fields.items():
        values[positions[name]] = value
    data[offset:offset + motec_ld.CHANNEL.size] = motec_ld.CHANNEL.pack(*values)
    path.write_bytes(bytes(data))
    return values


def test_motec_channels_bounded(tmp_path, monkeypatch):
    from neopedal.userfile import motec_ld
    from neopedal.userfile.motec_ld import Channel, read_ld

    samples = [float(index) for index in range(100)]
    channels = [Channel(name, name, "m", 10, samples) for name in ("Alpha", "Beta", "Gamma", "Delta")]
    path = ld_file(tmp_path, channels)
    assert [channel.name for channel in read_ld(str(path))[1]] == ["Alpha", "Beta", "Gamma", "Delta"]
    first = patch_channel(path, 0)
    patch_channel(path, 1, name=b"ALPHA")  # same name: first kept
    patch_channel(path, 2, data_ptr=first[2] + 8)  # data inside Alpha data: skipped
    patch_channel(path, 3, frequency=motec_ld.MAX_FREQUENCY + 1)
    assert [channel.name for channel in read_ld(str(path))[1]] == ["Alpha"]
    path = ld_file(tmp_path, channels)
    monkeypatch.setattr(motec_ld, "MAX_SAMPLES", 250)
    with pytest.raises(ValueError, match="samples"):
        read_ld(str(path))


def test_motec_ranges_overlap():
    from neopedal.userfile.motec_ld import overlaps

    ranges = [(0, 100), (200, 300)]
    assert overlaps(ranges, 0, 100) and overlaps(ranges, 50, 60) and overlaps(ranges, 90, 210)
    assert overlaps(ranges, 250, 400) and overlaps(ranges, 199, 201)
    assert not overlaps(ranges, 100, 200) and not overlaps(ranges, 300, 301) and not overlaps([], 0, 1)


def test_motec_decimals_out_of_range(tmp_path):
    from neopedal.userfile.motec_ld import DTYPE_INTEGERS, Channel, read_ld

    path = ld_file(tmp_path, [Channel("Speed", "Spd", "km/h", 10, [1.0] * 20)])
    patch_channel(path, 0, dtype=DTYPE_INTEGERS[0], decimals=-32768)  # float32 bytes read as int32
    channel = read_ld(str(path))[1][0]  # no OverflowError (10.0 ** 32768)
    assert len(channel.values) == 20


def test_motec_import_catches_arithmetic_error(tmp_path, monkeypatch):
    from neopedal.userfile import motec_import, motec_ld

    def overflow(filename, folder):
        raise OverflowError("cannot convert float infinity to integer")

    monkeypatch.setattr(motec_import, "import_ld_file", overflow)
    paths, error = motec_ld.import_ld_job(str(tmp_path / "log.ld"), str(tmp_path))
    assert paths == [] and "infinity" in error


# Finding 15: language packs
def write_pack(tmp_path, ui=None, messages=None, options=None):
    from neopedal.i18n import LANGUAGE_PACK_FORMAT

    path = tmp_path / "xx.json"
    path.write_text(json.dumps({
        "format": LANGUAGE_PACK_FORMAT, "name": "Test", "code": "xx",
        "ui": ui or {}, "options": options or {}, "messages": messages or [],
    }), encoding="utf-8")
    return str(path)


def test_language_pack_rules_never_freeze(tmp_path):
    from neopedal.i18n import MAX_RULE_PATTERN, read_language_pack

    messages = [
        ["(a+)+$", "x"], ["(\\w+\\s?)*!", "x"], ["(a|ab)*c", "x"], ["(x{1,9}){1,9}", "x"],
        ["." * (MAX_RULE_PATTERN + 1), "x"], [".*" * 9, "x"],
        ["^Delete <b>(.+?)</b> preset\\?$", "Supprimer <b>\\1</b> ?"], ["^Hello (\\d+)$", "Bonjour \\1"],
    ]
    rules = read_language_pack(write_pack(tmp_path, messages=messages))["messages"]
    assert [pattern for pattern, _ in rules] == ["^Delete <b>(.+?)</b> preset\\?$", "^Hello (\\d+)$"]


def test_language_pack_markup_never_added(tmp_path):
    from neopedal.i18n import read_language_pack

    pack = read_language_pack(write_pack(
        tmp_path,
        ui={
            "Settings": "<img src='file:///x'>Réglages",
            "<b>Hi</b>": "<b>Salut</b>",
            "Open <a href='https://a'>page</a>": "Ouvrir <a href='https://evil'>page</a>",
            "Name": "Nom <a href=x",  # unclosed tag
            "Start at <date time>": "Départ à <date heure>",  # placeholder, not a tag
        },
        options={"font_name": "<b>Police</b>", "font_size": "Taille"},
        messages=[["^Hi$", "<img src=x>Salut"], ["^(<b>.+?</b>) done$", "\\1 fait"]],
    ))
    assert pack["ui"] == {"<b>Hi</b>": "<b>Salut</b>", "Start at <date time>": "Départ à <date heure>"}
    assert pack["options"] == {"font_size": "Taille"}
    assert [pattern for pattern, _ in pack["messages"]] == ["^(<b>.+?</b>) done$"]


def test_language_pack_nested_too_deeply(tmp_path):
    from neopedal.i18n import read_language_pack

    path = tmp_path / "deep.json"
    path.write_text(DEEP, encoding="utf-8")
    with pytest.raises(ValueError):
        read_language_pack(str(path))


def test_bundled_translations_pass_pack_checks():
    """Built-in French tables would load as a language pack: rules & markup accepted"""
    from neopedal.i18n import safe_markup, unsafe_pattern
    from neopedal.i18n.fr import TRANSLATION
    from neopedal.i18n.fr_messages import MESSAGE_RULES
    from neopedal.i18n.fr_overlay import OVERLAY_LABELS
    from neopedal.i18n.options import load_data

    for pattern, replacement in MESSAGE_RULES:
        assert unsafe_pattern(pattern) == "", pattern
        assert not isinstance(replacement, str) or safe_markup(replacement, pattern), pattern
    for table in (TRANSLATION, OVERLAY_LABELS, load_data("fr_option_help.json")):
        assert not [key for key, value in table.items() if not safe_markup(value, key)]
    assert not [key for key, value in load_data("fr_options.json").items() if not safe_markup(value, "")]


# Finding 19: plugin trust digest
@pytest.fixture
def trust_file(monkeypatch, tmp_path):
    filename = tmp_path / "plugin_trust.json"
    monkeypatch.setattr(plugin_loader, "trust_filename", lambda: str(filename))
    return filename


def make_plugin(folder, name, code="Realtime = object"):
    path = folder / name
    path.mkdir(parents=True)
    (path / "setting.json").write_text("{}", encoding="utf-8")
    (path / "widget.py").write_text(code, encoding="utf-8")
    return path


def test_plugin_digest_unambiguous_and_covers_every_file(tmp_path, trust_file):
    joined = {"a.py": b"1\0b.py\0" + b"2"}
    split = {"a.py": b"1", "b.py": b"2"}
    assert plugin_loader.sources_digest(joined) == plugin_loader.sources_digest(split)  # legacy flaw
    assert plugin_loader.contents_digest(joined) != plugin_loader.contents_digest(split)
    path = make_plugin(tmp_path, "gauge")
    plugin_loader.trust_plugin("plugin_gauge", str(tmp_path))
    stored = json.loads(trust_file.read_text(encoding="utf-8"))["plugin_gauge"]
    assert stored == plugin_loader.DIGEST_PREFIX + plugin_loader.plugin_digest(str(path))
    assert plugin_loader.is_trusted("plugin_gauge", str(tmp_path))
    (path / "data.bin").write_bytes(b"\0")  # any file counts
    assert not plugin_loader.is_trusted("plugin_gauge", str(tmp_path))


@pytest.mark.parametrize("native", ["helper.pyd", "lib/x.DLL", "mod.cpython-311-x86_64-linux-gnu.so", "a.pth"])
def test_plugin_native_files_never_trusted(tmp_path, trust_file, native):
    path = make_plugin(tmp_path, "gauge", "import os\nRealtime = object\nLOADED = True")
    plugin_loader.trust_plugin("plugin_gauge", str(tmp_path))
    (path / native).parent.mkdir(parents=True, exist_ok=True)
    (path / native).write_bytes(b"MZ")
    with pytest.raises(ValueError, match="native"):
        plugin_loader.trust_plugin("plugin_gauge", str(tmp_path))
    module = plugin_loader.load_plugin_widget("neopedal.widget", "plugin_gauge", str(tmp_path))
    assert not hasattr(module, "LOADED")
    assert plugin_loader.PLUGIN_ERRORS.pop("plugin_gauge") == plugin_loader.NATIVE_ERROR


def test_plugin_package_with_native_file_refused(tmp_path):
    import zipfile

    package = tmp_path / "gauge.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("gauge/widget.py", "Realtime = object")
        archive.writestr("gauge/setting.json", "{}")
        archive.writestr("gauge/helper.pyd", b"MZ")
    with pytest.raises(ValueError, match="native"):
        plugin_loader.install_plugin_package(str(package), str(tmp_path / "plugins"))
    assert not (tmp_path / "plugins" / "gauge").exists()


def test_plugin_legacy_digest_accepted_then_upgraded(tmp_path, trust_file):
    path = make_plugin(tmp_path, "gauge", "Realtime = object\nLOADED = True")
    (path / "icon.png").write_bytes(b"\x89PNG")
    legacy = plugin_loader.sources_digest(plugin_loader.plugin_sources(str(path)))
    trust_file.write_text(json.dumps({"plugin_gauge": legacy}), encoding="utf-8")
    assert plugin_loader.is_trusted("plugin_gauge", str(tmp_path))
    module = plugin_loader.load_plugin_widget("neopedal.widget", "plugin_gauge", str(tmp_path))
    assert module.LOADED
    stored = json.loads(trust_file.read_text(encoding="utf-8"))["plugin_gauge"]
    assert stored == plugin_loader.DIGEST_PREFIX + plugin_loader.plugin_digest(str(path))
    (path / "icon.png").write_bytes(b"\x89PNG changed")  # covered from now on
    assert not plugin_loader.is_trusted("plugin_gauge", str(tmp_path))


def test_plugin_legacy_digest_refused_for_uncovered_files(tmp_path, trust_file):
    path = make_plugin(tmp_path, "gauge")
    legacy = plugin_loader.sources_digest(plugin_loader.plugin_sources(str(path)))
    trust_file.write_text(json.dumps({"plugin_gauge": legacy}), encoding="utf-8")
    (path / "loader.cfg").write_text("x", encoding="utf-8")  # not a package file type: trust again
    assert not plugin_loader.is_trusted("plugin_gauge", str(tmp_path))
    module = plugin_loader.load_plugin_widget("neopedal.widget", "plugin_gauge", str(tmp_path))
    assert plugin_loader.PLUGIN_ERRORS.pop("plugin_gauge") == plugin_loader.UNTRUSTED_ERROR
    assert module.Realtime.__doc__ == "Plugin error"
    assert json.loads(trust_file.read_text(encoding="utf-8"))["plugin_gauge"] == legacy  # not upgraded


# Finding 26: bug report
@pytest.fixture
def short_home(monkeypatch):
    from neopedal import bug_report

    short = os.path.join(os.path.dirname(os.path.expanduser("~")), "STEPHA~1")
    monkeypatch.setattr(bug_report, "short_path", lambda path: short)
    bug_report.home_variants.cache_clear()
    yield short
    bug_report.home_variants.cache_clear()


def test_bug_report_redacts_short_home_ips_and_team_names(short_home):
    from neopedal.bug_report import redact_setting, redact_text

    text = redact_text(
        f"log {short_home}{os.sep}NeoPedal {short_home.replace(os.sep, '/')}/x {short_home.lower()}{os.sep}y "
        "LAN 192.168.1.5. 10.0.0.12:8338 169.254.3.4 lo 127.0.0.1 any 0.0.0.0 public 8.8.8.8 "
        "time 12:34:56 version 6.8.1 v6 fe80::1%eth0 [2001:db8::5]:80 ::1")
    assert "STEPHA~1" not in text.upper()
    assert "192.168" not in text and "10.0.0.12" not in text and "169.254" not in text
    assert "fe80" not in text and "2001:db8" not in text
    for kept in ("127.0.0.1", "0.0.0.0", "8.8.8.8", "12:34:56", "6.8.1", "::1", ":8338"):
        assert kept in text
    data = redact_setting({"race_calculator": {"input_driver_names": "Alice\nBob", "input_stint": 3}})
    assert data == {"race_calculator": {"input_driver_names": "<removed>", "input_stint": 3}}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 8.3 short path")
def test_short_path_of_existing_folder():
    from neopedal.bug_report import short_path

    home = os.path.expanduser("~")
    assert os.path.normcase(os.path.realpath(short_path(home))) == os.path.normcase(os.path.realpath(home))


# Finding 28: reserved file names & control characters
def test_reserved_file_names():
    for name in ("CON", "con.txt", "Nul.tar.gz", "AUX .json", "COM0", "lpt9.log", "CONIN$", "conout$.x", "COM¹",
                 "LPT³.txt", "PRN.", "NUL "):
        assert is_reserved_filename(name), name
    for name in ("CONSOLE", "COM10", "LPT", "my con", "CON_", "nul_.txt", "COM⁴"):
        assert not is_reserved_filename(name), name
    assert avoid_reserved_filename("CON.txt") == "CON_.txt"
    assert avoid_reserved_filename("nul") == "nul_" and avoid_reserved_filename("Spa") == "Spa"
    assert not is_reserved_filename(avoid_reserved_filename("AUX .json"))
    assert len(WINDOWS_RESERVED_NAMES) == 6 + 2 * 13


def test_file_name_helpers_handle_devices_and_control_characters():
    from neopedal.formatter import strip_invalid_char
    from neopedal.userfile.game_images import safe_name
    from neopedal.userfile.preset_package import is_windows_filename
    from neopedal.userfile.telemetry_lap import lap_folder_name

    assert strip_invalid_char("Spa\x01\x1f - GT3") == "Spa - GT3"
    assert strip_invalid_char("CON") == "CON_" and strip_invalid_char("com¹.") == "com¹_"
    assert strip_invalid_char("") == "" and strip_invalid_char("\x01") == "unknown"
    assert safe_name("NUL") == "NUL_" and safe_name("conin$") != "conin$"
    assert lap_folder_name("AUX - ") == "AUX_" and lap_folder_name("Spa\x00 - GT3") == "Spa - GT3"
    assert not is_windows_filename("CONOUT$.tptn") and not is_windows_filename("com0.json")
    assert is_windows_filename("Spa.tptn")
    assert plugin_loader.is_safe_package_path(["gauge", "widget.py"])
    assert not plugin_loader.is_safe_package_path(["lpt².py"])
    assert not plugin_loader.is_safe_package_path(["a\x01.py"])


# Finding 29: Linux instance lock
@pytest.mark.skipif(sys.platform == "win32", reason="Linux lock file")
def test_instance_lock_folder_private(tmp_path, monkeypatch):
    from neopedal import main

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    folder = main.instance_lock_folder()
    assert folder == str(tmp_path / f"{main.CONFIG_ID}-{os.getuid()}")
    assert os.stat(folder).st_mode & 0o777 == 0o700
    assert os.path.dirname(main.instance_lock_file()) == folder
    os.chmod(folder, 0o777)  # opened to others (made by another user): cache folder used
    assert main.instance_lock_folder() == str(tmp_path / "cache" / main.CONFIG_ID)
    os.rmdir(folder)
    os.symlink(str(tmp_path), folder)  # link: refused
    assert main.instance_lock_folder() == str(tmp_path / "cache" / main.CONFIG_ID)
    with pytest.raises(OSError):
        main.private_folder(folder, os.getuid())


@pytest.mark.skipif(sys.platform == "win32", reason="Linux lock file")
def test_instance_lock_file_never_followed_link(tmp_path, monkeypatch):
    from neopedal import main

    monkeypatch.setattr(main, "_instance_lock", None)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    target = tmp_path / "target"
    os.symlink(str(target), main.instance_lock_file())
    with pytest.raises(OSError):
        main.lock_instance()
    assert not target.exists()
    assert not main.other_instance_running()


def test_struct_layout_of_test_helper():
    """patch_channel field positions match CHANNEL descriptor"""
    from neopedal.userfile import motec_ld

    assert motec_ld.CHANNEL.format == "<IIIIHHHHhhhh32s8s12s40x"
    assert struct.calcsize(motec_ld.CHANNEL.format) == motec_ld.CHANNEL.size
