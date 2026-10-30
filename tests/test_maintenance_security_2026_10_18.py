"""Maintenance & low severity security (2026-10-18): data paths independent of working folder, CI dependency
lists, updater temporary folder, stream origin, secrets in logs, picture policy, response size, corrupted JSON,
pure functions of tools"""

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import zipfile

import pytest

from neopedal import plugin_loader, update, userfile
from neopedal.userfile import json_setting

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")


def read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as file:
        return file.read()


# --- 1. Local files never committed
@pytest.mark.parametrize("pattern", ["discord_*.md", "patreon_*", "tests_en_jeu_*", "prof.out", "*.prof"])
def test_local_files_ignored(pattern):
    assert pattern in read(".gitignore").splitlines()


# --- 2. Data & plugin folders resolved against app folder, never the working folder
def test_app_root_is_source_folder():
    assert userfile.APP_ROOT == ROOT
    assert os.path.isfile(os.path.join(userfile.APP_ROOT, "run.py"))


def test_app_root_of_installed_app(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "neopedal.exe"))
    assert userfile.app_root_folder() == str(tmp_path)


def test_app_path(monkeypatch, tmp_path):
    monkeypatch.setattr(userfile, "APP_ROOT", str(tmp_path))
    assert userfile.app_path("settings/") == os.path.join(str(tmp_path), "settings/")
    absolute = str(tmp_path / "elsewhere") + "/"
    assert userfile.app_path(absolute) == absolute
    assert userfile.app_path("") == ""  # invalid path stays invalid (default used)


def test_user_paths_resolved_against_app_folder(monkeypatch, tmp_path):
    from neopedal.setting import FilePath

    app, cwd = tmp_path / "app", tmp_path / "cwd"
    app.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(userfile, "APP_ROOT", str(app))
    monkeypatch.chdir(cwd)
    path = FilePath.__new__(FilePath)
    outside = f"{(tmp_path / 'data').as_posix()}/"
    path.update({"settings_path": "settings/", "telemetry_path": outside},
                {"settings_path": "settings/", "telemetry_path": "telemetry/"})
    assert path.settings == os.path.join(str(app), "settings/")
    assert path.telemetry == outside  # absolute user path unchanged
    assert (app / "settings").is_dir() and (tmp_path / "data").is_dir()
    assert not list(cwd.iterdir())


def test_relative_path_against_app_folder(monkeypatch, tmp_path):
    app, cwd = tmp_path / "app", tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(userfile, "APP_ROOT", str(app))
    monkeypatch.chdir(cwd)
    assert userfile.set_relative_path(str(app / "deltabest")) == "deltabest/"
    assert userfile.set_relative_path("trackmap") == "trackmap/"  # typed relative path kept
    assert userfile.set_user_data_path("trackmap/") == "trackmap/"
    assert (app / "trackmap").is_dir() and not list(cwd.iterdir())


def test_plugin_folder_next_to_app():
    assert os.path.join(ROOT, "plugins") == plugin_loader.PLUGIN_FOLDER


