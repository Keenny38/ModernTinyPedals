"""
Run the checks of GitHub before pushing: lint, type check (Windows & Linux), tests with coverage

Same commands as the Checks workflow, so a push to master is not the first time they run.
Also warns when the changelogs have no section for the next version (needed to publish it),
and lints edited workflows when actionlint / zizmor are installed.

Usage (from project root):
    python tools/check.py                 every check (about 4 minutes)
    python tools/check.py --quick         without tests
    python tools/check.py --install-hook  run every check before each push to master (git pre-push hook)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOOK = """#!/bin/sh
# Installed by "python tools/check.py --install-hook": every check before a push to master
# (pushes to other branches are not checked)
while read -r local_ref local_sha remote_ref remote_sha; do
  if [ "$remote_ref" = "refs/heads/master" ]; then
    to_master=1
  fi
done
[ -z "$to_master" ] && exit 0
python=python3
[ -x .venv/Scripts/python.exe ] && python=.venv/Scripts/python.exe
[ -x .venv/bin/python ] && python=.venv/bin/python
exec "$python" tools/check.py --pre-push
"""


def run(title: str, command: list[str], env: dict | None = None) -> bool:
    """Run one check, True if passed"""
    print(f"\n=== {title}", flush=True)
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env={**os.environ, **(env or {})}, check=False)
    passed = result.returncode == 0
    print(f"--- {title}: {'passed' if passed else 'FAILED'} ({time.monotonic() - started:.0f} s)", flush=True)
    return passed


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def uncommitted_changes() -> list[str]:
    """Tracked files changed but not committed (untracked files ignored)"""
    return [line for line in git("status", "--porcelain", "--untracked-files=no").splitlines() if line.strip()]


def changelog_warnings() -> list[str]:
    """Changelogs without section of next version (a release needs both)"""
    version = subprocess.run([sys.executable, "tools/next_version.py", "--bump", "auto"], cwd=ROOT,
                             capture_output=True, text=True, check=False).stdout.strip()
    if not version:
        return []
    missing = []
    for changelog in ("CHANGELOG.md", "CHANGELOG.fr.md"):
        result = subprocess.run([sys.executable, "tools/gen_release_notes.py", "--check-changelog", version,
                                 "--changelog", changelog], cwd=ROOT, capture_output=True, check=False)
        if result.returncode != 0:
            missing.append(f"{changelog} has no '## {version}' section (needed to publish {version})")
    return missing


def workflow_linters() -> list[tuple[str, list[str]]]:
    """actionlint & zizmor on workflows changed since origin/master, if installed"""
    changed = [path for path in git("diff", "--name-only", "origin/master", "--", ".github/workflows").splitlines()
               if path.endswith((".yml", ".yaml")) and os.path.exists(os.path.join(ROOT, path))]
    if not changed:
        return []
    linters = []
    for name, args in (("actionlint", []), ("zizmor", ["--offline"])):
        executable = shutil.which(name)
        if executable:
            linters.append((f"{name} (workflows)", [executable, *args, *changed]))
        else:
            print(f"(workflows changed: {name} not installed, skipped)")
    return linters


def install_hook() -> int:
    hooks = git("rev-parse", "--git-path", "hooks")
    path = os.path.join(ROOT, hooks, "pre-push")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as file:
            if "tools/check.py" not in file.read():
                print(f"{path} already exists (not from tools/check.py): not replaced")
                return 1
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(HOOK)
    os.chmod(path, 0o755)
    print(f"Installed {path}: every check runs before each push to master")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="skip tests")
    parser.add_argument("--install-hook", action="store_true", help="install git pre-push hook")
    parser.add_argument("--pre-push", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.install_hook:
        return install_hook()

    if options.pre_push and uncommitted_changes():
        print("Push to master refused: commit or stash your changes first, the checks would not test what you push:")
        print("\n".join(uncommitted_changes()))
        return 1

    python = sys.executable
    checks: list[tuple[str, list[str], dict | None]] = [
        ("ruff", [python, "-m", "ruff", "check", "."], None),
        ("mypy (Windows)", [python, "-m", "mypy", "--platform", "win32", "tinypedal"], None),
        ("mypy (Linux)", [python, "-m", "mypy", "--platform", "linux", "tinypedal"], None),
    ]
    checks += [(title, command, None) for title, command in workflow_linters()]
    if not options.quick:
        checks.append(("tests with coverage", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                               "--timeout=300", "--cov=tinypedal", "--cov-report=term:skip-covered"],
                       {"QT_QPA_PLATFORM": "offscreen"}))

    failed = [title for title, command, env in checks if not run(title, command, env)]
    warnings = changelog_warnings()
    print()
    for warning in warnings:
        print(f"Warning: {warning}")
    if failed:
        print(f"FAILED: {', '.join(failed)}" + (" (push refused)" if options.pre_push else ""))
        return 1
    print("Every check passed" + (" (tests skipped)" if options.quick else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
