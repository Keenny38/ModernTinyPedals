# Getting Started

This page walks you through the first launch and the everyday tasks: placing overlays, configuring them and finding options. Make sure your game is set up first: see [Game Setup](Game-Setup.md).

## First launch

On first launch, the **setup wizard** asks a few questions. Every choice can be changed later, and nothing is applied before `Finish Setup`: closing the wizard (`Esc` or the window close button, after a confirmation) keeps everything as it was. The steps are listed on the left: click one to go back to it, `Enter` goes to the next one.

1. **Welcome**: `English` or `Français`. The wizard switches language at once, the app once setup is finished.
2. **Game**: the game to read telemetry from (`Le Mans Ultimate` or `rFactor 2`). A game running now is marked `Running` and picked for you.
3. **Units**: `Metric` (km/h, °C, L, kPa, kg) or `Imperial` (mph, °F, gal, psi, lb), saved in the preset. A preset with mixed units can keep them (`Keep current units`). Each unit can be changed later in the preset units.
4. **Appearance**: the window theme (`Modern Dark`, `Modern Light`, `Legacy Dark` or `Legacy Light`, each drawn in its colors), the overlay theme (the same four, with an overlay drawn in each), `Colorblind safe colors` and the modern font (JetBrains Mono). A preview shows overlays in the chosen style.
5. **Overlays**: create a new preset (the name is checked as you type) or pick an existing one, then check the overlays to show, each shown as a picture: Relative, Standings, Deltabest, Fuel, Virtual Energy, Pedal, Gear, Steering Wheel, Tyre Temperature, Brake Temperature, Flag, Session, Weather, Radar, Track Map and Trailing. `Recommended` checks Relative, Deltabest, Fuel, Pedal, Gear and Flag. With an existing preset, the overlays it already shows are checked, and unchecking one turns it off; overlays not listed keep their state.
6. **Ready**: every choice, with `Change` to go back to its step, and tips for the first drive.

Overlay pictures are drawn with the overlay settings but without game data, so some overlays look empty until you drive.

The wizard is shown once. Open it again from `Help` > `Setup Wizard`.

## The main window

The navigation bar on the left gives access to pages and tools:

