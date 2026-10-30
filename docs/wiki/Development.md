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
- `pytest -n auto` (pytest-xdist) spreads the tests over every CPU, about 3 times faster; CI does it on Linux. A test opening a server uses a port of its own per worker (`PYTEST_XDIST_WORKER`).
- `pytest -m benchmark` runs the widget render benchmark (separate CI step); `pytest -m manual` runs tests that need a running game.
- **Recorded game sessions** (`tests/test_recorded_sessions.py`): real Le Mans Ultimate recordings in `tests/fixtures/sessions` are played frame by frame through the reader of the app, every data module (in lock step: each module computes every frame once, in the same order every run) and every overlay in both designs. Module values are checked against the game values of the recording (fuel, lap times, field, pit stops, consumption history, driver stats distance), and the facts written in the `.json` next to each recording. To add one (rain, multiclass race, safety car...): record a session with `Tools` > `Advanced` > session recorder, then `python tools/make_replay_fixture.py SOURCE.tpreplay tests/fixtures/sessions/NAME.tpreplay --start S --end S` keeps that part at 2 frames per second without the telemetry of the other cars (a few MB for 4 minutes), replaces your driver name everywhere and removes chat messages; write `NAME.json` with what the session holds (see the existing one).
- **Startup ratchet** (`tests/test_startup_imports.py`): imports of app start are measured with `python -X importtime` in a new interpreter. Tool pages, overlays, services, QML and charts must load when first used; the number of app modules imported at startup and their import time have a ceiling. Lower `MAX_APP_MODULES` when startup gets lighter.
- `python tools/check.py` runs every check of CI in one command: ruff, mypy for Windows **and** Linux, tests with coverage spread over every CPU when `pytest-xdist` is installed (`--quick`: without tests). It also warns when a changelog lacks the section of the next version, and lints changed workflows when `actionlint` / `zizmor` are installed. `python tools/check.py --install-hook` runs it before each push to `master` (a failed check refuses the push, pushes to other branches are not checked).
- CI installs `requirements-dev.txt` with `requirements-lock.txt` as constraints (`pip install -r requirements-dev.txt -c requirements-lock.txt`): runtime packages at the versions of release builds, the latest `ruff` and `mypy`. If a check fails in CI but passes locally, update them: `pip install -U ruff mypy`. `pyproject.toml` reads its dependencies from `requirements.txt`.
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
| `neopedal/ui/` | Qt Widgets pages and dialogs; QML pages in `ui/qml` (`components/` shared Tp* controls, one folder per zone: `home/`, `config/`, `overlays/`, `director/`, `telemetry/`, `analysis/`), their Python backends in `ui/quick` |
| `neopedal/userfile/` | File formats and data: presets, laps, MoTeC, track corners and geometry, lap geometry jobs |
| `neopedal/i18n/` | Translations (`fr.py`, `fr_messages.py`, `fr_overlay.py`) and option labels / help (`data/`) |
| `neopedal/update.py`, `command_server.py`, `web_dashboard.py`, `vr_overlay.py`, `replay.py` | Updater, remote control, web dashboard, VR, telemetry replay |
| `pyLMUSharedMemory/`, `pyRfactor2SharedMemory/` | Bundled shared memory libraries (no submodule) |
| `tests/`, `tools/`, `installer/`, `fonts/`, `images/`, `docs/` | Tests, maintenance scripts, Inno Setup script, bundled fonts, icons, documentation |

## Architecture notes

### Overlays and the modern design

- Every overlay has a modern design in `neopedal/widget/_modern/<name>.py` (the Dashboard HUD and Pace Notes restyle their classic drawing), registered in `neopedal/template/widget/modern.py` (`MODERN_DESIGN_OPTIONS`) with the options it reads: only these are shown in the Overlay Options page. That page (`neopedal/ui/overlay_options.py`, `ui/quick/overlay_options_backend.py`, `qml/overlays/OverlayOptions.qml`) cuts the options of each overlay into sections from their order in the template (`ui/quick/overlay_sections.py`: an item section starts at its `show_*` / `enable_*` option and takes the options naming that item), so keep the options of an item together after its on/off option; an overlay with many options can declare its own sections in `WIDGET_OPTION_UI` (see `black_box_ui.OptionUI`). Shared components (value tiles, tables, gauges, wheels, car colors of maps and radar in `cars.py`, restyling of classic drawing) are in the same folder. A modern design reads game data like the classic widget through a mixin of the classic module (`RadarMixin`, `TrackMapMixin`, `TrailingMixin`...), so both layouts show the same values. The Barlow font is in `fonts`.
- A changed overlay keeps both its modern design and its classic layout.
- Every built-in overlay is declared once in `neopedal/template/widget/registry.py` (`OVERLAYS`, one `overlay(name, category, ...)` line in display order: Overlays page category, modern design, preview feed, config dialog extras). Display order, default settings, keyboard shortcuts, modern designs, `WIDGET_OPTION_UI` and the Overlays page categories are derived from it; startup fails if an overlay has default options but no line there. Options read only by the modern design go in `MODERN_ONLY_OPTIONS` (`modern.py`).
- Every new option has a default value in `neopedal/template/`, a label and a help text. Renaming or removing an option needs a migration in `neopedal/setting_preupdate.py`, so existing presets still load.
- The settings format version (`SETTING_VERSION` in `neopedal/version.py`) is independent of the app version (2.x numbering), so presets load without needless migration.

