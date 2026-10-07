"""Update flow audit fixes (package C): installed vs portable copy, checker thread, download
(once, partial file removed), installer signature, install only once app can quit"""

import hashlib
import io
import json
import os
import sys
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal import app_signal, update
from tinypedal.setting import cfg

DIGEST = "a" * 64
ASSET = update.InstallerAsset("Setup.exe", "https://github.com/x/Setup.exe", DIGEST)


def wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return condition()


@pytest.fixture
def frozen_exe(monkeypatch, tmp_path):
    """App run as Windows executable from tmp folder"""
    monkeypatch.setattr(update.sys, "platform", "win32")
    monkeypatch.setattr(update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(update.sys, "executable", str(tmp_path / "tinypedal.exe"))
    return tmp_path


# Item 5: installer update only for installed copy
def test_portable_copy_is_not_auto_updated(frozen_exe):
    assert not update.can_auto_update() and update.is_portable_copy()
    (frozen_exe / update.UNINSTALLER_NAME).write_bytes(b"")
    assert update.can_auto_update() and not update.is_portable_copy()


def test_source_run_installs_on_windows_only(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(update.sys, "platform", "linux")
    assert not update.can_auto_update() and not update.is_portable_copy()
    monkeypatch.setattr(update.sys, "platform", "win32")  # installer updates the installed app
    assert update.can_auto_update() and not update.is_portable_copy()


def test_portable_notes_open_release_page(ui_env, monkeypatch):
    from tinypedal.ui import notification, release_notes

    opened = []
    monkeypatch.setattr(release_notes.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    monkeypatch.setattr(notification, "is_portable_copy", lambda: True)
    monkeypatch.setattr(notification, "can_auto_update", lambda: False)
    monkeypatch.setattr(update.update_checker, "installer", ASSET)
    button = notification.UpdatesNotifyButton("")
    dialog = button.release_notes_dialog(prompt=True)
    try:
        assert dialog.portable and dialog.download_url == ""  # never the installer
        assert release_notes.tr(release_notes.PORTABLE_UPDATE_NOTE) in dialog.button_install.toolTip()
        dialog.button_install.click()
        assert opened and opened[0].endswith("/releases")
    finally:
        dialog.deleteLater()
        button.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# Item 15: sha256 file separated by tab, partial downloads removed
def test_parse_sha256_any_whitespace():
    assert update.parse_sha256(f"{DIGEST}\tSetup.exe\n") == DIGEST
    assert update.parse_sha256(f"{DIGEST.upper()} *Setup.exe") == DIGEST
    with pytest.raises(ValueError):
        update.parse_sha256("")


class FakeResponse(io.BytesIO):
    """urlopen response, optionally failing after first chunk"""

    def __init__(self, data: bytes, fail: bool = False):
        super().__init__(data)
        self.fail = fail

    def read(self, size=-1):
        chunk = super().read(size)
        if self.fail and self.tell() >= len(self.getvalue()):
            raise OSError("connection reset")
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.mark.parametrize("failure", ["network", "hash"])
def test_failed_download_leaves_no_file(monkeypatch, tmp_path, failure):
    content = b"installer" * 20000
    digest = hashlib.sha256(content if failure == "network" else b"other").hexdigest()

    def urlopen(url, timeout=0):
        return FakeResponse(content, fail=failure == "network")

    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    with pytest.raises((OSError, ValueError)):
        update.download_installer(ASSET._replace(sha256=digest), str(tmp_path))
    assert not list(tmp_path.iterdir())  # no partial nor invalid installer kept


def test_download_replaces_previous_file(monkeypatch, tmp_path):
    content = b"new installer"
    digest = hashlib.sha256(content).hexdigest()
    (tmp_path / "Setup.exe").write_bytes(b"old")
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda url, timeout=0: FakeResponse(content))
    path = update.download_installer(ASSET._replace(sha256=digest), str(tmp_path))
    with open(path, "rb") as file:
        assert file.read() == content
    assert [item.name for item in tmp_path.iterdir()] == ["Setup.exe"]


# Item 35: installer signature checked before running
@pytest.mark.parametrize("signature, started", [
    (update.SIGNATURE_VALID, True),
    (update.SIGNATURE_UNSIGNED, True),  # current releases: hash checked, logged
    (update.SIGNATURE_UNKNOWN, True),
    (update.SIGNATURE_INVALID, False),
])
def test_run_installer_checks_signature(monkeypatch, signature, started):
    runs = []
    monkeypatch.setattr(update, "update_repository", lambda: update.FORK_REPO_NAME)
    monkeypatch.setattr(update, "installer_signature", lambda path: signature)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    if started:
        update.run_installer("Setup.exe")
        assert runs and runs[0][0] == "Setup.exe" and "/SILENT" in runs[0]
    else:
        with pytest.raises(ValueError):
            update.run_installer("Setup.exe")
        assert not runs


@pytest.mark.parametrize("repo, signature, started", [
    ("Keenny38/ModernTinyPedals", update.SIGNATURE_UNSIGNED, True),  # official releases unsigned
    ("keenny38/moderntinypedals", update.SIGNATURE_UNSIGNED, True),
    ("Keenny38/overlays", update.SIGNATURE_UNSIGNED, True),  # renamed official repository
    ("someone/fork", update.SIGNATURE_UNSIGNED, False),  # other repository: signature required
    ("", update.SIGNATURE_UNSIGNED, False),
    ("someone/fork", update.SIGNATURE_VALID, True),
    ("someone/fork", update.SIGNATURE_UNKNOWN, True),  # not checked (not Windows)
    ("someone/fork", update.SIGNATURE_INVALID, False),
])
def test_run_installer_custom_repository_requires_signature(ui_env, monkeypatch, repo, signature, started):
    runs = []
    monkeypatch.setitem(cfg.application, "update_repository", repo)
    monkeypatch.setattr(update, "installer_signature", lambda path: signature)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    if started:
        update.run_installer("Setup.exe", "")
        assert runs and "/SILENT" in runs[0]
    else:
        with pytest.raises(ValueError):
            update.run_installer("Setup.exe", "")
        assert not runs


def test_run_installer_start_error_raised(monkeypatch):
    def refused(args, **kwargs):
        raise PermissionError(13, "blocked")

    monkeypatch.setattr(update, "installer_signature", lambda path: update.SIGNATURE_UNSIGNED)
    monkeypatch.setattr(update, "update_repository", lambda: update.FORK_REPO_NAME)
    monkeypatch.setattr(update.subprocess, "Popen", refused)
    with pytest.raises(OSError):
        update.run_installer("Setup.exe")


def test_run_installer_install_folder(monkeypatch):
    runs = []
    monkeypatch.setattr(update, "installer_signature", lambda path: update.SIGNATURE_UNSIGNED)
    monkeypatch.setattr(update, "update_repository", lambda: update.FORK_REPO_NAME)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    monkeypatch.setattr(update, "install_folder", lambda: "E:/Modern Tiny Pedals/")
    update.run_installer("Setup.exe")  # folder of install_folder by default
    update.run_installer("Setup.exe", "")  # installer picks it
    assert runs[0][-1] == f"/DIR={os.path.normpath('E:/Modern Tiny Pedals')}"
    assert not any(arg.startswith("/DIR") for arg in runs[1])


def shortcut_bytes(base: str, suffix: str = "", unicode: bool = True) -> bytes:
    """Minimal Windows shortcut: header, target ID list, link info with local path (MS-SHLLINK)"""
    header_size = 0x24 if unicode else 0x1C
    volume_id = (16).to_bytes(4, "little") + bytes(12)
    ansi_base = (b"" if unicode else base.encode("ascii")) + b"\x00"
    ansi_suffix = (b"" if unicode else suffix.encode("ascii")) + b"\x00"
    strings = volume_id + ansi_base + ansi_suffix
    offsets = [header_size, header_size + len(volume_id), 0, header_size + len(volume_id) + len(ansi_base)]
    unicode_part = b""
    if unicode:
        unicode_base = base.encode("utf-16-le") + b"\x00\x00"
        unicode_part = unicode_base + suffix.encode("utf-16-le") + b"\x00\x00"
        offsets += [header_size + len(strings), header_size + len(strings) + len(unicode_base)]
    size = header_size + len(strings) + len(unicode_part)
    info = b"".join(value.to_bytes(4, "little") for value in [size, header_size, 0x01, *offsets])
    header = bytearray(76)
    header[0:4] = (0x4C).to_bytes(4, "little")
    header[20:24] = (0x03).to_bytes(4, "little")  # HasLinkTargetIDList, HasLinkInfo
    id_list = (4).to_bytes(2, "little") + bytes(4)
    return bytes(header) + id_list + info + strings + unicode_part


@pytest.mark.parametrize("unicode", [True, False])
def test_shortcut_target(tmp_path, unicode):
    link = tmp_path / "app.lnk"
    link.write_bytes(shortcut_bytes("E:\\Modern Tiny Pedals\\", "tinypedal.exe", unicode))
    assert update.shortcut_target(str(link)) == "E:\\Modern Tiny Pedals\\tinypedal.exe"
    link.write_bytes(shortcut_bytes("E:\\Modern Tiny Pedals\\tinypedal.exe", "", unicode))
    assert update.shortcut_target(str(link)) == "E:\\Modern Tiny Pedals\\tinypedal.exe"


def test_shortcut_target_unreadable(tmp_path):
    link = tmp_path / "app.lnk"
    assert update.shortcut_target(str(link)) == ""  # missing
    link.write_bytes(b"not a shortcut")
    assert update.shortcut_target(str(link)) == ""
    data = bytearray(shortcut_bytes("E:\\app\\tinypedal.exe"))
    data[20:24] = (0x01).to_bytes(4, "little")  # no link info
    link.write_bytes(bytes(data))
    assert update.shortcut_target(str(link)) == ""
    link.write_bytes(shortcut_bytes("E:\\app\\tinypedal.exe")[:100])  # truncated
    assert update.shortcut_target(str(link)) == ""


def make_install(folder):
    folder.mkdir(parents=True)
    (folder / update.APP_EXECUTABLE).write_bytes(b"")
    (folder / update.UNINSTALLER_NAME).write_bytes(b"")
    return str(folder)


def test_installed_app_folder(monkeypatch, tmp_path):
    installed = make_install(tmp_path / "installed")
    stale = tmp_path / "old"  # left by an earlier install: no uninstaller
    stale.mkdir()
    (stale / update.APP_EXECUTABLE).write_bytes(b"")
    appdata = tmp_path / "appdata"
    link = appdata / update.START_MENU_SHORTCUT
    link.parent.mkdir(parents=True)
    link.write_bytes(shortcut_bytes(os.path.join(installed, update.APP_EXECUTABLE)))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(update, "registry_install_folder", lambda: str(stale))
    assert update.installed_app_folder() == os.path.normpath(installed)  # stale registry: shortcut
    other = make_install(tmp_path / "other")
    monkeypatch.setattr(update, "registry_install_folder", lambda: other)
    assert update.installed_app_folder() == os.path.normpath(other)  # registry first
    link.unlink()
    monkeypatch.setattr(update, "registry_install_folder", lambda: "")
    assert update.installed_app_folder() == ""


def test_install_folder(monkeypatch, frozen_exe):
    monkeypatch.setattr(update, "installed_app_folder", lambda: "E:\\Modern Tiny Pedals")
    assert update.install_folder() == ""  # portable copy: never installed
    (frozen_exe / update.UNINSTALLER_NAME).write_bytes(b"")
    assert update.install_folder() == str(frozen_exe)  # installed copy: itself
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert update.install_folder() == "E:\\Modern Tiny Pedals"  # run from source: installed app
    monkeypatch.setattr(update.sys, "platform", "linux")
    assert update.install_folder() == ""


def test_signature_check_errors_are_unknown(monkeypatch):
    def broken(path):
        raise OSError("wintrust unavailable")

    monkeypatch.setattr(update, "_win_verify_trust", broken)
    monkeypatch.setattr(update.sys, "platform", "win32")
    assert update.installer_signature("Setup.exe") == update.SIGNATURE_UNKNOWN
    monkeypatch.setattr(update.sys, "platform", "linux")
    assert update.installer_signature("Setup.exe") == update.SIGNATURE_UNKNOWN


@pytest.mark.skipif(sys.platform != "win32", reason="WinVerifyTrust is Windows only")
def test_real_signature_check(tmp_path):
    unsigned = tmp_path / "unsigned.exe"
    unsigned.write_bytes(b"MZ" + bytes(4000))
    assert update.installer_signature(str(unsigned)) == update.SIGNATURE_UNSIGNED
    assert update.installer_signature(str(tmp_path / "missing.exe")) == update.SIGNATURE_INVALID
    assert update.installer_signature(sys.executable) in (update.SIGNATURE_VALID, update.SIGNATURE_UNSIGNED)


# Item 15 & 36: checker thread never stuck
@pytest.fixture
def checker(ui_env, monkeypatch):
    checker = update.UpdateChecker()
    states = []
    app_signal.updates.connect(states.append)
    cfg.application["update_repository"] = "Keenny38/ModernTinyPedals"
    yield checker, states
    app_signal.updates.disconnect(states.append)


def release_response(tag: str) -> bytes:
    name = "X-setup.zip"
    body = json.dumps({
        "tag_name": tag, "published_at": "2099-01-02T00:00:00Z", "body": "### Added\n\n- New",
        "assets": [
            {"name": name, "browser_download_url": f"https://github.com/x/{name}", "digest": f"sha256:{DIGEST}"},
        ],
    })
    return b"HTTP/1.1 200 OK\r\n\r\n" + body.encode()


def test_checker_finds_update(checker, monkeypatch):
    checker, states = checker
    checked = threading.Event()  # answer held until checking state seen (else may end first: flaky)

    async def request(repo):
        checked.wait(5)
        return release_response("v99.0.0")

    monkeypatch.setattr(update, "request_latest_release", request)
    checker.check(True)
    assert states[0] is True and checker.is_checking()
    checked.set()
    assert wait_for(lambda: not checker.is_checking() and False in states)
    assert checker.is_updates() and checker.installer is not None and checker.release_notes == "### Added\n\n- New"
    assert checker.latest_version() == (99, 0, 0) and checker.latest_date() == (2099, 1, 2)
    assert checker.message().startswith("New Updates: v99.0.0") and checker.is_manual()


def test_checker_error_never_stuck(checker, monkeypatch):
    checker, states = checker

    async def broken(repo):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(update, "request_latest_release", broken)
    checker.check(False)
    assert wait_for(lambda: not checker.is_checking() and False in states)
    assert checker.message() == "Unable To Find Updates"
    checker.check(False)  # checking again possible
    assert wait_for(lambda: states.count(False) == 2)


def test_checker_disabled_without_repository(checker):
    checker, states = checker
    cfg.application["update_repository"] = ""
    checker.check(True)
    assert states == [False] and not checker.is_checking()
    assert checker.message() == "Update Checking Disabled (Set Update Repository)"


# Items 7, 15, 16: notify button & installer
@pytest.fixture
def updates(ui_env, monkeypatch):
    """Update available with installer, app can install it"""
    from tinypedal.ui import notification

    checker = update.update_checker
    monkeypatch.setattr(checker, "_update_available", True)
    monkeypatch.setattr(checker, "_disabled", False)
    monkeypatch.setattr(checker, "_manual_checking", False)
    monkeypatch.setattr(checker, "_last_checked_version", (99, 0, 0))
    monkeypatch.setattr(checker, "_last_checked_date", (2099, 1, 2))
    monkeypatch.setattr(checker, "installer", ASSET)
    monkeypatch.setattr(checker, "release_notes", "### Added\n\n- New")
    monkeypatch.setattr(notification, "can_auto_update", lambda: True)
    monkeypatch.setattr(notification.UpdatesNotifyButton, "prompted_version", "")
    monkeypatch.setattr(notification.UpdatesNotifyButton, "dismissed_message", "")
    installer = notification.UpdateInstaller()
    monkeypatch.setattr(notification, "_update_installer", installer)
    return installer


class FakeWindow:
    """Main window methods used by update install, calls recorded"""

    def __init__(self, can_quit: bool = True):
        self.calls: list[str] = []
        self.can_quit = can_quit

    def close_pages_for_quit(self):
        self.calls.append("close pages")
        return self.can_quit

    def cancel_quit(self):
        self.calls.append("cancel")

    def quit_app(self):
        self.calls.append("quit")
        return True


@pytest.fixture
def messages(monkeypatch):
    found = {"warnings": [], "questions": [], "reply": QMessageBox.StandardButton.Yes}
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda parent, title, text, *a, **k: found["warnings"].append(text)))

    def question(*args, **kwargs):
        found["questions"].append(args[2])
        return found["reply"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return found


def test_install_only_after_pages_closed(updates, monkeypatch, messages):
    from tinypedal.ui import notification

    order = []
    monkeypatch.setattr(notification, "run_installer", lambda path, **kwargs: order.append("installer"))
    window = FakeWindow(can_quit=False)
    assert not notification.install_update(window, "Setup.exe")  # unsaved changes kept
    assert window.calls == ["close pages"] and not order
    window = FakeWindow()
    monkeypatch.setattr(notification, "run_installer", lambda path, **kwargs: window.calls.append("installer"))
    assert notification.install_update(window, "Setup.exe")
    assert window.calls == ["close pages", "installer", "quit"]


def test_installer_errors_keep_app_running(updates, monkeypatch, messages, tmp_path):
    from tinypedal.ui import notification

    def blocked(path, **kwargs):
        raise PermissionError(13, "blocked by antivirus")

    window = FakeWindow()
    monkeypatch.setattr(notification, "run_installer", blocked)
    assert not notification.install_update(window, "Setup.exe")
    assert window.calls == ["close pages", "cancel"] and "Unable to install update" in messages["warnings"][0]

    def bad_signature(path, **kwargs):
        raise ValueError("installer signature is not valid")

    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"MZ")
    monkeypatch.setattr(notification, "run_installer", bad_signature)
    assert not notification.install_update(window, str(installer))
    assert not installer.exists()  # never kept
    assert "signature" in messages["warnings"][1]