| Entry | What it does |
|---|---|
| `Home` | Game and session state, overlay lock, last session, quick access, release notes |
| `Overlays` | Turn overlays on or off and configure them |
| `Stats` | [Driver Stats](Driver-Stats.md) |
| `Results` | Results of past sessions: classification, laps, sectors, incidents and penalties |
| `Replays` | Replays saved by Le Mans Ultimate, see [Connections](Connections.md#game-replays-le-mans-ultimate) |
| `Telemetry` | [Telemetry Viewer](Telemetry-Viewer.md) |
| `Spectate` | Show the data of another driver |
| `Race` | [Race Calculator](Race-Calculator.md) |
| `Preset` | Load, create and manage presets, see [Presets and Settings](Presets-and-Settings.md) |
| `Config` | Every global option of the app (`Ctrl+,`), see [Presets and Settings](Presets-and-Settings.md#global-config) |

- Right-click the bar and choose `Customize Navigation Bar...` to show, hide or reorder entries. The `Module` (data modules used by overlays and tools), `Hotkey` (keyboard shortcuts), `Tools` (every tool and editor) and `Pacenotes` pages are not in the bar by default: add them back there, or open them from the command palette (`Ctrl+K`). `Ctrl+1` to `Ctrl+9` open the first nine entries.
- Tools, editors and settings open as pages inside the window. `Alt+Left` or the mouse back button goes back to the previous page. A page you leave closes by itself, unless it has unsaved changes. Navigation bar tools stay as you left them, and are reopened at the next start with the page shown last (`Window` > `Reopen Pages at Startup`).
- `Ctrl+K` opens the **command palette**: type to find and run pages, overlays, modules, tools, presets and options.
- A dot (`•`) marks pages with unsaved changes. `Ctrl+S` saves the page shown. Invalid values are outlined in red with the reason while you type.
- The menu bar has `Overlay`, `API`, `Config`, `Tools`, `Window` and `Help` menus.
- **Window size**: at first launch the window opens at a comfortable size, centered on the screen. Its size, position and maximized state are remembered (`Window` > `Remember Size` and `Remember Position`), saved a moment after each change so a crash keeps them too. Wide tools (race results, telemetry, layout editor...) grow the window while they are open, keeping it inside the screen, and give it back its size and place once closed: the grown size is never remembered. The window can never be made so small that pages overlap or get cut: the page area keeps a minimum size (about 650 × 445 pixels at 100% scale), larger while the telemetry viewer (its toolbar and three panels stay whole, in every language) or driver stats are shown. The navigation bar keeps its width, and its selected entry stays in view when the window is short. The window is also brought back on screen if it was left on a monitor that is no longer there. `Window` > `Reset Window Size and Position` (also in the command palette) puts it back to the default size, centered.

The app also has a **tray icon**. Click it to show the main window, right-click it for the overlay menu (`Lock Overlay`, `Auto Hide`, `Reload`, `Quit`...). With `Window` > `Minimize to Tray`, the window close button hides the app to the tray instead of quitting.

## Home page

The `Home` page shows at a glance:

- the installed version, with a `Release Notes` button (what's new in this version, readable offline) and the available update, if any;
- the game state with the current session (track, session, position, lap), and a reminder of the game setup while the game is not running;
- a one-click `Lock Overlay` / `Unlock Overlay` button;
- the preset, overlays and modules in use, and the last session you drove;
- **Quick Access** buttons (by default: Lap Telemetry Viewer, Race Calculator, Driver Stats Viewer, Layout Editor, Widget Performance, Game Replays, the Overlays, Module, Preset, Spectate, Hotkey and Tools pages, Create Bug Report, Check for Updates). The Module, Hotkey and Tools pages, not in the navigation bar by default, are one click away there. Use `Customize...` next to `Quick Access`, or right-click the buttons, to choose tools, pages and actions.

## When overlays are shown

Overlays appear when your car is on track and hide when you are in menus or not driving (`Auto Hide`, on by default in the tray menu). Each overlay can also be limited to some sessions or to the pits: see [Overlays](Overlays.md#visibility-by-session-and-pit).

## Move overlays

While the overlay is unlocked you can move overlays with the mouse; once locked, they stay in place and clicks go through to the game. The lock state is kept between starts.

1. **Unlock** if needed: tray icon menu > uncheck `Lock Overlay`, or `Unlock Overlay` on the Home page. Unlocked overlays show an outline, their name and a corner handle.
2. **Drag** an overlay to move it. Hold `Ctrl` to snap to screen edges and other overlays. Alignment guides appear while dragging. `Grid Move` (tray or `Overlay` menu) moves overlays on a grid.
3. **Resize** an overlay with its corner handle: its size options (font size, bar size...) are scaled.
4. Right-click an overlay for `Config`, `Center Horizontally`, `Center Vertically`, `Reload` and `Disable`.
5. **Lock** again when done.

Positions are saved in the preset, and remembered per screen setup (screens plugged, resolution). To make every overlay bigger or smaller at once, set `overlay_scale` in `Config` > `Overlay Style`.

### Layout editor

`Tools` > `Layout Editor` places overlays on a picture of the game instead of over the desktop:

- `Load Screenshot...` uses a game screenshot as background, `Capture Screen` grabs the primary screen.
- Drag the boxes: edges and centers snap to other overlays, screen edges and screen center (turn off with `Snap`, or hold `Alt`).
- Arrow keys move the selected overlay by 1 pixel (`Shift`: 10 pixels).
- `Apply` moves the overlays and saves their positions, `Reset` reloads the current positions.

## Configure an overlay

1. Open the `Overlays` page. Each overlay is a card with a preview drawn with your settings, its category and its switch. The buttons at top right switch to a compact list (preview in a tooltip); the choice is kept (`show_overlay_previews` in `Config` > `Application`).
2. Turn an overlay on or off with its switch. Type part of a name in the search box (accents and case ignored, several words allowed), choose `All`, `Active` or `Inactive`, or click a category chip (the number of matching overlays is shown on each chip, click it again to show all).
3. Click a card (or the gear button shown on its preview) to open its options in the **Overlay Options** page. Right-click a card for its menu: options, enable or disable, show only its category.
4. Change options, then `Apply` (`Ctrl+S`): the preset is saved and the edited overlays restart. See [The Overlay Options page](#the-overlay-options-page).

At the bottom, `Enable All` and `Disable All` switch every overlay at once (with a confirmation). While a search or filter is active they become `Enable Shown` and `Disable Shown` and only switch the overlays shown. An overlay that is on but could not start shows an `Error` badge, with a notice at top to open the log. Every option is described in its tooltip and in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widgets).

Keyboard: type anywhere on the page to search, `/` jumps to the search box, arrows move between overlays, `Space` switches the selected overlay, `Enter` opens its options, `Esc` clears the search.

### The Overlay Options page

One page holds the options of every overlay: the overlays on the left (by category, a filled dot when the overlay is on), the options of the selected one in the middle, and a live preview on the right (on wide windows) drawn with the values you have not applied yet. It also opens from a right-click on an overlay on screen, `Find Option` and the command palette (`Ctrl+K`).

- **Sections**: `General`, `Position & Layout`, `Font`, then one section per item the overlay shows (Speed, Time Gap, Fuel Level Bar...). The on/off switch of an item is in the title of its section; while it is off, its options are dimmed. Click a section title to fold it (`Collapse All` / `Expand All` at top), its `Reset` button puts its options back to default. `Display Order` is a list moved with the arrows.
- **Only the options of the design in use** are shown: switch `Enable Classic Layout` and the options of the classic layout show up at once.
- **Search** (`Ctrl+F`): in `This overlay` or in `Every overlay`, for example `opacity` to set it for all overlays in one list. `Changed only` lists the options changed from their default (in one overlay or in all of them); the overlay list shows how many options each overlay has changed.
- **`...` button of an option**: `Reset to Default`, `Apply to All Overlays` (the value goes to every overlay having this option: font, opacity, update interval, theme...), `Copy Option Name`.
- **Changes stay pending** until `Apply`, for as many overlays as you like: the overlay list shows how many changes each one has, `Undo` / `Redo` (`Ctrl+Z` / `Ctrl+Y`) and `Discard` are in the bar at the bottom. An invalid value is marked at once with the reason and blocks `Apply` (click the message to show it). `Apply` saves the preset once and restarts only the overlays you changed.
- **Black box**: its own sections, `Advanced Options` (simple mode shows the common options), `Color Theme...` (default or colorblind safe colors) and display profile (options set by the profile are locked and say so).

### Find any option

Press `Ctrl+F` (`Config` > `Find Option...`) to search all options of all overlays, modules, the preset and the application, in English or in the current language (accents and case are ignored). Best matches come first, with the current value of each option; a dot marks options changed from their default.

- Click a result (or `Enter`) to open it: the `Overlay Options` page or the `Config` page scrolled to the option, or a module page filtered on it.
- On / off options have a switch in the list (or `Space`): the change is saved and applied at once.
- The chips (`Overlays`, `Modules`, `Preset`, `Application`) narrow the results; `Changed only` lists every option set apart from its default, even without search words.
- Right-click a result: `Reset to Default`, `Copy Option Key` (the name used in setting files and in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md)).

### Units

`Config` > `Units` sets units for distance, fuel, speed, temperature, pressures, power and weight. Overlays, tools and the web dashboard follow them.

## Data modules

Modules compute the data that overlays show: lap times and deltas, fuel and energy, positions of every car, tyre and brake wear, track map... The `Module` page (command palette `Ctrl+K`, or add it to the navigation bar) shows each module as a card:

- what it computes, its state (`Running`, `Disabled`, or `Error` when it could not start: see the log) and its update interval;
- how many enabled overlays use its data (their names in the tooltip) and the modules using it. A module turned off that enabled overlays or modules need is flagged in orange, and `Enable Them` at the top of the page turns those modules back on;
- its switch and its `Config` button (update intervals and options of the module). Right-click a card to reset its saved data: delta best (Delta), fuel and energy delta (Fuel), consumption history (Stint), sector best (Sectors), track map (Mapping).

Search, `All` / `Active` / `Inactive` and the keyboard work as on the `Overlays` page. Keep every module on unless you know an overlay does not need it.

## Presets

A preset stores the layout and options of all overlays and modules. You can keep several (one per car class, one for VR...), load one with a double-click on the `Preset` page, and have one loaded automatically per class or track. See [Presets and Settings](Presets-and-Settings.md).

## Hotkeys

The `Hotkey` page binds keys to commands: show, hide or lock the overlay, reload or switch presets, restart the API, spectate the next driver, cycle the delta best source, show the next Black box incident, turn any overlay or module on or off, load a given preset, restart or quit the app.

1. Click the `Disabled` button to turn global hotkeys on (it then shows `Enabled`).
2. Click the key button of a command and press a key or key combination (`Clear` removes it, `Clear All` removes every binding). Preset commands also ask which preset to load.

Hotkeys do not block the key for other programs. Global hotkeys are not supported on Linux. The same commands can be run by other programs (Stream Deck, SimHub...): see [Connections](Connections.md#remote-control).

## Spectate

The `Spectate` page shows the data of another driver in your overlays (delta, fuel, timing, inputs...): in a replay, or while watching a session.

1. Turn on the switch at top right (or click any driver: spectate mode turns on).
2. Click a driver to follow it. The card on top shows the driver followed, with place, class, car and best lap; the arrows (`Alt+Left`, `Alt+Right`) go to the previous or next driver by place, `Stop` follows nobody.
3. Search by driver, car or class, keep one class with its chip, sort by position or name. Your own car is marked `You`.

Drivers are read only while the page is shown. The `spectate_mode`, `spectate_next_driver` and `spectate_previous_driver` hotkeys do the same from the game.

## Next steps

- [Overlays](Overlays.md): designs, themes and the list of all overlays.
- [Telemetry Viewer](Telemetry-Viewer.md): analyze your laps.
- [Race Calculator](Race-Calculator.md): plan fuel, energy and tyres.
- [Troubleshooting](Troubleshooting.md) if something does not show up.