### Adding an overlay / a tool page

A new overlay touches 7 files (10 before the registry): `neopedal/widget/<name>.py` (classic layout), `neopedal/widget/_modern/<name>.py` (modern design), its default options in `neopedal/template/widget/<category>.py`, one line in `neopedal/template/widget/registry.py`, then option docs in `docs/customization.md` (`python tools/gen_option_help.py` writes `option_help.json`) and French labels and help in `neopedal/i18n/data/fr_options.json` and `fr_option_help.json`. Also run `python tools/gen_widget_config_types.py` (a test checks the generated settings types). `modern.py` only when the modern design reads options of its own.

A new tool page touches 2 files (5 before): its dialog module in `neopedal/ui/` and one `PageSpec` in `neopedal/template/page_registry.py` (label, short rail label, icon glyph, `"module.DialogClass"` path, Tools section, default rail position, command palette words, on / off status function, one-line `description` and `wiki` user guide page opened by the help button; `listed=False` keeps it off the Tools page and menu, like Settings). The Tools page, menu, command palette, navigation rail, home quick access and default rail are derived from it; dialog modules are still imported only when first opened. Add the French label & description in `neopedal/i18n/fr.py`. The short rail label is a short form of the label (`Race Calculator` → `Calculator`), and the window title of the page is its label. A dialog page that is not a `PageSpec` (Overlay Options, Find Option, What's New...) gets its help page from `DIALOG_WIKI` of the same file (`tests/test_ui_audit_2026_10_29_navigation.py` checks that every wiki page and anchor exists).

Shown as a page, a dialog gets the shell header of `app_tab_view.DialogPage`: breadcrumb (page opened from, else page shown when it opened: `Home ›`, `Tools ›`...), title in the `TpText` title look and one `Close` (navigation bar tools: title only) (the dialog's own `Close` buttons are hidden). Class attributes: `OWNS_TITLE = True` when its page shows its own title (found by itself for a Qt Quick `TpPageHeader` with a title), `ESC_CLOSES = False` when Esc must never close it (Broadcast Director). Shell popups (command palette, notification center, keyboard shortcuts) are Qt Quick pages in `ui/qml/shell/` hosted by `quick/shell_popup.ShellPopup` (frameless popup window, closed by a click outside, Esc or the page, deleted once closed). Messages of background work go to the notification center with `app_signal.error` (or `notification.notification_store().add(text, severity, actions)`); window shortcuts get a `whatsThis` text to be listed by the keyboard shortcuts sheet.

### Qt Quick pages

- The Lap Telemetry Viewer, Track Map Viewer, Session Recorder (`telemetry/SessionRecorder.qml`, `quick/session_recorder_backend.py`, playback bar shared with the lap viewer: `PlaybackBar.qml` takes either the lap viewer charts or a player's values and signals), Driver Stats, Race Calculator and the Overlays page are QML pages in `neopedal/ui/qml`, with their state in `neopedal/ui/quick` (pure Python, testable without a display). New tool pages should preferably be Qt Quick, with logic in Python.
- QML files: shared components in `ui/qml/components/`, pages and their panels in one folder per zone (`home`, `config`, `overlays`, `director`, `telemetry`, `analysis`). A zone file imports the folders it uses (`import "../components"`, `import "../director"`...). Python loads pages by file name (`create_quick_view(parent, "Overlays.qml")`, `quick.qml_path(name)` finds the subfolder); QML text written elsewhere (tests, tools) gets every folder with `quick.qml_folder_imports()`.
- Race Calculator: `race_backend.py` (QObject: inputs, actions, one property per part of the results, emitted only when that part changes), `race_model.py` (saved inputs & their ranges, texts), `race_results.py` (results as plain values for QML), `race_tyres.py` (tyre plan model), `race_picture.py` (plan picture). The hosting page `ui/race_calculator.py` gives the dialogs, toasts and undo history, and builds the QML view when first shown.
- Curves and maps are sent once to the graphics card (`GpuShape`); zooming only changes a matrix.
- The executable bundles only the QML modules listed in `neopedal/ui/quick/qml_modules.py`. A QML module newly imported by a page must be added there (a test loads every page with only these modules).
- Official corner numbers are in `neopedal/userfile/track_corners.py`, the LMU official track layouts in `neopedal/userfile/track_geometry.py`.
- A large page backend is split into parts: child QObjects exposed as constant properties (QML `backend.timing.timingRows`), holding the page weakly. The Broadcast Director page (`director_backend.py`) has `game` (state requests), `camera` (camera, HUD, playback, commands), `graphics` (broadcast graphics), `timing` (timing table) and `log` (events log); the page keeps the session state, the cuts, its jobs, its settings file and releases its parts.
- Texts from outside the app (names other online players chose, results files, shared laps, downloaded sheets, file names) are never markup. A QML `Text` bound to a value says `textFormat: Text.PlainText`; `Text.StyledText` only for markup built from escaped values (`html.escape` in Python, an `esc()` function in QML). Tooltip objects are `TpToolTip` (`ToolTip.text` uses the engine's shared tooltip, set to plain text), menus are `TpMenu`, and a Basic `Button`/`ItemDelegate`/`MenuItem` showing a value needs its own `contentItem`. `tests/test_security_lot_a.py` fails otherwise. Qt Widgets messages escape their values too: toasts, `confirm_action` and `message_text()` keep only `<b>`, `<i>`, `<br>` and `<code>` (`safe_markup`). QML page engines have no network (`secure_engine`), and links of pages open through `quick.open_web_link` (https only, never another scheme).

### QML design system

Pages take every size, color and timing from the `theme` context object (`neopedal/ui/quick/__init__.py`, copied into a QML object so bindings never call Python) and are built from the shared `Tp*` components. `tests/test_qml_design_tokens.py` keeps it that way: ratchets count raw values (tints, breakpoints, button heights, em spacings, hex colors, `Qt.lighter` / `Qt.darker`, `theme.dark ?`, numeric `tint()` alphas, `"white"` / `"black"`, copied control heights, delay literals, icon sizes in em, raw action glyphs, `theme.base` fills, `EmptyState` used directly, pulse durations) and fail when one is added; lower a ceiling when you remove some. Shared components hold none of them; raw `BusyIndicator`, `ProgressBar`, `ToolTip {}`, `radiusXl`, half-faded buttons and accent hover borders are refused.

| Need | Use |
|---|---|
| Spacing | `theme.space1`..`space6` (0.2 to 1.2 em), `padPage` (page margins), `padCard` (card padding), `padPopup` |
| Heights | `controlHeight` / `controlHeightSm` / `controlHeightXs` (`TpButton { size: "sm" }`), `fieldHeight`, rows `rowCompact` / `row` / `rowTall`, table column headers `headerHeight`, tags & count badges `chipHeight` / `chipHeightSm`, filter chips `chipFilterHeight` / `chipFilterHeightSm` |
| Icons | `iconXs` (in chips, tags, menu checks & chevrons), `iconSm` (beside small texts, rows, tiles), `iconMd` (default of `Icon` and buttons), `iconLg` (compact empty states, section badges), `iconHero` (empty states, drop zones, page badges) |
| Corners | controls (buttons, fields, combo boxes, segmented, menu items, tabs, swatches) `radiusSm` (about 4 px), cards, card rows, popups, menus & toasts `radiusLg` (about 8 px), surfaces nested in a card (previews, inner tiles, frames) `radiusMd`, small parts `radiusXs`; marks of a few pixels (bars, ticks) keep a pixel radius; `radiusXl` is not used; Legacy themes halve them all |
| Surfaces | `surfacePage` < `surfaceCard` (cards, panels, tiles) < `surfaceFlyout` (popups, menus, toasts, tooltips, with `TpShadow`); `surfaceSunken` (fields, segmented tracks, pressed cards), `surfaceHover` (hovered clickable card); strokes `strokeSubtle` (cards, rows, dividers; `cardBorder` is the same) and `strokeStrong` (hovered control outline); `scrim` under modal popups |
| Text | `TpText { role }` (table below), `displayFont` / `displayStyle`; page title `TpPageHeader`, card / popup title `TpCardHeader` (`level: "card"` or `"popup"`), section label `TpSectionLabel` (overline role) |
| Colors | palette roles, status `gain` / `loss` / `warning` / `purple` / `gold` (colorblind safe variants follow the overlay style option), `accentFill` / `accentHover` / `accentPressed` and `lossFill` / `lossHover` / `lossPressed` under `accentInk` (white), `headerTint` (card header icons: accent, dim on Legacy), `plotBase` / `plotBorder`, chart lines `chartGrid` (grid & ticks) / `chartAxis` (axes & zero lines), `mapRoad` (track surface of maps), `stage*` (overlay preview: `stageInk`, `stageScrim`), `legacy` |
| Glyphs | `theme.glyphs.<action>`: one glyph per action on every page (table below) |
| Functions | `tint(color, "subtle" \| "selected" \| "strong" \| "outline" \| "stripe")`, `tintInk(color)` (text in a tint of its color), `rowColor(hovered, selected)`, `dimOn(background)`, `inkOn(fill)`, `tone(name)` (backend tone strings), `sessionColor(code)`, `compound(name)` |
| Timing | `motionFast` / `motionBase` / `motionSlow`, `tipDelay`, `hoverIntentDelay` (hover before a hover-only action shows), `flashDuration` (corrected value flagged, row flash), `pulseDuration` (each half of a status pulse: `TpPulseDot`, `TpTally`, loading placeholders) |
| Text spacing | `letterSpacingOverline` (overline texts, capitals of column headers), `letterSpacingCode` (codes read out character by character) |
| Components | `TpButton`, `TpToolbar` + `TpAction` (text, then icons only, then a "⋯" menu as room runs out), `TpSwitch`, `TpSegmented`, `TpCombo`, `TpTabBar`, `TpChip` (filter chip, `interactive: false` for a tag of a value, `removable`), `TpSlider`, `TpTextField`, `NumberField`, `TpSearchField`, `TpMenu`, `TpDialog` / `TpConfirmDialog` / `TpPopup`, `TpDialogHost`, `TpToast`, `TpToolTip`, `TpShadow`, `TpText`, `Card`, `TpSectionCard`, `TpCardHeader`, `TpPageHeader`, `TpStatTile`, `TpKeyValue`, `TpMeter`, `TpListRow`, `TpHeaderCell`, `TpStateView`, `TpSpinner`, `TpNotice`, `Pill`, `TpCountBadge`, `TpTally`, `TpPulseDot`, `TpIconTile`, `TpRankLine`, `TpHudAction`, `TpTransportButton`, `TpColorSwatch`, `TpDropZone`, `ColorDot`, `FocusRing` |

Action glyphs (`theme.glyphs`, from `GLYPHS` in `neopedal/ui/quick/__init__.py`; `glyph: theme.glyphs.export`, with a `fallback` text for systems without the icon font):

| Action | Key | Glyph |
|---|---|---|
| Add, New | `add` | `E710` |
| Remove (out of a list, a filter, a selection: the item stays elsewhere), Clear | `remove` | `E711` |
| Close | `close` | `E711` |
| Delete (to trash, or for good) | `delete` | `E74D` |
| Copy, Duplicate | `copy` | `E8C8` |
| Undo, Restore | `undo` / `restore` | `E7A7` |
| Reset to default | `reset` | `E777` |
| Refresh, Ask again | `refresh` | `E72C` |
| Open Folder (in the file explorer) | `openFolder` | `E8DA` |
| Choose a folder or a file (browse) | `browse` | `E838` |
| Open a file, Import | `openFile` / `import` | `E8E5` |
| Export (to a file) | `export` | `EDE1` |
| Share (picture, code, file for someone else) | `share` | `E72D` |
| Open in browser or another app | `openExternal` | `E8A7` |
| Edit | `edit` | `E70F` |
| More actions ("⋯" menu) | `more` | `E712` |
| Favorite (outline: add, filled: is a favorite) | `favorite` / `favoriteOn` | `E734` / `E735` |
| Lock: the state is shown (locked: lock), the text or tip tells the action | `lock` / `unlock` | `E72E` / `E785` |

Type roles (`TpText { role: "caption"; text: ... }`, plain text & cut with "..." by default, any font or color set by the page wins):

| Role | Size | Weight | Color | Use |
|---|---|---|---|---|
| `display` | `fontDisplay` | DemiBold, display face | text | key figure of a page |
| `title` | `fontTitle` | DemiBold, display face | text | page title |
| `subtitle` | `fontSubtitle` | DemiBold | text | card & section titles |
| `body` | base | Normal | text | running text (default) |
| `label` | `fontLabel` | Normal | text | field & setting labels, list names |
| `caption` | `fontCaption` | Normal | dimText | help & detail lines |
| `overline` | `fontCaption`, capitals, `letterSpacingOverline` | DemiBold | dimText | small label above a group |
| `numeric` | base, tabular figures | Normal | text | numbers & times (`tabular: true` for any role) |

The display face is Segoe UI Variable Display: the FreeType font engine of the app lists no "Segoe UI Variable" family, so its file is loaded once (about 1 MB) and its "Semibold Display" instance picked by style name; other systems use the app font.

Rules:

- **Responsive**: page modes switch at `theme.bpCompact` / `bpNarrow` / `bpWide` (a content-tuned threshold carries a `// content-tuned` comment). Toolbars wrap (`Flow`) or move rare actions into a menu and show icons only below `bpWide`; multi-column pages stack their columns into tabs below `bpWide`; wide tables scroll horizontally; on ultrawide screens cards keep a reading width. Rows or bars that come and go keep their height (no layout jump).
- **Feedback**: an action without confirmation shows a toast with **Undo** (`TpToast { actionText }`), and Undo never disappears together with the state it undoes; only irreversible actions (file deletion, full reset) ask first with `TpConfirmDialog` (QML) or `_common.confirm_action` (widgets): Cancel, then a button named after the action, Esc cancels. Copy and export confirm with a short toast. A data panel always uses `TpStateView` (loading, empty, error) centered in the panel, never "nothing recorded" while loading. Fields validate as you type (`invalid`), Esc puts the value back, `NumberField` tells its range (`showRange`) and flags clamped values. Popups holding typed input close only with Esc or their buttons (`dismissOnOutside: false`).
- **Saving**: turning an overlay, a module or a server on or off is immediate everywhere (a switch, never a pending change); option values stay pending in editors until applied (`Apply`, `Ctrl+S`). A switch following a backend value is `checkable: false` with `onClicked: backend.set(!backend.value)`: a checkable `TpSwitch` would break its `checked:` binding at the first click.
- **Surfaces & elevation**: a card is `Card` / `TpSectionCard` on `surfaceCard`, never `theme.base` with its own border; popups, menus, toasts and tooltips sit on `surfaceFlyout` with a soft shadow (`TpShadow`: one static blurred 9-patch, `tools/gen_shadow.py`, scaled by `shadowExtent`, opacity `shadowOpacity`; no `QtQuick.Effects`, no layer). A clickable card shows hover with `surfaceHover` (pressed: `surfaceSunken`) and a focus ring; the accent stays for selection and the main action, never a hover border.
- **Tabs, modes & menus**: `TpTabBar` moves between contents (tabs of a page); `TpSegmented` picks a mode or a filter of the same content (options as texts, or `{ text, glyph, fallback, tip }`: icon & text, or icon only with its tip). A menu opened by a button uses `menu.toggleBelow(button)` (`toggleBelow(button, true)` aligns right edges): opens below the button with the theme gap, a second click on the button closes it, keyboard focus goes back to the button after Esc.
- **Page header & cards**: a page title row is `TpPageHeader` (title in the display face, `status: [Pill {...}]` right after it, `count`, `subtitle`, actions as children). Cards are `TpSectionCard` (`eyebrow`, icon `glyph` / `fallback` / `tint`, `title`, `count`, `actions`, `trailing`, content, `footer` buttons at the bottom; `clickable` + `onOpened`; `spacing` between content items), never a `Card` with its own `TpCardHeader` or a title made by hand; a popup or panel header is `TpCardHeader { level: "popup"; closable: true; onClosed: ... }` (title, `count`, actions as children, then the close button; `closeTip` adds " (Esc)" in popup windows). An error badge is `Pill { solid: true; tint: theme.lossFill; glyph; fallback }` everywhere (overlays & modules), over an overlay preview `Pill { onStage: true }`; an on-air light `TpTally`, a status dot `TpPulseDot` (a few pulses at `pulseDuration`, then still). A count is a `TpCountBadge` (`tone`: `"neutral"`, `"accent"` when something is on, `"error"` with a "!" mark); a tag of a value is `TpChip { interactive: false }` (removable with its ✕), a status `Pill`. A key figure is a `TpStatTile` (tile with tint strip) or a `TpKeyValue` (label & value); four page tiles stay their own on purpose: Home `Figure` (value first in the display face, then its label: on-track figures read at a glance, with a "/24" suffix), lap viewer `ReadingTile` (lap color dot, signed value with words under it), Director sheet `Stat` (compound badges in place of the value) and track map `InfoCard` (value over several detail lines).
- **Lists & tables**: every row background is `TpListRow` (hover `theme.hover`, pressed `surfaceSunken`, selected accent tint, emphasized own tint; `card: true` for rows drawn as cards: card surface, `surfaceHover`, tinted outline when selected). Row heights `rowCompact` (dense tables), `row` (lists), `rowTall` (two text lines); column headers `headerHeight` (`TpHeaderCell`). Striping: dense tables with column headers stripe their odd rows (`striped: index % 2 === 1`); lists of `row` / `rowTall` items and card rows never do (hover and selection tell rows apart); a table whose rows are interleaved with group headers does not stripe (parity would jump).
- **Hover-revealed actions**: icon-only actions of a row (more, reset, cut, set as reference) are hidden at rest (`opacity: 0`, room kept), shown at full opacity while the row is hovered, the button focused or the row current; never a half-faded button. Buttons with a text stay shown.
- **States, drops & colors**: loading, empty and error states of a data panel are `TpStateView` (`secondaryActionText`: a "Clear Search" next to the action; `topPadding` for no results at the top of a list instead of centered), spinners `TpSpinner` (never a raw `BusyIndicator`), progress `TpMeter`. Files dropped on a page go through `TpDropZone` (`accepts(urls)`, `filesDropped(urls)`), color pickers through `TpColorSwatch`. Chart lines use `chartGrid` / `chartAxis` (never text color with an opacity), chart tooltips are `TpToolTip`.
- **Dialogs & toasts of backends**: a page backend asks through `ui/quick/dialogs.py`, giving the widget hosting its page: `ask_text(parent, title, label, on_accept, text="", multiline=False, placeholder="", accept_text="")` (`on_accept(text)` returns True to close, False keeps the input: refused name), `confirm(parent, title, text, action_text, on_result, danger=False, cancel_text="")` (`on_result(bool)`, run after the dialog closed), `alert(parent, title, text, level="warning", on_closed=None)`; toasts keep `ui/toast.show_toast(widget, text, duration=0, action_text="", action=None, level="")`. When the page is a shown QML page with a `TpDialogHost {}` (last child of its root item), they are a `TpDialog` / `TpToast` inside the page; otherwise the widget dialogs answer (small `TextInputDialog` window, `_common.confirm_action`, `QMessageBox`, widget toast). Texts are translated by the caller; `<b>`, `<i>`, `<br>` of escaped names are kept (`safe_markup`). Pending requests of a page closed are cancelled (`on_result(False)`). Tests keep patching `QMessageBox.question` / `warning`, a host's `confirm_operation` or `TextInputDialog.show` / `open`: a replaced entry point answers instead of the page.
- **Keyboard & accessibility**: everything clickable is a button-like control (Tab, visible `FocusRing`, Enter / Space, `Accessible` name), lists move with the arrows. A focused control takes its own keys (`Keys.onShortcutOverride`), so page shortcuts on single keys never fire under it. Icon only buttons have a `tip` (screen readers) and show `fallback` text when the icon font is missing (Linux). Color is never the only signal: add a shape, an icon or a text mark. Text is never faded with `opacity` (use `theme.dimText`).

### Table editors

The style data editors (brakes, tyre compounds, car classes & brands, track info, heatmaps) are one Qt Quick page, `qml/editors/TableEditor.qml`, hosted by `quick/table_editor_host.TableEditorPage` (undo history, unsaved marker, Ctrl+S, warnings & file / color dialogs). Each editor is a `TableEditorBackend` subclass (`quick/table_editor.py`) in its own module: `COLUMNS` (`Column`: kind `name`, `text`, `number` with an optional user `unit` converted for display and stored in base units, `color`, `choice`, `clock`, `symbol`, `preset` among existing presets; `replace`, cell menu `action`), `CONFIG_TYPE`, and the hooks `load`, `default_rows`, `to_setting`, `session_rows` (Add), `new_row`, `choice_values`. Confirmations, warnings and toasts go through the page's `TpDialogHost` (`ui/quick/dialogs.py` `confirm` / `alert`, `show_toast`); a confirmed action is kept as a method name with a weak reference to the backend, never a bound method. Parts of one editor only (heatmap presets & preview) are in `FEATURES` and declared in a mixin with its own signals.

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

A key of `fr.py` is the English text itself: changing a text in the code means changing its `fr.py` key in the same change (and any test quoting it), or the text shows in English. French values stay unique (`tests/test_i18n.py`: menu actions are found back from their translated text).

### Writing rules and glossary

English (the source language):

- **Title Case** for buttons, toolbar actions, menu items (checkable ones too), page, dialog and card titles, table headers: `Export Map Picture…`, `Follow Cars`, `Changed Only`. Small words stay lower case (`a`, `of`, `to`, `with`, `by`...): `Group Cars by Class`.
- **Sentence case** for messages, tooltips, hints, progress, empty states, switch and check box labels (they read like option labels): `Checking for updates…`, `Hide sessions without laps`. A feature named the same in menus and switches keeps one text (`Colorblind Colors`).
- Ellipsis is the single character `…` (U+2026), never three dots. On an action it means "asks something first" (a name, a file, a confirmation): `Rename…`, `Import Overlay Settings…`; an action done at once has none (`Copy Picture`). Progress texts end with it: `Loading replay…`.
- Toasts: a single sentence has no final period (`Picture copied`, `Game window not found: LMU must be running on this computer`); two sentences keep their periods. A copy says what was copied, without "to clipboard": `Address copied`, `Log copied`.
- Questions: a title and one question; the consequence goes below (`This cannot be undone!`), not a whole question in bold.
- **Car** in interface texts (`Car`, `Find car`, `Remove Car`); `vehicle` stays in option keys, file formats and the `Vehicle` choice of driver stats classification.
- **Delete** destroys (a file, a lap, a note, stats); **Remove** takes something out of a list and keeps it elsewhere (a car from a table, a tyre from stock).
- **Trash** is the app's own trash (deleted presets, laps: restored from the app); **recycle bin** is the system one (replay files, plugins).

French:

| English | French | Not |
|---|---|---|
| Compound | gomme | composé |
| Tread (tyre rubber left) | épaisseur restante (`Épaisseur minimale`, `Épaisseur au départ`) | gomme |
| Replay (game file) | rejeu | replay, rediffusion, enregistrement |
| Instant replay (Broadcast Director) | ralenti | rejeu |
| Track (the place: name, map, presets, stats) | circuit (`carte du circuit`, `Nom du circuit`) | piste |
| Track (the surface: temperature, limits, wetness, on / off track) | piste (`Température de la piste`, `Limites de piste`, `en piste`) | circuit |
| Class | catégorie (overlays: `Cat.`) | classe |
| Car | voiture | véhicule (kept for the `Vehicle` classification choice and editor names) |
| Settings (the app: Settings page, global settings, settings import, safe mode) | paramètres | réglages |
| Settings of an overlay, a preset, the car, the director, the game | réglages | paramètres |
| Reset … to default, back to default | Rétablir … par défaut, `Rétablir les valeurs par défaut` | Remettre, Revenir aux… |
| Reset (a view state: zoom, column widths, counters, layout) | Réinitialiser | (`Rétablir` alone is Redo) |
| Enabled / Disabled (state) | Activé / Désactivé | |
| Trash / recycle bin | corbeille / corbeille du système | |
| & | et (kept in names: `Stop & go`, `Lift & coast`, `Driver & Safety Rank`) | & |

French texts use "vous", a space before `:` `?` `!` like the existing texts, and sentence case everywhere (titles and menus too: `Grouper les voitures par catégorie`).

## Windows build

```bash
pip install -r requirements-build.txt
```

```bash
python build_pyinstaller.py -c
```

The executable is built in `dist\NeoPedal` (`neopedal.exe`, program files in `lib`). `-c` removes the previous build first. The hook `tools/pyinstaller_hooks/hook-PySide6.QtQml.py` bundles only the QML modules in use (about 2 MB instead of about 300 MB with WebEngine and 3D). `requirements-build.txt` pins PyInstaller and the runtime versions used by the release workflow.

The release workflow installs `requirements-build-lock.txt` instead: every package and dependency with the SHA-256 of its files (`pip install --require-hashes --no-deps --only-binary :all: -r requirements-build-lock.txt`). After changing `requirements-build.txt` or `requirements-lock.txt`, regenerate it with the `uv pip compile` command written at the top of `requirements-build.txt` (same for `requirements-sign-lock.txt`, the signing package of the release job, from `requirements-sign.txt`); `tests/test_signed_release.py` fails when a lock no longer matches. The pre-commit hooks are pinned to commit SHAs: update them with `pre-commit autoupdate --freeze`.

Check the build like CI does (the report file is optional, the executable has no console):

```bash
dist\NeoPedal\neopedal.exe --self-test report.txt
```

To build the installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then (with the version):

```bash
iscc /DAppVersion=0.20.0 installer\neopedal.iss
```

The installer `NeoPedal-<version>-windows-setup.exe` is written to `dist`. Its shortcut icon follows the Windows light or dark mode (`images/icon.ico` or `images/icon_dark.ico`). Icons are generated from `images/src/icon.webp` and `images/src/icon_dark.webp` with `images/export_icon.sh` (ImageMagick 7).

User folders are named `NeoPedal` (`CONFIG_ID` in `const_app.py`). `Settings` > `Import Settings…` (`ui/settings_import.py`) saves an import request in the config folder and restarts; `userfile/settings_import.py` applies it on next start, before settings are loaded (current folder renamed aside, chosen folder copied, Linux data folder of the same name and `user_path` values too). Single instance mode holds a system lock named after the config folder (`main.instance_lock_name`: Windows named mutex `Local\NeoPedal-<hash>`, Linux `flock` of a file in `XDG_RUNTIME_DIR`), taken in one step and released by the system when the app exits, even after a crash; a restarted app waits for the previous one to release it. The executable is `neopedal.exe` (`APP_ID`, build folder `dist\NeoPedal`). Versions until 0.23.0 used another name (`LEGACY_NAME` in `const_app.py`), only read for compatibility: the installer removes the old executable and points shortcuts to `neopedal.exe` (older updaters run it with the folder of the running copy), `update.installed_app_folder` finds both names, plugins importing the old package name get this package (`plugin_loader.LegacyPackageFinder`), presets get their option keys renamed (`setting_preupdate`, 2.50.9), old preset packages still import, the remote control still accepts the old header besides `X-NeoPedal`, and the old OpenXR layer registration is replaced or removed (`vr_shared.LAYER_MANIFESTS`). The restart variable is `NEOPEDAL_RESTART`, the Linux desktop entry `NeoPedal.desktop` (`DESKTOP_FILE_NAME`), the SteamVR overlay key `neopedal.overlay`. Release files are named `NeoPedal-<version>-…`: every updater, also the one of 0.19, finds the installer by its end (`-setup.zip`, `-windows-setup.exe`). The repository keeps its `Keenny38/ModernTinyPedals` address: updaters up to 0.22.4 send a raw request that never follows GitHub's redirect of a renamed repository (they would find no update). Since 0.23.0, `request_latest_release` requests again with redirects followed (GitHub API host only) when the direct request gives nothing, so a rename becomes possible once most users have that version; then add the old name to `RENAMED_REPOS`.

## Release process

Releases are published **on demand**: pushes to `master` only run the `Checks` workflow, so fixes can follow each other until everything is green. When `master` is ready:

1. `python tools/check.py` passes (automatic before each push to `master` once the hook is installed), everything is pushed;
2. both changelogs have the section of the next version (see [Changelog](#changelog));
3. publish with **one** command, by one person (or one Claude session) at a time:

```bash
python tools/release.py
```

It refuses when `master` has changes not pushed, when there is nothing to release, when a changelog lacks the version section, or when `Checks` did not pass on the `master` commit (it waits while they run). Then it asks before publishing, starts the `Build and Release` workflow, follows it and checks the published files. `--dry-run` only checks. `Run workflow` on the Actions tab (branch `master`) does the same without the local checks: the workflow itself refuses a commit without passed `Checks` or without both changelog sections.

The `Build and Release` workflow computes the version, builds and self-tests the Windows executable, builds the installer and the source ZIP, signs the release manifest, attests the files, writes the release notes and publishes the release.

**Releases must be built by this workflow, with the `RELEASE_SIGNING_KEY` secret set**: apps since 0.28 refuse an official release without a valid signed manifest (see [Signed release manifest](#signed-release-manifest)). Never publish or edit a release by hand.

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

`python tools/gen_release_notes.py --draft-changelog X.Y.Z` prints a draft of the section from the commits since the last release (titles under `New`, `Improvements` and `Fixes`, images added in `docs/changes`), to rewrite for users.

Without both sections, `tools/release.py` and the workflow refuse to publish. Inside a section, `###` headings are the groups of the app's What's New page (`New`, `Improvements`, `Fixes`...) and `####` headings its cards (bullets right under a `###` heading make a card without title); an indented `  - ` bullet is a sub-bullet. A `####` heading naming an overlay gets a `Try` button, and option keys written as code (`` `show_apex_speed` ``) become links to the option.

### Before / after visuals

When a commit changes how an overlay looks, add a before / after image in `docs/changes` before committing. The left side renders the last commit, the right side your working tree, on the same simulated race as the README preview. Write the title in English:

```bash
python tools/make_change_visual.py black_box --title "Dashboard HUD: engine map"
```

`--set black_box.show_motor_map=true` shows an option that is off by default, `--slug` sets the file name, `--base` chooses the "before" revision. The release notes show added images in a **Visuals** section, unless the changelog section already embeds them (the app shows that section folded, `Before / After`).

### Changelog screenshots

Screenshots of new app pages go in `docs/changes` and are inserted in the changelog by their `https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/…` address, so they show on GitHub, in the release notes and in the app's What's New page (shipped with the app for the newest version, else downloaded once; other image addresses are skipped).

The README preview image is generated from the real overlays, on the simulated race of `neopedal/demo_data.py` (the one the app's overlay pictures show: widget modules read it only while a picture is drawn, see `demo_globals`; `demo_state` keeps simulated cars out of user presets):

```bash
python tools/make_readme_preview.py
```

### Release files and checksums

Each release publishes the Windows installer `NeoPedal-<version>-windows-setup.exe` with its `.sha256` file (the updater of apps up to 0.19 needs both), the same installer zipped as `NeoPedal-<version>-setup.zip` (downloaded by the updater since 0.20) and `NeoPedal-<version>-source.zip`, with their SHA-256 in the release notes and a signed build provenance attestation for each file, plus the signed manifest `NeoPedal-<version>-manifest.json` and `.json.sig` (since 0.28). `tests/test_release_assets.py` reads the workflow and fails when a change of release files would leave an installed app (from 0.10) without an installer to update to. The release is created as a draft, gets its files, then is published: releases are immutable. See [Updates and Security](Updates-and-Security.md#release-files).

### Signed release manifest

`tools/sign_release.py` (release job, after the build files are checked) writes `NeoPedal-<version>-manifest.json` (canonical JSON: format, repository, tag, version, and the SHA-256 and size of the installer, its `.sha256` file, the setup ZIP and the source ZIP) and signs its exact bytes with Ed25519 (`.json.sig`, base64). The private key comes from the `RELEASE_SIGNING_KEY` secret (PEM PKCS8) of the `release` environment, given to that step only; the job fails, and nothing is published, when the secret is missing or its public key is not in `RELEASE_PUBLIC_KEYS` of `neopedal/release_manifest.py`. The release job runs in the `release` environment for this secret: with required reviewers, the run waits for a second approval (build job, then release job).

The app (`update.verified_release`) downloads both files for an available official update, checks the signature against `RELEASE_PUBLIC_KEYS`, the repository, tag and version (newer than the running app), and takes the SHA-256 and size of the files from the manifest only. No manifest, a bad signature or a mismatch: the update is refused (`Update Refused` notice, reason in the log). A custom `update_repository` needs no manifest but an Authenticode-signed installer (revocation checked online, signer shown before installing).

Key rotation: generate a new Ed25519 key, add its public key (raw 32 bytes, base64) to `RELEASE_PUBLIC_KEYS` beside the old one and release; then replace the secret, and remove the old public key a few releases later. If the private key leaks, publish at once a release (still signed with it, the only key installed apps know) whose `RELEASE_PUBLIC_KEYS` holds only a new key, then sign with the new key: apps updated to it refuse releases signed with the leaked key (older apps still accept it). Check a published release with `python tools/sign_release.py <version> --dist <folder> --verify`.

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
