"""Wheels module calculation tests

These generators turn raw shared-memory readings into most of what the tyre and wheel widgets
display (slip ratio, locking, angles, weight distribution), and had almost no coverage. They
are driven directly here: build one with an output object, then send it a reset token per frame.
"""

import math

import pytest

from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module.module_wheels import (
    calc_vehicle_weight,
    calc_wheel_angle,
    calc_wheel_rotation,
)
from tinypedal.module_info import WheelsInfo


@pytest.fixture
def driving(ui_env, monkeypatch):
    """Realtime state as if on track, so the generators pass their reset gate"""
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(realtime_state, "resets", 0)
    return WheelsInfo()


def set_reader(monkeypatch, group: str, name: str, value):
    monkeypatch.setattr(getattr(api.read, group), name, lambda *a, **k: value, raising=False)


# --- Wheel angles
def test_wheel_angles_are_converted_to_degrees(driving, monkeypatch):
    quarter_turn = math.pi / 4  # 45 degrees, in radians as the game reports it
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "tyre", "slip_angle", (quarter_turn, 0.0, 0.0, 0.0))
    set_reader(monkeypatch, "wheel", "toe", (0.0, 0.0, 0.0, 0.0))
    set_reader(monkeypatch, "wheel", "camber", (-quarter_turn, -quarter_turn, 0.0, 0.0))

    calc_wheel_angle(driving).send(0)

    assert driving.slipAngle[0] == pytest.approx(45.0)
    assert driving.camberAngle[0] == pytest.approx(-45.0)
    assert driving.averageFrontSlipAngle == pytest.approx(22.5)
    assert driving.frontCamberAngleDifference == pytest.approx(0.0)


def test_slip_angle_is_zero_below_walking_speed(driving, monkeypatch):
    """Slip angle is meaningless at a standstill and would otherwise show noise"""
    set_reader(monkeypatch, "vehicle", "speed", 0.5)
    set_reader(monkeypatch, "tyre", "slip_angle", (1.0, 1.0, 1.0, 1.0))
    set_reader(monkeypatch, "wheel", "toe", (0.0,) * 4)
    set_reader(monkeypatch, "wheel", "camber", (0.0,) * 4)

    calc_wheel_angle(driving).send(0)

    assert list(driving.slipAngle) == [0.0] * 4


# --- Wheel rotation, slip ratio and locking
def rolling(monkeypatch, *, speed=50.0, rotation=(-25.0,) * 4, brake=0.0, elapsed=0.0, start=0.0):
    """Reader values for a car rolling in a straight line (rotation is negative when driving)"""
    set_reader(monkeypatch, "vehicle", "speed", speed)
    set_reader(monkeypatch, "wheel", "rotation", rotation)
    set_reader(monkeypatch, "vehicle", "acceleration_lateral", 0.0)
    set_reader(monkeypatch, "vehicle", "acceleration_longitudinal", 1.0)
    set_reader(monkeypatch, "inputs", "brake_raw", brake)
    set_reader(monkeypatch, "timing", "elapsed", elapsed)
    set_reader(monkeypatch, "timing", "start", start)
    set_reader(monkeypatch, "vehicle", "vehicle_name", "car")


def learn_radius(generator, monkeypatch):
    """Roll straight with a slight left/right difference, as on track: wheel radius gets learned"""
    rolling(monkeypatch, rotation=(-25.0, -25.02, -25.0, -25.02), elapsed=0.0)
    generator.send(0)


def test_no_lock_before_wheel_radius_is_learned(driving, monkeypatch):
    generator = calc_wheel_rotation(driving, 1.5, 1.5, 0.1, -0.2)
    rolling(monkeypatch, rotation=(-25.0,) * 4, brake=0.9, elapsed=0.0)
    generator.send(0)  # identical rotations: radius not learned
    assert list(driving.slipRatio) == [0.0] * 4


def test_locking_time_only_accumulates_while_braking_and_locked(driving, monkeypatch):
    generator = calc_wheel_rotation(driving, 1.5, 1.5, 0.1, -0.2)
    learn_radius(generator, monkeypatch)
    # Coasting with a locked front wheel: no brake input, so nothing is recorded
    rolling(monkeypatch, rotation=(0.0, -25.0, -25.0, -25.0), brake=0.0, elapsed=0.1)
    generator.send(0)
    assert driving.lockingTime[0] == 0.0
    # Same wheel, now under braking
    rolling(monkeypatch, rotation=(0.0, -25.0, -25.0, -25.0), brake=0.9, elapsed=0.2)
    generator.send(0)
    assert driving.lockingTime[0] == pytest.approx(0.1)


