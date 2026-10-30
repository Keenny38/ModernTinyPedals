#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Dialogs & toasts of page backends, shown inside their QML page

A page backend asks for a text, a number, a confirmation or shows an alert / toast with the functions below, giving
the widget hosting its page (self._window...). When that page is a shown QML page holding a TpDialogHost item, the
request is a TpDialog / TpToast inside the page (no window over the app, no page replaced by a text input). Otherwise
the widget dialogs of before answer: TextInputDialog, QInputDialog (numbers), _common.confirm_action, QMessageBox,
ui/toast.

Answers come back by callback (the page keeps running while asked): ask_text(..., on_accept) as TextInputDialog
(on_accept(text) returns True to close, False keeps the input open: refused name), ask_number(..., on_accept)
on_accept(number) once closed, confirm(..., on_result) on_result(bool), alert(..., on_closed) on_closed().
Number, confirmation & alert callbacks run after the dialog closed (queued: a callback may close the page or ask
again). Pending requests of a page closed or hidden are cancelled (on_result(False), on_accept never called).

Tests & scripts: when QMessageBox.question / warning / information / critical, the host's confirm_operation,
TextInputDialog.show / open or QInputDialog.getInt / getDouble are replaced (monkeypatch), the replacement answers as
before, never the QML page.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from PySide6 import QtGui
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget
from shiboken6 import isValid

from ...i18n import tr
from .. import message_text, safe_markup

logger = logging.getLogger(__name__)

LEVELS = ("success", "info", "warning", "error")  # toast & alert levels (TpToast level)
# Number inputs of before (no page host): replaced from outside (tests, scripts), the replacement answers
NUMBER_DIALOGS = {name: QInputDialog.__dict__.get(name) for name in ("getInt", "getDouble")}


@dataclass
class DialogRequest:
    """One dialog asked by a backend: kind "text", "confirm" or "alert", what TpDialogHost shows (payload)"""
    request_id: int
    kind: str
    payload: dict[str, Any]
    on_accept: Callable[[Any], object] | None = None  # text: True closes, number: number chosen (once closed)
    on_result: Callable[[bool], object] | None = None  # confirm: chosen or not, alert: closed (True)
    extra: dict[str, Any] = field(default_factory=dict)

    def shown(self) -> dict[str, Any]:
        """Values of TpDialogHost (QML object)"""
        return {"id": self.request_id, "kind": self.kind, **self.payload}