def test_unsigned_installer_of_custom_repository_refused(updates, monkeypatch, messages, tmp_path):
    from tinypedal.ui import notification

    runs = []
    monkeypatch.setitem(cfg.application, "update_repository", "someone/fork")
    monkeypatch.setattr(update, "installer_signature", lambda path: update.SIGNATURE_UNSIGNED)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"MZ")
    window = FakeWindow()
    assert not notification.install_update(window, str(installer))
    assert not runs and not installer.exists()
    assert window.calls == ["close pages", "cancel"]
    assert "custom update repository is not signed" in messages["warnings"][0]  # not "signature not valid"


def test_installer_checked_against_repository_found_at_check(updates, monkeypatch, messages, tmp_path):
    """Update repository blanked or changed between check & install: repository of release checked"""
    from tinypedal.ui import notification

    runs = []
    monkeypatch.setitem(cfg.application, "update_repository", "")  # blanked after check
    monkeypatch.setattr(update, "installer_signature", lambda path: update.SIGNATURE_UNSIGNED)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    monkeypatch.setattr(update, "install_folder", lambda: "")
    window = FakeWindow()
    assert notification.install_update(window, "Setup.exe", update.FORK_REPO_NAME)  # official release
    assert runs and window.calls == ["close pages", "quit"]
    monkeypatch.setitem(cfg.application, "update_repository", update.FORK_REPO_NAME)  # set back after check
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"MZ")
    window = FakeWindow()
    assert not notification.install_update(window, str(installer), "someone/fork")  # found in a fork
    assert len(runs) == 1 and not installer.exists()
    assert "custom update repository is not signed" in messages["warnings"][0]


