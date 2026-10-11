"""Overlay pictures on simulated race data (neopedal.demo_data): values shown, real data untouched"""

import threading

import pytest

from neopedal import demo_data
from neopedal.setting import cfg


def widget_globals() -> set[tuple[str, str, int]]:
    """api & minfo globals of loaded widget modules"""
    return {
        (module.__name__, attr, id(vars(module)[attr]))
        for module in demo_data.widget_modules()
        for attr in ("api", "minfo")
        if attr in vars(module)
    }


def test_render_reads_simulated_race_then_puts_real_data_back(ui_env, bundled_fonts):
    from neopedal import race_live
    from neopedal.api_control import api
    from neopedal.module_info import minfo
    from neopedal.ui.widget_preview import render_widget
    from neopedal.widget._modern import gear

    render_widget(cfg, "gear", dict(cfg.user.setting["gear"]))  # widget modules loaded
    before = widget_globals()
    session = demo_data.demo_session(cfg.user.setting["standings"])
    with demo_data.demo_globals(session):
        assert gear.minfo is session.minfo and gear.api is session.api
        assert session.api.read.vehicle.driver_name() == "You"
        assert race_live.api is session.api
        with demo_data.demo_globals(session):  # nested: outer session kept
            pass
        assert gear.minfo is session.minfo
    assert gear.minfo is minfo and gear.api is api
    assert widget_globals() == before
    with pytest.raises(RuntimeError), demo_data.demo_globals(session):
        raise RuntimeError
    assert widget_globals() == before
    # Data modules never pointed to simulated data
    from neopedal.module import module_relative

    assert module_relative.api is api and module_relative.minfo is minfo


def test_render_never_changes_user_presets(ui_env, bundled_fonts, monkeypatch):
    from neopedal.ui.widget_preview import render_widget

    saved = []
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: saved.append(kwargs))
    presets = {name: dict(getattr(cfg.user, name)) for name in ("brands", "brakes", "compounds", "classes")}
    for name in ("brake_temperature", "black_box", "tyre_temperature", "relative", "standings", "brake_wear"):
        assert not render_widget(cfg, name, dict(cfg.user.setting[name])).isNull()
    assert {name: dict(getattr(cfg.user, name)) for name in presets} == presets
    assert saved == []


def test_demo_state_is_per_thread():
    from neopedal.demo_state import demo_drawing, demo_reader, drawing_demo

    reader = object()
    seen = []
    with demo_drawing(reader):
        thread = threading.Thread(target=lambda: seen.append((demo_reader(), drawing_demo())))
        thread.start()
        thread.join()
        assert demo_reader() is reader and drawing_demo()
    assert seen == [(None, False)]  # data module threads keep real data
    assert demo_reader() is None


def test_simulated_lists_match_relative_module(ui_env, monkeypatch):
    """vehicles_info copies module_relative.get_vehicles_info (without its shared buffers)"""
    from neopedal.module import module_relative
    from neopedal.module_info import RelativeInfo

    session = demo_data.DemoSession(cfg.user.setting["standings"])
    monkeypatch.setattr(module_relative, "api", session.api)
    relative = RelativeInfo()
    size = len(demo_data.FIELD)
    ahead, behind, classes, order, multi = module_relative.get_vehicles_info(
        size, demo_data.PLAYER, False, False, relative.relativeDeltaAhead, relative.relativeDeltaBehind)
    assert demo_data.vehicles_info(session.api.read, size, demo_data.PLAYER) == (ahead, behind, classes, order)
    assert multi
    assert session.minfo.relative.relativeAhead == ahead and session.minfo.relative.drawOrder == order


def test_history_replays_put_state_back():
    session = demo_data.DemoSession(cfg.default.setting["standings"])
    tele = session.data.telemetry.telemInfo[demo_data.PLAYER]
    scor = session.data.scoring.vehScoringInfo[demo_data.PLAYER]
    updates = []
    before = (tele.mElapsedTime, tele.mUnfilteredThrottle, scor.mLapDist, scor.mTotalLaps,
              session.minfo.delta.deltaBest, session.minfo.force.latGForceRaw)
    demo_data.replay_history(object(), session.data, session.minfo, updates.append)
    demo_data.replay_lap(object(), session.data, session.minfo, updates.append)
    assert len(updates) == demo_data.HISTORY_FRAMES + demo_data.LAP_FRAMES + demo_data.LAP_FRAMES // 2 + 1
    assert (tele.mElapsedTime, tele.mUnfilteredThrottle, scor.mLapDist, scor.mTotalLaps,
            session.minfo.delta.deltaBest, session.minfo.force.latGForceRaw) == before
    assert demo_data.lap_delta(demo_data.PLAYER_LAPS, demo_data.LAP_DISTANCE / demo_data.TRACK_LENGTH) == (
        pytest.approx(session.minfo.delta.deltaBest))


def test_preview_zoom_steps():
    from neopedal.ui.quick.overlay_options_backend import drawn_scale, preview_zoom

    assert preview_zoom(0.4) == preview_zoom(float("nan")) == preview_zoom(1) == 1
    assert preview_zoom(1.1) == 1.25 and preview_zoom(2) == 2 and preview_zoom(9) == 3
    assert drawn_scale(1.0, 2.0) == 2.0
    assert drawn_scale(2.0, 2.0) == 1.5  # global overlay scale limited to 3
    assert drawn_scale(5.0, 2.0) == 1.0


def test_zoomed_preview_drawn_bigger(ui_env, bundled_fonts):
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend
    from neopedal.ui.quick.preview_provider import STORE, key_of
    from tests.test_overlay_options import Control, Host, flush

    backend = OverlayOptionsBackend(None, Host(), Control())
    try:
        backend.selectOverlay("speedometer")
        backend.set_active(True)
        backend.render_preview()
        width, height = backend.previewWidth, backend.previewHeight
        assert backend.previewScale == 1 and width > 0
        backend.setPreviewScale(1.03)  # fit zoom moving a little: picture kept
        assert backend._preview_signature is not None
        backend.setPreviewScale(1.9)
        backend.render_preview()
        assert backend.previewScale == 2
        assert backend.previewWidth == pytest.approx(width * 2, rel=0.15)
        assert backend.previewHeight == pytest.approx(height * 2, rel=0.15)
        image = STORE.get(key_of(backend.previewUrl.removeprefix("image://overlaypreview/")))
        assert image is not None and image.width() >= backend.previewWidth
    finally:
        backend.close()
        backend.deleteLater()
        flush()
