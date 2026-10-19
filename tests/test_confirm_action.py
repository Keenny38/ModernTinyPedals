"""Confirmation boxes: Cancel then the named action on every platform (same order as QML TpConfirmDialog),
Esc cancels, Cancel focused unless the action is harmless; a replaced QMessageBox.question answers instead"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox


def buttons_in_order(box: QMessageBox) -> list[str]:
    """Button texts left to right, as laid out"""
    button_box = box.findChild(QDialogButtonBox)
    buttons = [button for button in button_box.buttons() if button.isVisible()]
    return [button.text() for button in sorted(buttons, key=lambda button: button.mapTo(box, button.rect().topLeft()).x())]


def test_cancel_first_then_action(ui_env):
    from neopedal.ui._common import confirm_box

    box, action = confirm_box(None, "Delete Preset", "Delete <b>x</b>?", "Delete", danger=True)
    try:
        box.show()
        QApplication.processEvents()
        assert buttons_in_order(box) == ["Cancel", "Delete"]
        assert box.escapeButton().text() == "Cancel" and box.defaultButton().text() == "Cancel"
        assert action.text() == "Delete" and box.icon() == QMessageBox.Icon.Warning
    finally:
        box.close()
    box, _action = confirm_box(None, "Install", "Install now?", "Install Now", cancel_text="Later", default_action=True)
    try:
        box.show()
        QApplication.processEvents()
        assert buttons_in_order(box) == ["Later", "Install Now"] and box.defaultButton().text() == "Install Now"
    finally:
        box.close()


def test_answer_from_box_clicks(ui_env):
    from neopedal.ui import _common

    def click(name):
        def press():
            box = QApplication.activeModalWidget()
            assert isinstance(box, QMessageBox)
            next(button for button in box.buttons() if button.text() == name).click()
        return press

    QTimer.singleShot(50, click("Reset"))
    assert _common.confirm_action(None, "Reset", "Reset?", "Reset") is True
    QTimer.singleShot(50, click("Cancel"))
    assert _common.confirm_action(None, "Reset", "Reset?", "Reset") is False


def test_replaced_question_answers(ui_env, monkeypatch):
    """Tests & scripted runs that replace QMessageBox.question keep driving every confirmation"""
    from neopedal.ui import _common

    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: asked.append(args[1:3]) or QMessageBox.StandardButton.Yes))
    assert _common.confirm_action(None, "Title", "Text", "Do it") is True
    assert asked == [("Title", "Text")]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No))
    assert _common.confirm_action(None, "Title", "Text", "Do it") is False
