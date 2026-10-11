"""
Windows version resource of the executable (PyInstaller --version-file)

Windows shows FileDescription as the process name (Task Manager, Alt+Tab grouping,
file properties); without it, the executable name ("neopedal") is shown.
"""

from __future__ import annotations

import re


def written_version(version_file: str = "neopedal/version.py") -> str:
    """Version written in version file by release workflow (next_version.py --write)

    Not neopedal.version.__version__: when not frozen (build script), it is the last git tag.
    """
    with open(version_file, encoding="utf-8") as file:
        match = re.search(r'^__version__ = "([^"]+)"', file.read(), re.MULTILINE)
    if match is None:
        raise ValueError(f"no __version__ in {version_file}")
    return match.group(1)


def version_numbers(version: str) -> tuple[int, int, int, int]:
    """Four version numbers from version text ("0.22.5", "0.22.5-dev" -> (0, 22, 5, 0))"""
    numbers = [int(part) for part in re.findall(r"\d+", version.split("-")[0])[:4]]
    return tuple(numbers + [0] * (4 - len(numbers)))  # type: ignore[return-value]


def version_info_text(
    name: str, version: str, exe_name: str, copyright_text: str, company: str
) -> str:
    """PyInstaller version file text (Python expression read by PyInstaller)"""
    numbers = version_numbers(version)
    strings = {
        "CompanyName": company,
        "FileDescription": name,
        "FileVersion": version,
        "InternalName": exe_name,
        "LegalCopyright": copyright_text,
        "OriginalFilename": f"{exe_name}.exe",
        "ProductName": name,
        "ProductVersion": version,
    }
    structs = ",\n".join(f"          StringStruct({key!r}, {value!r})" for key, value in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
{structs},
        ],
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""
