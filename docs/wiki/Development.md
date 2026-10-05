# Development

This page is for contributors and maintainers: running from source, checks, project layout, Windows build and release process. The contribution rules are in [CONTRIBUTING.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/CONTRIBUTING.md).

## Set up

You need Python 3.11 or newer (CI tests 3.11, 3.13 and 3.14 on Windows and Linux).

```bash
git clone https://github.com/Keenny38/ModernTinyPedals.git
```

```bash
cd ModernTinyPedals
```

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

On Linux: `source .venv/bin/activate`.

```bash
pip install -r requirements-dev.txt
```

```bash
python run.py
```

`requirements-dev.txt` adds pytest (with coverage and timeout plugins), ruff, mypy and pre-commit to `requirements.txt`. `requirements-lock.txt` pins the runtime versions tested for releases. From a git checkout, the app shows the last release tag and the commits since (for example `0.19.1+3.g8a0f9f3`) and does not offer to update to the release it started from.

## Checks

These run in CI (`Checks` workflow) and must pass before a pull request is merged:

```bash
ruff check .
```

```bash
mypy tinypedal
```

```bash
pytest --cov=tinypedal
```

- CI fails when total coverage drops under `fail_under` in `pyproject.toml` (88 % at the time of writing; current coverage is about 91 %). There are more than 2,300 tests.
- Tests run headless in CI with `QT_QPA_PLATFORM=offscreen`, and a hung test fails after 300 seconds (`--timeout=300`).
- `pytest -m benchmark` runs the widget render benchmark (separate CI step); `pytest -m manual` runs tests that need a running game.
- CI always installs the latest `ruff` and `mypy`. If a check fails in CI but passes locally, update them: `pip install -U ruff mypy`.
- `pre-commit install` runs JSON / YAML checks, `ruff --fix` and `mypy` before each commit (not the tests).
- The `visual-regression` job renders every overlay with the base commit and with your changes and compares them. An overlay change fails the check unless a before / after image is added in `docs/changes` (see [Visuals](#before--after-visuals)) or a commit message contains `[visual]`.
- Pull requests that change requirements go through a dependency review (known vulnerabilities fail it).

## Project layout

| Path | Content |
|---|---|
| `run.py` | Entry point, command line arguments, `multiprocessing.freeze_support()` |
| `tinypedal/main.py`, `loader.py`, `safe_mode.py` | Start, single instance check, load / reload / close, safe mode |
| `tinypedal/adapter/` | Shared memory readers and REST API connectors (LMU, rFactor 2) |
| `tinypedal/api_connector.py`, `api_control.py` | Game API selection |
| `tinypedal/module/` | Data modules (`module_delta.py`, `module_fuel.py`, `module_recorder.py`, `module_stats.py`...) |
| `tinypedal/process/` | Game data processing; LMU REST data in `game_info.py` and `team_usage.py` |
| `tinypedal/widget/` | Overlays: classic layout `<name>.py`, modern design `_modern/<name>.py`, Black box `_black_box/`, base class `_base.py` |
| `tinypedal/template/` | Default settings; overlay defaults per category in `template/widget/<category>.py` |
| `tinypedal/ui/` | Qt Widgets pages and dialogs; QML pages in `ui/qml`, their Python backends in `ui/quick` |
| `tinypedal/userfile/` | File formats and data: presets, laps, MoTeC, track corners and geometry, lap geometry jobs |
| `tinypedal/i18n/` | Translations (`fr.py`, `fr_messages.py`, `fr_overlay.py`) and option labels / help (`data/`) |
| `tinypedal/update.py`, `command_server.py`, `web_dashboard.py`, `vr_overlay.py`, `replay.py` | Updater, remote control, web dashboard, VR, telemetry replay |
| `pyLMUSharedMemory/`, `pyRfactor2SharedMemory/` | Bundled shared memory libraries (no submodule) |
| `tests/`, `tools/`, `installer/`, `plugins/`, `fonts/`, `images/`, `docs/` | Tests, maintenance scripts, Inno Setup script, example plugin, bundled fonts, icons, documentation |

## Architecture notes

### Overlays and the modern design

- Every overlay except the Black box has a modern design in `tinypedal/widget/_modern/<name>.py`, registered in `tinypedal/template/widget/modern.py` (`MODERN_DESIGN_OPTIONS`) with the options it reads: only these are shown in its config page. Shared components (value tiles, tables, gauges, wheels, restyling of graphic overlays) are in the same folder. The Barlow font is in `fonts`.
- A changed overlay keeps both its modern design and its classic layout.
- A new overlay needs its default options in `tinypedal/template/widget/<category>.py` and an entry in `WIDGET_DISPLAY_ORDER` (`tinypedal/template/widget/__init__.py`): startup fails if it is missing. Its category in the `Overlays` page comes from name prefixes in `tinypedal/ui/quick/overlay_backend.py` (`WIDGET_CATEGORIES`).
- Every new option has a default value in `tinypedal/template/`, a label and a help text. Renaming or removing an option needs a migration in `tinypedal/setting_preupdate.py`, so existing presets still load.
- The settings format version (`SETTING_VERSION` in `tinypedal/version.py`) is independent of the app version and stays on the TinyPedal 2.x numbering, so presets load without needless migration.

### Qt Quick pages

- The Lap Telemetry Viewer, Track Map Viewer, Driver Stats Viewer, Race Calculator and the Overlays page are QML pages in `tinypedal/ui/qml`, with their state in `tinypedal/ui/quick` (pure Python, testable without a display). New tool pages should preferably be Qt Quick, with logic in Python.
- Race Calculator: `race_backend.py` (QObject: inputs, actions, one property per part of the results, emitted only when that part changes), `race_model.py` (saved inputs & their ranges, texts, share code), `race_results.py` (results as plain values for QML), `race_tyres.py` (tyre plan model), `race_picture.py` (plan picture). The hosting page `ui/race_calculator.py` gives the dialogs, toasts and undo history, and builds the QML view when first shown.
- Curves and maps are sent once to the graphics card (`GpuShape`); zooming only changes a matrix.
- The executable bundles only the QML modules listed in `tinypedal/ui/quick/qml_modules.py`. A QML module newly imported by a page must be added there (a test loads every page with only these modules).
- Official corner numbers are in `tinypedal/userfile/track_corners.py`, the LMU official track layouts in `tinypedal/userfile/track_geometry.py`.

### Lap viewer worker process

Heavy viewer jobs (track limits, session values) run in a separate process (`tinypedal/userfile/lap_geometry.py`, which must not import Qt GUI). `multiprocessing.freeze_support()` must stay at the top of the main block of `run.py`, and any script that opens the viewer needs an `if __name__ == "__main__":` guard.

### Le Mans Ultimate REST API

The REST connection is in `tinypedal/adapter/` (`lmu_restapi.py`, `restapi_connector.py`). Game data is read in `tinypedal/process/game_info.py` (chat, contacts, pit entry, setup name, replays) and `tinypedal/process/team_usage.py` (team stints, tyre allocation, tank capacity). The app never sends commands to the game automatically, only on an explicit user action; features that change race data or give a competitive advantage are not accepted.

### Translations (i18n)

Source strings are English; `tinypedal/i18n/fr.py` maps them to French.

| Text | Function | French source |
|---|---|---|
| Interface text (labels, menus, buttons) | `tr("...")` | `tinypedal/i18n/fr.py` |
| Messages with variable content | `trm(f"...")` | Regular expression rules in `tinypedal/i18n/fr_messages.py` |
| Labels drawn in modern overlays (keep them short) | `tr_overlay("...")` | `tinypedal/i18n/fr_overlay.py` |
| QML pages | `i18n.tr("...")`, `i18n.trm("...")` | Same tables (a test checks every page in French) |
| Option labels and help | Generated | `tinypedal/i18n/data/` |

After adding options or editing the documentation, regenerate option labels and help:

```bash
python tools/gen_fr_options.py
```

```bash
python tools/gen_option_help.py
```

The second script lists help texts that have no French translation yet (`tinypedal/i18n/data/fr_option_help.json`). `python tools/make_language_template.py <code> <name>` creates a language pack template (see [Presets and Settings](Presets-and-Settings.md#language-packs)).

## Windows build

```bash
pip install -r requirements-build.txt
```

```bash
python build_pyinstaller.py -c
```

The executable is built in `dist\TinyPedal` (`tinypedal.exe`, program files in `lib`). `-c` removes the previous build first. The hook `tools/pyinstaller_hooks/hook-PySide6.QtQml.py` bundles only the QML modules in use (about 2 MB instead of about 300 MB with WebEngine and 3D). `requirements-build.txt` pins PyInstaller and the runtime versions used by the release workflow.

Check the build like CI does (the report file is optional, the executable has no console):

```bash
dist\TinyPedal\tinypedal.exe --self-test report.txt
```

To build the installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then (with the version):

```bash
iscc /DAppVersion=0.20.0 installer\tinypedal.iss
```

The installer `ModernTinyPedals-<version>-windows-setup.exe` is written to `dist`. Its shortcut icon follows the Windows light or dark mode (`images/icon.ico` or `images/icon_dark.ico`). Icons are generated from `images/src/icon.webp` and `images/src/icon_dark.webp` with `images/export_icon.sh` (ImageMagick 7).

The display name is "Modern Tiny Pedals", but the internal name stays `TinyPedal` (config folder `%APPDATA%\TinyPedal`, `tinypedal.exe`, `X-TinyPedal` header of the remote control) to keep existing settings and tool compatibility.

## Release process

Releases are automatic: every push to `master` publishes a new release once the `Checks` workflow passes. The `Build and Release` workflow computes the version, builds and self-tests the Windows executable, builds the installer and the source ZIP, attests the files, writes the release notes and publishes the release.

Commits that only change documentation (`docs/wiki/`, `README.md`, `CHANGELOG*.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/ROADMAP.md`, `docs/AUDIT.md`, images of `docs/changes` and `docs/changelog`) do not publish a release on their own: they are listed in the next release.

### Versioning

The version (`MAJOR.MINOR.PATCH`, from `0.10.0`) comes from the commits since the last release tag:

- a commit title starting with `Add` (also `New`, `Create`, `Introduce`, `Support`) bumps the minor version (`0.10.3` → `0.11.0`);
- anything else bumps the patch version (`0.10.0` → `0.10.1`);
- a major version is chosen by hand: run `Build and Release` from the Actions tab with `bump: major`. The manual run also offers `patch` and `minor`, and `test_build` to build without publishing (any branch).

Write commit titles in English, in the imperative: they become the release notes, sorted into **Added**, **Fixed** (titles starting with `Fix`, `Correct`, `Prevent`...) and **Changed**. Merge commits and commits with `[skip ci]` are left out of the notes.

Preview the next version and its notes locally:

```bash
python tools/next_version.py
```

```bash
python tools/gen_release_notes.py v0.20.0
```

### Changelog

Before pushing, run `git fetch --tags` (to start from the real last release), then add the section of the next version, `## X.Y.Z (YYYY-MM-DD)`, to **both** files:

- [`CHANGELOG.md`](https://github.com/Keenny38/ModernTinyPedals/blob/master/CHANGELOG.md), in English: the start of the GitHub release notes, and the notes the app shows in English;
- [`CHANGELOG.fr.md`](https://github.com/Keenny38/ModernTinyPedals/blob/master/CHANGELOG.fr.md), in French: the notes the app shows in French (fetched at the release tag for an available update, bundled file for the installed version).

Without a section, the release notes only list commits and the workflow shows a warning. The `##` to `####` headings inside a section become the cards of the app's What's New page.

### Before / after visuals

When a commit changes how an overlay looks, add a before / after image in `docs/changes` before committing. The left side renders the last commit, the right side your working tree, on the same simulated race as the README preview. Write the title in English:

```bash
python tools/make_change_visual.py black_box --title "Black box: engine map"
```

`--set black_box.show_motor_map=true` shows an option that is off by default, `--slug` sets the file name, `--base` chooses the "before" revision. The release notes show added images in a **Visuals** section, unless the changelog section already embeds them (the app does not show images).

### Changelog screenshots

Screenshots of new app pages go in `docs/changelog` and are inserted in the changelog by their `https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/...` address, so they show on GitHub and in the release notes. The app's What's New page skips image lines.

The README preview image is generated from the real overlays:

```bash
python tools/make_readme_preview.py
```

### Release files and checksums

Each release publishes `ModernTinyPedals-<version>-setup.zip` (the Windows installer inside) and `ModernTinyPedals-<version>-source.zip`, with their SHA-256 in the release notes and a signed build provenance attestation for each file. The release is created as a draft, gets its files, then is published: releases are immutable. See [Updates and Security](Updates-and-Security.md#release-files).

### Code signing

The workflow signs the executable and the installer when signing is configured in the `release` environment of the repository (open to `master` only); otherwise they are published unsigned:

- a `.pfx` certificate: secrets `WINDOWS_CERT_PFX_BASE64` (base64 of the file) and `WINDOWS_CERT_PASSWORD`;
- or Azure Artifact Signing: variables `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT`, `AZURE_SIGNING_PROFILE` and secrets `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (used only without a `.pfx`).

Details are in `.github/workflows/build-release.yml`.

## Wiki

This wiki is generated from `docs/wiki/` in the repository by the `.github/workflows/wiki.yml` workflow, on every push to `master` that changes `docs/wiki/`. **Edit the files in the repository, not the wiki**: changes made on the wiki are overwritten.

- One Markdown file per page (`Home.md`, `Getting-Started.md`...), plus `_Sidebar.md` and `_Footer.md`.
- Link pages with their file name, `.md` included (`[Installation](Installation.md#linux)`), so links also work when browsing the repository; the workflow removes `.md` for the wiki.
- Link repository files with absolute `https://github.com/Keenny38/ModernTinyPedals/blob/master/<path>` addresses, and images with `https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/<path>`.
- GitHub creates the wiki repository only once a first page exists: the wiki must have been initialized once from the `Wiki` tab.

## Contributing

- Open an [issue](https://github.com/Keenny38/ModernTinyPedals/issues) first for a large feature.
- Every bug fix comes with a regression test in `tests/`.
- Test UI changes in light and dark theme, and if possible on Windows and Linux.
- AI-assisted code is accepted on the same terms as other code: you understand it, reviewed it, it follows the rules and its tests pass. Mention it in the pull request.
- Contributions are distributed under the project license, the GNU GPL v3 or later.

Full rules: [CONTRIBUTING.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/CONTRIBUTING.md). Security issues: [SECURITY.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/SECURITY.md).
