"""Race calculator page: new cards (compound comparison, safety car risk, pit exit, pit menu button, pace
inputs) shown without QML warnings"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.module_info import minfo
from neopedal.setting import cfg
from tests.test_perf_page_state import qml_warnings  # noqa: F401 (fixture)
from tests.test_race_calculator import host  # noqa: F401 (fixture)


@pytest.fixture
def watched_page(ui_env, monkeypatch, host, qml_warnings):  # noqa: F811
    """Page created once QML warnings are watched"""
    from neopedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    dialog = race_calculator.RaceCalculator(None)
    dialog.show()
    yield dialog
    dialog.set_unmodified()
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def settle():
    for _ in range(5):
        QCoreApplication.processEvents()


def test_new_cards_without_warnings(watched_page, qml_warnings):  # noqa: F811
    from neopedal.ui.quick.race_base import TABS

    backend = watched_page.backend
    backend.set_values({
        "input_lap_time": 100.0, "input_tank_capacity": 100.0, "input_fuel_per_lap": 4.0, "input_race_minutes": 360,
        "enable_lap_race": False, "input_pit_seconds": 40.0, "input_wear_per_lap": 1.0, "input_minimum_tread": 30.0,
        "input_tyre_deg": 0.3, "input_temp_effect": 0.05, "input_temp_slope": 1.0, "enable_sc_risk": True,
        "input_sc_risk": 0.5, "input_sc_laps": 4,
    })
    settle()
    backend.update_scenarios()
    settle()
    assert backend.scenarios["risk"]["visible"]
    assert backend.scenarios["compounds"]["visible"]
    backend.setTab(TABS.index("tyres"))
    settle()
    backend.setTab(TABS.index("fuel"))
    settle()
    assert not qml_warnings, qml_warnings
