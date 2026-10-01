"""Write language pack template: every UI text, message & option label to translate

Usage (from repository root):
    python tools/make_language_template.py de Deutsch [output.json]

Translate the values (empty values stay in English), then put the file in the "languages"
folder of the global config folder (Config > Open Folder > Config), and restart.
French text is given in "_reference" of each section to help translating.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tinypedal.i18n import LANGUAGE_PACK_FORMAT
from tinypedal.i18n.fr import TRANSLATION
from tinypedal.i18n.fr_messages import MESSAGE_RULES
from tinypedal.i18n.options import load_data


def build_template(code: str, name: str) -> dict:
    """Language pack with English keys & empty translations"""
    options = load_data("fr_options.json")
    option_help = load_data("fr_option_help.json")
    return {
        "format": LANGUAGE_PACK_FORMAT,
        "code": code,
        "name": name,
        "ui": {key: "" for key in TRANSLATION},
        "messages": [[pattern, ""] for pattern, _ in MESSAGE_RULES if isinstance(pattern, str)],
        "options": {key: "" for key in options},
        "option_help": {key: "" for key in option_help},
        "_reference": {
            "ui": dict(TRANSLATION),
            "messages": [[pattern, replacement] for pattern, replacement in MESSAGE_RULES
                         if isinstance(pattern, str) and isinstance(replacement, str)],
            "options": options,
        },
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    code, name = sys.argv[1], sys.argv[2]
    output = sys.argv[3] if len(sys.argv) > 3 else f"{code}.json"
    with open(output, "w", encoding="utf-8", newline="\n") as file:
        json.dump(build_template(code, name), file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Language template written to {output}")


if __name__ == "__main__":
    main()
