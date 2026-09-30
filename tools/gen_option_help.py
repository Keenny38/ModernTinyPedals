"""
Generate option help (tooltips) from docs/customization.md: tinypedal/i18n/data/option_help.json

Run from project root after editing documentation:
    python tools/gen_option_help.py

Each documented option is an indented key line (keys separated by comma, "*" wildcard),
followed by description paragraphs. Descriptions are grouped by documentation section,
which is matched to setting section name (widget, module, global config).
"""

from __future__ import annotations

import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOC = "docs/customization.md"
OUTPUT = "tinypedal/i18n/data/option_help.json"
MAX_LENGTH = 700
COMMON = "_common"  # options shared by all sections (Common terms and keywords)
SHARED_OPTIONS = ("widget_theme",)  # documented once in a section, present in every widget

SECTION_ALIAS = {
    "common terms and keywords": COMMON,
    "telemetry api": COMMON,
    "le mans ultimate api": "api_lmu",
    "rfactor 2 api": "api_rf2",
    "global font override": "",
    "tyre carcass temperature": "tyre_carcass",
    "hotkey": "",
}
_key_line = re.compile(r"^    ([a-z0-9_*]+(?:, [a-z0-9_*]+)*)\s*$")
_markdown = re.compile(r"\*\*|`|\\$")
_link = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def known_sections() -> list[str]:
    from tinypedal.setting import cfg

    cfg.default.set_default()
    sections = set()
    for name in ("config", "setting", "shortcuts"):
        sections.update(dict(getattr(cfg.default, name)))
    return sorted(sections)


def section_key(title: str, sections: list[str]) -> str:
    """Match documentation title to setting section name"""
    lower = title.strip().lower()
    if lower in SECTION_ALIAS:
        return SECTION_ALIAS[lower]
    name = lower.replace(" ", "_")
    if name.endswith("_module"):
        name = f"module_{name[:-len('_module')]}"
    if name in sections:
        return name
    match = difflib.get_close_matches(name, sections, n=1, cutoff=0.8)
    return match[0] if match else name


def clean(text: str) -> str:
    text = _link.sub(r"\1", text)
    text = _markdown.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def parse(lines: list[str], sections: list[str]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    section = ""
    keys: list[str] = []
    paragraphs: list[str] = []

    def flush():
        if keys and paragraphs:
            text = "\n\n".join(clean(paragraph) for paragraph in paragraphs if clean(paragraph))
            if len(text) > MAX_LENGTH:
                text = text[:MAX_LENGTH].rsplit(" ", 1)[0] + "…"
            for key in keys:
                output.setdefault(section, {}).setdefault(key, text)
        keys.clear()
        paragraphs.clear()

    for line in lines:
        if line.startswith("#"):
            flush()
            section = section_key(line.lstrip("#"), sections)
            continue
        match = _key_line.match(line)
        if match:
            flush()
            keys.extend(match.group(1).split(", "))
            continue
        if not keys:
            continue
        if line.startswith(("[**`Back to Top", "**")):  # end of option description
            flush()
            continue
        if not line.strip():
            if paragraphs and paragraphs[-1]:
                paragraphs.append("")
            continue
        if paragraphs and paragraphs[-1]:
            paragraphs[-1] += " " + line.strip()
        else:
            if paragraphs and not paragraphs[-1]:
                paragraphs.pop()
            paragraphs.append(line.strip())
    flush()
    for section_options in list(output.values()):
        for key in SHARED_OPTIONS:
            if key in section_options:
                output.setdefault(COMMON, {})[key] = section_options[key]
    return output


def main():
    sections = known_sections()
    with open(DOC, encoding="utf-8") as file:
        lines = file.read().splitlines()
    data = parse(lines, sections)
    unmatched = sorted(name for name in data if name and name != COMMON and name not in sections)
    if unmatched:
        print("Doc sections not matched to setting:", ", ".join(unmatched))
    count = sum(len(options) for options in data.values())
    # {"common": common section name, "help": {section name: {option key or wildcard pattern: description}}}
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as file:  # generated, do not edit by hand
        json.dump({"common": COMMON, "help": data}, file, ensure_ascii=False, indent=4, sort_keys=True)
        file.write("\n")
    print(f"{count} descriptions written to {OUTPUT}")
    # Translations are keyed by English text: edited descriptions need a new translation
    texts = {text for options in data.values() for text in options.values()}
    for translation_file in sorted(glob.glob(os.path.join(os.path.dirname(OUTPUT), "*_option_help.json"))):
        with open(translation_file, encoding="utf-8") as file:
            missing = texts - set(json.load(file))
        if missing:
            print(f"{len(missing)} descriptions not translated in {translation_file} (shown in English)")


if __name__ == "__main__":
    main()
