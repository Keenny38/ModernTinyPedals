"""Settings imported from TinyPedal: question at first start, Config menu entries"""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from tinypedal.setting import cfg
from tinypedal.ui import settings_import as si
from tinypedal.userfile import folder_migration as fm


class Window(QWidget):
    """Main window stand-in: records restarts"""

    def __init__(self):
        super().__init__()
        self.restarts = 0
        self.wizard = 0

    def restart_app(self):
        self.restarts += 1
        return True

    def open_setup_wizard(self):
        self.wizard += 1


@pytest.fixture
def config_folder(monkeypatch, tmp_path):
    folder = tmp_path / "NeoPedal"
    folder.mkdir()
    monkeypatch.setattr(cfg.path, "config", f"{folder.as_posix()}/")
    legacy = tmp_path / "TinyPedal"
    legacy.mkdir()
    monkeypatch.setattr(fm, "legacy_config_folder", lambda: str(legacy))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(("information", args[2])))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(("warning", args[2])))
    return SimpleNamespace(path=str(folder), shown=shown)


def click(monkeypatch, text: str):
    """Next message box answered with button of given text"""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == text))


def test_pending_only_after_copy(config_folder):
    assert not si.import_pending()  # no migration state: never asked
    fm.write_state(config_folder.path, fm.STATE_PENDING)
    assert si.import_pending()
    fm.write_state(config_folder.path, fm.STATE_KEPT)
    assert not si.import_pending()


def test_keep_imported_settings(config_folder, monkeypatch):
    fm.write_state(config_folder.path, fm.STATE_PENDING)
    click(monkeypatch, "Keep Imported Settings")
    window = Window()
    si.ask_imported_settings(window)
    assert fm.read_state(config_folder.path)["state"] == fm.STATE_KEPT
    assert window.restarts == 0


def test_use_default_settings(config_folder, monkeypatch):
    fm.write_state(config_folder.path, fm.STATE_PENDING)
    click(monkeypatch, "Use Default Settings")
    window = Window()
    si.ask_imported_settings(window)
    assert fm.read_state(config_folder.path)["state"] == fm.STATE_RESET  # applied before loading, next start
    assert window.restarts == 1


def test_menu_import_again(config_folder, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window = Window()
    si.confirm_change(window, fm.STATE_REIMPORT)
    assert fm.read_state(config_folder.path)["state"] == fm.STATE_REIMPORT
    assert window.restarts == 1


def test_menu_cancelled(config_folder, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    window = Window()
    si.confirm_change(window, fm.STATE_RESET)
    assert fm.read_state(config_folder.path) == {}
    assert window.restarts == 0


def test_import_again_without_tinypedal(config_folder, monkeypatch, tmp_path):
    monkeypatch.setattr(fm, "legacy_config_folder", lambda: str(tmp_path / "missing"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window = Window()
    si.confirm_change(window, fm.STATE_REIMPORT)
    assert window.restarts == 0 and config_folder.shown[0][0] == "warning"
    assert not si.legacy_folder_found()


def test_first_launch_asks_then_wizard(ui_env, config_folder, monkeypatch):
    from tinypedal import safe_mode
    from tinypedal.ui.app import AppWindow

    asked = []
    monkeypatch.setattr(si, "ask_imported_settings", lambda parent: asked.append(parent))
    monkeypatch.setitem(cfg.application, "show_setup_wizard_at_startup", True)
    window = Window()
    fm.write_state(config_folder.path, fm.STATE_PENDING)
    AppWindow.first_launch_steps(window)  # type: ignore[arg-type]
    assert asked == [window] and window.wizard == 1
    monkeypatch.setattr(safe_mode.state, "enabled", True)
    AppWindow.first_launch_steps(window)  # type: ignore[arg-type]
    assert len(asked) == 1  # safe mode: not asked (user fixes settings)
    monkeypatch.setattr(safe_mode.state, "enabled", False)
    monkeypatch.setitem(cfg.application, "show_setup_wizard_at_startup", False)
    fm.write_state(config_folder.path, fm.STATE_KEPT)
    AppWindow.first_launch_steps(window)  # type: ignore[arg-type]
    assert len(asked) == 1 and window.wizard == 2


def test_config_menu_entries(config_folder, monkeypatch):
    from tinypedal.ui.menu import ConfigMenu

    window = Window()
    menu = ConfigMenu("Config", window)
    submenu = next(action.menu() for action in menu.actions() if action.text() == "TinyPedal Settings")
    texts = [action.text() for action in submenu.actions()]
    assert texts == ["Import Again from TinyPedal...", "Start with Default Settings..."]
    menu.refresh_tinypedal_settings()
    assert menu.import_again.isEnabled()
    changes = []
    monkeypatch.setattr(si, "confirm_change", lambda parent, state: changes.append((parent, state)))
    submenu.actions()[1].trigger()
    assert changes == [(window, fm.STATE_RESET)]
