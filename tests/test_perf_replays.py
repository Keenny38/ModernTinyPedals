"""Game Replays page: folder info made once per change (not per read), copy progress on its own signal,
incidents / standings / laps signals emitted only when what they tell changed, timeline markers cached"""

import pytest

from tests.test_game_info import GAME_ANSWERS, answered, replays_page, wait_requests  # noqa: F401


def counter(signal) -> list:
    calls: list = []
    signal.connect(lambda *args: calls.append(True))
    return calls


def test_folder_info_cached_and_copy_progress_signal(replays_page, monkeypatch, tmp_path):  # noqa: F811
    from tinypedal.ui.quick import replays_backend

    backend = answered(replays_page, GAME_ANSWERS)
    sizes = []
    file_size = replays_backend.file_size
    monkeypatch.setattr(replays_backend, "file_size", lambda path: sizes.append(path) or file_size(path))
    backend.temp = [str(tmp_path / "a.tmp"), str(tmp_path / "b.tmp")]
    first = backend.folderInfo
    assert first["temp"] == 2 and len(sizes) == 2
    for _ in range(6):  # read by several bindings
        assert backend.folderInfo == first
    assert len(sizes) == 2  # temporary files sized once
    backend.toggleProtected(backend.replayRows.rows[0]["key"])
    assert backend.folderInfo["protected"] == 1 and len(sizes) == 4  # protected replays changed: made again
    files, progress = counter(backend.filesChanged), counter(backend.copyProgressChanged)
    backend.set_copy_progress(0.25)
    backend.set_copy_progress(0.25)  # same value: nothing told
    assert progress == [True] and not files and backend.copyProgress == 0.25
    backend.update_files()
    assert files and backend.folderInfo["temp"] == 0


def test_signals_only_when_changed(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    incidents = counter(backend.incidentsChanged)
    standings = counter(backend.standingsChanged)
    laps = counter(backend.lapsChanged)
    backend.update_incidents()
    backend.update_standings()
    backend.record_laps()
    assert not incidents and not standings and not laps  # nothing changed
    backend.setIncidentFilter(2)  # walls only
    assert incidents and backend.counts["shown"] == 1
    incidents.clear()
    backend.update_incidents()
    assert not incidents
    backend.setClassFilter(backend.classes[0]["name"])
    assert standings
    standings.clear()
    backend.update_standings()
    assert not standings


def test_timeline_markers_cached(replays_page):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    first = backend.timeline
    assert len(first["markers"]) == 2 and first["end"] == pytest.approx(3600.0)
    assert backend.timeline["markers"] is first["markers"]  # not made again per read
    backend.setIncidentFilter(2)  # incident rows changed: shown flags made again
    markers = backend.timeline["markers"]
    assert markers is not first["markers"] and [marker["shown"] for marker in markers].count(True) == 1
    backend.setIncidentFilter(0)
    assert all(marker["shown"] for marker in backend.timeline["markers"])