def test_installer_keeps_repository_of_check(monkeypatch):
    raw = b'{"assets": [{"name": "A-1.0.0-setup.zip", "browser_download_url": "https://github.com/a/A-1.0.0-setup.zip", ' \
        b'"digest": "sha256:' + b"b" * 64 + b'"}]}'
    asset = update.parse_installer(raw, "someone/fork")
    assert asset is not None and asset.repository == "someone/fork"
    assert update.parse_installer(raw).repository == ""  # type: ignore[union-attr]


@pytest.mark.parametrize("repo, official", [
    (update.FORK_REPO_NAME, True), ("keenny38/moderntinypedals/", True), ("Keenny38/overlays", True),
    ("someone/fork", False), ("", False),
])
def test_is_official_repository(repo, official):
    assert update.is_official_repository(repo) is official


def test_download_keeps_repository_of_check(updates, monkeypatch, messages):
    """Installer installed with repository it was found in, even if a later check replaced it"""
    from tinypedal.ui import notification

    installs = []
    monkeypatch.setattr(update.update_checker, "installer", ASSET._replace(repository="someone/fork"))
    monkeypatch.setattr(notification, "download_installer", lambda asset, **kwargs: "Setup.exe")
    monkeypatch.setattr(
        notification, "install_update", lambda window, path, repository=None: installs.append((path, repository)))
    monkeypatch.setattr(notification, "main_window", lambda: None)
    assert updates.download(auto_install=True)
    monkeypatch.setattr(update.update_checker, "installer", ASSET._replace(repository=update.FORK_REPO_NAME))
    assert wait_for(lambda: not updates.busy)
    assert installs == [("Setup.exe", "someone/fork")]


