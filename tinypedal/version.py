import os
import re
import subprocess
import sys

# App version (MAJOR.MINOR.PATCH), set by the release workflow from commits since last release:
# minor for new features (commit titles starting with "Add"), patch for fixes & changes
__version__ = "0.10.0"
# Development version tag (set to "" for release-version).
# Starting with "+": local build made after that version (commits since release), not a pre-release.
DEVELOPMENT = ""
# Setting format version, stored in presets and used by setting_preupdate migrations.
# Kept on the TinyPedal numbering (independent from app version), so presets from
# TinyPedal 2.x keep loading. Raise it only with a new migration in setting_preupdate.
SETTING_VERSION = "2.50.2"


def source_version(default: tuple[str, str]) -> tuple[str, str]:
    """Version of a git checkout: last release tag & commits since (release builds have no git folder)"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists(os.path.join(root, ".git")):
        return default
    try:
        output = subprocess.run(
            ["git", "describe", "--tags", "--long", "--match", "v[0-9]*"],
            cwd=root, capture_output=True, text=True, timeout=3, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return default
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)", output)
    if match is None:
        return default
    tag_version, commits, sha = match.groups()
    return tag_version, (f"+{commits}.g{sha}" if commits != "0" else "")


# Running from source: show real version, & never offer the release it was made from as an update
if not getattr(sys, "frozen", False):
    __version__, DEVELOPMENT = source_version((__version__, DEVELOPMENT))
