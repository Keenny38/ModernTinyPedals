"""Regression tests for audit fixes"""

import os

from tinypedal import calculation as calc
from tinypedal.userfile import atomic_write


def test_distance_interp_between_points():
    # Halfway between (0, 0) at 100m and (10, 20) at 200m
    pos = calc.distance_interp_coordinate(10, 0, 20, 0, 200, 100, 150)
    assert pos == (5, 10)


def test_distance_interp_edge_cases():
    # Before start point, same distance points (no division by zero), past end point
    assert calc.distance_interp_coordinate(10, 0, 20, 0, 200, 100, 90) == (0, 0)
    assert calc.distance_interp_coordinate(10, 0, 20, 0, 100, 100, 100) == (0, 0)
    assert calc.distance_interp_coordinate(10, 0, 20, 0, 200, 100, 300) == (10, 20)


def test_tri_coords_angle_collinear_no_domain_error():
    # Floating point error can push cos above 1.0
    assert calc.tri_coords_angle(0.1 + 0.2 - 0.3, 1.0000000000000002, 1.0) >= 0


def test_scale_elevation_flat_track():
    coords = ((0.0, 5.0), (100.0, 5.0), (200.0, 5.0))
    calc.scale_elevation(coords, 300, 100)  # no ZeroDivisionError


def test_atomic_write(tmp_path):
    target = tmp_path / "data.csv"
    with atomic_write(str(target), newline="") as file:
        file.write("a,b\n")
    assert target.read_text(encoding="utf-8") == "a,b\n"
    assert not os.path.exists(f"{target}.tmp")


def test_atomic_write_keeps_old_file_on_error(tmp_path):
    target = tmp_path / "data.csv"
    target.write_text("old", encoding="utf-8")
    missing_dir_target = tmp_path / "missing" / "data.csv"
    with atomic_write(str(missing_dir_target)) as file:  # error is logged, not raised
        file.write("new")
    assert target.read_text(encoding="utf-8") == "old"


def test_versioned_backup(tmp_path, monkeypatch):
    from tinypedal.userfile import json_setting

    folder = f"{tmp_path}/"
    (tmp_path / "preset.json").write_text("{}", encoding="utf-8")
    assert json_setting.create_versioned_backup("preset.json", folder, max_count=2, min_interval=600)
    # Throttled: no second backup within interval
    assert not json_setting.create_versioned_backup("preset.json", folder, max_count=2, min_interval=600)
    # Keep only max_count backups
    for index in range(4):
        monkeypatch.setattr(json_setting, "set_backup_timestamp", lambda prefix, i=index: f"{prefix}-9999-{i}")
        json_setting.create_versioned_backup("preset.json", folder, max_count=2, min_interval=0)
    backups = sorted(p.name for p in tmp_path.iterdir() if ".backup-auto-" in p.name)
    assert backups == ["preset.json.backup-auto-9999-2", "preset.json.backup-auto-9999-3"]
    # Disabled
    assert not json_setting.create_versioned_backup("preset.json", folder, max_count=0)