def test_download_runs_once(updates, monkeypatch, messages):
    from tinypedal.ui import notification

    release = threading.Event()
    downloads = []

    def download(asset, **kwargs):
        downloads.append(asset)
        release.wait(5)
        return "Setup.exe"

    installs = []
    monkeypatch.setattr(notification, "download_installer", download)
    monkeypatch.setattr(notification, "install_update", lambda window, path, repository=None: installs.append(path))
    monkeypatch.setattr(notification, "main_window", lambda: None)
    button =notification.UpdatesNotifyButton("")
    button.install_update.setVisible(True)  # app can install (hidden action is always disabled)
    try:
        assert updates.download(auto_install=True)
        assert not updates.download(auto_install=True)  # second Install (reopened page): ignored
        button.install_from_notes()
        assert updates.busy and button.text() == "Downloading Update..." and not button.install_update.isEnabled()
        release.set()
        assert wait_for(lambda: not updates.busy)
        assert len(downloads) == 1 and installs == ["Setup.exe"] and not messages["questions"]  # no second question
        assert button.install_update.isEnabled()
    finally:
        release.set()
        button.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_download_failure_warned(updates, monkeypatch, messages):
    from tinypedal.ui import notification

    def failing(asset, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(notification, "download_installer", failing)
    monkeypatch.setattr(notification, "main_window", lambda: None)
    assert updates.download()
    assert wait_for(lambda: not updates.busy)
    assert messages["warnings"] and "no network" in messages["warnings"][0]


def test_downloaded_update_asks_first(updates, monkeypatch, messages):
    from tinypedal.ui import notification

    installs = []
    monkeypatch.setattr(notification, "install_update", lambda window, path, repository=None: installs.append(path))
    monkeypatch.setattr(notification, "main_window", lambda: None)
    messages["reply"] = QMessageBox.StandardButton.No
    updates.install_downloaded("Setup.exe", "")
    assert messages["questions"] and not installs
    messages["reply"] = QMessageBox.StandardButton.Yes
    updates.install_downloaded("Setup.exe", "")
    assert installs == ["Setup.exe"]


@pytest.fixture
def window(ui_env, monkeypatch):
    from contextlib import suppress

    from PySide6.QtWidgets import QSystemTrayIcon

    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_prompt_never_pops_hidden_window(window, updates, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    from tinypedal.ui.release_notes import ReleaseNotesDialog

    messages = []
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: True)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, title, text, *args: messages.append(text))
    view = window.centralWidget()
    assert not window.isVisible()  # started hidden in tray
    from tinypedal.ui.notification import UpdatesNotifyButton

    button = window.centralWidget().findChild(UpdatesNotifyButton)
    button.checking(False)
    assert not window.isVisible()  # not shown over the game
    assert messages and "v99.0.0" in messages[0]
    pages = view.dialog_pages()
    assert len(pages) == 1 and isinstance(pages[0].dialog, ReleaseNotesDialog)  # waits inside app
    button.checking(False)
    assert len(messages) == 1  # asked once per version


def test_prompt_shown_when_window_visible(window, updates, monkeypatch):
    from tinypedal.ui.notification import UpdatesNotifyButton

    window.show()
    try:
        button = window.centralWidget().findChild(UpdatesNotifyButton)
        button.checking(False)
        pages = window.centralWidget().dialog_pages()
        assert len(pages) == 1 and pages[0].dialog.prompt
    finally:
        window.hide()


def test_update_notice_kept_after_language_change(window, updates):
    from tinypedal.ui.notification import UpdatesNotifyButton

    UpdatesNotifyButton.prompted_version = update.update_checker.message()  # already proposed
    window.centralWidget().findChild(UpdatesNotifyButton).checking(False)
    window.retranslate()
    button = window.centralWidget().findChild(UpdatesNotifyButton)
    assert button.isVisibleTo(window) and "99.0.0" in button.text()
    assert not window.centralWidget().dialog_pages()  # not proposed again
    button.dismiss()
    window.retranslate()
    assert not window.centralWidget().findChild(UpdatesNotifyButton).isVisibleTo(window)  # dismissed stays hidden
