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
mypy neopedal
```

```bash
pytest --cov=neopedal
```

- CI fails when total coverage drops under `fail_under` in `pyproject.toml` (88 % at the time of writing; current coverage is about 91 %). There are more than 2,300 tests.
- Tests run headless in CI with `QT_QPA_PLATFORM=offscreen`, and a hung test fails after 300 seconds (`--timeout=300`).
- `pytest -m benchmark` runs the widget render benchmark (separate CI step); `pytest -m manual` runs tests that need a running game.
- `python tools/check.py` runs every check of CI in one command: ruff, mypy for Windows **and** Linux, tests with coverage (`--quick`: without tests). It also warns when a changelog lacks the section of the next version, and lints changed workflows when `actionlint` / `zizmor` are installed. `python tools/check.py --install-hook` runs it before each push to `master` (a failed check refuses the push, pushes to other branches are not checked).
- CI always installs the latest `ruff` and `mypy`. If a check fails in CI but passes locally, update them: `pip install -U ruff mypy`.
- `pre-commit install` runs JSON / YAML checks, `ruff --fix` and `mypy` before each commit (not the tests).
- The `visual-regression` job renders every overlay with the base commit and with your changes and compares them. An overlay change fails the check unless a before / after image is added in `docs/changes` (see [Visuals](#before--after-visuals)) or a commit message contains `[visual]`.
- Pull requests that change requirements go through a dependency review (known vulnerabilities fail it).

## Project layout

| Path | Content |
|---|---|
| `run.py` | Entry point, command line arguments, `multiprocessing.freeze_support()` |
| `neopedal/main.py`, `loader.py`, `safe_mode.py` | Start, single instance check, load / reload / close, safe mode |
| `neopedal/adapter/` | Shared memory readers and REST API connectors (LMU, rFactor 2) |
| `neopedal/api_connector.py`, `api_control.py` | Game API selection |
| `neopedal/module/` | Data modules (`module_delta.py`, `module_fuel.py`, `module_recorder.py`, `module_stats.py`...) |
| `neopedal/process/` | Game data processing; LMU REST data in `game_info.py` and `team_usage.py` |
| `neopedal/widget/` | Overlays: classic layout `<name>.py`, modern design `_modern/<name>.py`, Dashboard HUD (`black_box`) `_black_box/`, base class `_base.py` |
| `neopedal/template/` | Default settings; overlay defaults per category in `template/widget/<category>.py` |
| `neopedal/ui/` | Qt Widgets pages and dialogs; QML pages in `ui/qml`, their Python backends in `ui/quick` |
| `neopedal/userfile/` | File formats and data: presets, laps, MoTeC, track corners and geometry, lap geometry jobs |
| `neopedal/i18n/` | Translations (`fr.py`, `fr_messages.py`, `fr_overlay.py`) and option labels / help (`data/`) |
| `neopedal/update.py`, `command_server.py`, `web_dashboard.py`, `vr_overlay.py`, `replay.py` | Updater, remote control, web dashboard, VR, telemetry replay |
| `pyLMUSharedMemory/`, `pyRfactor2SharedMemory/` | Bundled shared memory libraries (no submodule) |
| `tests/`, `tools/`, `installer/`, `fonts/`, `images/`, `docs/` | Tests, maintenance scripts, Inno Setup script, bundled fonts, icons, documentation |

## Architecture notes

### Overlays and the modern design

- Every overlay has a modern design in `neopedal/widget/_modern/<name>.py` (the Dashboard HUD and Pace Notes restyle their classic drawing), registered in `neopedal/template/widget/modern.py` (`MODERN_DESIGN_OPTIONS`) with the options it reads: only these are shown in the Overlay Options page. That page (`neopedal/ui/overlay_options.py`, `ui/quick/overlay_options_backend.py`, `qml/OverlayOptions.qml`) cuts the options of each overlay into sections from their order in the template (`ui/quick/overlay_sections.py`: an item section starts at its `show_*` / `enable_*` option and takes the options naming that item), so keep the options of an item together after its on/off option; an overlay with many options can declare its own sections in `WIDGET_OPTION_UI` (see `black_box_ui.OptionUI`). Shared components (value tiles, tables, gauges, wheels, car colors of maps and radar in `cars.py`, restyling of classic drawing) are in the same folder. A modern design reads game data like the classic widget through a mixin of the classic module (`RadarMixin`, `TrackMapMixin`, `TrailingMixin`...), so both layouts show the same values. The Barlow font is in `fonts`.
- A changed overlay keeps both its modern design and its classic layout.
- Every built-in overlay is declared once in `neopedal/template/widget/registry.py` (`OVERLAYS`, one `overlay(name, category, ...)` line in display order: Overlays page category, modern design, preview feed, config dialog extras). Display order, default settings, keyboard shortcuts, modern designs, `WIDGET_OPTION_UI` and the Overlays page categories are derived from it; startup fails if an overlay has default options but no line there. Options read only by the modern design go in `MODERN_ONLY_OPTIONS` (`modern.py`).
- Every new option has a default value in `neopedal/template/`, a label and a help text. Renaming or removing an option needs a migration in `neopedal/setting_preupdate.py`, so existing presets still load.
- The settings format version (`SETTING_VERSION` in `neopedal/version.py`) is independent of the app version (2.x numbering), so presets load without needless migration.

### Adding an overlay / a tool page

A new overlay touches 7 files (10 before the registry): `neopedal/widget/<name>.py` (classic layout), `neopedal/widget/_modern/<name>.py` (modern design), its default options in `neopedal/template/widget/<category>.py`, one line in `neopedal/template/widget/registry.py`, then option docs in `docs/customization.md` (`python tools/gen_option_help.py` writes `option_help.json`) and French labels and help in `neopedal/i18n/data/fr_options.json` and `fr_option_help.json`. Also run `python tools/gen_widget_config_types.py` (a test checks the generated settings types). `modern.py` only when the modern design reads options of its own.

A new tool page touches 2 files (5 before): its dialog module in `neopedal/ui/` and one `PageSpec` in `neopedal/template/page_registry.py` (label, short rail label, icon glyph, `"module.DialogClass"` path, Tools section, default rail position, command palette words, on / off status function). The Tools page, menu, command palette, navigation rail, home quick access and default rail are derived from it; dialog modules are still imported only when first opened. Add the French label in `neopedal/i18n/fr.py`.

### Qt Quick pages

- The Lap Telemetry Viewer, Track Map Viewer, Driver Stats Viewer, Race Calculator and the Overlays page are QML pages in `neopedal/ui/qml`, with their state in `neopedal/ui/quick` (pure Python, testable without a display). New tool pages should preferably be Qt Quick, with logic in Python.
- Race Calculator: `race_backend.py` (QObject: inputs, actions, one property per part of the results, emitted only when that part changes), `race_model.py` (saved inputs & their ranges, texts), `race_results.py` (results as plain values for QML), `race_tyres.py` (tyre plan model), `race_picture.py` (plan picture). The hosting page `ui/race_calculator.py` gives the dialogs, toasts and undo history, and builds the QML view when first shown.
- Curves and maps are sent once to the graphics card (`GpuShape`); zooming only changes a matrix.
- The executable bundles only the QML modules listed in `neopedal/ui/quick/qml_modules.py`. A QML module newly imported by a page must be added there (a test loads every page with only these modules).
- Official corner numbers are in `neopedal/userfile/track_corners.py`, the LMU official track layouts in `neopedal/userfile/track_geometry.py`.
- A large page backend is split into parts: child QObjects exposed as constant properties (QML `backend.timing.timingRows`), holding the page weakly. The Broadcast Director page (`director_backend.py`) has `game` (state requests), `camera` (camera, HUD, playback, commands), `graphics` (broadcast graphics), `timing` (timing table) and `log` (events log); the page keeps the session state, the cuts, its jobs, its settings file and releases its parts.

### App context

`neopedal/context.py` gathers the app-wide objects (`api`, `cfg`, `minfo`, `mctrl`, `wctrl`, `octrl`). New code takes them from a context instead of module globals: widgets (`widget/_base.py`), data modules (`module/_base.py`) and page backends (`PageBackend`) have `self.ctx` (default `app_context()`, the real globals; a `ctx=` argument overrides it). Code reading game data many times a frame may keep its module globals or bind context values to locals once. Tests swap app objects with the `app_ctx` fixture (`app_ctx(mctrl=fake)`): every module's copy of the global and the default context are replaced and put back after the test, instead of patching one module's copy by hand.

### Lap viewer worker process

Heavy viewer jobs (track limits, session values) run in a separate process (`neopedal/userfile/lap_geometry.py`, which must not import Qt GUI). `multiprocessing.freeze_support()` must stay at the top of the main block of `run.py`, and any script that opens the viewer needs an `if __name__ == "__main__":` guard.

### Le Mans Ultimate REST API

The REST connection is in `neopedal/adapter/` (`lmu_restapi.py`, `restapi_connector.py`). Game data is read in `neopedal/process/game_info.py` (chat, contacts, pit entry, setup name, replays) and `neopedal/process/team_usage.py` (team stints, tyre allocation, tank capacity). The app never sends commands to the game automatically, only on an explicit user action; features that change race data or give a competitive advantage are not accepted.

### Translations (i18n)

Source strings are English; `neopedal/i18n/fr.py` maps them to French.

| Text | Function | French source |
|---|---|---|
| Interface text (labels, menus, buttons) | `tr("...")` | `neopedal/i18n/fr.py` |
| Messages with variable content | `trm(f"...")` | Regular expression rules in `neopedal/i18n/fr_messages.py` |
| Labels drawn in modern overlays (keep them short) | `tr_overlay("...")` | `neopedal/i18n/fr_overlay.py` |
| QML pages | `i18n.tr("...")`, `i18n.trm("...")` | Same tables (a test checks every page in French) |
| Option labels and help | Generated | `neopedal/i18n/data/` |

After adding options or editing the documentation, regenerate option labels and help:

```bash
python tools/gen_fr_options.py
```

```bash
python tools/gen_option_help.py
```

The second script lists help texts that have no French translation yet (`neopedal/i18n/data/fr_option_help.json`). `python tools/make_language_template.py <code> <name>` creates a language pack template (see [Presets and Settings](Presets-and-Settings.md#language-packs)).

## Windows build

```bash
pip install -r requirements-build.txt
```

```bash
python build_pyinstaller.py -c
```

The executable is built in `dist\NeoPedal` (`neopedal.exe`, program files in `lib`). `-c` removes the previous build first. The hook `tools/pyinstaller_hooks/hook-PySide6.QtQml.py` bundles only the QML modules in use (about 2 MB instead of about 300 MB with WebEngine and 3D). `requirements-build.txt` pins PyInstaller and the runtime versions used by the release workflow.

Check the build like CI does (the report file is optional, the executable has no console):

```bash
dist\NeoPedal\neopedal.exe --self-test report.txt
```

To build the installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then (with the version):

```bash
iscc /DAppVersion=0.20.0 installer\neopedal.iss
```

The installer `NeoPedal-<version>-windows-setup.exe` is written to `dist`. Its shortcut icon follows the Windows light or dark mode (`images/icon.ico` or `images/icon_dark.ico`). Icons are generated from `images/src/icon.webp` and `images/src/icon_dark.webp` with `images/export_icon.sh` (ImageMagick 7).

User folders are named `NeoPedal` (`CONFIG_ID` in `const_app.py`). `Config` > `Import Settings...` (`ui/settings_import.py`) saves an import request in the config folder and restarts; `userfile/settings_import.py` applies it on next start, before settings are loaded (current folder renamed aside, chosen folder copied, Linux data folder of the same name and `user_path` values too). `pid.log` ends with the app name (`<pid>,<create time>,NeoPedal`): a PID saved by another app is ignored. The executable is `neopedal.exe` (`APP_ID`, build folder `dist\NeoPedal`). Versions until 0.23.0 used another name (`LEGACY_NAME` in `const_app.py`), only read for compatibility: the installer removes the old executable and points shortcuts to `neopedal.exe` (older updaters run it with the folder of the running copy), `update.installed_app_folder` finds both names, plugins importing the old package name get this package (`plugin_loader.LegacyPackageFinder`), presets get their option keys renamed (`setting_preupdate`, 2.50.9), old preset packages still import, the remote control still accepts the old header besides `X-NeoPedal`, and the old OpenXR layer registration is replaced or removed (`vr_shared.LAYER_MANIFESTS`). The restart variable is `NEOPEDAL_RESTART`, the Linux desktop entry `NeoPedal.desktop` (`DESKTOP_FILE_NAME`), the SteamVR overlay key `neopedal.overlay`. Release files are named `NeoPedal-<version>-…`: every updater, also the one of 0.19, finds the installer by its end (`-setup.zip`, `-windows-setup.exe`). The repository keeps its `Keenny38/ModernTinyPedals` address: updaters up to 0.22.4 send a raw request that never follows GitHub's redirect of a renamed repository (they would find no update). Since 0.23.0, `request_latest_release` requests again with redirects followed (GitHub API host only) when the direct request gives nothing, so a rename becomes possible once most users have that version; then add the old name to `RENAMED_REPOS`.

## Release process

Releases are published **on demand**: pushes to `master` only run the `Checks` workflow, so fixes can follow each other until everything is green. When `master` is ready:

1. `python tools/check.py` passes (automatic before each push to `master` once the hook is installed), everything is pushed;
2. both changelogs have the section of the next version (see [Changelog](#changelog));
3. publish with **one** command, by one person (or one Claude session) at a time:

```bash
python tools/release.py
```

It refuses when `master` has changes not pushed, when there is nothing to release, when a changelog lacks the version section, or when `Checks` did not pass on the `master` commit (it waits while they run). Then it asks before publishing, starts the `Build and Release` workflow, follows it and checks the published files. `--dry-run` only checks. `Run workflow` on the Actions tab (branch `master`) does the same without the local checks: the workflow itself refuses a commit without passed `Checks` or without both changelog sections.

The `Build and Release` workflow computes the version, builds and self-tests the Windows executable, builds the installer and the source ZIP, attests the files, writes the release notes and publishes the release.

Commits that only change documentation (`docs/wiki/`, `README.md`, `CHANGELOG*.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/ROADMAP.md`, `docs/AUDIT.md`, images of `docs/changes` and `docs/changelog`) are not a release on their own (`tools/release.py` says there is nothing to release): they are listed in the next one.

### Versioning

The version (`MAJOR.MINOR.PATCH`, from `0.10.0`) comes from the commits since the last release tag:

- a commit title starting with `Add` (also `New`, `Create`, `Introduce`, `Support`) bumps the minor version (`0.10.3` → `0.11.0`);
- anything else bumps the patch version (`0.10.0` → `0.10.1`);
- a major version is chosen by hand: `python tools/release.py --bump major` (also `patch` and `minor`). `Run workflow` with `test_build` builds without publishing, from any branch.

Write commit titles in English, in the imperative: they become the release notes, sorted into **Added**, **Fixed** (titles starting with `Fix`, `Correct`, `Prevent`...) and **Changed**. Merge commits and commits with `[skip ci]` are left out of the notes.

Preview the next version and its notes locally:

```bash
python tools/next_version.py
```

```bash
python tools/gen_release_notes.py v0.20.0
```

### Changelog

Before publishing, run `git fetch --tags` (to start from the real last release) and `python tools/next_version.py`, then add the section of that version, `## X.Y.Z (YYYY-MM-DD)`, to **both** files:

