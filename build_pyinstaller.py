"""
PyInstaller build script (Windows)

Args:
    -c, --clean: force remove old build folder before building.
    --require-openxr-layer: fail if the OpenXR layer is not built (release builds).

OpenXR layer (VR overlay in OpenXR games), built before with CMake (see native/openxr_layer/CMakeLists.txt):
    cmake -S native/openxr_layer -B native/openxr_layer/build -A x64
    cmake --build native/openxr_layer/build --config Release
bundled in lib/openxr_layer_bundle (found there by tinypedal/vr_shared.py, which copies it next to the
executable before registering it: games never load the DLL from lib, rewritten by each update).
"""

import argparse
import os
import shutil
from glob import glob

import PyInstaller.__main__

from tinypedal import version_check
from tinypedal.const_app import APP_ID, PLATFORM, VERSION

DIST_FOLDER = "dist"
WORK_FOLDER = "build"
APP_FOLDER = os.path.join(DIST_FOLDER, APP_ID)
EXE_NAME = APP_ID.lower()  # "tinypedal.exe" is checked for restart & cli arguments

EXCLUDE_MODULES = [
    "difflib",
    "pdb",
    "venv",
    "tkinter",
    "curses",
    "distutils",
    "lib2to3",
    "unittest",
    "xmlrpc",
]

# OpenXR layer: DLL & its manifest, kept together (manifest gives DLL path relative to itself)
OPENXR_LAYER_BUILD = os.path.join("native", "openxr_layer", "build", "bin")
OPENXR_LAYER_FILES = ("TinyPedalXrLayer.dll", "TinyPedalXrLayer.json")
OPENXR_LAYER_FOLDER = "openxr_layer_bundle"  # in lib folder (sys._MEIPASS)

# Files that must stay next to executable (loaded with relative path)
DATA_FILES = {
    "": ["LICENSE.txt", "NOTICE.md", "README.md", "CHANGELOG.md", *glob("CHANGELOG.*.md")],  # changelog translations
    "docs": ["docs/customization.md", "docs/contributors.md"],
    "docs/licenses": glob("docs/licenses/*"),
    "fonts": [*glob("fonts/*.ttf"), *glob("fonts/OFL*.txt")],
    "images": [
        "images/CC-BY-SA-4.0.txt",
        "images/icon_compass.png",
        "images/icon_instrument.png",
        "images/icon_steering_wheel.png",
        "images/icon_weather.png",
        "images/icon.png",
        "images/icon_dark.png",
        "images/icon_dark.ico",  # installer shortcut icon for dark theme
    ],
}


def get_cli_argument():
    """Get command line argument"""
    parse = argparse.ArgumentParser(
        description="TinyPedal windows executable build command line arguments"
    )
    parse.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help="force remove old build folder before building",
    )
    parse.add_argument(
        "--require-openxr-layer",
        action="store_true",
        help="fail if the OpenXR layer is not built (release builds)",
    )
    return parse.parse_args()


def openxr_layer_arguments(required: bool) -> list[str] | None:
    """PyInstaller arguments bundling the OpenXR layer, empty if not built (None: required but missing)"""
    paths = [os.path.abspath(os.path.join(OPENXR_LAYER_BUILD, name)) for name in OPENXR_LAYER_FILES]
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        if required:
            print("ERROR:OpenXR layer not built:", ", ".join(missing))
            return None
        print("WARNING:OpenXR layer not built, VR overlay limited to SteamVR & mirror window:", ", ".join(missing))
        return []
    dll, manifest = paths
    return [
        f"--add-binary={dll}{os.pathsep}{OPENXR_LAYER_FOLDER}",
        f"--add-data={manifest}{os.pathsep}{OPENXR_LAYER_FOLDER}",
    ]


def remove_old_build(clean_build: bool) -> bool:
    """Remove old build folder, return False if canceled"""
    if not os.path.exists(APP_FOLDER):
        return True
    if not clean_build:
        answer = input("INFO:Remove old build folder before building? Yes/Quit \n").lower()
        if "y" not in answer:
            return False
    shutil.rmtree(APP_FOLDER)
    print("INFO:Old build files removed")
    return True


def build_exe(extra_arguments: list[str]):
    """Build executable with PyInstaller (one folder mode)"""
    temp_dist = os.path.join(WORK_FOLDER, "dist")
    PyInstaller.__main__.run([
        os.path.abspath("run.py"),
        "--noconfirm",
        "--clean",
        "--windowed",
        f"--name={EXE_NAME}",
        f"--icon={os.path.abspath('images/icon.ico')}",
        "--contents-directory=lib",
        f"--distpath={temp_dist}",
        f"--workpath={WORK_FOLDER}",
        f"--specpath={WORK_FOLDER}",
        "--optimize=2",
        f"--add-data={os.path.abspath('tinypedal/i18n/data')}{os.pathsep}tinypedal/i18n/data",
        # Qt Quick pages (ui/qml), loaded by file path
        f"--add-data={os.path.abspath('tinypedal/ui/qml')}{os.pathsep}tinypedal/ui/qml",
        # Only QML modules used by pages (default PySide6.QtQml hook bundles every one, about 300 MB)
        f"--additional-hooks-dir={os.path.abspath('tools/pyinstaller_hooks')}",
        # Widget & module packages import submodules dynamically via __all__
        "--collect-submodules=tinypedal.widget",
        "--collect-submodules=tinypedal.module",
        # Tool dialogs are imported by name when first opened (ui.tools_view.open_tool)
        "--collect-submodules=tinypedal.ui",
        *(f"--exclude-module={name}" for name in EXCLUDE_MODULES),
        *extra_arguments,
    ])
    shutil.move(os.path.join(temp_dist, EXE_NAME), APP_FOLDER)


def copy_data_files():
    """Copy data files next to executable"""
    for dest, files in DATA_FILES.items():
        dest_path = os.path.join(APP_FOLDER, dest)
        os.makedirs(dest_path, exist_ok=True)
        for file in files:
            shutil.copy2(file, dest_path)


def build_start():
    """Start building"""
    print("INFO:Platform:", PLATFORM.SYSTEM)
    print("INFO:TinyPedal:", VERSION)
    print("INFO:Python:", version_check.python())
    print("INFO:Qt:", version_check.qt())
    print("INFO:PySide:", version_check.pyside())
    print("INFO:psutil:", version_check.psutil())

    if not PLATFORM.WINDOWS:
        print("ERROR:Build script does not support none Windows platform")
        return

    cli_args = get_cli_argument()
    layer_arguments = openxr_layer_arguments(cli_args.require_openxr_layer)
    if layer_arguments is None:
        raise SystemExit(1)
    if not remove_old_build(cli_args.clean):
        print("INFO:Building canceled")
        return
    os.makedirs(DIST_FOLDER, exist_ok=True)
    build_exe(layer_arguments)
    copy_data_files()
    print("INFO:Building finished:", APP_FOLDER)


if __name__ == "__main__":
    build_start()