class DialogBridge(QObject):
    """Requests of one QML page (context property "dialogs" of every page): its TpDialogHost item shows them one at
    a time, in order, and answers through answer(). Toasts go to the host's TpToast (toastRequested)."""

    currentChanged = Signal()
    hostChanged = Signal()
    toastRequested = Signal(str, str, int, str)  # text (safe markup), level, duration (ms, 0: from length), action

    def __init__(self, view: QWidget):
        super().__init__(view)
        self._view = view
        self._hosts = 0
        self._serial = 0
        self._queue: list[DialogRequest] = []
        self._toast_action: Callable[[], object] | None = None

    # Host item of the page
    @Slot()
    def attach(self):
        """TpDialogHost made: requests of the page shown in it"""
        self._hosts += 1
        if self._hosts == 1:
            self.hostChanged.emit()

    @Slot()
    def detach(self):
        """TpDialogHost gone (page unloaded): pending requests cancelled"""
        self._hosts = max(0, self._hosts - 1)
        if not self._hosts:
            self.cancel_all()
            self._toast_action = None
            self.hostChanged.emit()

    @Property(bool, notify=hostChanged)
    def attached(self) -> bool:
        return self._hosts > 0

    def usable(self) -> bool:
        """A host shows requests now: attached, page on screen"""
        view = self._view
        return self._hosts > 0 and isValid(view) and view.isVisible()

    # Dialogs
    @Property(dict, notify=currentChanged)
    def current(self) -> dict[str, Any]:
        """Request shown now ({"id": 0} when none)"""
        return self._queue[0].shown() if self._queue else {"id": 0}

    @property
    def pending(self) -> int:
        return len(self._queue)

    def request(self, kind: str, payload: dict[str, Any], on_accept: Callable[[str], object] | None = None,
                on_result: Callable[[bool], object] | None = None) -> int:
        """Ask the page (queued behind the one shown), id of the request"""
        self._serial += 1
        self._queue.append(DialogRequest(self._serial, kind, payload, on_accept, on_result))
        if len(self._queue) == 1:
            self.currentChanged.emit()
        return self._serial

    def _pop(self, request: DialogRequest):
        if self._queue and self._queue[0] is request:
            self._queue.pop(0)
            self.currentChanged.emit()

    @Slot(int, bool, str, result=bool)
    def answer(self, request_id: int, accepted: bool, value: str = "") -> bool:
        """Answer of TpDialogHost: True when the dialog closes (a text refused by on_accept keeps it open)"""
        if not self._queue or self._queue[0].request_id != request_id:
            return True  # answered or cancelled already
        request = self._queue[0]
        if request.kind == "text":
            if accepted and request.on_accept is not None and not request.on_accept(value):
                return False  # refused (name taken...): input kept, on_accept told why
            self._pop(request)
            return True
        if request.kind == "number":
            number = parse_number(value, request.payload) if accepted else None
            if accepted and number is None:
                return False  # not a number: input kept to correct
            self._pop(request)
            if number is not None and request.on_accept is not None:  # queued: it may ask again (confirm)
                self._deliver(request.on_accept, number)
            return True
        self._pop(request)
        if request.on_result is not None:  # after the dialog closed: the callback may close the page
            if request.kind == "confirm":
                self._deliver(request.on_result, accepted)
            else:
                self._deliver(request.on_result)  # alert: on_closed() without argument
        return True

    def _deliver(self, callback: Callable[..., object], *args):
        """Callback run once the QML handler is done (queued), skipped if the page (its view) was deleted
        meanwhile (Esc right after Enter, page closed, language changed): a lambda or partial given as callback
        would otherwise run on a released backend"""
        QTimer.singleShot(0, partial(_call_alive_in, self._view, callback, *args))

    def cancel_all(self):
        """Every pending request dropped: confirmations answered False, text inputs never accepted"""
        queue, self._queue = self._queue, []
        if queue:
            self.currentChanged.emit()
        for request in queue:
            if request.kind == "confirm" and request.on_result is not None:
                QTimer.singleShot(0, partial(_call_alive, request.on_result, False))

    # Toasts
    def show_toast(self, text: str, level: str = "success", duration: int = 0, action_text: str = "",
                   action: Callable[[], object] | None = None):
        """Toast of the page (replaces the shown one), text with <b>, <i>, <br> (safe_markup)"""
        self._toast_action = action if action_text and action is not None else None
        self.toastRequested.emit(safe_markup(text), level if level in LEVELS else "success", max(0, int(duration)),
                                 action_text if self._toast_action is not None else "")

    @Slot()
    def toastAction(self):
        """Action button of the toast clicked: runs once (queued: the toast is hidden first)"""
        action, self._toast_action = self._toast_action, None
        if action is not None:
            QTimer.singleShot(0, partial(_call_alive, action))


def parse_number(text: str, payload: dict[str, Any]) -> int | float | None:
    """Number typed in a number input (decimal comma or point, spaces), put back in its range, int without decimals;
    None if not a number"""
    try:
        number = float("".join(str(text).split()).replace(",", "."))  # any space (no-break: thousands)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):  # nan, inf
        return None
    number = min(max(number, float(payload["minimum"])), float(payload["maximum"]))
    decimals = int(payload.get("decimals", 0))
    return round(number, decimals) if decimals > 0 else round(number)


