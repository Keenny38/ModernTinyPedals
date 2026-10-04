"""
PyInstaller hook replacing PySide6.QtQml default hook: bundle only QML modules used by app pages

Default hook bundles every QML module & its libraries (about 300 MB: WebEngine, 3D, charts...).
Kept modules: tinypedal/ui/quick/qml_modules.py
"""

import os
import runpy
from pathlib import PurePath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

QML_MODULES = runpy.run_path(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tinypedal", "ui", "quick", "qml_modules.py"))["QML_MODULES"]

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
qml_root = PurePath(pyside6_library_info.qt_rel_dir) / "qml"
# Module folders (qmldir): files belong to deepest module folder containing them
module_folders = {
    PurePath(dest).relative_to(qml_root).as_posix()
    for src, dest in qml_datas if os.path.basename(src) == "qmldir"
}


def kept(dest: str) -> bool:
    folder = PurePath(dest).relative_to(qml_root).as_posix()
    while folder not in module_folders and "/" in folder:
        folder = folder.rsplit("/", 1)[0]
    return folder in QML_MODULES


binaries += [entry for entry in qml_binaries if kept(entry[1])]
datas += [entry for entry in qml_datas if kept(entry[1])]