def test_plugin_functions_follow_plugin_folder(monkeypatch, tmp_path):
    folder = tmp_path / "plugins" / "gauge"
    folder.mkdir(parents=True)
    (folder / "widget.py").write_text("Realtime = object\n", encoding="utf-8")
    (folder / "setting.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(plugin_loader, "PLUGIN_FOLDER", str(tmp_path / "plugins"))
    assert plugin_loader.discover_plugins() == {"plugin_gauge": str(folder)}
    assert plugin_loader.plugin_path("plugin_gauge") == str(folder)
    assert list(plugin_loader.load_plugin_defaults()) == ["plugin_gauge"]


def test_settings_from_other_working_folder_create_nothing_there(tmp_path):
    """Settings loaded with another working folder (tests, tools): user folders created in app folder only"""
    app, cwd = tmp_path / "app", tmp_path / "cwd"
    app.mkdir()
    cwd.mkdir()
    env = {
        **os.environ,
        "APPDATA": str(tmp_path / "appdata"), "LOCALAPPDATA": str(tmp_path / "local"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "share"),
        "PYTHONPATH": ROOT, "QT_QPA_PLATFORM": "offscreen",
    }
    script = (
        "import sys\n"
        "sys.frozen = True\n"  # installed app: app folder is folder of executable
        f"sys.executable = {str(app / 'neopedal.exe')!r}\n"
        "from neopedal.setting import cfg\n"
        "cfg.load_global()\n"
        "cfg.load_user()\n"
        "from neopedal import plugin_loader\n"
        "print(plugin_loader.PLUGIN_FOLDER)\n"
        "print(cfg.path.settings)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    plugins, settings = result.stdout.splitlines()[-2:]
    assert not list(cwd.iterdir())
    assert plugins == os.path.join(str(app), "plugins")
    assert os.path.isdir(settings) and os.path.isabs(settings)
    if sys.platform == "win32":  # Linux: XDG folders
        assert os.path.normcase(os.path.dirname(os.path.normpath(settings))) == os.path.normcase(str(app))


# --- 3. CI dependencies: one list each, release lock as constraints
def test_requirement_lists_single_source():
    dev = read("requirements-dev.txt").splitlines()
    assert "-r requirements.txt" in dev
    assert {"pytest", "pytest-cov", "pytest-timeout", "pytest-xdist", "ruff", "mypy", "pre-commit"} <= {
        re.split(r"[<>=;\s]", line, maxsplit=1)[0] for line in dev if line and not line.startswith(("#", "-"))}
    pyproject = read("pyproject.toml")
    assert 'dependencies = { file = ["requirements.txt"] }' in pyproject
    assert "\ndev = [" not in pyproject  # dev tools listed in requirements-dev.txt only


def test_lock_pins_every_runtime_requirement():
    def names(text: str) -> set[str]:
        return {re.split(r"[<>=;\s\[]", line, maxsplit=1)[0].lower().replace("_", "-")
                for line in text.splitlines() if line.strip() and not line.startswith(("#", "-"))}

    assert names(read("requirements.txt")) <= names(read("requirements-lock.txt"))


def test_checks_install_dev_list_with_lock():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(read(".github/workflows/checks.yml"))
    assert set(workflow["jobs"]) == {"checks", "openxr-layer", "visual-regression"}  # required check names
    for job in ("checks", "visual-regression"):
        installs = [step["run"] for step in workflow["jobs"][job]["steps"] if step.get("name") == "Install dependencies"]
        assert len(installs) == 1
        assert "pip install -r requirements-dev.txt -c requirements-lock.txt" in installs[0]


# --- 4a. Updater: private temporary folder, hash checked on the file used
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def installer_asset(name: str, content: bytes) -> update.InstallerAsset:
    return update.InstallerAsset(name, f"https://github.com/x/{name}", hashlib.sha256(content).hexdigest())


@pytest.fixture
def temp_root(monkeypatch, tmp_path):
    """Temporary folders of downloads made in tmp_path"""
    root = tmp_path / "temp"
    root.mkdir()
    real_mkdtemp = update.tempfile.mkdtemp
    monkeypatch.setattr(update.tempfile, "mkdtemp", lambda prefix: real_mkdtemp(prefix=prefix, dir=str(root)))
    return root


def test_download_in_private_folder_removed_on_discard(monkeypatch, temp_root):
    content = b"installer" * 100
    monkeypatch.setattr(update, "open_url", lambda url, timeout=0: FakeResponse(content))
    path = update.download_installer(installer_asset("Setup.exe", content))
    folder = os.path.dirname(path)
    assert os.path.dirname(folder) == str(temp_root)
    assert os.path.basename(folder).startswith(update.DOWNLOAD_FOLDER_PREFIX)
    with open(path, "rb") as file:
        assert file.read() == content
    second = update.download_installer(installer_asset("Setup.exe", content))
    assert os.path.dirname(second) != folder  # each download its own folder (never a predictable name)
    update.discard_installer(path)
    assert not os.path.exists(folder)
    update.discard_installer(second)
    assert not list(temp_root.iterdir())


def test_failed_download_removes_private_folder(monkeypatch, temp_root):
    monkeypatch.setattr(update, "open_url", lambda url, timeout=0: FakeResponse(b"other"))
    with pytest.raises(ValueError):
        update.download_installer(installer_asset("Setup.exe", b"expected"))
    assert not list(temp_root.iterdir())


def test_discard_keeps_other_folders(tmp_path):
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"x")
    update.discard_installer(str(installer))
    assert tmp_path.is_dir()  # not a download folder: kept


def tamper_after_replace(monkeypatch, suffix: str):
    """File changed by another program once moved into place (between hash check and use)"""
    real_replace = os.replace

    def replace(src, dst):
        real_replace(src, dst)
        if str(dst).endswith(suffix):
            with open(dst, "ab") as file:
                file.write(b"tampered")

    monkeypatch.setattr(update.os, "replace", replace)


def test_installer_changed_after_download_refused(monkeypatch, tmp_path):
    content = b"installer" * 100
    monkeypatch.setattr(update, "open_url", lambda url, timeout=0: FakeResponse(content))
    tamper_after_replace(monkeypatch, ".exe")
    with pytest.raises(ValueError, match="changed"):
        update.download_installer(installer_asset("Setup.exe", content), str(tmp_path))
    assert not list(tmp_path.iterdir())


def setup_zip(installer: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("NeoPedal-1.0.0-windows-setup.exe", installer)
    return buffer.getvalue()


def test_setup_zip_extracted_from_verified_file(monkeypatch, tmp_path):
    data = setup_zip(b"setup program")
    monkeypatch.setattr(update, "open_url", lambda url, timeout=0: FakeResponse(data))
    path = update.download_installer(installer_asset("NeoPedal-1.0.0-setup.zip", data), str(tmp_path))
    assert os.path.basename(path) == "NeoPedal-1.0.0-windows-setup.exe"
    with open(path, "rb") as file:
        assert file.read() == b"setup program"
    assert [item.name for item in tmp_path.iterdir()] == ["NeoPedal-1.0.0-windows-setup.exe"]


def test_setup_zip_changed_after_download_refused(monkeypatch, tmp_path):
    data = setup_zip(b"setup program")
    monkeypatch.setattr(update, "open_url", lambda url, timeout=0: FakeResponse(data))
    tamper_after_replace(monkeypatch, ".zip")
    with pytest.raises(ValueError, match="changed"):
        update.download_installer(installer_asset("NeoPedal-1.0.0-setup.zip", data), str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_verify_file_sha256_rewinds():
    file = io.BytesIO(b"abc")
    file.read(1)
    update.verify_file_sha256(file, hashlib.sha256(b"abc").hexdigest())
    assert file.tell() == 0
    with pytest.raises(ValueError):
        update.verify_file_sha256(file, hashlib.sha256(b"abd").hexdigest())


# --- 4b. Telemetry stream: pages of own local servers only
def test_own_page_ports_from_setting(monkeypatch):
    from neopedal import command_server
    from neopedal.setting import cfg

    config = {
        "remote_control": {"remote_control_port": 9001},
        "web_dashboard": {"web_dashboard_port": 9002},
        "stream_overlay": {"stream_overlay_port": "bad"},  # invalid value skipped
    }
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    monkeypatch.setattr(command_server, "own_server_running", lambda section: True)
    assert command_server.own_page_ports() == {9001, 9002}
    assert command_server.is_allowed_origin("http://localhost:9002")
    assert command_server.is_allowed_origin("http://127.0.0.1:9001")
    assert not command_server.is_allowed_origin("http://localhost:9003")
    assert command_server.is_allowed_origin(None)  # program without Origin (Companion, SimHub)


# --- 4c. Access code & token never in logs or bug reports
def test_dashboard_request_log_redacts_code(caplog):
    from types import SimpleNamespace

    from neopedal import web_dashboard

    caplog.set_level(logging.DEBUG, logger=web_dashboard.logger.name)
    web_dashboard.DashboardHandler.log_message(
        SimpleNamespace(), '"%s" %s %s', "GET /?lang=fr&code=ab12cd HTTP/1.1", "200", "-")
    assert "ab12cd" not in caplog.text
    assert "code=<redacted>" in caplog.text and "lang=fr" in caplog.text


@pytest.mark.parametrize(("text", "secret"), [
    ("GET /?code=4821 HTTP/1.1", "4821"),
    ("http://127.0.0.1:8339/overlay/gear?token=Zx9_-a&view=1", "Zx9_-a"),
    ("url /a?x=1&CODE=secret'", "secret"),
    ("/api?access_token=t0k3n#frag", "t0k3n"),
])
def test_bug_report_redacts_query_secrets(text, secret):
    from neopedal.bug_report import redact_text

    redacted = redact_text(text)
    assert secret not in redacted and "<redacted>" in redacted


def test_unrelated_code_words_kept():
    from neopedal.bug_report import redact_text

    assert redact_text("exit code=1, error code: 5") == "exit code=1, error code: 5"


# --- 4d. Stream overlay: no script in pictures (SVG of user logo folders)
class Recorder:
    def __init__(self):
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        pass


@pytest.mark.parametrize(("content_type", "scripts"), [
    ("text/html; charset=utf-8", True),
    ("image/svg+xml", False),
    ("image/png", False),
    ("application/json", False),
])
def test_stream_overlay_content_policy(content_type, scripts):
    from neopedal.stream_overlay import StreamHandler

    recorder = Recorder()
    StreamHandler.send_body(recorder, 200, b"<svg/>", content_type)  # type: ignore[arg-type]
    policy = recorder.headers["Content-Security-Policy"]
    assert ("script-src" in policy) is scripts
    assert policy.startswith("default-src 'none'")
    if not scripts:
        assert "sandbox" in policy


# --- 4e. REST answers: body size limited
def read_response(data: bytes):
    from neopedal import async_request

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        return await async_request.read_response(reader)

    return asyncio.run(run())


def test_response_body_size_limited(monkeypatch):
    from neopedal import async_request

    too_large = async_request.MAX_BODY + 1
    with pytest.raises(ValueError, match="too large"):
        read_response(f"HTTP/1.1 200 OK\r\nContent-Length: {too_large}\r\n\r\n".encode())
    monkeypatch.setattr(async_request, "MAX_BODY", 10)
    chunked = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n6\r\nabcdef\r\n6\r\nghijkl\r\n0\r\n\r\n"
    with pytest.raises(ValueError, match="too large"):
        read_response(chunked)
    assert read_response(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nbody").body == b"body"


def test_dev_scratch_code_removed():
    source = read("neopedal/async_request.py")
    assert "_test_async_get" not in source and "__main__" not in source and "print(" not in source


# --- 4f. Corrupted JSON: defaults at once, only access errors retried
@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(json_setting, "sleep", sleeps.append)
    return sleeps


def test_corrupted_setting_not_read_again(tmp_path, no_sleep, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    (tmp_path / "user.json").write_text('{"widget": {"enable": tru', encoding="utf-8")
    loads = []
    real_load = json_setting.json.load
    monkeypatch.setattr(json_setting.json, "load", lambda file: loads.append(1) or real_load(file))
    default = {"widget": {"enable": False}}
    loaded = json_setting.load_setting_json_file("user.json", folder, default, validator=lambda user, d: user)
    assert loaded == default and loaded is not default
    assert len(loads) == 1 and not no_sleep
    assert any(".backup" in name for name in os.listdir(tmp_path))  # broken file kept


def test_corrupted_style_not_read_again(tmp_path, no_sleep):
    folder = f"{tmp_path.as_posix()}/"
    (tmp_path / "brands.json").write_text("{broken", encoding="utf-8")
    assert json_setting.load_style_json_file("brands.json", folder, {"A": "B"}) == {"A": "B"}
    assert not no_sleep
    with open(tmp_path / "brands.json", encoding="utf-8") as file:
        assert json.load(file) == {"A": "B"}  # repaired


def test_locked_setting_still_retried(tmp_path, no_sleep, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    (tmp_path / "user.json").write_text('{"widget": {"enable": true}}', encoding="utf-8")
    real_open = open
    calls = []

    def flaky_open(file, *args, **kwargs):
        calls.append(file)
        if len(calls) < 3:
            raise PermissionError(13, "Permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    loaded = json_setting.load_setting_json_file("user.json", folder, {}, validator=lambda user, d: user)
    assert loaded == {"widget": {"enable": True}} and len(no_sleep) == 2


# --- 5. Pure functions of tools
@pytest.fixture
def tools_path(monkeypatch):
    monkeypatch.syspath_prepend(TOOLS)


def test_change_visual_overrides():
    from tools.make_change_visual import parse_overrides

    assert parse_overrides(["gear.font_size=20", "gear.show_rpm=false", "relative.font_name=Barlow Bold",
                            "relative.colors=[1, 2]"]) == {
        "gear": {"font_size": 20, "show_rpm": False},
        "relative": {"font_name": "Barlow Bold", "colors": [1, 2]},
    }
    for bad in ("gear=1", "gear.size=", ".size=1"):
        with pytest.raises(SystemExit):
            parse_overrides([bad])


def test_change_visual_compose(ui_env, tmp_path, tools_path):
    from gen_release_notes import png_title
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap

    from tools.make_change_visual import GAP, LABEL_HEIGHT, MARGIN, compose

    before_dir, after_dir = tmp_path / "before", tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()
    for folder, size in ((before_dir, 40), (after_dir, 60)):
        pixmap = QPixmap(size, size // 2)
        pixmap.fill(Qt.GlobalColor.red)
        pixmap.save(str(folder / "gear.png"))
    new = QPixmap(30, 30)
    new.fill(Qt.GlobalColor.blue)
    new.save(str(after_dir / "flag.png"))  # new widget: no before picture
    output = str(tmp_path / "change.png")
    compose(["gear", "flag"], str(before_dir), str(after_dir), "Gear & flag", output)
    image = QImage(output)
    assert image.width() >= MARGIN * 2 + 60 * 2 + GAP
    assert image.height() == MARGIN * 2 + LABEL_HEIGHT * 2 + (30 + LABEL_HEIGHT) + (30 + LABEL_HEIGHT)
    assert image.text("Title") == "Gear & flag"
    with open(output, "rb") as file:
        assert png_title(file.read()) == "Gear & flag"  # caption read by release notes


def test_change_visual_long_title_never_cut(ui_env, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap

    from tools.make_change_visual import compose

    for folder in ("before", "after"):
        (tmp_path / folder).mkdir()
        pixmap = QPixmap(10, 10)
        pixmap.fill(Qt.GlobalColor.white)
        pixmap.save(str(tmp_path / folder / "gear.png"))
    output = str(tmp_path / "change.png")
    compose(["gear"], str(tmp_path / "before"), str(tmp_path / "after"), "A very long title " * 6, output)
    assert QImage(output).width() > 400


def test_version_file_read_and_written(tools_path, tmp_path, monkeypatch):
    from next_version import file_version, write_version

    (tmp_path / "neopedal").mkdir()
    version_file = tmp_path / "neopedal" / "version.py"
    version_file.write_text('"""Version"""\n\n__version__ = "0.25.0"\nDEVELOPMENT = ""\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert file_version() == (0, 25, 0)
    write_version("0.26.1")
    assert file_version() == (0, 26, 1)
    assert version_file.read_text(encoding="utf-8").endswith('__version__ = "0.26.1"\nDEVELOPMENT = ""\n')
    version_file.write_text("nothing\n", encoding="utf-8")
    with pytest.raises(ValueError):
        file_version()


@pytest.mark.parametrize(("path", "docs_only"), [
    ("docs/wiki/Overlays.md", True),
    ("docs/changes/2026-10-18-gear.png", True),
    ("README.md", True),
    ("CHANGELOG.fr.md", True),
    ("images/readme_preview.png", True),
    ("docs/customization.md", False),  # option help generated from it: app changes
    ("neopedal/widget/gear.py", False),
    ("README.md.bak", False),
])
def test_docs_only_files(tools_path, path, docs_only):
    from next_version import DOCS_ONLY

    assert bool(DOCS_ONLY.match(path)) is docs_only


def test_release_note_kinds(tools_path):
    from gen_release_notes import Commit, format_notes, kind_of

    assert kind_of("Add Tyre Overview overlay") == "added"
    assert kind_of("Fix sector times") == "fixed"
    assert kind_of("Addition of nothing") == "changed"  # whole word only
    assert format_notes([]) == "No changes.\n"
    notes = format_notes([Commit("def5678", "2026-10-18", "Tidy code"), Commit("abc1234", "2026-10-18", "Add gauge")])
    assert notes.index("### Added") < notes.index("abc1234") < notes.index("### Changed") < notes.index("def5678")
    assert notes.endswith("\n")
