"""
Run the Checks workflow of GitHub on the working tree, without touching master nor the working tree

Takes every file of the working tree (committed or not, new files included, ignored files left out) into a
commit on top of HEAD, pushes it to a "preflight/<date>" branch of GitHub and starts Checks on it: the whole
matrix (3 Python versions x 2 OS), not only this PC. Uses a temporary git index: the working tree, the index and
the current branch stay as they are (other sessions can keep editing). Run it at the end of each working day and
before writing a release commit: tools/check.py refuses to push a release commit to master whose code had no
passed Checks (0.28.0: nine days of work met the CI the night of the release, nine red runs).

Usage (from project root, GitHub CLI logged in):
    python tools/ci_preflight.py             snapshot, push, start Checks and wait for the result
    python tools/ci_preflight.py --no-wait   start only (result: gh run list --workflow checks.yml)
    python tools/ci_preflight.py --yes       do not ask before including new (untracked) files
    python tools/ci_preflight.py --status    has the current code passed Checks (master or preflight)?
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from release import REPO, checks_state, follow, gh_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRANCH_PREFIX = "preflight/"
KEEP_BRANCHES = 5  # older preflight branches deleted from GitHub
# Files a change of which does not need Checks again (a release commit: changelogs, README, change images, wiki)
DOC_ONLY = ("CHANGELOG.md", "CHANGELOG.fr.md", "README.md", "README.*.md", "docs/changes/*", "docs/wiki/*")


def git(*args: str, env: dict | None = None, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False,
                            env={**os.environ, **(env or {})})
    if check and result.returncode != 0:
        raise SystemExit(f"Failed: git {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def snapshot() -> tuple[str, list[str]]:
    """Commit of the whole working tree on top of HEAD (temporary index), untracked files it includes"""
    index = os.path.join(ROOT, git("rev-parse", "--git-path", "preflight-index"))
    env = {"GIT_INDEX_FILE": index}
    try:
        git("read-tree", "HEAD", env=env)
        git("add", "--all", ".", env=env)
        tree = git("write-tree", env=env)
        added = git("diff", "--cached", "--name-only", "--diff-filter=A", "HEAD", env=env).splitlines()
    finally:
        if os.path.exists(index):
            os.remove(index)
    tracked = set(git("ls-files").splitlines())
    untracked = [path for path in added if path not in tracked]
    message = f"Preflight of the working tree on {git('rev-parse', '--short', 'HEAD')}"
    sha = git("commit-tree", tree, "-p", "HEAD", "-m", message)
    return sha, untracked


def doc_only(paths: list[str]) -> bool:
    return all(any(fnmatch.fnmatch(path, pattern) for pattern in DOC_ONLY) for path in paths)


def passed_base(sha: str, limit: int = 30) -> str | None:
    """Commit with passed Checks (master or preflight) whose code is the code of sha: same files, or only
    documentation differs. None if no such commit (Checks never ran on this code)"""
    runs = gh_json("run", "list", "--repo", REPO, "--workflow", "checks.yml", "--status", "success",
                   "--limit", str(limit), "--json", "headSha,event")
    for item in runs or []:
        if item["event"] not in ("push", "workflow_dispatch"):
            continue
        base = item["headSha"]
        if subprocess.run(["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=ROOT,
                          capture_output=True, check=False).returncode:
            git("fetch", "--quiet", "origin", base, check=False)  # pushed from another clone
        diff = subprocess.run(["git", "diff", "--name-only", base, sha], cwd=ROOT, capture_output=True, text=True,
                              check=False)
        if diff.returncode == 0 and doc_only([path for path in diff.stdout.splitlines() if path]):
            return base
    return None


def start_checks(branch: str) -> int:
    """Start Checks on branch, id of its run"""
    before = {item["databaseId"] for item in gh_json(
        "run", "list", "--repo", REPO, "--workflow", "checks.yml", "--branch", branch, "--json", "databaseId") or []}
    subprocess.run(["gh", "workflow", "run", "checks.yml", "--repo", REPO, "--ref", branch], cwd=ROOT, check=True,
                   capture_output=True)
    for _ in range(20):
        time.sleep(3)
        for item in gh_json("run", "list", "--repo", REPO, "--workflow", "checks.yml", "--branch", branch,
                            "--json", "databaseId") or []:
            if item["databaseId"] not in before:
                return int(item["databaseId"])
    raise SystemExit("Checks started, but the run was not found: see the Actions tab on GitHub")


def prune_branches(current: str) -> None:
    """Delete older preflight branches from GitHub (their runs stay listed)"""
    refs = git("ls-remote", "--heads", "origin", f"refs/heads/{BRANCH_PREFIX}*", check=False).splitlines()
    branches = sorted(line.split("refs/heads/", 1)[1] for line in refs if "refs/heads/" in line)
    for branch in [name for name in branches if name != current][:-KEEP_BRANCHES or None]:
        git("push", "--quiet", "origin", "--delete", branch, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--no-wait", action="store_true", help="start Checks, do not wait for the result")
    parser.add_argument("--yes", action="store_true", help="do not ask before including untracked files")
    parser.add_argument("--status", action="store_true", help="has the current code passed Checks?")
    options = parser.parse_args()

    subprocess.run(["gh", "auth", "status"], cwd=ROOT, capture_output=True, check=True)
    sha, untracked = snapshot()
    base = passed_base(sha)
    if options.status:
        print(f"Code passed Checks on {base[:7]}" if base else "Checks never passed on this code: run tools/ci_preflight.py")
        return 0 if base else 1
    if base:
        print(f"Checks already passed on this code ({base[:7]}): nothing to run")
        return 0

    if untracked:
        print(f"New files included ({len(untracked)}), not in git yet:")
        print("\n".join(f"  {path}" for path in untracked))
        if not options.yes and input("Include them and push to GitHub? [y/N] ").strip().lower() not in (
                "y", "yes", "o", "oui"):
            print("Cancelled: add the files to .gitignore, or run again")
            return 1
    branch = f"{BRANCH_PREFIX}{time.strftime('%Y-%m-%d-%H%M%S')}"
    git("push", "--quiet", "origin", f"{sha}:refs/heads/{branch}")
    run_id = start_checks(branch)
    print(f"Checks on {branch} ({sha[:7]}): https://github.com/{REPO}/actions/runs/{run_id}")
    prune_branches(branch)
    if options.no_wait:
        return 0
    conclusion = follow(run_id)
    if conclusion == "success":
        print(f"\nChecks passed: this code can go to master and into a release ({sha[:7]})")
        return 0
    _, failed = checks_state(sha)
    print(f"\nChecks {conclusion}: {', '.join(failed)}")
    print(f"Failed tests: gh run view {run_id} --repo {REPO} --log-failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
