"""Audit fixes: driver stats laps read debounced & stale reads ignored, lap reference cache not written, lap viewer
lap infos read in background, damaged track limits cache, circuit shapes cache trimmed by several jobs, replay
temporary files removed while sized"""

import json
import os
import threading

from tests.test_driver_stats_e2 import OREGA, SPA, stats_page, wait_stints  # noqa: F401
from tests.test_driver_stats_viewer import SHEET
from tests.test_lap_viewer_e2 import START, TRACK
from tests.test_lap_viewer_fix_backend import backend, write_other_track  # noqa: F401


# --- 40. Recorded laps of selected vehicle read once selection settles, older reads never overwrite newer ones
def test_stints_read_debounced_and_stale_read_ignored(stats_page, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick import stats_backend

    calls: list[str] = []
    real = stats_backend.read_laps
    def counted(path, *args):
        calls.append(path)
        return real(path, *args)

    monkeypatch.setattr(stats_backend, "read_laps", counted)
    stats_page.selectTrack(SPA)
    stats_page.selectRow(OREGA)
    for _ in range(5):  # selection changing quickly (arrow keys)
        stats_page._laps_key = ""
        stats_page.update_stints()
    assert stats_page.laps_timer.isActive() and not calls and stats_page.stints["busy"]
    wait_stints(stats_page)
    assert len(calls) == 1 and stats_page.stints["note"] == ""
    shown = stats_page.stints
    key, generation = stats_page._laps_key, stats_page._laps_generation
    stats_page.stints_loaded(key, generation - 1, None)  # older read of same laps finishing late: ignored
    assert stats_page.stints == shown
    stats_page.stints_loaded(key, generation, None)
    assert "Unable" in stats_page.stints["note"]


def test_stints_read_one_at_a_time(stats_page):  # noqa: F811
    stats_page.selectTrack(SPA)
    stats_page.selectRow(OREGA)
    stats_page.laps_timer.stop()
    stats_page._laps_running = 99  # a read still running: next one waits for it
    stats_page.start_laps_read()
    assert stats_page._laps_job is not None and stats_page.stints["busy"]
    stats_page.stints_loaded("other", 99, None)  # running read done (not shown): waiting read started
    assert stats_page._laps_job is None
    wait_stints(stats_page)
    assert stats_page.stints["note"] == ""


def test_reference_kept_when_cache_not_written(stats_page, monkeypatch):  # noqa: F811
    from tinypedal.userfile import lap_reference

    def failing(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(lap_reference, "save_cache", failing)
    stats_page.reference_downloaded(SHEET, "")
    assert stats_page.references.entries and not stats_page._downloading


# --- 41. Lap infos of a track with many new lap files read in background, stale reads ignored
def test_track_infos_read_in_background(backend, monkeypatch):  # noqa: F811
    from tinypedal.setting import cfg
    from tinypedal.ui.quick import lap_backend

    monkeypatch.setattr(lap_backend, "INFO_BACKGROUND", 1)
    folder = cfg.path.telemetry.rstrip("/")
    other = "Other - GT3"
    for number in range(1, 4):
        write_other_track(folder, other, number, 95.0 + number, START + 1000 + number * 100)
    backend.refresh()
    backend.currentTrack = other
    assert backend.currentTrack == TRACK and backend.status == "Reading laps..."  # shown track kept meanwhile
    backend.currentTrack = TRACK  # picked back before read: read result ignored
    backend.wait_jobs()
    assert backend.currentTrack == TRACK and len(backend.entries) == 3
    backend.currentTrack = other
    backend.wait_jobs()
    assert backend.currentTrack == other and len(backend.entries) == 3 and backend.status != "Reading laps..."
    assert all(entry.info for entry in backend.entries)


# --- 42d. Track limits cache that is not a JSON object computed again
def test_damaged_limits_cache_ignored(backend):  # noqa: F811
    cache = backend.limits_cache_path(TRACK)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as file:
        json.dump(["not", "a", "dict"], file)
    backend._limits_track = ""
    backend._limits_job = None
    backend.start_limits(TRACK)
    assert backend._limits_job is not None  # computed again


# --- 42a. Circuit shapes cache filled & trimmed by several map jobs at once
def test_circuit_shapes_trimmed_from_threads(backend):  # noqa: F811
    from tinypedal.ui.quick import lap_map_view

    errors: list[BaseException] = []

    def scales(offset: int):
        try:
            for step in range(40):
                backend.scale_shapes(0.5 + (offset * 40 + step) * 0.01)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=scales, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(backend._circuit_shapes) <= lap_map_view.BAND_CACHE_STEPS * 2


# --- 42c. Temporary replay files removed while sized
def test_temp_size_of_removed_files(tmp_path):
    from types import SimpleNamespace

    from tinypedal.ui.quick import replays_backend

    kept = tmp_path / "a.tmp"
    kept.write_bytes(b"x" * 2048)
    assert replays_backend.file_size(str(tmp_path / "gone.tmp")) == 0
    page = SimpleNamespace(temp=[str(kept), str(tmp_path / "gone.tmp")])
    assert replays_backend.GameReplaysBackend.temp_size(page) == replays_backend.size_text(2048)  # type: ignore[arg-type]
