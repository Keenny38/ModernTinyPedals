"""MoTeC .ld import: integer channels, lap split, unit conversion, lap viewer integration"""

import os
import struct
from array import array

import pytest

from tinypedal.userfile.motec_import import import_laps, import_ld_file, is_worn_percent
from tinypedal.userfile.motec_ld import CHANNEL, EVENT, HEAD, LD_MARKER, VEHICLE, VENUE


def write_logger_ld(filename, channels, venue="Spa", vehicle="GT3", driver="Pro Driver"):
    """Write .ld file like LMU built-in logger: int16 samples scaled by shift, multiplier & decimals

    channels: (name, unit, frequency, values, shift, multiplier, decimals)
    """
    event_ptr = HEAD.size
    venue_ptr = event_ptr + EVENT.size
    vehicle_ptr = venue_ptr + VENUE.size
    meta_ptr = vehicle_ptr + VEHICLE.size
    data_ptr = meta_ptr + CHANNEL.size * len(channels)
    with open(filename, "wb") as file:
        file.write(HEAD.pack(
            LD_MARKER, meta_ptr, data_ptr, event_ptr, 1, 0x4240, 0xF, 0x1F44, b"ADL", 420, 0xADB0, len(channels),
            b"24/09/2026", b"14:05:12", driver.encode(), vehicle.encode(), venue.encode(), 0, b""))
        file.write(EVENT.pack(venue.encode(), b"Practice", b"", venue_ptr))
        file.write(VENUE.pack(venue.encode(), vehicle_ptr))
        file.write(VEHICLE.pack(vehicle.encode(), 0, b"", b""))
        offset = data_ptr
        raws = []
        for index, (name, unit, frequency, values, shift, multiplier, decimals) in enumerate(channels):
            raw = array("h", (round((value - shift) * 10 ** decimals / multiplier) for value in values))
            next_ptr = meta_ptr + CHANNEL.size * (index + 1) if index < len(channels) - 1 else 0
            file.write(CHANNEL.pack(
                0, next_ptr, offset, len(raw), index, 0x03, 2, frequency, shift, multiplier, 1, decimals,
                name.encode(), unit.encode(), b""))  # unit in short name field, as LMU does
            offset += len(raw) * 2
            raws.append(raw)
        for raw in raws:
            file.write(raw.tobytes())


