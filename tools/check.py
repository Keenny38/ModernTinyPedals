"""
Run the checks of GitHub before pushing: lint, type check (Windows & Linux), tests with coverage

Same commands as the Checks workflow, so a push to master is not the first time they run.
Also warns when the changelogs have no section for the next version (needed to publish it),
and lints edited workflows when actionlint / zizmor are installed.

Installed tools must be the versions of requirements-dev-lock.txt (what Checks install): else a warning, and
the pre-push hook refuses the push. The hook also refuses a release commit (new version section in
CHANGELOG.md) whose code never passed Checks: run tools/ci_preflight.py first.

Tests are spread over every CPU when pytest-xdist is installed (requirements-dev.txt), as on Linux CI.

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


def lock_mismatches(lock: str = "requirements-dev-lock.txt") -> list[str]:
    """Installed packages not at the version of the lock Checks install (only those for this OS & Python)"""
    from importlib import metadata

    try:
        from packaging.requirements import Requirement
    except ImportError:
        return ["packaging not installed"]
    mismatches = []
    with open(os.path.join(ROOT, lock), encoding="utf-8") as file:
        for line in file:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            requirement = Requirement(line)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            wanted = next(iter(requirement.specifier)).version
            try:
                installed = metadata.version(requirement.name)
            except metadata.PackageNotFoundError:
                installed = "not installed"
            if installed != wanted:
                mismatches.append(f"{requirement.name} {installed} (Checks: {wanted})")
    return mismatches


def new_release_versions(base: str, head: str) -> list[str]:
    """Versions whose section the commits base..head add to CHANGELOG.md (a release commit)"""
    diff = git("diff", "--unified=0", base, head, "--", "CHANGELOG.md")
    return [line[4:].split()[0] for line in diff.splitlines()
            if line.startswith("+## ") and line[4:5].isdigit()]


def release_without_checks() -> str:
    """Refusal message when a push to master adds a release section to the changelog while its code never
    passed Checks (master or tools/ci_preflight.py), empty if fine. NEOPEDAL_SKIP_PREFLIGHT=1: not checked"""
    if os.environ.get("NEOPEDAL_SKIP_PREFLIGHT") == "1":
        return ""
    head = git("rev-parse", "HEAD")
    base = git("rev-parse", "--verify", "--quiet", "origin/master")
    versions = new_release_versions(base, head) if base else []
    if not versions:
        return ""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from ci_preflight import passed_base

        if passed_base(head):
            return ""
    except (OSError, ValueError, subprocess.CalledProcessError, SystemExit) as error:
        return f"release {', '.join(versions)}: Checks state not read ({error})"
    return (f"release {', '.join(versions)}: Checks never passed on this code. Run python tools/ci_preflight.py "
            "first (whole matrix on a branch, master untouched), then push again")


def parallel_test_args() -> list[str]:
    """pytest-xdist arguments: tests spread over every CPU, none if not installed (one process)"""
    import importlib.util

    if importlib.util.find_spec("xdist") is None:
        print("(pytest-xdist not installed: tests run in one process, pip install -r requirements-dev.txt)")
        return []
    return ["-n", "auto"]


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
    if options.pre_push and (refusal := release_without_checks()):
        print(f"Push to master refused: {refusal}")
        return 1

    mismatches = lock_mismatches()
    if mismatches:
        print("Installed versions differ from the ones of Checks (requirements-dev-lock.txt):")
        print("\n".join(f"  {item}" for item in mismatches))
        print(f"Fix: {sys.executable} -m pip install -r requirements-dev-lock.txt")
        if options.pre_push:
            print("Push to master refused: the checks would not test what Checks run")
            return 1

    python = sys.executable
    checks: list[tuple[str, list[str], dict | None]] = [
        ("ruff", [python, "-m", "ruff", "check", "."], None),
        ("mypy (Windows)", [python, "-m", "mypy", "--platform", "win32", "neopedal"], None),
        ("mypy (Linux)", [python, "-m", "mypy", "--platform", "linux", "neopedal"], None),
    ]
    checks += [(title, command, None) for title, command in workflow_linters()]
    if not options.quick:
        checks.append(("tests with coverage", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                               *parallel_test_args(), "--timeout=300", "--cov=neopedal",
                                               "--cov-report=term:skip-covered"],
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
