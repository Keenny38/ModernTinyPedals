"""Stream & local servers resource use: capture timer only while a source watches, layout source with one canvas per
overlay, director graphics without hidden animations or moving filters, servers stopped off the GUI thread,
remote control stream sending unchanged telemetry only as keep-alive"""

import json
import shutil
import subprocess
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import command_server, stream_director, stream_overlay
from neopedal.command_server import CommandHandler, LocalHTTPServer
from neopedal.stream_overlay import FrameStore, OverlayCapture
from tests.test_command_server import ws_connect, ws_read


def test_capture_timer_runs_only_while_watched(ui_env):
    store = FrameStore()
    capture = OverlayCapture(store)
    store.on_watch = capture.wake.emit
    try:
        capture.start(30)
        assert capture.running and not capture.capturing  # nobody watching: no timer
        store.touch("layout")  # frames request (same thread: woken at once)
        assert capture.capturing
        seen = []
        store.on_watch = lambda: seen.append(1) or capture.wake.emit()
        store.touch("layout")  # still watched: no wake
        assert not seen
        store._requests["layout"] -= stream_overlay.WATCH_SECONDS + 1  # source gone
        capture.capture()
        assert not capture.capturing and capture.running
        thread = threading.Thread(target=store.touch, args=("gear",))  # server thread: queued wake
        thread.start()
        thread.join()
        QCoreApplication.processEvents()
        assert seen and capture.capturing
        capture.stop()
        store.touch("other")
        QCoreApplication.processEvents()
        assert not capture.capturing  # stopped (overlays reloading): never woken
    finally:
        capture.stop()


def script_of(page: str) -> str:
    return page.split("<script>", 1)[1].split("</script>", 1)[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("page", ["source", "director"])
def test_page_scripts_parse(page, tmp_path):
    if page == "source":
        html = stream_overlay.SOURCE_HTML.replace("@@view@@", '"layout"').replace("@@labels@@", "{}")
    else:
        html = stream_director.director_html("en", "Director")
    path = tmp_path / "page.js"
    path.write_text(script_of(html), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_layout_source_one_canvas_per_overlay():
    script = script_of(stream_overlay.SOURCE_HTML)
    assert "function drawLayout()" in script and "if(layout){drawLayout();return}" in script
    assert "#layers{position:absolute" in stream_overlay.SOURCE_HTML


def test_director_no_hidden_animation_nor_moving_filter():
    html = stream_director.director_html("en", "Director")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "#replay.show i{animation:blink" in css and "#replay i{" in css
    assert "animation" not in css.split("#replay i{", 1)[1].split("}", 1)[0]  # no blink while hidden
    map_rule = css.split("#map{", 1)[1].split("}", 1)[0]
    assert "filter" not in map_rule  # cars moving never blur the map again
    assert 'filter="url(#mapGlow)"' in html and 'id="mapShade"' in html


def test_server_stop_never_waits_for_serving_loop():
    server = LocalHTTPServer(("127.0.0.1", 0), CommandHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    start = time.monotonic()
    server.stop()
    assert time.monotonic() - start < 0.1 and server.stopping.is_set()
    # Same port again at once: waits for the previous socket to close (no "port unavailable")
    again = LocalHTTPServer(("127.0.0.1", port), CommandHandler)
    assert server.closed.is_set()
    again.server_close()
    assert command_server.wait_servers_stopped()
    thread.join(2)
    assert not thread.is_alive()


def test_stream_unchanged_data_sent_as_keepalive_only(monkeypatch):
    data = {"tick": 1}
    monkeypatch.setattr(CommandHandler, "snapshot", staticmethod(lambda: dict(data)))
    monkeypatch.setattr(command_server, "STREAM_KEEPALIVE", 0.4)
    server = LocalHTTPServer(("127.0.0.1", 0), CommandHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sock, _, _ = ws_connect("/stream?interval=20", port=port)
        with sock:
            assert json.loads(ws_read(sock)[1]) == {"tick": 1}
            start = time.monotonic()
            assert json.loads(ws_read(sock)[1]) == {"tick": 1}  # same data: only after the keep-alive delay
            assert time.monotonic() - start >= 0.3
            data["tick"] = 2
            start = time.monotonic()
            assert json.loads(ws_read(sock)[1]) == {"tick": 2}  # changed: next interval
            assert time.monotonic() - start < 0.3
    finally:
        server.stop(wait=True)
