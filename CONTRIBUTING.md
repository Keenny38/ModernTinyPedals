# Contributing to Modern Tiny Pedals

Thank you for your interest in **Modern Tiny Pedals**! Every contribution is welcome: bug report, idea, translation or code.

Modern Tiny Pedals is a modified version of [TinyPedal](https://github.com/TinyPedal/TinyPedal) (see [NOTICE.md](NOTICE.md)). Report here what concerns this project; a problem that also exists in the original TinyPedal can be reported to both projects.

Before opening an issue, check the [wiki](https://github.com/Keenny38/ModernTinyPedals/wiki), especially [Troubleshooting](https://github.com/Keenny38/ModernTinyPedals/wiki/Troubleshooting), and search the [existing issues](https://github.com/Keenny38/ModernTinyPedals/issues?q=is%3Aissue) to avoid duplicates.

> [!IMPORTANT]
> **One request or problem per issue**, with a short title that describes it. Issues in English or French are both fine.

## Reporting a problem

Open an [issue](https://github.com/Keenny38/ModernTinyPedals/issues/new) with:

- the app version (`Help > About`), the game (Le Mans Ultimate or rFactor 2) and your system;
- what you were doing, what happened and what you expected;
- a **bug report** (`Help > Create Bug Report...`): it gathers logs, settings and system info in a ZIP file, without your personal data (user folder name, access codes).

Many problems come from other apps or plugins: disable them before testing, to rule out outside causes.

> [!WARNING]
> A **security vulnerability** must not be reported in a public issue: use [private reporting](https://github.com/Keenny38/ModernTinyPedals/security/advisories/new), as explained in [SECURITY.md](SECURITY.md).

## Suggesting an idea

Open an [issue](https://github.com/Keenny38/ModernTinyPedals/issues/new) that describes the need (what you want to see or do while racing) rather than the solution. What is already planned is in the [roadmap](docs/ROADMAP.md). The project is made in spare time: no promise on delays.

## Contributing code

Open a [pull request](https://github.com/Keenny38/ModernTinyPedals/pulls). For a big feature, open an issue first to discuss it. Pull requests must pass the `Checks` workflow before they are merged.

### Setting up

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux: .venv/bin/python
.venv/Scripts/python run.py
```

Before you submit your change, these three commands must pass (CI runs them on Windows and Linux, Python 3.13 and 3.14):

```bash
ruff check .
mypy tinypedal
pytest
```

`pre-commit install` runs ruff (with fixes) and mypy automatically on every commit; run the tests yourself. The [Development](https://github.com/Keenny38/ModernTinyPedals/wiki/Development) wiki page explains the project layout, the architecture and the release process.

### Project rules

- **Tests**: every bug fix comes with its regression test in `tests/`. CI checks the minimum coverage (`fail_under` in `pyproject.toml`).
- **Texts**: every visible text goes through `tr()` / `trm()` (interface) or `tr_overlay()` (overlays), with its French translation in `tinypedal/i18n/`. Every new option has a label and a tooltip (`tinypedal/i18n/data/`, regenerated with `tools/gen_fr_options.py` and `tools/gen_option_help.py`).
- **Presets**: a new option has a default value in `tinypedal/template/`. Renaming or removing an option needs a migration in `tinypedal/setting_preupdate.py`, so that existing presets keep loading.
- **Overlays**: a changed overlay keeps both its modern design (`tinypedal/widget/_modern/`) and its classic design. A visible change comes with a before/after image, titled in English (`python tools/make_change_visual.py <overlay> --title "..."`), shown in the release notes.
- **Interface**: test your changes in light and dark theme, and on Windows and Linux if you can. New tool pages are preferably written in Qt Quick (`tinypedal/ui/qml/`), with their logic in Python (`tinypedal/ui/quick/`).
- **Commit titles** in English, imperative mood. A title starting with "Add" publishes a minor version, the others a patch version ([tools/next_version.py](tools/next_version.py)). Commits that only change documentation (wiki, README, changelogs, this file) do not publish a release on their own.
- **Changelog**: a notable version has its section in [CHANGELOG.md](CHANGELOG.md) (English, used for the GitHub release notes) **and** in [CHANGELOG.fr.md](CHANGELOG.fr.md) (French, shown by the app in French), with the same `## X.Y.Z (date)` headings. Use the English UI labels of the app in CHANGELOG.md.
- **Documentation**: the wiki is generated from [docs/wiki](docs/wiki) on every push to `master`: update the matching page in the same pull request, never on the wiki itself.

### Game access

The app reads the game data (shared memory and the local REST API of Le Mans Ultimate). The only commands sent to the game follow an explicit user action (replay controls, for example), never automatically. No feature that changes race data or gives an advantage in competition will be accepted.

### Code written with AI

Code written with the help of AI is accepted under the same conditions as any other code: you understand it, you have reviewed it, it follows the rules above and its tests pass. Mention it in the pull request.

## License

By contributing, you agree that your code is distributed under the project license, the [GNU GPL v3 or later](LICENSE.txt).