- [`CHANGELOG.md`](https://github.com/Keenny38/ModernTinyPedals/blob/master/CHANGELOG.md), in English: the start of the GitHub release notes, and the notes the app shows in English;
- [`CHANGELOG.fr.md`](https://github.com/Keenny38/ModernTinyPedals/blob/master/CHANGELOG.fr.md), in French: the notes the app shows in French (fetched at the release tag for an available update, bundled file for the installed version).

Without both sections, `tools/release.py` and the workflow refuse to publish. The `##` to `####` headings inside a section become the cards of the app's What's New page.

### Before / after visuals

When a commit changes how an overlay looks, add a before / after image in `docs/changes` before committing. The left side renders the last commit, the right side your working tree, on the same simulated race as the README preview. Write the title in English:

```bash
python tools/make_change_visual.py black_box --title "Dashboard HUD: engine map"
```

`--set black_box.show_motor_map=true` shows an option that is off by default, `--slug` sets the file name, `--base` chooses the "before" revision. The release notes show added images in a **Visuals** section, unless the changelog section already embeds them (the app does not show images).

### Changelog screenshots

Screenshots of new app pages go in `docs/changelog` and are inserted in the changelog by their `https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/...` address, so they show on GitHub and in the release notes. The app's What's New page skips image lines.

The README preview image is generated from the real overlays, on the simulated race of `neopedal/demo_data.py` (the one the app's overlay pictures show: widget modules read it only while a picture is drawn, see `demo_globals`; `demo_state` keeps simulated cars out of user presets):

```bash
python tools/make_readme_preview.py
```

### Release files and checksums

Each release publishes the Windows installer `NeoPedal-<version>-windows-setup.exe` with its `.sha256` file (the updater of apps up to 0.19 needs both), the same installer zipped as `NeoPedal-<version>-setup.zip` (downloaded by the updater since 0.20) and `NeoPedal-<version>-source.zip`, with their SHA-256 in the release notes and a signed build provenance attestation for each file. `tests/test_release_assets.py` reads the workflow and fails when a change of release files would leave an installed app (from 0.10) without an installer to update to. The release is created as a draft, gets its files, then is published: releases are immutable. See [Updates and Security](Updates-and-Security.md#release-files).

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
