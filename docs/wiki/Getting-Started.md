# Getting Started

This page walks you through the first launch and the everyday tasks: placing overlays, configuring them and finding options. Make sure your game is set up first: see [Game Setup](Game-Setup.md).

## First launch

On first launch, the **setup wizard** asks a few questions. Every choice can be changed later.

1. **Language and window theme**: `English` or `Français`; `Dark`, `Light` or `System` window theme.
2. **Game**: the game to read telemetry from (`Le Mans Ultimate` or `rFactor 2`).
3. **Overlay style**: the overlay color theme, and the modern font (JetBrains Mono).
4. **Preset and widgets**: create a new preset or pick an existing one, then choose starter overlays among Relative, Standings, Deltabest, Fuel, Pedal, Gear, Tyre Temperature, Brake Temperature, Flag, Session, Weather and Radar.

The wizard is shown once. Open it again from `Help` > `Setup Wizard`.

## The main window

The navigation bar on the left gives access to pages and tools:

| Entry | What it does |
|---|---|
| `Home` | Game and session state, overlay lock, last session, quick access, release notes |
| `Overlays` | Turn overlays on or off and configure them |
| `Module` | Data modules (delta, fuel, recorder, stats...) used by overlays and tools |
| `Preset` | Load, create and manage presets, see [Presets and Settings](Presets-and-Settings.md) |
| `Spectate` | Show the data of another driver |
| `Hotkey` | Keyboard shortcuts |
| `Tools` | Every tool and editor |
| `Telemetry`, `Stats`, `Race` | [Telemetry Viewer](Telemetry-Viewer.md), [Driver Stats](Driver-Stats.md), [Race Calculator](Race-Calculator.md) |

- Right-click the bar and choose `Customize Navigation Bar...` to show, hide or reorder entries (the `Pacenotes` page, for pace notes playback, is hidden by default). `Ctrl+1` to `Ctrl+9` open the first nine entries.
- Tools, editors and settings open as pages inside the window. `Alt+Left` or the mouse back button goes back to the previous page. A page you leave closes by itself, unless it has unsaved changes. Navigation bar tools stay as you left them, and are reopened at the next start with the page shown last (`Window` > `Reopen Pages at Startup`).
- `Ctrl+K` opens the **command palette**: type to find and run pages, overlays, modules, tools, presets and options.
- A dot (`•`) marks pages with unsaved changes. `Ctrl+S` saves the page shown. Invalid values are outlined in red with the reason while you type.
- The menu bar has `Overlay`, `API`, `Config`, `Tools`, `Window` and `Help` menus.

The app also has a **tray icon**. Click it to show the main window, right-click it for the overlay menu (`Lock Overlay`, `Auto Hide`, `Reload`, `Quit`...). With `Window` > `Minimize to Tray`, the window close button hides the app to the tray instead of quitting.

## Home page

The `Home` page shows at a glance:

- the installed version, with a `Release Notes` button (what's new in this version, readable offline) and the available update, if any;
- the game state with the current session (track, session, position, lap), and a reminder of the game setup while the game is not running;
- a one-click `Lock Overlay` / `Unlock Overlay` button;
- the preset, overlays and modules in use, and the last session you drove;
- **Quick Access** buttons (by default: Lap Telemetry Viewer, Race Calculator, Driver Stats Viewer, Layout Editor, Command Palette). Use `Customize...` next to `Quick Access`, or right-click the buttons, to choose tools, pages and actions.

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
3. Click a card (or the gear button shown on its preview) to open its options. Only the options used by the current design are shown. Right-click a card for its menu: options, enable or disable, show only its category.
4. `Apply` applies the changes and keeps the page open, `Save` applies and closes it: the card preview is redrawn.

At the bottom, `Enable All` and `Disable All` switch every overlay at once (with a confirmation). While a search or filter is active they become `Enable Shown` and `Disable Shown` and only switch the overlays shown. An overlay that is on but could not start shows an `Error` badge, with a notice at top to open the log. Every option is described in its tooltip and in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widgets).

Keyboard: type anywhere on the page to search, `/` jumps to the search box, arrows move between overlays, `Space` switches the selected overlay, `Enter` opens its options, `Esc` clears the search.

### Find any option

Press `Ctrl+F` (`Config` > `Find Option...`) to search all options of all overlays, modules and global settings, in English or in the current language. Double-click a result to open its page, filtered on that option.

### Units

`Config` > `Units` sets units for distance, fuel, speed, temperature, pressures, power and weight. Overlays, tools and the web dashboard follow them.

## Presets

A preset stores the layout and options of all overlays and modules. You can keep several (one per car class, one for VR...), load one with a double-click on the `Preset` page, and have one loaded automatically per class or track. See [Presets and Settings](Presets-and-Settings.md).

## Hotkeys

The `Hotkey` page binds keys to commands: show, hide or lock the overlay, reload or switch presets, restart the API, spectate the next driver, cycle the delta best source, show the next Black box incident, turn any overlay or module on or off, load a given preset, restart or quit the app.

1. Click the `Disabled` button to turn global hotkeys on (it then shows `Enabled`).
2. Click the key button of a command and press a key or key combination (`Clear` removes it, `Clear All` removes every binding). Preset commands also ask which preset to load.

Hotkeys do not block the key for other programs. Global hotkeys are not supported on Linux. The same commands can be run by other programs (Stream Deck, SimHub...): see [Connections](Connections.md#remote-control).

## Next steps

- [Overlays](Overlays.md): designs, themes and the list of all overlays.
- [Telemetry Viewer](Telemetry-Viewer.md): analyze your laps.
- [Race Calculator](Race-Calculator.md): plan fuel, energy and tyres.
- [Troubleshooting](Troubleshooting.md) if something does not show up.
