"""
Generate release notes (the changelog shown on GitHub Releases) from git history

Notes list the commits since the previous release tag (vX.Y.Z), sorted by kind from
their first word: Add... (Added), Fix... (Fixed), everything else (Changed).
Used by the "Build and Release" workflow; the app shows the same notes in its
update notification. Write clear commit titles, there is no changelog file to edit.

Usage (from project root):
    python tools/gen_release_notes.py v2.51.0      notes of v2.51.0 (commits up to HEAD if tag is new)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import NamedTuple

REPO_URL = "https://github.com/Keenny38/ModernTinyPedals"
TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
SKIP_PATTERN = re.compile(r"\[skip ci\]|^Merge |^Update changelog", re.IGNORECASE)
KINDS = (
    ("added", "Added", re.compile(r"^(Add|Adds|Added|New|Create|Introduce|Support)\b", re.IGNORECASE)),
    ("fixed", "Fixed", re.compile(r"^(Fix|Fixes|Fixed|Correct|Repair|Prevent|Stop|Avoid)\b", re.IGNORECASE)),
    ("changed", "Changed", re.compile(r"")),
)


class Commit(NamedTuple):
    sha: str
    date: str
    title: str


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, encoding="utf-8").stdout


def release_tags() -> list[tuple[str, str]]:
    """Release tags (name, date), newest first"""
    output = git("tag", "--list", "v*", "--sort=-creatordate", "--format=%(refname:short)\t%(creatordate:short)")
    tags = []
    for line in output.splitlines():
        name, _, date = line.partition("\t")
        if TAG_PATTERN.match(name):
            tags.append((name, date))
    return tags


def commits(revision_range: str) -> list[Commit]:
    """Commits in range, newest first, without merge & bot commits"""
    output = git("log", "--no-merges", "--format=%h\t%ad\t%s", "--date=short", revision_range)
    result = []
    for line in output.splitlines():
        sha, date, title = line.split("\t", 2)
        if not SKIP_PATTERN.search(title):
            result.append(Commit(sha, date, title.strip()))
    return result


def kind_of(title: str) -> str:
    for kind, _, pattern in KINDS:
        if pattern.search(title):
            return kind
    return "changed"


def format_notes(items: list[Commit]) -> str:
    """Commits grouped by kind, as Markdown"""
    if not items:
        return "No changes.\n"
    lines = []
    for kind, label, _ in KINDS:
        group = [commit for commit in items if kind_of(commit.title) == kind]
        if group:
            lines += [f"### {label}", ""]
            lines += [f"- {commit.title} ([{commit.sha}]({REPO_URL}/commit/{commit.sha}))" for commit in group]
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def release_notes(tag: str) -> str:
    """Notes of one release: commits since previous tag (tag may not exist yet: use HEAD)"""
    tags = [name for name, _ in release_tags()]
    if tag in tags:
        index = tags.index(tag)
        previous = tags[index + 1] if index + 1 < len(tags) else ""
        end = tag
    else:
        previous = tags[0] if tags else ""
        end = "HEAD"
    items = commits(f"{previous}..{end}" if previous else end)
    return format_notes(items)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("tag", help="release tag, for example v2.51.0")
    sys.stdout.write(release_notes(parser.parse_args().tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
