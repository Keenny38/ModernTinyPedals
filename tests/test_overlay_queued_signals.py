"""Overlay stopped while a signal of the overlay control thread was queued: delivered before the widget is
deleted (deferred), ignored instead of raising on the unloaded widget"""

from importlib import import_module


def test_overlay_signals_after_stop(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern import create_widget

    widget = create_widget(import_module("neopedal.widget.track_map"), cfg, "track_map")
    widget.start()
    # Deletion deferred: widget alive, resources unloaded. Assigned, never monkeypatched: stop() clears the
    # instance dict, so the undo of pytest (delattr since pytest 9.2) would raise and leave every other patch
    # of the test in place (ui_env's Setting.save & find_results_folders stayed patched for the whole CI run)
    widget.close = lambda: True  # type: ignore[method-assign]
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
    widget.deleteLater()
