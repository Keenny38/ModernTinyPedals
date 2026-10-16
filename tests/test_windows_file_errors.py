"""Windows file errors simulated on every platform: files held a moment by antivirus, cloud sync or another
instance (WinError 5 access denied, 32 sharing violation), retried or reported, never a half-written file"""

import errno
import os

import pytest

from neopedal import userfile
from neopedal.userfile import settings_import as si


def win_error(winerror: int, text: str = "in use") -> PermissionError:
    """PermissionError as Windows raises it (errno EACCES, winerror set)"""
    error = PermissionError(errno.EACCES, text)
    error.winerror = winerror  # type: ignore[attr-defined]
    return error


@pytest.fixture
def no_wait(monkeypatch):
    waits = []
    monkeypatch.setattr(userfile.time, "sleep", waits.append)
    return waits


def flaky_replace(monkeypatch, failures: int, winerror: int = 32):
    """os.replace failing the first times (file held a moment)"""
    replace = os.replace
    calls = []

    def held(src, dst):
        calls.append(dst)
        if len(calls) <= failures:
            raise win_error(winerror)
        replace(src, dst)

    monkeypatch.setattr(userfile.os, "replace", held)
    return calls


@pytest.mark.parametrize("winerror", [5, 32])
def test_replace_retried_while_file_held(tmp_path, monkeypatch, no_wait, winerror):
    target = tmp_path / "a.json"
    target.write_text("old", encoding="utf-8")
    calls = flaky_replace(monkeypatch, userfile.REPLACE_ATTEMPTS - 1, winerror)
    userfile.atomic_replace(str(target), b"new")
    assert target.read_text(encoding="utf-8") == "new" and len(calls) == userfile.REPLACE_ATTEMPTS
    assert no_wait == sorted(no_wait) and len(no_wait) == userfile.REPLACE_ATTEMPTS - 1  # longer each time


def test_file_held_too_long_left_untouched(tmp_path, monkeypatch, no_wait):
    target = tmp_path / "a.json"
    target.write_text("old", encoding="utf-8")
    flaky_replace(monkeypatch, userfile.REPLACE_ATTEMPTS)
    with pytest.raises(PermissionError):
        userfile.atomic_replace(str(target), b"new")
    assert target.read_text(encoding="utf-8") == "old"
    assert os.listdir(tmp_path) == ["a.json"]  # temporary file removed


def test_other_errors_not_retried(tmp_path, monkeypatch, no_wait):
    calls = []

    def full(src, dst):
        calls.append(dst)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(userfile.os, "replace", full)
    with pytest.raises(OSError):
        userfile.atomic_replace(str(tmp_path / "a.json"), b"new")
    assert len(calls) == 1 and not no_wait


@pytest.mark.parametrize(("error", "temporary"), [
    (win_error(32), True),  # sharing violation: other instance closing
    (win_error(5), True),  # access denied: antivirus scan
    (OSError(errno.EBUSY, "busy"), True),
    (OSError("copy failed: [Errno 28] No space left on device"), False),
    (FileNotFoundError(errno.ENOENT, "gone"), False),
])
def test_settings_import_retried_on_held_files_only(error, temporary):
    assert si.is_temporary_error(error) is temporary


def test_settings_import_kept_for_next_start_on_sharing_violation(tmp_path, monkeypatch):
    current = tmp_path / "NeoPedal"
    current.mkdir()
    (current / "config.json").write_text('{"current": true}', encoding="utf-8")
    source = tmp_path / "Other"
    source.mkdir()
    (source / "config.json").write_text('{"other": true}', encoding="utf-8")
    assert si.request_import(str(current), str(source))
    rename = os.rename

    def held(src, dst):
        if os.path.basename(str(src)) == "NeoPedal":
            raise win_error(32)
        rename(src, dst)

    monkeypatch.setattr(si.os, "rename", held)
    assert not si.apply_pending_import(str(current))
    assert si.read_request(str(current)) == str(source)
    assert (current / "config.json").read_text(encoding="utf-8") == '{"current": true}'
    si._report.clear()


def test_lap_folder_rename_retried_while_lap_open(tmp_path, monkeypatch):
    from neopedal.userfile import lap_library

    folder = lap_library.import_folder(f"{tmp_path.as_posix()}/")
    os.makedirs(os.path.join(folder, "old"))
    rename = os.rename
    calls = []

    def held(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise win_error(32)
        rename(src, dst)

    monkeypatch.setattr(lap_library.os, "rename", held)
    monkeypatch.setattr(lap_library.time, "sleep", lambda seconds: None)
    lap_library.rename_group(f"{tmp_path.as_posix()}/", "old", "new")
    assert os.path.isdir(os.path.join(folder, "new")) and len(calls) == 3
