"""
Generate CHANGELOG.md from git history

Commits are grouped by release tag (vX.Y.Z), newest first; commits after the last tag
go under "Unreleased". Within a version, commits are sorted by kind from their first
word: Add... (added), Fix... (fixed), everything else (changed).

Usage (from project root):
    python tools/gen_changelog.py                 write CHANGELOG.md
    python tools/gen_changelog.py --check         exit 1 if CHANGELOG.md is out of date
    python tools/gen_changelog.py --release v2.51.0
                                                  print notes of one version (release body)

Runs on every push to GitHub (.github/workflows/changelog.yml), so the file never needs
editing by hand: write clear commit titles instead.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import NamedTuple

OUTPUT = "CHANGELOG.md"
REPO_URL = "https://github.com/Keenny38/overlays"
TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
SKIP_PATTERN = re.compile(r"\[skip ci\]|^Merge |^Update changelog", re.IGNORECASE)
KINDS = (
    ("added", "Added", re.compile(r"^(Add|Adds|Added|New|Create|Introduce|Support)\b", re.IGNORECASE)),
    ("fixed", "Fixed", re.compile(r"^(Fix|Fixes|Fixed|Correct|Repair|Prevent|Stop|Avoid)\b", re.IGNORECASE)),
    ("changed", "Changed", re.compile(r"")),
)
UNRELEASED = "Unreleased"


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


def versions() -> list[tuple[str, str, list[Commit]]]:
    """(version, date, commits) newest first, including unreleased commits"""
    tags = release_tags()
    # Each range ends at a version (HEAD for unreleased) and starts at the next older tag
    ends = [(UNRELEASED, "", "HEAD"), *((name, date, name) for name, date in tags)]
    starts = [name for name, _ in tags] + [""]
    result = []
    for (name, date, end), start in zip(ends, starts):
        items = commits(f"{start}..{end}" if start else end)
        if items or name != UNRELEASED:
            result.append((name, date, items))
    return result


def format_version(name: str, date: str, items: list[Commit], heading: str = "##") -> str:
    title = name if name == UNRELEASED else f"[{name}]({REPO_URL}/releases/tag/{name})"
    lines = [f"{heading} {title}" + (f" - {date}" if date and name != UNRELEASED else ""), ""]
    if not items:
        lines += ["No changes.", ""]
    for kind, label, _ in KINDS:
        group = [commit for commit in items if kind_of(commit.title) == kind]
        if not group:
            continue
        lines += [f"### {label}", ""]
        lines += [f"- {commit.title} ([{commit.sha}]({REPO_URL}/commit/{commit.sha}))" for commit in group]
        lines.append("")
    return "\n".join(lines)


def changelog() -> str:
    header = (
        "# Changelog\n\n"
        "All changes of Modern Tiny Pedals, generated from commit history on every push "
        "(`tools/gen_changelog.py`). Do not edit by hand.\n\n"
        "The changelog of the original TinyPedal releases (2.50.0 and older) is in "
        "[docs/changelog.txt](docs/changelog.txt).\n"
    )
    return header + "\n" + "\n".join(format_version(*version) for version in versions()).rstrip("\n") + "\n"


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
    body = format_version(tag, "", items, heading="##").split("\n", 2)[2]  # drop version title
    return body.rstrip("\n") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if CHANGELOG.md is out of date")
    parser.add_argument("--release", metavar="TAG", help="print release notes of TAG")
    args = parser.parse_args()
    if args.release:
        sys.stdout.write(release_notes(args.release))
        return 0
    text = changelog()
    try:
        with open(OUTPUT, encoding="utf-8") as file:
            current = file.read()
    except OSError:
        current = ""
    if args.check:
        return 0 if current == text else 1
    if current != text:
        with open(OUTPUT, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        print(f"{OUTPUT} updated")
    else:
        print(f"{OUTPUT} already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
