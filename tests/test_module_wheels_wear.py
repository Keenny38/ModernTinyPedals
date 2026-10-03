"""Wheels module: tyre & brake wear per lap with delta estimate, brake failure, suspension travel"""

from types import SimpleNamespace

import pytest

from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module.module_wheels import calc_brake_wear, calc_suspension_travel, calc_tyre_wear
from tinypedal.module_info import WheelsInfo


class Group(SimpleNamespace):
    """Reader group: values from telemetry dict, unknown methods return 0"""

    def __init__(self, tele: dict, prefix: str):
        super().__init__()
        self._tele = tele
        self._prefix = prefix

    def __getattr__(self, name):
        key = f"{self._prefix}.{name}"
        return lambda *args, **kwargs: self._tele.get(key, 0)


@pytest.fixture
def tele(ui_env, monkeypatch):
    values: dict = {
        "vehicle.class_name": "GT3",
        "vehicle.vehicle_name": "Car #1",
        "inputs.brake_raw": 0.0,
        "vehicle.in_pits": False,
    }
    groups = ("session", "lap", "timing", "vehicle", "inputs", "tyre", "brake", "wheel")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(values, name) for name in groups}))
    monkeypatch.setattr(realtime_state, "active", True)
    return values


def drive_lap(tele: dict, gen, lap_start: float, start_wear: float, lap_wear: float, key: str,
              scale: float, steps: int = 20, length: float = 4000.0):
    """Drive one lap in steps, wear (fraction or meters) going down linearly"""
    tele["timing.start"] = lap_start
    for step in range(steps + 1):
        progress = step / steps
        tele.update({
            "timing.current_laptime": 0.0 if step == 0 else 0.5 + progress * 90,
            "lap.distance": progress * length * 0.999,
            "lap.progress": progress,
            key: (start_wear - lap_wear * progress / scale,) * 4,
        })
        gen.send(0)
    return start_wear - lap_wear / scale


# --- Tyre wear
def test_tyre_wear_per_lap_and_estimate(tele):
    output = WheelsInfo()
    gen = calc_tyre_wear(output, min_delta_distance=50, lock_threshold=-0.2)
    wear = drive_lap(tele, gen, 0.0, 1.0, 2.0, "tyre.wear", 100)  # first lap: 2% worn
    wear = drive_lap(tele, gen, 91.0, wear, 2.0, "tyre.wear", 100)  # second lap recorded as delta reference
    assert output.lastLapTreadWear[0] == pytest.approx(2.0, abs=0.01)
    assert output.currentTreadDepth[0] == pytest.approx(96.0, abs=0.01)
    # Third lap, halfway, wearing faster: estimate from last lap wear & delta at this point
    tele["timing.start"] = 182.0
    for step in range(11):
        progress = step / 20
        tele.update({"timing.current_laptime": 0.0 if step == 0 else 0.5 + progress * 90,
                     "lap.distance": progress * 4000 * 0.999, "lap.progress": progress,
                     "tyre.wear": (wear - 0.03 * progress,) * 4})
        gen.send(0)
    assert output.currentLapTreadWear[0] == pytest.approx(1.5, abs=0.05)
    assert output.estimatedTreadWear[0] == pytest.approx(2.5, abs=0.15)  # 2% + 0.5% more than last lap


def test_tyre_wear_ignored_in_pits_and_locking_counted(tele):
    output = WheelsInfo()
    output.slipRatio[:] = (-0.5,) * 4  # locked
    gen = calc_tyre_wear(output, min_delta_distance=50, lock_threshold=-0.2)
    tele.update({"timing.start": 0.0, "timing.current_laptime": 5.0, "lap.distance": 100.0,
                 "tyre.wear": (0.90,) * 4})
    gen.send(0)
    tele.update({"inputs.brake_raw": 1.0, "tyre.wear": (0.89,) * 4})
    gen.send(0)
    assert output.lockingTreadWear[0] == pytest.approx(1.0)  # 1% worn while braking locked
    tele.update({"inputs.brake_raw": 0.0, "vehicle.in_pits": True, "tyre.wear": (1.0,) * 4})  # new tyres
    gen.send(0)
    assert output.lockingTreadWear[0] == 0.0
    assert output.currentLapTreadWear[0] == pytest.approx(1.0)  # tyre change not counted as wear


