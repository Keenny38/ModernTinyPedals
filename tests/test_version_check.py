"""Version parsing & new version check (pre-release and local build tags)"""

import sys

import pytest

from neopedal import version, version_check
from neopedal.const_common import VERSION_NA
from neopedal.version_check import is_new_version, parse_version_string


@pytest.mark.parametrize(("text", "expected"), [
    ("1.2.3", (1, 2, 3)),
    ("0.25.0", (0, 25, 0)),
    ("10.0.1.4", (10, 0, 1)),  # extra part ignored
    ("1.2", VERSION_NA),
    ("", VERSION_NA),
    ("a.b.c", VERSION_NA),
    ("0.19.1+3", VERSION_NA),  # local build suffix is not a version
    (None, VERSION_NA),
    (123, VERSION_NA),
])
def test_parse_version_string(text, expected):
    assert parse_version_string(text) == expected


@pytest.mark.parametrize(("checked", "current", "tag", "expected"), [
    (VERSION_NA, (0, 1, 0), "", False),  # release info not read
    (VERSION_NA, VERSION_NA, "beta", False),
    ((0, 26, 0), (0, 25, 0), "", True),
    ((1, 0, 0), (0, 99, 99), "", True),
    ((0, 25, 1), (0, 25, 0), "+3.g8a0f9f3", True),  # newer release than local build
    ((0, 25, 0), (0, 25, 0), "", False),  # same release
    ((0, 25, 0), (0, 25, 0), "beta", True),  # final release of running pre-release
    ((0, 25, 0), (0, 25, 0), "+3.g8a0f9f3", False),  # local build made after that release
    ((0, 24, 0), (0, 25, 0), "beta", False),  # older release, also for a pre-release
    ((0, 24, 9), (0, 25, 0), "", False),
])
def test_is_new_version(checked, current, tag, expected):
    assert is_new_version(checked, current, tag) is expected


@pytest.mark.parametrize(("development", "expected"), [
    ("", "0.25.0"),
    ("beta", "0.25.0-beta"),
    ("+3.g8a0f9f3", "0.25.0+3.g8a0f9f3"),
])
def test_app_version_text(monkeypatch, development, expected):
    monkeypatch.setattr(version, "__version__", "0.25.0")
    monkeypatch.setattr(version, "DEVELOPMENT", development)
    assert version_check.neopedal() == expected


def test_library_versions():
    assert version_check.python() == ".".join(map(str, sys.version_info))
    for text in (version_check.qt(), version_check.pyside(), version_check.psutil()):
        assert parse_version_string(text) != VERSION_NA