def logger_channels(laps=3, lap_seconds=10.0, rate=10, track=1000.0):
    """Laps at constant speed (100 m/s = 360 km/h), first & last partial"""
    count = int((laps + 1) * lap_seconds * rate)
    start = lap_seconds * 0.5  # log starts mid lap
    times = [index / rate for index in range(count)]
    lap_number = [int((t + start) // lap_seconds) + 10 for t in times]
    distance = [((t + start) % lap_seconds) * track / lap_seconds for t in times]
    speed = [360.0] * count
    wear = [2.0 + t * 0.05 for t in times]  # worn %, going up
    return [
        ("Lap Number", "", rate, lap_number, 32760, 1, 0),
        ("Lap Distance", "m", rate, distance, 31780, 1, 0),
        ("Ground Speed", "km/h", rate, speed, 641, 2, 2),
        ("Throttle Pos", "%", rate, [100.0] * count, 50, 2, 3),
        ("Tyre Wear FL", "%", rate, wear, 50, 2, 3),
        ("Tyre Temp FL Inner", "C", rate, [90.0] * count, 585, 2, 2),
        ("Tyre Temp FL Centre", "C", rate, [80.0] * count, 585, 2, 2),
        ("Tyre Temp FL Outer", "C", rate, [70.0] * count, 585, 2, 2),
        ("Gear", "", rate, [4.0] * count, 0, 1, 0),
    ]


def test_import_logger_laps(tmp_path):
    filename = str(tmp_path / "spa.ld")
    write_logger_ld(filename, logger_channels())
    info, laps = import_laps(filename)
    assert info.venue == "Spa" and info.vehicle == "GT3" and info.driver == "Pro Driver"
    assert [lap.number for lap in laps] == [11, 12, 13]  # partial first & last laps left out
    lap = laps[0]
    assert lap.lap_time == pytest.approx(10.0, abs=0.11)
    columns = lap.columns
    assert columns["speed_kph"][5] == pytest.approx(360.0, abs=0.1)  # int16 * multiplier * 10^-decimals + shift
    assert columns["throttle"][5] == pytest.approx(1.0)  # percent to fraction
    assert columns["distance"][0] < 20 and max(columns["distance"]) > 970
    assert columns["tyre_temp_fl"][3] == pytest.approx(80.0, abs=0.1)  # average of inner, centre & outer
    assert columns["tyre_wear_fl"][0] > columns["tyre_wear_fl"][-1] > 90  # worn % to remaining %
    assert columns["lap_time"][0] == 0.0 and columns["gear"][0] == 4
    assert lap.info["track"] == "Spa" and lap.info["source"] == "MoTeC" and lap.info["lap_number"] == 11


def test_import_saves_lap_files(tmp_path):
    from tinypedal.userfile.telemetry_lap import lap_time_of, list_tracks, load_lap, read_lap_info

    filename = str(tmp_path / "spa.ld")
    write_logger_ld(filename, logger_channels())
    folder = str(tmp_path / "telemetry" / ".imported")
    paths = import_ld_file(filename, folder)
    assert len(paths) == 3 and all(os.path.dirname(path).endswith("spa") for path in paths)
    assert lap_time_of(os.path.basename(paths[0])) == pytest.approx(10.0, abs=0.11)
    lap = load_lap(paths[0])
    assert lap.meta["imported_from"] == "spa.ld" and read_lap_info(paths[0])["vehicle"] == "GT3"
    assert max(lap.distance) > 970
    assert list_tracks(str(tmp_path / "telemetry")) == []  # import folder is not a track


def test_exported_lap_imported_back(tmp_path):
    from tinypedal.userfile.motec_ld import export_lap
    from tinypedal.userfile.telemetry_lap import LapData

    times = [index / 50 for index in range(3001)]  # 60 s at 50 Hz
    lap = LapData("lap", {
        "lap_time": times,
        "distance": [t * 50 for t in times],
        "speed_kph": [180.0] * len(times),
        "throttle": [0.5] * len(times),
        "tyre_wear_fl": [99.0 - t * 0.01 for t in times],  # remaining %, going down
    }, {"vehicle": "Car", "track": "Monza"})
    filename = str(tmp_path / "lap.ld")
    export_lap(lap, filename)
    info, laps = import_laps(filename)
    assert info.venue == "Monza" and len(laps) == 1
    columns = laps[0].columns
    assert laps[0].lap_time == pytest.approx(60.0)
    assert max(columns["distance"]) == pytest.approx(3000.0, abs=1)
    assert columns["throttle"][10] == pytest.approx(0.5)
    assert columns["tyre_wear_fl"][0] == pytest.approx(99.0, abs=0.01)  # already remaining %


def test_import_invalid_files(tmp_path):
    bad = tmp_path / "bad.ld"
    bad.write_bytes(b"not a motec file")
    with pytest.raises(ValueError):
        import_laps(str(bad))
    empty = str(tmp_path / "empty.ld")
    write_logger_ld(empty, [("Unknown", "", 10, [1.0] * 10, 0, 1, 0)])
    with pytest.raises(ValueError):
        import_laps(empty)


def test_worn_or_remaining_wear():
    assert is_worn_percent([2.0, 2.5])
    assert not is_worn_percent([98.0, 97.5])
    assert is_worn_percent([0.0, 0.0]) and not is_worn_percent([100.0, 100.0])


def test_lap_viewer_imports_motec_file(ui_env, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent

    from tinypedal.ui import lap_viewer

    filename = str(tmp_path / "pro lap.ld")
    write_logger_ld(filename, logger_channels())
    monkeypatch.setattr(lap_viewer.QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([filename], ""))
    viewer = lap_viewer.LapViewer(None)
    try:
        viewer.add_files()
        imported = [entry for entry in viewer.external if entry.info.get("source") == "MoTeC"]
        assert len(imported) == 3
        assert viewer.reference_key in {entry.file.path for entry in imported}  # fastest imported lap
        assert viewer.lap_list.topLevelItem(0).text(0) == "Added Laps"  # added files on top
        assert viewer.lap_items()[0].text(0).startswith("pro lap:")
        assert viewer.plot.lap_a is not None
        bad = tmp_path / "bad.ld"
        bad.write_bytes(b"x" * 10)
        monkeypatch.setattr(lap_viewer.QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([str(bad)], ""))
        viewer.add_files()
        assert "MoTeC" in viewer.label_cursor.text()
    finally:
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_read_ld_skips_unknown_channel_types(tmp_path):
    from tinypedal.userfile.motec_ld import raw_typecode, read_ld

    assert raw_typecode(0x07, 4) == "f" and raw_typecode(0x07, 2) == "e" and raw_typecode(0x03, 4) == "i"
    assert raw_typecode(0x09, 4) == "" and raw_typecode(0x03, 8) == ""
    filename = str(tmp_path / "x.ld")
    write_logger_ld(filename, logger_channels(laps=1))
    with open(filename, "rb") as file:
        data = bytearray(file.read())
    meta_ptr = struct.unpack_from("<I", data, 8)[0]
    struct.pack_into("<H", data, meta_ptr + 18, 0x09)  # first channel: unknown data type
    with open(filename, "wb") as file:
        file.write(bytes(data))
    _, channels = read_ld(filename)
    assert "Lap Number" not in [channel.name for channel in channels] and channels


def test_lap_time_from_line_crossing(tmp_path):
    """Distance at 5 Hz, lap number changing 0.05-0.15 s late (as LMU logs): lap time from line crossing"""
    lap_seconds, track, start = 10.0, 1000.0, 3.03  # line crossed between distance samples
    distance_rate, rate = 5, 50
    seconds = 3 * lap_seconds
    distance = [((index / distance_rate + start) % lap_seconds) * track / lap_seconds
                for index in range(int(seconds * distance_rate))]
    lags = (0.15, 0.05, 0.12, 0.08)  # lap number change after line crossing, not the same every lap
    changes = [k * lap_seconds - start + lags[k % len(lags)] for k in range(1, 5)]
    lap_number = [sum(index / rate >= change for change in changes) for index in range(int(seconds * rate))]
    filename = str(tmp_path / "late.ld")
    write_logger_ld(filename, [
        ("Lap Number", "", rate, lap_number, 32760, 1, 0),
        ("Lap Distance", "m", distance_rate, distance, 31780, 1, 0),
        ("Ground Speed", "km/h", rate, [360.0] * len(lap_number), 641, 2, 2),
    ])
    _, laps = import_laps(filename)
    assert laps and laps[0].lap_time == pytest.approx(lap_seconds, abs=0.01)
    distances = laps[0].columns["distance"]
    # No made-up distance while crossing start line (was interpolated across lap reset: 0 to 1000)
    assert all(value < 60 or value > 940 for value in distances[:15])
