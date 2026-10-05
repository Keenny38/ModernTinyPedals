"""Release files: what the release workflow publishes lets every installed app update itself

Release 0.20.0 published the installer only inside setup.zip: installed apps up to 0.19 found no installer
and could not update from the app. These tests read the workflow, so a change of release files that
breaks an app updater fails here, before anything is published.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from release import RELEASE_ASSETS

from tinypedal import update

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "build-release.yml")
VERSIONED_NAME = re.compile(r"ModernTinyPedals-\$\{\{ needs\.version\.outputs\.app_ver \}\}(\S+)")
DIGEST = "ab" * 32


def published_suffixes() -> set[str]:
    """Name suffixes of files uploaded by the build jobs (the release job publishes every one of them)"""
    with open(WORKFLOW, encoding="utf-8") as file:
        lines = file.read().splitlines()
    suffixes = set()
    for index, line in enumerate(lines):
        if "uses: actions/upload-artifact@" not in line:
            continue
        for following in lines[index + 1:]:
            if following.strip().startswith("- name:"):  # next step
                break
            suffixes.update(VERSIONED_NAME.findall(following))
    return suffixes


def release_response(version: str = "9.9.9") -> bytes:
    """GitHub API response of a release with the files the workflow publishes"""
    base = f"https://github.com/Keenny38/ModernTinyPedals/releases/download/v{version}/"
    names = [f"ModernTinyPedals-{version}{suffix}" for suffix in sorted(published_suffixes())]
    return b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps({
        "tag_name": f"v{version}", "published_at": "2026-10-06T00:00:00Z", "body": "",
        "assets": [{"name": name, "browser_download_url": base + name, "digest": f"sha256:{DIGEST}"}
                   for name in names],
    }).encode()


def legacy_installer(data: bytes) -> str:
    """Installer found by the updater of apps 0.10 to 0.19 (installed, cannot change): the .exe AND its .sha256"""
    release = json.loads(data[data.index(b"{"):].decode("utf-8"))
    assets = {str(asset["name"]): str(asset["browser_download_url"]) for asset in release["assets"]}
    for name, url in assets.items():
        if (name.endswith("-windows-setup.exe") and assets.get(f"{name}.sha256")
                and url.startswith(("https://github.com/", "https://objects.githubusercontent.com/"))):
            return name
    return ""


def test_workflow_publishes_release_files():
    assert published_suffixes() == set(RELEASE_ASSETS)


def test_every_app_updater_finds_installer():
    data = release_response()
    assert legacy_installer(data) == "ModernTinyPedals-9.9.9-windows-setup.exe"  # apps up to 0.19
    found = update.parse_installer(data)  # apps since 0.20
    assert found is not None and found.name == "ModernTinyPedals-9.9.9-setup.zip" and found.sha256 == DIGEST


def test_installer_sha256_file_in_sha256sum_format():
    """Apps up to 0.19 read the hash as first word of the .sha256 file ("<hash>  <file>")"""
    with open(WORKFLOW, encoding="utf-8") as file:
        workflow = file.read()
    assert 'installer_hash=$(sha256sum $installer' in workflow
    assert "printf '%s\\n' \"$installer_hash\" > $installer.sha256" in workflow
