"""Shared memory struct layout guard

Struct sizes must match the game plugin memory layout (LMU native, rF2 shared memory plugin).
Updating pyLMUSharedMemory / pyRfactor2SharedMemory submodules must not change them silently:
if a size changed on purpose (game update), check readers in tinypedal/adapter, then update below.

Note (2026-09): upstream submodules renamed modules (rF2data -> rf2_data, rF2MMap -> rf2_mmap,
lmu_type/rF2Type stubs removed) with identical struct layout, adapters must be ported before bumping.
"""

import ctypes
import inspect

import pytest

from pyLMUSharedMemory import lmu_data
from pyRfactor2SharedMemory import rF2data

LMU_SIZES = {
    "LMUApplicationState": 260,
    "LMUEvent": 64,
    "LMUGeneric": 332,
    "LMULayout": 324820,
    "LMUObjectOut": 324820,
    "LMUPathData": 1300,
    "LMUScoringData": 126832,
    "LMUScoringInfo": 548,
    "LMUTelemetryData": 196356,
    "LMUVect3": 24,
    "LMUVehicleScoring": 584,
    "LMUVehicleTelemetry": 1888,
    "LMUWheel": 260,
}

RF2_SIZES = {
    "rF2Extended": 10152,
    "rF2ForceFeedback": 16,
    "rF2Graphics": 272,
    "rF2GraphicsInfo": 264,
    "rF2HWControl": 116,
    "rF2MappedBufferVersionBlock": 8,
    "rF2MappedBufferVersionBlockWithSize": 12,
    "rF2PhysicsOptions": 40,
    "rF2PitInfo": 340,
    "rF2PitMenu": 332,
    "rF2PluginControl": 20,
    "rF2Rules": 45272,
    "rF2RulesControl": 45272,
    "rF2Scoring": 75312,
    "rF2ScoringInfo": 548,
    "rF2SessionTransitionCapture": 1036,
    "rF2Telemetry": 241680,
    "rF2TrackRules": 716,
    "rF2TrackRulesAction": 16,
    "rF2TrackRulesParticipant": 332,
    "rF2TrackedDamage": 16,
    "rF2Vec3": 24,
    "rF2VehScoringCapture": 8,
    "rF2VehicleScoring": 584,
    "rF2VehicleTelemetry": 1888,
    "rF2Weather": 632,
    "rF2WeatherControl": 628,
    "rF2WeatherControlInfo": 616,
    "rF2Wheel": 260,
}


def struct_sizes(module) -> dict[str, int]:
    return {
        name: ctypes.sizeof(cls)
        for name, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, ctypes.Structure) and cls.__module__ == module.__name__
    }


@pytest.mark.parametrize(("module", "expected"), [(lmu_data, LMU_SIZES), (rF2data, RF2_SIZES)])
def test_struct_layout_unchanged(module, expected):
    assert struct_sizes(module) == expected
