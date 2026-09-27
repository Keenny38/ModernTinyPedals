"""Manual API check (requires running sim)

Usage: python tests/manual_api_check.py [lmu|rf2]
or with pytest: pytest -m manual (see test_manual_api.py, skipped in normal test run)
"""

import logging
import os
import sys
from time import sleep

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEPARATOR = "=" * 50


def check_api(info, read_info) -> tuple[str, str, str]:
    """Start, restart, read, close API, returns (version, driver name, track name)"""
    logging.basicConfig(level=logging.INFO)
    print("Test API - Start")
    info.setMode(1)  # set direct access
    info.setPlayerOverride(True)  # enable player override
    info.setPlayerIndex(0)  # set player index to 0
    info.start()
    sleep(0.2)

    print(SEPARATOR)
    print("Test API - Restart")
    info.stop()
    info.setMode()  # set copy access
    info.setPlayerOverride()  # disable player override
    info.start()

    print(SEPARATOR)
    print("Test API - Read")
    version, driver, track = read_info(info)
    print(f"version: {version if version else 'not running'}")
    print(f"driver name   : {driver if version else 'not running'}")
    print(f"track name    : {track if version else 'not running'}")

    print(SEPARATOR)
    print("Test API - Close")
    info.stop()
    return version, driver, track


def check_lmu() -> tuple[str, str, str]:
    from tinypedal.adapter.lmu_connector import LMUInfo

    return check_api(LMUInfo(), lambda info: (
        info.lmuGeneric.gameVersion,
        info.lmuScorVeh(0).mDriverName.decode(),
        info.lmuScorInfo.mTrackName.decode(),
    ))


def check_rf2() -> tuple[str, str, str]:
    from tinypedal.adapter.rf2_connector import RF2Info

    info = RF2Info()
    info.setPID("")
    return check_api(info, lambda info: (
        info.rf2Ext.mVersion.decode(),
        info.rf2ScorVeh(0).mDriverName.decode(),
        info.rf2ScorInfo.mTrackName.decode(),
    ))


if __name__ == "__main__":
    check_rf2() if sys.argv[1:] == ["rf2"] else check_lmu()
