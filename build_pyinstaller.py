"""
PyInstaller build script (Windows)

Args:
    -c, --clean: force remove old build folder before building.
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
    "multiprocessing",
]

# Files that must stay next to executable (loaded with relative path)
DATA_FILES = {
    "": ["LICENSE.txt", "README.md"],
    "docs": ["docs/changelog.txt", "docs/customization.md", "docs/contributors.md"],
    "docs/licenses": glob("docs/licenses/*"),
    "fonts": [*glob("fonts/*.ttf"), "fonts/OFL.txt"],
    "plugins/example_speed": ["plugins/example_speed/setting.json", "plugins/example_speed/widget.py"],
    "images": [
        "images/CC-BY-SA-4.0.txt",
        "images/icon_compass.png",
        "images/icon_instrument.png",
        "images/icon_steering_wheel.png",
        "images/icon_weather.png",
        "images/icon.png",
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
    return parse.parse_args()


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


def build_exe():
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
        # Widget & module packages import submodules dynamically via __all__
        "--collect-submodules=tinypedal.widget",
        "--collect-submodules=tinypedal.module",
        # Tool dialogs are imported by name when first opened (ui.tools_view.open_tool)
        "--collect-submodules=tinypedal.ui",
        *(f"--exclude-module={name}" for name in EXCLUDE_MODULES),
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
    if not remove_old_build(cli_args.clean):
        print("INFO:Building canceled")
        return
    os.makedirs(DIST_FOLDER, exist_ok=True)
    build_exe()
    copy_data_files()
    print("INFO:Building finished:", APP_FOLDER)


if __name__ == "__main__":
    build_start()
