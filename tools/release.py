"""
Publish a release of master: one command, checked before and after

Refuses when master has local changes not pushed, nothing to release, a changelog without the version
section, or Checks not passed on the master commit (waits while they run). Then starts the
"Build and Release" workflow, follows it, and checks the published files (installer .exe, its .sha256,
setup ZIP, source ZIP: every app updater finds its installer).

Usage (from project root, GitHub CLI logged in):
    python tools/release.py               publish next version (asks before publishing)
    python tools/release.py --dry-run     only check, publish nothing
    python tools/release.py --yes         no question
    python tools/release.py --bump minor  version bump other than from commit titles
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "Keenny38/ModernTinyPedals"
WORKFLOW = "build-release.yml"
# Files of every release (name: ModernTinyPedals-<version><suffix>). Apps up to 0.19 update only with the
# installer .exe & its .sha256 file, apps since 0.20 with the setup ZIP (else the .exe), see tinypedal/update.py
RELEASE_ASSETS = ("-windows-setup.exe", "-windows-setup.exe.sha256", "-setup.zip", "-source.zip")
POLL = 30  # seconds between GitHub checks


def run(*command: str, check: bool = True) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"Failed: {' '.join(command)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def gh_json(*args: str):
    return json.loads(run("gh", *args) or "null")


def stop(message: str) -> int:
    print(f"\nRelease refused: {message}")
    return 1


def checks_state(sha: str) -> tuple[str, list[str]]:
    """State of Checks on commit: success, failure, running or missing; names of failed jobs"""
    runs = gh_json("run", "list", "--repo", REPO, "--workflow", "checks.yml", "--commit", sha, "--limit", "5",
                   "--json", "databaseId,status,conclusion,event")
    runs = [item for item in runs or [] if item["event"] in ("push", "workflow_dispatch")]
    if not runs:
        return "missing", []
    if any(item["conclusion"] == "success" for item in runs):
        return "success", []
    latest = runs[0]
    if latest["status"] != "completed":
        return "running", []
    jobs = gh_json("run", "view", str(latest["databaseId"]), "--repo", REPO, "--json", "jobs")["jobs"]
    return "failure", [f"{job['name']} ({job['conclusion']})" for job in jobs if job["conclusion"] != "success"]


def wait_checks(sha: str) -> tuple[str, list[str]]:
    state, failed = checks_state(sha)
    while state in ("running", "missing"):
        print(f"Checks of {sha[:7]}: {'running' if state == 'running' else 'not started yet'}, waiting...", flush=True)
        time.sleep(POLL)
        state, failed = checks_state(sha)
    return state, failed


def start_release(bump: str) -> int:
    """Start release workflow on master, id of its run"""
    before = {item["databaseId"] for item in gh_json(
        "run", "list", "--repo", REPO, "--workflow", WORKFLOW, "--limit", "10", "--json", "databaseId") or []}
    run("gh", "workflow", "run", WORKFLOW, "--repo", REPO, "--ref", "master", "-f", f"bump={bump}")
    for _ in range(20):
        time.sleep(3)
        for item in gh_json("run", "list", "--repo", REPO, "--workflow", WORKFLOW, "--limit", "10",
                            "--json", "databaseId,event") or []:
            if item["databaseId"] not in before and item["event"] == "workflow_dispatch":
                return int(item["databaseId"])
    raise SystemExit("Release workflow started, but its run was not found: see the Actions tab on GitHub")


def follow(run_id: int) -> str:
    """Wait for workflow run, printing job changes, its conclusion"""
    shown: set[str] = set()
    while True:
        data = gh_json("run", "view", str(run_id), "--repo", REPO, "--json", "status,conclusion,jobs")
        for job in data["jobs"]:
            line = f"  {job['name']}: {job['conclusion'] or job['status']}"
            if line not in shown:
                shown.add(line)
                print(line, flush=True)
        if data["status"] == "completed":
            return data["conclusion"]
        time.sleep(POLL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--bump", choices=("auto", "patch", "minor", "major"), default="auto")
    parser.add_argument("--dry-run", action="store_true", help="check only, publish nothing")
    parser.add_argument("--yes", action="store_true", help="do not ask before publishing")
    options = parser.parse_args()

    run("gh", "auth", "status")
    run("git", "fetch", "--quiet", "--tags", "origin")
    if run("git", "branch", "--show-current") != "master":
        return stop("switch to master first")
    if run("git", "status", "--porcelain", "--untracked-files=no"):
        return stop("master has uncommitted changes: commit and push them, or stash them")
    sha = run("git", "rev-parse", "HEAD")
    if sha != run("git", "rev-parse", "origin/master"):
        return stop("local master differs from GitHub: push your commits (or pull) first")

    version = run(sys.executable, "tools/next_version.py", "--bump", options.bump)
    if not version:
        return stop("nothing to release since the last version (or only documentation changed)")
    print(f"Next version: {version} (master {sha[:7]})")
    for changelog in ("CHANGELOG.md", "CHANGELOG.fr.md"):
        if subprocess.run([sys.executable, "tools/gen_release_notes.py", "--check-changelog", version,
                           "--changelog", changelog], cwd=ROOT, capture_output=True, check=False).returncode:
            return stop(f"{changelog} has no '## {version}' section: write it (both languages), commit, push")
    print("Changelogs: both have the section")

    state, failed = wait_checks(sha)
    if state != "success":
        return stop(f"Checks failed on {sha[:7]}: {', '.join(failed)}. Cancelled jobs (GitHub outage): "
                    "rerun them with \"gh run rerun <id> --failed\", then run this again")
    print("Checks: passed")
    if options.dry_run:
        print(f"\nReady to publish {version} (dry run: nothing published)")
        return 0
    if not options.yes and input(f"\nPublish {version}? [y/N] ").strip().lower() not in ("y", "yes", "o", "oui"):
        return stop("cancelled")

    run_id = start_release(options.bump)
    print(f"Release workflow: https://github.com/{REPO}/actions/runs/{run_id}")
    conclusion = follow(run_id)
    if conclusion != "success":
        return stop(f"release workflow {conclusion}: see https://github.com/{REPO}/actions/runs/{run_id}")

    release = gh_json("release", "view", f"v{version}", "--repo", REPO, "--json", "url,assets")
    names = {asset["name"] for asset in release["assets"]}
    missing = [f"ModernTinyPedals-{version}{suffix}" for suffix in RELEASE_ASSETS
               if f"ModernTinyPedals-{version}{suffix}" not in names]
    if missing:
        print(f"\nPublished, but files are missing: {', '.join(missing)}")
        return 1
    print(f"\nPublished {version}: {release['url']}")
    for name in sorted(names):
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