def callback_owner(callback: Callable[..., object]) -> object:
    """Object a bound method belongs to, through functools.partial layers (partial(backend.method, ...)), None
    for a function or lambda"""
    while isinstance(callback, partial):
        callback = callback.func
    return getattr(callback, "__self__", None)


def _call_alive(callback: Callable[..., object], *args):
    """Callback of an object deleted meanwhile (page closed) skipped"""
    owner = callback_owner(callback)
    if isinstance(owner, QObject) and not isValid(owner):
        return
    callback(*args)


def _call_alive_in(view: QWidget, callback: Callable[..., object], *args):
    """Callback of a page skipped once its view is deleted (see DialogBridge._deliver), else as _call_alive"""
    if not isValid(view):
        return
    _call_alive(callback, *args)


# Finding the page of a widget
def page_bridge(widget: QWidget | None, window_wide: bool = False) -> DialogBridge | None:
    """Bridge of the shown QML page with a TpDialogHost: widget's own page (the widget, the dialog hosting the
    page...), else with window_wide (toasts) the shown QML page of widget's window. None: widget dialogs answer."""
    if widget is None or not isValid(widget):
        return None
    for bridge in widget.findChildren(DialogBridge):  # the view itself, the page dialog holding it
        if bridge.usable():
            return bridge
    if window_wide:
        for bridge in widget.window().findChildren(DialogBridge):
            if bridge.usable():
                return bridge
    return None


def _replaced(current: object, original: object) -> bool:
    """Method replaced from outside the app (test monkeypatch, script): it answers instead of the QML page"""
    if current is None or current is original:
        return False
    function = getattr(current, "__func__", current)  # bound method of a host
    if function is original:
        return False
    return not str(getattr(function, "__module__", "") or "").startswith("neopedal.")


def _message(text: str) -> tuple[str, bool]:
    """(text, rich) of a message: markup kept to safe_markup when Qt would read it as rich text (as message boxes)"""
    rich = bool(QtGui.Qt.mightBeRichText(text))
    return (safe_markup(text) if rich else text), rich


def _originals() -> dict[str, object]:
    from .._common import ORIGINAL_DIALOG_METHODS

    return ORIGINAL_DIALOG_METHODS


# Requests
def ask_text(parent: QWidget | None, title: str, label: str, on_accept: Callable[[str], bool], text: str = "",
             multiline: bool = False, placeholder: str = "", accept_text: str = "") -> None:
    """Text input (translated title & label, label may hold <b> of escaped names), on_accept(text) returns True
    to close (False: refused, input kept). In the QML page, else TextInputDialog (small window over the page)."""
    from .. import _common

    originals = _originals()
    dialog_class = _common.TextInputDialog
    patched = (_replaced(dialog_class.show, originals["text_input_show"])
               or _replaced(dialog_class.open, originals["text_input_open"]))
    bridge = None if patched else page_bridge(parent)
    if bridge is None:
        dialog = dialog_class(parent, title, label, on_accept, text, multiline)
        if _replaced(dialog_class.open, originals["text_input_open"]):
            dialog.open()  # replaced open answers (tests, scripts), as the page called before
        else:
            dialog.show()
        return
    bridge.request("text", {
        "title": title, "text": safe_markup(label), "rich": True, "value": text, "multiline": bool(multiline),
        "placeholder": placeholder, "acceptText": accept_text or tr("OK"), "cancelText": tr("Cancel"),
        "danger": False, "level": "",
    }, on_accept=on_accept)


