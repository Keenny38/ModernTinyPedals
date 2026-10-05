"""
Next release version from commits since the last release tag

Semantic versioning, MAJOR.MINOR.PATCH:
    - first release: version from tinypedal/version.py (0.10.0)
    - a commit title starting with "Add" (new feature) since last release: minor + 1, patch 0
    - otherwise (fixes, changes): patch + 1
    - no commit since last release: prints nothing (no release)
Commits that only change documentation (wiki pages, README, changelogs, CONTRIBUTING...,
see DOCS_ONLY) do not publish a release on their own: they are listed in the next one.
A major version (1.0.0...) is chosen by hand: run the release workflow with bump "major".

Usage (from project root):
    python tools/next_version.py [--bump auto|patch|minor|major]
    python tools/next_version.py --write 0.11.0     set tinypedal/version.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen_release_notes import commits, git, kind_of, release_tags

VERSION_FILE = os.path.join("tinypedal", "version.py")
VERSION_LINE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)
# Documentation files: a commit changing only these does not change the app
DOCS_ONLY = re.compile(
    r"^(?:docs/wiki/|docs/changes/|docs/changelog/|\.github/ISSUE_TEMPLATE/"
    r"|(?:README|CHANGELOG(?:\.[\w-]+)?|CONTRIBUTING|SECURITY)\.md$"
    r"|docs/(?:ROADMAP|AUDIT)\.md$|images/readme_preview\.png$)"
)


def is_docs_only(sha: str) -> bool:
    """Commit only changes documentation files"""
    files = [path for path in git("diff-tree", "-z", "--no-commit-id", "--name-only", "-r", "--root", sha)
             .split("\0") if path]
    return bool(files) and all(DOCS_ONLY.match(path) for path in files)


def file_version() -> tuple[int, int, int]:
    with open(VERSION_FILE, encoding="utf-8") as file:
        match = VERSION_LINE.search(file.read())
    if match is None:
        raise ValueError(f"no __version__ in {VERSION_FILE}")
    return int(match[1]), int(match[2]), int(match[3])


def write_version(version: str) -> None:
    with open(VERSION_FILE, encoding="utf-8") as file:
        text = file.read()
    text = VERSION_LINE.sub(f'__version__ = "{version}"', text)
    with open(VERSION_FILE, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)


def next_version(bump: str = "auto") -> str:
    """Next version string, empty if nothing to release"""
    tags = release_tags()
    if not tags:
        return "{}.{}.{}".format(*file_version())
    last = tags[0][0]
    major, minor, patch = (int(part) for part in last.lstrip("v").split("."))
    items = [commit for commit in commits(f"{last}..HEAD") if not is_docs_only(commit.sha)]
    if not items and bump == "auto":
        return ""
    if bump == "auto":
        bump = "minor" if any(kind_of(commit.title) == "added" for commit in items) else "patch"
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--bump", choices=("auto", "patch", "minor", "major"), default="auto")
    parser.add_argument("--write", metavar="VERSION", help="write VERSION to tinypedal/version.py")
    args = parser.parse_args()
    if args.write:
        write_version(args.write)
        return 0
    print(next_version(args.bump))
    return 0


if __name__ == "__main__":
    sys.exit(main())
