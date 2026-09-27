"""Live API checks, require running sim (skipped by default)

Run with: pytest -m manual -k lmu   (or -k rf2)
"""

import pytest
from manual_api_check import check_lmu, check_rf2

pytestmark = pytest.mark.manual


def test_lmu_api():
    version, driver, track = check_lmu()
    assert version, "LMU not running"
    assert driver and track


def test_rf2_api():
    version, driver, track = check_rf2()
    assert version, "rF2 not running (or shared memory plugin disabled)"
    assert driver and track