def test_locking_time_resets_on_a_new_lap(driving, monkeypatch):
    generator = calc_wheel_rotation(driving, 1.5, 1.5, 0.1, -0.2)
    learn_radius(generator, monkeypatch)
    for elapsed in (0.0, 0.1, 0.2):
        rolling(monkeypatch, rotation=(0.0,) * 4, brake=0.9, elapsed=elapsed, start=0.0)
        generator.send(0)
    assert driving.lockingTime[0] > 0
    accumulated = driving.lockingTime[0]
    rolling(monkeypatch, rotation=(0.0,) * 4, brake=0.9, elapsed=0.3, start=100.0)  # lap start changed
    generator.send(0)
    # Cleared for the new lap, then this frame's own 0.1s is counted against it
    assert driving.lockingTime[0] == pytest.approx(0.1)
    assert driving.lockingTime[0] < accumulated


def test_a_long_frame_gap_is_not_counted_as_locking(driving, monkeypatch):
    """A pause or a stutter must not add its whole duration to the locking time"""
    generator = calc_wheel_rotation(driving, 1.5, 1.5, 0.1, -0.2)
    rolling(monkeypatch, rotation=(0.0,) * 4, brake=0.9, elapsed=0.0)
    generator.send(0)
    rolling(monkeypatch, rotation=(0.0,) * 4, brake=0.9, elapsed=30.0)  # 30 second gap
    generator.send(0)
    assert driving.lockingTime[0] == 0.0


# --- Vehicle weight
def test_weight_distribution_from_tyre_load(driving, monkeypatch):
    set_reader(monkeypatch, "tyre", "load", (3000.0, 3000.0, 2000.0, 2000.0))
    set_reader(monkeypatch, "wheel", "suspension_force", (0.0,) * 4)
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    set_reader(monkeypatch, "vehicle", "vehicle_name", "car")

    calc_vehicle_weight(driving, 9.81, 0.0, 0.0).send(0)

    assert driving.frontWeightRatio == pytest.approx(0.6)
    assert driving.leftWeightRatio == pytest.approx(0.5)
    assert driving.totalDynamicWeight == pytest.approx(10000 / 9.81)


def test_weight_falls_back_to_suspension_load(driving, monkeypatch):
    """Some cars report no tyre load; distribution then comes from suspension force"""
    set_reader(monkeypatch, "tyre", "load", (0.0,) * 4)
    set_reader(monkeypatch, "wheel", "suspension_force", (3000.0, 3000.0, 1000.0, 1000.0))
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    set_reader(monkeypatch, "vehicle", "vehicle_name", "car")

    calc_vehicle_weight(driving, 9.81, 0.0, 0.0).send(0)

    assert driving.frontWeightRatio == pytest.approx(0.75)


def test_minimum_weight_override_wins(driving, monkeypatch):
    set_reader(monkeypatch, "tyre", "load", (3000.0,) * 4)
    set_reader(monkeypatch, "wheel", "suspension_force", (0.0,) * 4)
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "inputs", "throttle_raw", 1.0)
    set_reader(monkeypatch, "vehicle", "vehicle_name", "car")

    calc_vehicle_weight(driving, 9.81, 0.0, 1250.0).send(0)

    assert driving.minimumStaticWeight == 1250.0
    assert driving.totalDynamicWeight == 0.0  # not available when overridden


def test_generators_wait_for_the_car_to_be_on_track(ui_env, monkeypatch):
    """Nothing is calculated while the session is not live, so stale values are not published"""
    monkeypatch.setattr(realtime_state, "active", False)
    output = WheelsInfo()
    set_reader(monkeypatch, "vehicle", "speed", 30.0)
    set_reader(monkeypatch, "tyre", "slip_angle", (1.0,) * 4)
    set_reader(monkeypatch, "wheel", "toe", (0.0,) * 4)
    set_reader(monkeypatch, "wheel", "camber", (1.0,) * 4)

    calc_wheel_angle(output).send(0)

    assert list(output.camberAngle) == [0.0] * 4
