"""Windows version resource of executable (process name in Task Manager)"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import pytest
from exe_version_info import version_info_text, version_numbers, written_version


def test_version_numbers():
    assert version_numbers("0.22.5") == (0, 22, 5, 0)
    assert version_numbers("0.22.5-dev") == (0, 22, 5, 0)
    assert version_numbers("1.2.3.4.5") == (1, 2, 3, 4)
    assert version_numbers("") == (0, 0, 0, 0)


def test_version_info_text_is_valid_for_pyinstaller():
    text = version_info_text("NeoPedal", "0.22.5", "tinypedal", "Copyright (C) 'x' developers", "NeoPedal")
    try:
        from PyInstaller.utils.win32 import versioninfo
    except ImportError:  # PyInstaller only in build environment
        assert "StringStruct('FileDescription', 'NeoPedal')" in text
        return
    info = eval(text, vars(versioninfo))  # the format PyInstaller reads
    strings = {item.name: item.val for item in info.kids[0].kids[0].kids}
    assert strings["FileDescription"] == "NeoPedal"
    assert strings["ProductName"] == "NeoPedal"
    assert strings["OriginalFilename"] == "tinypedal.exe"
    assert strings["LegalCopyright"] == "Copyright (C) 'x' developers"
    assert info.ffi.fileVersionMS == (0 << 16) | 22 and info.ffi.fileVersionLS == 5 << 16


def test_written_version(tmp_path):
    version_file = tmp_path / "version.py"
    version_file.write_text('import os\n__version__ = "0.22.5"\nSETTING_VERSION = "2.50.5"\n', encoding="utf-8")
    assert written_version(str(version_file)) == "0.22.5"
    version_file.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        written_version(str(version_file))


def test_build_uses_version_file():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "build_pyinstaller.py"), encoding="utf-8") as file:
        script = file.read()
    assert "--version-file=" in script and "version_info_text(APP_NAME, written_version()" in script