# --- Brake wear
def test_brake_wear_per_lap_and_max_thickness(tele):
    output = WheelsInfo()
    gen = calc_brake_wear(output, min_delta_distance=50)
    thickness = drive_lap(tele, gen, 0.0, 0.030, 0.2, "brake.wear", 1000)  # 30 mm, 0.2 mm per lap
    drive_lap(tele, gen, 91.0, thickness, 0.2, "brake.wear", 1000)
    assert output.maxBrakeThickness[0] == pytest.approx(30.0)
    assert output.lastLapBrakeWear[0] == pytest.approx(0.2, abs=0.005)
    assert output.currentBrakeThickness[0] == pytest.approx(29.6, abs=0.01)


def test_brake_failure_thickness_saved(tele):
    from tinypedal.setting import cfg

    output = WheelsInfo()
    gen = calc_brake_wear(output, min_delta_distance=50)
    tele.update({"timing.start": 0.0, "timing.current_laptime": 5.0, "lap.distance": 100.0,
                 "brake.wear": (0.0123, 0.03, 0.03, 0.03)})
    gen.send(0)
    tele["brake.wear"] = (0.0, 0.03, 0.03, 0.03)  # front left brake failed
    gen.send(0)
    saved = [data["failure_thickness"] for name, data in cfg.user.brakes.items() if "GT3" in name]
    assert pytest.approx(12.3) in saved
    assert output.failureBrakeThickness[0] == pytest.approx(12.3)


def test_brake_wear_unavailable_skipped(tele):
    output = WheelsInfo()
    gen = calc_brake_wear(output, min_delta_distance=50)
    tele["brake.wear"] = (-1.0, -1.0, -1.0, -1.0)  # not provided by game
    gen.send(0)
    assert output.currentBrakeThickness[0] == 0.0


# --- Suspension travel
def test_suspension_travel_range_and_motion_ratio(tele):
    output = WheelsInfo()
    gen = calc_suspension_travel(output, average_samples=3, average_margin=10, wheel_liftoff=0.1, enable_offroad=True)
    tele.update({"vehicle.speed": 0.0, "wheel.suspension_force": (3000.0,) * 4,
                 "wheel.suspension_deflection": (50.0,) * 4, "tyre.vertical_deflection": (1.0,) * 4,
                 "timing.elapsed": 10.0, "vehicle.impact_time": -100.0})
    gen.send(0)
    assert output.staticSuspensionPosition[0] == 50.0  # recorded while stationary
    tele.update({"vehicle.speed": 50.0, "inputs.throttle_raw": 1.0})
    for step, (susp, wheel) in enumerate(((40.0, 0.020), (60.0, 0.030), (45.0, 0.0225), (55.0, 0.0275))):
        tele.update({"timing.elapsed": 20.0 + step, "wheel.suspension_deflection": (susp,) * 4,
                     "wheel.position_vertical": (wheel,) * 4})
        gen.send(0)
    assert output.minSuspensionPosition[0] < 50 < output.maxSuspensionPosition[0]
    assert output.motionRatio[0] == pytest.approx(20 / 0.01)  # 20 mm suspension for 10 mm (0.01 m) wheel


def test_suspension_skipped_after_impact_and_offroad(tele):
    output = WheelsInfo()
    gen = calc_suspension_travel(output, average_samples=3, average_margin=10, wheel_liftoff=0.1, enable_offroad=False)
    tele.update({"vehicle.speed": 50.0, "inputs.throttle_raw": 1.0, "timing.elapsed": 20.0,
                 "vehicle.impact_time": 19.0, "wheel.suspension_deflection": (40.0,) * 4,
                 "tyre.vertical_deflection": (1.0,) * 4, "wheel.position_vertical": (0.02,) * 4})
    gen.send(0)  # impact 1 s ago
    assert output.minSuspensionPosition[0] == 0.0
    tele.update({"vehicle.impact_time": -100.0, "wheel.offroad": True, "timing.elapsed": 30.0})
    gen.send(0)  # off track
    assert output.minSuspensionPosition[0] == 0.0
    tele.update({"wheel.offroad": False, "timing.elapsed": 34.0})
    gen.send(0)  # 4 s after off track
    assert output.minSuspensionPosition[0] == pytest.approx(40.0)
