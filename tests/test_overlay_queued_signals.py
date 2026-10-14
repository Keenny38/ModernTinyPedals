"""Overlay stopped while a signal of the overlay control thread was queued: delivered before the widget is
deleted (deferred), ignored instead of raising on the unloaded widget"""

from importlib import import_module


def test_overlay_signals_after_stop(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.widget._modern import create_widget

    widget = create_widget(import_module("neopedal.widget.track_map"), cfg, "track_map")
    widget.start()
    monkeypatch.setattr(widget, "close", lambda: True)  # deletion deferred: widget alive, resources unloaded
    widget.stop()
    assert not widget.__dict__
    # Queued calls delivered now (was: AttributeError 'Realtime' object has no attribute 'cfg' / '_update_timer')
    widget._Base__toggle_timer(False)
    widget._Base__toggle_timer(True)
    widget._Base__set_hidden(True)
    widget._Base__context_changed()
    widget._Base__toggle_lock(True)
    widget._Base__toggle_vr_compat(True)
    widget._Base__set_editing(True)
    monkeypatch.undo()
    widget.deleteLater()
