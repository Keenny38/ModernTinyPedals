"""User file & game data processing tests: setup values, car setup export, consumption & delta files"""

import pytest

from tinypedal.module_info import ConsumptionDataSet
from tinypedal.process import garage, vehicle
from tinypedal.userfile.consumption_history import load_consumption_history_file, save_consumption_history_file
from tinypedal.userfile.fuel_delta import load_fuel_delta_file, save_fuel_delta_file


# --- Vehicle setup values
def test_export_wheels():
    assert vehicle.export_wheels([1, 2, 3, 4, 5], (0, 0, 0, 0)) == (1, 2, 3, 4)
    assert vehicle.export_wheels([1, 2], (0, 0, 0, 0)) == (0, 0, 0, 0)
    assert vehicle.export_wheels(None, (9, 9, 9, 9)) == (9, 9, 9, 9)


@pytest.mark.parametrize("value, expected", [
    ("2.85L/3.00", 0.95),
    ("100/10", 10.0),
    ("no number", -1.0),
    ("5/0", -1.0),
    (None, -1.0),
])
def test_expected_usage(value, expected):
    assert vehicle.expected_usage(value, -1.0) == pytest.approx(expected)


def test_steerlock_to_number():
    assert vehicle.steerlock_to_number("540 deg", 0.0) == 540.0
    assert vehicle.steerlock_to_number("17.5", 0.0) == 17.5
    assert vehicle.steerlock_to_number("N/A", 400.0) == 400.0
    assert vehicle.steerlock_to_number(None, 400.0) == 400.0


def test_absolute_refilling():
    fuel = [{"name": "TIRES:"}, {"name": "FUEL:", "currentSetting": 1, "settings": [{"text": "0L"}, {"text": "45.5L"}]}]
    assert vehicle.absolute_refilling(fuel, 0.0) == 45.5
    gallons = [{"name": "FUEL:", "currentSetting": 0, "settings": [{"text": "10 gal"}]}]
    assert vehicle.absolute_refilling(gallons, 0.0) == pytest.approx(37.854118)
    energy = [{"name": "VIRTUAL ENERGY:", "currentSetting": "87"}, {"name": "FUEL:"}]
    assert vehicle.absolute_refilling(energy, 0.0) == 87.0  # energy first, fuel ignored
    assert vehicle.absolute_refilling([{"name": "FUEL:", "currentSetting": 0, "settings": [{"text": "-"}]}], 5.0) == 5.0
    assert vehicle.absolute_refilling([{"name": "FUEL:", "currentSetting": 3, "settings": []}], 5.0) == 5.0
    assert vehicle.absolute_refilling(None, 5.0) == 5.0


# --- Car setup export
@pytest.fixture
def class_name(monkeypatch):
    from types import SimpleNamespace

    from tinypedal.api_control import api

    reader = SimpleNamespace(vehicle=SimpleNamespace(class_name=lambda: "GT3"))
    monkeypatch.setattr(api, "read", reader)
    return reader


def test_export_lmu_car_setup(class_name):
    source = {
        "VM_FRONT_WING": {"value": 3},
        "symmetric": True,
        "WM_PRESSURE-W_FL": {"value": "135 kPa"},
        "VM_REAR_WING": {"other": 1},  # no value, skipped
    }
    lines = garage.export_lmu_car_setup(source, ())
    assert lines[0] == 'VehicleClassSetting="GT3"'
    assert "Symmetric=1" in lines
    assert lines[lines.index("[FRONTWING]") + 1] == "FWSetting=3"
    assert lines[lines.index("[REARWING]") + 1] == ""  # empty section
    assert lines[lines.index("[FRONTLEFT]") + 1] == "PressureSetting=135 kPa"
    assert garage.export_lmu_car_setup({}, ("default",)) == ("default",)


def test_export_lmu_car_setup_needs_class_name(class_name):
    class_name.vehicle.class_name = lambda: ""
    assert garage.export_lmu_car_setup({"VM_FRONT_WING": {"value": 3}}, ()) == ()


def test_export_rf2_car_setup_waits_for_every_part(class_name):
    keys = garage.RF2_CARSETUP_REFERENCE_KEY
    first = {key: {"value": 1} for key in keys[:4]}
    second = {key: {"value": 2} for key in keys[4:]}
    assert garage.export_rf2_car_setup(first, ("partial",)) == ("partial",)
    lines = garage.export_rf2_car_setup(second, ())
    assert "SteerLockSetting=1" in lines and "CamberSetting=2" in lines
    # Parts restart after export: a part seen twice resets incomplete data
    assert garage.export_rf2_car_setup(first, ()) == ()
    assert garage.export_rf2_car_setup(first, ()) == ()
    assert garage.export_rf2_car_setup({}, ("empty",)) == ("empty",)


