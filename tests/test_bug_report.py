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
        assert "TinyPedal" in package.read("system-info.txt").decode()


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
    assert busy_thread.cpu_percent > 20


def test_perf_view(ui_env):
    from tinypedal.ui.perf_view import PerformanceView

    view = PerformanceView(None)
    assert view.table_threads.rowCount() >= 1
    assert "MB" in view.label_process.text()
    view.close()
