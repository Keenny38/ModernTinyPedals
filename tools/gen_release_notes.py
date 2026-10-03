"""
Generate release notes (the changelog shown on GitHub Releases) from git history

Notes start with the section of the version in CHANGELOG.md ("## X.Y.Z ..."), if written,
then list the commits since the previous release tag (vX.Y.Z), sorted by kind from
their first word: Add... (Added), Fix... (Fixed), everything else (Changed).
Before / after images of overlay changes added in the same commits under docs/changes
(tools/make_change_visual.py) follow in a Visuals section, captioned by their Title.
Used by the "Build and Release" workflow; the app shows the same notes in its
update notification, without the Visuals section. Write clear commit titles, and
describe notable releases in CHANGELOG.md (optional).

Usage (from project root):
    python tools/gen_release_notes.py v2.51.0      notes of v2.51.0 (commits up to HEAD if tag is new)
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
import zlib
from typing import NamedTuple

REPO_URL = "https://github.com/Keenny38/ModernTinyPedals"
RAW_URL = "https://raw.githubusercontent.com/Keenny38/ModernTinyPedals"
VISUALS_DIR = "docs/changes"
CHANGELOG = "CHANGELOG.md"
CHANGELOG_VERSION = re.compile(r"^## (\d+\.\d+\.\d+)\b")
VISUALS_HEADING = "### Visuals"  # app cuts notes here (images are not shown in its dialog)
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


class Visual(NamedTuple):
    sha: str
    path: str
    title: str


def png_title(data: bytes) -> str:
    """Title text chunk of a PNG image (tEXt, zTXt or iTXt), empty if none"""
    position = 8  # after signature
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        chunk = data[position + 8:position + 8 + length]
        position += 12 + length
        keyword, _, rest = chunk.partition(b"\0")
        if keyword != b"Title":
            continue
        try:
            if kind == b"tEXt":
                return rest.decode("latin-1")
            if kind == b"zTXt":
                return zlib.decompress(rest[1:]).decode("latin-1")
            if kind == b"iTXt":
                compressed, text = rest[0], rest[2:].split(b"\0", 2)[-1]  # skip language & keyword
                return (zlib.decompress(text) if compressed else text).decode("utf-8")
        except (IndexError, ValueError, zlib.error):
            return ""
    return ""


def visuals(revision_range: str) -> list[Visual]:
    """Images added under docs/changes in range, oldest first"""
    output = git("log", "--no-merges", "--reverse", "--diff-filter=A", "--name-only", "--format=@%H",
                 revision_range, "--", f"{VISUALS_DIR}/*.png")
    result = []
    sha = ""
    for line in output.splitlines():
        if line.startswith("@"):
            sha = line[1:]
        elif line.strip():
            path = line.strip()
            data = subprocess.run(["git", "show", f"{sha}:{path}"], capture_output=True, check=True).stdout
            title = png_title(data) or path.rsplit("/", 1)[-1][:-4]
            result.append(Visual(sha, path, title))
    return result


def format_visuals(items: list[Visual]) -> str:
    """Visuals section, as Markdown (empty if no image)"""
    if not items:
        return ""
    lines = [VISUALS_HEADING, ""]
    for visual in items:
        lines += [f"**{visual.title}**", "", f"![{visual.title}]({RAW_URL}/{visual.sha}/{visual.path})", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def changelog_section(version: str, filename: str = CHANGELOG) -> str:
    """Body of version section in changelog (without its heading), empty if none"""
    try:
        with open(filename, encoding="utf-8") as file:
            lines = file.read().splitlines()
    except OSError:
        return ""
    body: list[str] = []
    inside = False
    for line in lines:
        match = CHANGELOG_VERSION.match(line)
        if match or line.startswith("## "):
            if inside:
                break
            inside = bool(match) and match.group(1) == version
            continue
        if inside:
            body.append(line)
    return "\n".join(body).strip("\n") + "\n" if any(line.strip() for line in body) else ""


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
    revision_range = f"{previous}..{end}" if previous else end
    notes = format_notes(commits(revision_range))
    summary = changelog_section(tag.removeprefix("v"))
    if summary:  # written changelog first, then commits
        notes = f"{summary}\n## Commits\n\n{notes}"
    images = format_visuals(visuals(revision_range))
    return f"{notes}\n{images}" if images else notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("tag", help="release tag, for example v2.51.0")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # notes are UTF-8 (console codepage on Windows)
    sys.stdout.write(release_notes(parser.parse_args().tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