def ask_number(parent: QWidget | None, title: str, label: str, on_accept: Callable[[Any], object], value: float,
               minimum: float, maximum: float, decimals: int = 0, step: float = 1, suffix: str = "",
               accept_text: str = "") -> None:
    """Number input (translated title & label, label may hold <b> of escaped names), on_accept(number) once
    accepted: int without decimals, put back in [minimum, maximum]; never called when cancelled. In the QML page
    (NumberField: Up / Down step, decimal comma), else QInputDialog.getInt / getDouble (answer at once)."""
    decimals = max(0, int(decimals))
    getter = "getDouble" if decimals else "getInt"
    patched = _replaced(QInputDialog.__dict__.get(getter), NUMBER_DIALOGS[getter])
    bridge = None if patched else page_bridge(parent)
    if bridge is None:
        if decimals:
            number, accepted = QInputDialog.getDouble(parent, title, message_text(label), float(value),
                                                      float(minimum), float(maximum), decimals)
        else:
            number, accepted = QInputDialog.getInt(parent, title, message_text(label), int(value),
                                                   int(minimum), int(maximum))
        if accepted:
            on_accept(number)
        return
    bridge.request("number", {
        "title": title, "text": safe_markup(label), "rich": True, "value": value, "multiline": False,
        "placeholder": "", "acceptText": accept_text or tr("OK"), "cancelText": tr("Cancel"),
        "danger": False, "level": "", "minimum": minimum, "maximum": maximum, "decimals": decimals,
        "step": step, "suffix": suffix,
    }, on_accept=on_accept)


def confirm(parent: QWidget | None, title: str, text: str, action_text: str, on_result: Callable[[bool], object],
            danger: bool = False, cancel_text: str = "") -> None:
    """Confirmation (translated texts, text may hold <b> of escaped names): Cancel, then the action button named
    after the action; on_result(True) when the action was chosen. In the QML page, else the host's
    confirm_operation (a page dialog) or _common.confirm_action."""
    from .. import _common

    originals = _originals()
    host_confirm = getattr(parent, "confirm_operation", None)
    patched = (_replaced(QMessageBox.__dict__.get("question"), originals["question"])
               or (host_confirm is not None and _replaced(host_confirm, originals["confirm_operation"])))
    bridge = None if patched else page_bridge(parent)
    if bridge is None:
        if host_confirm is not None and _replaced(host_confirm, originals["confirm_operation"]):
            chosen = bool(host_confirm(title, text, action_text))
        else:
            chosen = _common.confirm_action(parent, title, text, action_text, cancel_text, danger)
        on_result(chosen)
        return
    shown, rich = _message(text)
    bridge.request("confirm", {
        "title": title, "text": shown, "rich": rich, "value": "", "multiline": False,
        "placeholder": "", "acceptText": action_text, "cancelText": cancel_text or tr("Cancel"), "danger": bool(danger),
        "level": "warning" if danger else "",
    }, on_result=on_result)


def alert(parent: QWidget | None, title: str, text: str, level: str = "warning",
          on_closed: Callable[[], object] | None = None) -> None:
    """Message with one button (translated texts): level "info", "warning" or "error". In the QML page, else
    QMessageBox.information / warning / critical. on_closed() once closed."""
    kind = {"info": "information", "success": "information", "error": "critical"}.get(level, "warning")
    function = QMessageBox.__dict__.get(kind)
    bridge = None if _replaced(function, _originals()[kind]) else page_bridge(parent)
    if bridge is None:
        getattr(QMessageBox, kind)(parent, title, message_text(text))
        if on_closed is not None:
            on_closed()
        return
    shown, rich = _message(text)
    bridge.request("alert", {
        "title": title, "text": shown, "rich": rich, "value": "", "multiline": False,
        "placeholder": "", "acceptText": tr("OK"), "cancelText": "", "danger": False,
        "level": level if level in LEVELS else "warning",
    }, on_result=on_closed)  # type: ignore[arg-type]  # called without argument once closed, see answer


def page_toast(widget: QWidget | None, text: str, level: str = "success", duration: int = 0, action_text: str = "",
               action: Callable[[], object] | None = None) -> bool:
    """Toast in the shown QML page of widget's window (TpDialogHost), False when there is none (ui/toast shows a
    widget toast instead)"""
    bridge = page_bridge(widget, window_wide=True)
    if bridge is None:
        return False
    bridge.show_toast(text, level, duration, action_text, action)
    return True
