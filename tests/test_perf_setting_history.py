"""Setting saver (queue changed within lock, event based delay) & last driven session read from end of
history file"""

import os
import threading
import time

from test_setting import config, read_json, wait_saved  # noqa: F401

from tinypedal.const_file import ConfigType
from tinypedal.userfile import driver_history
from tinypedal.userfile.driver_history import SessionRecord, last_record, read_records, record_line


# Setting saver
def test_save_delay_refreshed_and_shortened(config):  # noqa: F811
    config.load_user()
    start = time.monotonic()
    config.save(delay=500)  # ~5 s
    time.sleep(0.05)
    assert config.is_saving and config._save_queue  # waiting
    config.save(delay=0, config_type=ConfigType.CONFIG)  # shorter delay: saving thread woken
    wait_saved(config, timeout=2)
    assert time.monotonic() - start < 2
    assert os.path.exists(f"{config.path.config}config.json")
    assert os.path.exists(f"{config.path.settings}default.json")


def test_save_delay_debounced(config):  # noqa: F811
    config.load_user()
    config.save(delay=100)  # 1 s
    time.sleep(0.5)
    config.save(delay=100)  # delay refreshed
    time.sleep(0.6)
    assert config._save_queue  # not saved yet (1.1 s after first call)
    wait_saved(config)
    assert config.version_update == 1


def test_save_from_threads_while_saving(config):  # noqa: F811
    """Module threads queue files while saving thread takes them out: never "changed size during iteration\""""
    config.load_user()
    errors = []
    types = (ConfigType.SETTING, ConfigType.CONFIG, ConfigType.BRANDS, ConfigType.CLASSES, ConfigType.TRACKS)

    def saver(index):
        try:
            for count in range(60):
                config.save(delay=0, config_type=types[(index + count) % len(types)])
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=saver, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wait_saved(config)
    assert not errors and not config.is_saving and config._save_done.is_set()
    assert read_json(f"{config.path.config}config.json")


# Last driven session
def write_history(path, records, extra: bytes = b""):
    with open(driver_history.history_path(str(path)), "wb") as file:
        file.writelines(record_line(record).encode("utf-8") for record in records)
        file.write(extra)


def record(index: int, **values) -> SessionRecord:
    return SessionRecord(1_700_000_000.0 + index * 60, f"Track {index % 7}", "GT3 - BMW", 1, 100.0 + index % 9,
                         **values)


def test_last_record_matches_full_read(tmp_path):
    folder = str(tmp_path)
    assert last_record(folder) is None  # no file
    write_history(tmp_path, [record(1), record(2)])
    assert last_record(folder) == read_records(folder)[-1] == record(2)
    many = [record(index) for index in range(3000)]  # over tail size
    write_history(tmp_path, many, b'{"time": 5, "track": "half wri')
    assert os.path.getsize(driver_history.history_path(folder)) > driver_history.TAIL_BYTES
    assert last_record(folder) == read_records(folder)[-1] == many[-1]


def test_last_record_out_of_order_tail(tmp_path):
    folder = str(tmp_path)
    newest = record(50)
    same_time = record(50)._replace(track="Other")  # equal times: last line wins, as sorted read
    write_history(tmp_path, [record(1), newest, record(3), same_time, record(2)])
    assert last_record(folder) == read_records(folder)[-1] == same_time


def test_last_record_falls_back_to_full_read(tmp_path):
    folder = str(tmp_path)
    junk = b"not json\n" * (driver_history.TAIL_BYTES // 9 + 10)
    write_history(tmp_path, [record(1), record(2)], junk)
    assert last_record(folder) == read_records(folder)[-1] == record(2)


def test_last_record_cached_until_file_changes(tmp_path, monkeypatch):
    folder = str(tmp_path)
    write_history(tmp_path, [record(1)])
    assert last_record(folder) == record(1)
    opened = []
    original = driver_history.open if hasattr(driver_history, "open") else open
    monkeypatch.setattr(driver_history, "open", lambda *args, **kwargs: opened.append(1) or original(*args, **kwargs),
                        raising=False)
    assert last_record(folder) == record(1) and not opened  # unchanged file: not read again
    driver_history.append_record(folder, record(2))
    assert last_record(folder) == record(2) and opened
