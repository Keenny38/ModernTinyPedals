"""Bug report tests"""

import json
import os
import zipfile

from tinypedal.bug_report import create_bug_report, redact_setting, redact_text
from tinypedal.setting import cfg


def test_redact():
    home = os.path.expanduser("~")
    assert home not in redact_text(f"path {home}/TinyPedal")
    data = redact_setting({"web_dashboard": {"access_code": "SECRET12"}, "application": {"update_repository": "me/fork"}})
    assert data["web_dashboard"]["access_code"] == "<removed>"
    assert data["application"]["update_repository"] == "<removed>"
    data = redact_setting({"stream_overlay": {"access_token": "TOKEN123", "port": 1}})
    assert data["stream_overlay"] == {"access_token": "<removed>", "port": 1}


def test_create_report(ui_env, tmp_path):
    cfg.user.config["web_dashboard"]["access_code"] = "SECRET12"
    log_folder = cfg.path.config
    with open(f"{log_folder}tinypedal.log", "w", encoding="utf-8") as file:
        file.write(f"INFO start from {os.path.expanduser('~')}\n")
    zip_file = tmp_path / "report.zip"
    files = create_bug_report(str(zip_file), "session log line", "widget froze")
    assert {"system-info.txt", "description.txt", "logs/session.log", "logs/tinypedal.log", "settings/config.json"} <= set(files)
    with zipfile.ZipFile(zip_file) as package:
        config = json.loads(package.read("settings/config.json"))
        assert config["web_dashboard"]["access_code"] == "<removed>"
        assert os.path.expanduser("~") not in package.read("logs/tinypedal.log").decode()
        assert "Modern Tiny Pedals" in package.read("system-info.txt").decode()


def test_process_monitor():
    import threading
    import time

    from tinypedal.perf_monitor import ProcessMonitor

    stop = threading.Event()

    def busy():
        while not stop.is_set():
            sum(range(1000))

    worker = threading.Thread(target=busy, name="module:module_test", daemon=True)
    worker.start()
    monitor = ProcessMonitor()
    time.sleep(0.3)
    process, threads = monitor.sample()
    stop.set()
    worker.join()
    assert process.memory_mb > 10 and process.threads >= 2
    busy_thread = next(item for item in threads if item.name == "Module test")
    assert busy_thread.cpu_percent > 5  # low bar: shared CI runners give a busy thread far less than a core


def test_perf_view(ui_env):
    from tinypedal.ui.perf_view import PerformanceView

    view = PerformanceView(None)
    assert view.table_threads.rowCount() >= 1
    assert "MB" in view.label_process.text()
    close_view(view)


def close_view(view):
    """Close & delete view: singleton window type freed for next test"""
    from PySide6.QtCore import QCoreApplication, QEvent

    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_perf_view_game_data(ui_env, monkeypatch):
    """Connector health: shared memory update age & Rest API resource status"""
    from tinypedal.adapter.restapi_connector import EndpointStatus
    from tinypedal.api_connector import ConnectorHealth
    from tinypedal.ui import perf_view

    view = perf_view.PerformanceView(None)
    try:
        assert view.table_rest.rowCount() > 0  # LMU resources, not on track
        assert view.table_rest.item(0, 1).text() == "Not on track"
        health = ConnectorHealth(0.3, False, False, "", (
            EndpointStatus("/rest/chat/", "active", "parser error", 1.0),
            EndpointStatus("/rest/sessions", "missing", "no data", 0.0),
        ))
        monkeypatch.setattr(perf_view, "connection_health", lambda: health)
        view.refresh_connection()
        assert view.label_connection.text() == "Shared memory: last update 0.3 s ago"
        assert [view.table_rest.item(row, 1).text() for row in range(2)] == ["Receiving data", "No data yet"]
        assert view.table_rest.item(0, 3).text() == "Unreadable data" and view.table_rest.item(1, 2).text() == "-"
        for state, text in (
            (health._replace(error="denied"), "Shared memory unavailable: denied"),
            (health._replace(paused=True, data_age=12.0), "Shared memory: paused, last update 12.0 s ago"),
            (health._replace(data_age=-1.0), "Shared memory: no data yet"),
            (None, "API not connected"),
        ):
            monkeypatch.setattr(perf_view, "connection_health", lambda state=state: state)
            assert perf_view.shared_memory_status() == text
    finally:
        close_view(view)
