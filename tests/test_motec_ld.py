"""MoTeC .ld export of recorded laps"""

import pytest

from tinypedal.userfile.motec_ld import (
    CHANNEL,
    HEAD,
    Channel,
    LdInfo,
    export_lap,
    lap_channels,
    read_ld,
    sample_rate,
    write_ld,
)
from tinypedal.userfile.telemetry_lap import LapData


def make_lap(rate: int = 50, seconds: float = 2.0) -> LapData:
    count = int(seconds * rate) + 1
    times = [index / rate for index in range(count)]
    return LapData("lap1", {
        "lap_time": times,
        "distance": [t * 50 for t in times],
        "speed_kph": [180.0] * count,
        "throttle": [0.5] * count,
        "gear": [3.0] * count,
    })


def test_struct_sizes_match_format():
    assert HEAD.size == 0x6E2
    assert CHANNEL.size == 124


def test_write_read_roundtrip(tmp_path):
    filename = str(tmp_path / "out.ld")
    channels = [
        Channel("Ground Speed", "Spd", "km/h", 10, [1.0, 2.5, 3.0]),
        Channel("Gear", "Gear", "", 20, [1.0, 2.0]),
    ]
    write_ld(filename, channels, LdInfo(driver="Me", vehicle="Car", venue="Spa", session="Race", comment="c"))
    info, result = read_ld(filename)
    assert (info.driver, info.vehicle, info.venue, info.session, info.comment) == ("Me", "Car", "Spa", "Race", "c")
    assert [(c.name, c.unit, c.frequency, c.values) for c in result] ==         [(c.name, c.unit, c.frequency, c.values) for c in channels]
    assert result[0].short_name == "km/h"  # unit also in short name field, like MoTeC files seen in the wild


def test_unit_field_layout(tmp_path):
    """Unit at byte 64 of channel descriptor (as real MoTeC files), and in documented unit field"""
    import struct

    filename = str(tmp_path / "out.ld")
    write_ld(filename, [Channel("Ground Speed", "Spd", "km/h", 10, [1.0])], LdInfo())
    with open(filename, "rb") as file:
        data = file.read()
    meta_ptr = struct.unpack_from("<I4xI", data, 0)[1]
    assert data[meta_ptr + 32:meta_ptr + 44].rstrip(b"\0") == b"Ground Speed"
    assert data[meta_ptr + 64:meta_ptr + 68] == b"km/h"
    assert data[meta_ptr + 72:meta_ptr + 76] == b"km/h"


def test_sample_rate():
    assert sample_rate([0, 0.02, 0.04, 0.06]) == 50
    assert sample_rate([0, 0]) == 1


def test_lap_channels_resample_and_scale():
    channels = {channel.name: channel for channel in lap_channels(make_lap())}
    assert "Tyre Temp FL" not in channels  # missing column skipped
    speed = channels["Ground Speed"]
    assert speed.frequency == 50 and len(speed.values) == 101
    assert channels["Throttle Pos"].values[0] == pytest.approx(50.0)  # fraction to percent
    assert channels["Lap Distance"].values[-1] == pytest.approx(100.0)


def test_lap_channels_need_samples():
    with pytest.raises(ValueError):
        lap_channels(LapData("x", {"lap_time": [0.0], "distance": [0.0]}))


def test_export_lap(tmp_path):
    filename = str(tmp_path / "lap.ld")
    export_lap(make_lap(), filename, venue="Monza")
    info, channels = read_ld(filename)
    assert info.venue == "Monza" and info.comment == "lap1"
    assert len(channels) == 5