# --- Consumption history
def test_consumption_history_roundtrip(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    dataset = [
        ConsumptionDataSet(5, 1, 92.5, 2.85, 3.1, 0.0, 0.0, 0.4, 100.0),
        ConsumptionDataSet(4, 0, 98.1, 3.05, 3.3, 0.0, 0.0, 0.5, 100.0),
    ]
    save_consumption_history_file(dataset, filepath, "Spa - GT3")
    loaded = load_consumption_history_file(filepath, "Spa - GT3")
    assert loaded == tuple(dataset)


def test_consumption_history_not_saved_or_loaded_when_invalid(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    save_consumption_history_file([ConsumptionDataSet()], filepath, "Spa")  # single line not saved
    save_consumption_history_file([ConsumptionDataSet()] * 2, filepath, " - ")  # invalid name
    assert not list(tmp_path.iterdir())
    assert load_consumption_history_file(filepath, "missing") == (ConsumptionDataSet(),)
    (tmp_path / "bad.consumption").write_text("lapNumber\nnot a number\n", encoding="utf-8")
    assert load_consumption_history_file(filepath, "bad") == (ConsumptionDataSet(),)
    assert not [path.name for path in tmp_path.iterdir() if path.name.startswith("bad.consumption.")]
    # Own history file (stint module): unreadable file kept as backup, as next save replaces it
    assert load_consumption_history_file(filepath, "bad", backup=True) == (ConsumptionDataSet(),)
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith("bad.consumption.")]


def backups(tmp_path, name: str) -> list:
    return [path.name for path in tmp_path.iterdir() if path.name.startswith(f"{name}.consumption.")]


def test_consumption_history_backup_only_of_unreadable_content(tmp_path, monkeypatch):
    filepath = f"{tmp_path.as_posix()}/"
    header = ",".join(f'"{name}"' for name in ConsumptionDataSet._fields)
    # Header only (no lap yet) or empty file: nothing worth keeping, no backup at each session start
    (tmp_path / "header.consumption").write_text(f"{header}\n", encoding="utf-8")
    (tmp_path / "empty.consumption").write_text("", encoding="utf-8")
    for name in ("header", "empty"):
        assert load_consumption_history_file(filepath, name, backup=True) == (ConsumptionDataSet(),)
        assert not backups(tmp_path, name)
    # Not text (binary or other encoding): content, kept
    (tmp_path / "binary.consumption").write_bytes(b"\xff\xfe\x00garbage\x00\xff")
    assert load_consumption_history_file(filepath, "binary", backup=True) == (ConsumptionDataSet(),)
    assert backups(tmp_path, "binary")
    # File locked (OSError): never backed up
    (tmp_path / "locked.consumption").write_text(f"{header}\n1,0,90,2,2,0,0,0,100\n", encoding="utf-8")
    import builtins

    real_open = builtins.open

    def locked_open(file, *args, **kwargs):
        if str(file).endswith("locked.consumption"):
            raise PermissionError("locked")
        return real_open(file, *args, **kwargs)

    from tinypedal.userfile import consumption_history

    monkeypatch.setattr(consumption_history, "open", locked_open, raising=False)
    assert load_consumption_history_file(filepath, "locked", backup=True) == (ConsumptionDataSet(),)
    monkeypatch.undo()
    assert not backups(tmp_path, "locked")


def test_consumption_history_bad_line_left_out(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    dataset = [
        ConsumptionDataSet(5, 1, 92.5, 2.85, 3.1, 0.0, 0.0, 0.4, 100.0),
        ConsumptionDataSet(4, 0, 98.1, 3.05, 3.3, 0.0, 0.0, 0.5, 100.0),
    ]
    save_consumption_history_file(dataset, filepath, "Spa")
    file = tmp_path / "Spa.consumption"
    lines = file.read_text(encoding="utf-8").splitlines()
    lines.insert(2, "3.5,1,92.5,2.85,3.1,0.0,0.0,0.4,100.0")  # float in int field
    lines.insert(3, ",,,,,,,,")  # empty values
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert load_consumption_history_file(filepath, "Spa") == tuple(dataset)


# --- Fuel delta
def make_delta(rows: int = 20):
    """(distance, used, laptime) samples along lap"""
    return tuple((index * 100.0, index * 0.15, index * 4.5) for index in range(rows))


def test_fuel_delta_roundtrip(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    defaults = ((), 0.0, 0.0)
    save_fuel_delta_file(filepath, "Spa", ".fuel", make_delta())
    data, used, laptime = load_fuel_delta_file(filepath, "Spa", ".fuel", defaults)
    assert len(data) == 20
    assert used == pytest.approx(19 * 0.15) and laptime == pytest.approx(19 * 4.5)


def test_fuel_delta_invalid(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    defaults = ((), 0.0, 0.0)
    save_fuel_delta_file(filepath, "Spa", ".fuel", make_delta(5))  # under 10 samples, not saved
    assert load_fuel_delta_file(filepath, "Spa", ".fuel", defaults) == defaults
    backward = (*make_delta()[:-1], (1900.0, 0.0, 85.5))  # usage lower at end of lap
    save_fuel_delta_file(filepath, "Bad", ".fuel", backward)
    assert load_fuel_delta_file(filepath, "Bad", ".fuel", defaults) == defaults


# --- User data path
def test_invalid_user_data_path_falls_back(tmp_path, monkeypatch):
    """Invalid path (Windows "<": WinError 123) returns "" (default path used), no startup crash"""
    import os

    from tinypedal.userfile import set_user_data_path

    def invalid(path):
        raise OSError(22, "The filename, directory name, or volume label syntax is incorrect")

    monkeypatch.setattr(os, "mkdir", invalid)
    assert set_user_data_path(str(tmp_path / "bad<name")) == ""
    monkeypatch.undo()
    assert set_user_data_path(str(tmp_path / "good")) == str(tmp_path / "good")
    assert (tmp_path / "good").is_dir()
