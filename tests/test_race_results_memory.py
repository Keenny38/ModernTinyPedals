"""Race results page memory & work: session list keeps only list infos, session picked read in background (last
few kept), results released while hidden, logos fetched only tell what changed, positions lines on the GPU"""

from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_race_results import (  # noqa: F401
    RACE_NAME,
    RACE_XML,
    english,
    race,
    results_folder,
    wait_until,
    write_results,
)


def make_backend():
    from neopedal.ui.quick.results_backend import RaceResultsBackend

    backend = RaceResultsBackend()
    backend.page_shown()
    assert wait_until(lambda: backend.loaded_once)
    return backend


def drop(backend):
    backend.release()
    backend.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def race_files(folder, count):
    """Races of other days (newest last), names sorted like times"""
    names = []
    for day in range(count):
        name = f"2026_08_{day + 1:02d}_19_10_00-12R1.xml"
        write_results(folder, {name: RACE_XML.replace("1790000600", str(1780000000 + day * 86400))})
        names.append(name)
    return names


def counter(signal) -> list:
    calls: list = []
    signal.connect(lambda *args: calls.append(True))
    return calls


def test_list_keeps_infos_only(results_folder, english):  # noqa: F811
    from neopedal.process.results_file import SessionResult
    from neopedal.ui.quick.results_backend import KEPT_RESULTS, SessionInfo

    race_files(results_folder, 8)
    backend = make_backend()
    try:
        assert backend.sessionCount == 11
        infos = [info for _, info in backend.files.values() if info is not None]
        assert all(isinstance(info, SessionInfo) for info in infos)
        assert not any(isinstance(value, SessionResult) for info in infos for value in info)  # no laps, events
        assert len(backend.kept) <= KEPT_RESULTS and backend.selectedKey.endswith(RACE_NAME)
        oldest = backend.sessionModel.rows[-1]["key"]
        assert oldest not in backend.kept
        backend.select(oldest)  # not kept: read in background, list follows at once
        assert backend.selectedKey == oldest and backend.sessionHeader["title"] == "24 Heures du Mans"
        assert wait_until(lambda: backend.result is not None and backend.result.path == oldest)
        assert backend.selectedKey == oldest and oldest in backend.kept and len(backend.kept) <= KEPT_RESULTS
        assert backend.classificationModel.rowCount() == 3 and backend.eventModel.rowCount() == 5
        backend.select(backend.sessionModel.rows[0]["key"])  # kept: shown at once
        assert backend.selectedKey.endswith(RACE_NAME) and backend.result.path.endswith(RACE_NAME)
    finally:
        drop(backend)


def test_results_released_while_hidden(results_folder, english):  # noqa: F811
    backend = make_backend()
    try:
        backend.setChartView(600, 300, 1.5, 3, 4)
        from neopedal.ui.quick.lines import VertexStore

        keys = [series["thin"] for series in backend.positions["series"]]
        assert keys and all(VertexStore.has(key) for key in keys)
        backend.page_hidden()
        assert backend._release_timer.isActive()
        backend.release_results()  # hidden a while
        assert backend.result is None and not backend.kept and not VertexStore.has(keys[0])
        assert backend.hasSession and backend.classificationModel.rowCount() == 3  # rows kept while hidden
        backend.page_shown()
        assert not backend._release_timer.isActive()
        assert wait_until(lambda: backend.result is not None and not backend.loading)
        assert backend.selectedKey.endswith(RACE_NAME) and backend.selectedEntry == "0"
        assert VertexStore.has(keys[0])
    finally:
        drop(backend)
    assert not VertexStore.has(keys[0])


def test_pictures_tell_only_changes(results_folder, english, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import game_pictures
    from neopedal.userfile.game_images import images

    backend = make_backend()
    try:
        selection, classification = counter(backend.selectionChanged), counter(backend.classificationChanged)
        driver, sessions = counter(backend.driverChanged), counter(backend.sessionsChanged)
        resets = counter(backend.classificationModel.modelReset)
        backend.pictures_changed()  # nothing new
        assert not (selection or classification or driver or sessions or resets)
        monkeypatch.setattr(game_pictures, "brand_logo_url", lambda *names: "file:///logo.svg")
        monkeypatch.setattr(images, "version", images.version + 1)  # logos fetched from game
        backend.page_hidden()
        backend.pictures_changed()  # hidden: once shown
        assert backend._pictures_stale and not classification
        backend._shown = True
        backend.pictures_changed()
        assert classification and driver and not resets and not selection  # rows changed in place
        assert backend.classificationModel.rows[0]["brandLogo"] == "file:///logo.svg"
    finally:
        drop(backend)


def test_chart_lines_follow_view(results_folder, english):  # noqa: F811
    from neopedal.ui.quick.lines import VertexStore

    backend = make_backend()
    try:
        series = backend.positions["series"]
        assert series and "points" not in series[0] and series[0]["places"][0] == 2  # Alice: P2 on grid
        assert not VertexStore.has(series[0]["thin"])  # no plot size yet
        backend.setChartView(400, 200, 1.5, 3, 4)
        thin = VertexStore.get(series[0]["thin"])
        assert thin is not None and thin.vertex_count == 8  # 4 points
        serial = thin.serial
        backend.setChartView(400, 200, 1.5, 3, 4)  # same view: not built again
        assert VertexStore.get(series[0]["thin"]).serial == serial
        backend.setKindFilter(3)  # practice: no chart, lines forgotten
        assert backend.positions["series"] == [] and not VertexStore.has(series[0]["thin"])
    finally:
        drop(backend)


def test_chart_lines_in_plot_pixels(ui_env):
    from neopedal.ui.quick import results_backend as rb

    chart = rb.positions_chart(race(), "")
    lines = rb.chart_lines(chart, rb.ChartView(300, 100, 2, 4, 6))
    assert [sorted(bands) for bands in lines] == [["thick", "thin", "wide"], ["thick", "thin"], ["thick", "thin"]]
    xs = lines[0]["thin"].data[0::2]
    ys = lines[0]["thin"].data[1::2]
    assert (min(xs), max(xs)) == (0, 300)  # grid at x 0, lap 3 at plot width
    assert min(ys) == -1 and max(ys) == 51  # P1 at 0, P2 at plot height / 2 (3 places), 1 px either side
