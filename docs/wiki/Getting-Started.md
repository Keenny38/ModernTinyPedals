# Getting Started

This page walks you through the first launch and the everyday tasks: placing overlays, configuring them and finding options. Make sure your game is set up first: see [Game Setup](Game-Setup.md).

## First launch

On first launch, the **setup wizard** asks a few questions. Every choice can be changed later, and nothing is applied before `Finish Setup`: closing the wizard (`Esc` or the window close button, after a confirmation) keeps everything as it was. The steps are listed on the left: click one to go back to it, `Enter` goes to the next one.

1. **Welcome**: `English` or `Français`. The wizard switches language at once, the app once setup is finished.
2. **Game**: the game to read telemetry from (`Le Mans Ultimate` or `rFactor 2`). A game running now is marked `Running` and picked for you.
3. **Units**: `Metric` (km/h, °C, L, kPa, kg) or `Imperial` (mph, °F, gal, psi, lb), saved in the preset. A preset with mixed units can keep them (`Keep current units`). Each unit can be changed later in the preset units.
4. **Appearance**: the window theme (`Modern Dark`, `Modern Light`, `Legacy Dark` or `Legacy Light`, each drawn in its colors), the overlay theme (the same four, with an overlay drawn in each), `Colorblind Colors` and the modern font (values in monospace JetBrains Mono, labels in Barlow; off: each overlay in its own font). A preview shows overlays in the chosen style.
5. **Overlays**: create a new preset (the name is checked as you type) or pick an existing one, then check the overlays to show, each shown as a picture: Relative, Standings, Deltabest, Fuel, Virtual Energy, Pedal, Gear, Steering Wheel, Tyre Temperature, Brake Temperature, Flag, Session, Weather, Radar, Track Map and Trailing. `Recommended` checks Relative, Deltabest, Fuel, Pedal, Gear and Flag. With an existing preset, the overlays it already shows are checked, and unchecking one turns it off; overlays not listed keep their state.
6. **Streaming** (optional): `Show my overlays on stream` turns on the stream overlay server once setup is finished; `Copy Address` copies the address of the layout source (every overlay at its place, 1920 x 1080) to add as a browser source in OBS, Streamlabs, XSplit or vMix. `Next` without it keeps streaming off. See [Connections](Connections.md#stream-overlays-obs-streamlabs-xsplit-vmix).
7. **Ready**: every choice, with `Change` to go back to its step, what happens once finished (both on by default: the `Overlays` page opens in Screen view to move overlays, and overlays on screen show a simulated race for a few seconds, `Test on Screen`), and tips for the first drive.

Overlay pictures are drawn with the overlay settings on a simulated race (a GT3 mid race at Road Atlanta), so you see what each overlay shows before you drive.

The wizard is shown once. Open it again from `Help` > `Setup Wizard`.

## The main window

The navigation bar on the left gives access to pages and tools:

| Entry | What it does |
|---|---|
| `Home` | Checks, game and session state, overlay lock, preset, last session & its debrief, driver card, quick access, release notes |
| `Overlays` | Turn overlays on or off and configure them |
| `Stats` | [Driver Stats](Driver-Stats.md) |
| `Results` | Results of past sessions: classification, laps, sectors, incidents and penalties |
| `Broadcast` | [Broadcast Director](Broadcast-Director.md) (Le Mans Ultimate) |
| `Stream` | [Stream Overlays](Connections.md#stream-overlays-obs-streamlabs-xsplit-vmix): overlays as OBS browser sources |
| `Telemetry` | [Telemetry Viewer](Telemetry-Viewer.md) |
| `Calculator` | [Race Calculator](Race-Calculator.md) |
| `Presets` | Load, create and manage presets, see [Presets and Settings](Presets-and-Settings.md) |

The buttons under the bar: overlay lock, auto hide and VR compatibility switches, `Settings` (gear, `Ctrl+,`: every global option of the app, see [Presets and Settings](Presets-and-Settings.md#global-config)), the command palette, the game API state (dot: green while the game runs, click for the API menu), the **notification center** (bell, with the number of unread messages), `More` (`⋯`: pages and tools left out of the bar) and help (`?`: the page of this guide about the page shown). The back and forward arrows at the top of the bar go back and forth between pages, like a browser (`Alt+Left` / `Alt+Right`, mouse back and forward buttons).

- Right-click the bar and choose `Customize Navigation Bar…` to show, hide or reorder entries. The `Modules` (data modules used by overlays and tools), `Hotkeys` (keyboard shortcuts), `Tools` (every tool and editor), `Spectate` and `Pacenotes` pages are not in the bar by default: add them back there, or open them from `More`, `Tools` > `Pages`, the command palette (`Ctrl+K`) or the Home page quick access. In 0.23.0 the bar of every user was set once to this default (`Broadcast` in place of `Spectate`); after 0.25.0, `Stream` was added after `Broadcast` in every bar. `Ctrl+1` to `Ctrl+9` open the first nine entries.
- Tools, editors and settings open as pages inside the window, under a header showing the page you opened them from (`Tools › Brake Editor`, `Home › Race Calculator`, `Overlays › Overlay Options`: click it to go back there), the page title and a single `Close` button. Tools of the navigation bar show their title the same way, without breadcrumb or `Close` (pages like any other). The `Tools` page also lists the pages left out of the navigation bar (`Pages` section, as the `Tools` menu). `Alt+Left` or the mouse back button goes back to the previous page, `Alt+Right` or the mouse forward button forward again (a tool page closed meanwhile opens again). A page you leave closes by itself, unless it has unsaved changes. Navigation bar tools stay as you left them, and are reopened at the next start with the page shown last (`Window` > `Reopen Pages at Startup`).
- `Ctrl+K` opens the **command palette**: type to find and run pages, tools, every menu command (updates, bug report, log, restart, theme...), settings, overlays, modules, presets and options; recent commands come first. Start with `>` for commands only, `@` for options, `#` for presets. `Ctrl+F` searches the page shown (its search field), `Ctrl+Shift+F` finds any option. `Ctrl+/` or `F1` shows every keyboard shortcut.
- The **status bar** at the bottom shows chips while a mode is on (locked preset, spectate, pace notes, global hotkeys, setup backup, Broadcast Director, update available): click one to open its page. Background problems (an overlay that crashed, a file that could not be saved) go to the notification center with `View Log` and `Create Bug Report…`; while the window is hidden in the tray, Windows shows a notification (at most one a minute).
- A dot (`•`) marks pages with unsaved changes. `Ctrl+S` saves the page shown. Invalid values are outlined in red with the reason while you type.
- The menu bar has `Overlay`, `API`, `Settings`, `Tools`, `Window` and `Help` menus. The window title shows the page shown, with `*` while it has unsaved changes. The title bar follows the window theme (dark or light) on Windows.
- **Window size**: at first launch the window opens at a comfortable size, centered on the screen. Its size, position and maximized state are remembered (`Window` > `Remember Size` and `Remember Position`), saved a moment after each change so a crash keeps them too. Wide tools (race results, telemetry, layout editor...) grow the window while they are open, keeping it inside the screen, and give it back its size and place once closed: the grown size is never remembered. The window can never be made so small that pages overlap or get cut: the page area keeps a minimum size (about 650 × 445 pixels at 100% scale), larger while the telemetry viewer (its toolbar and three panels stay whole, in every language) or driver stats are shown. The navigation bar keeps its width, and its selected entry stays in view when the window is short. The window is also brought back on screen if it was left on a monitor that is no longer there. `Window` > `Reset Window Size and Position` (also in the command palette) puts it back to the default size, centered.

The app also has a **tray icon**. Click it to show the main window, right-click it for the loaded preset, `Presets` (switch preset), `Open NeoPedal` and the overlay menu (`Lock Overlay`, `Auto Hide`, `Reload`, `Quit`...). With `Window` > `Minimize to Tray`, the window close button hides the app to the tray instead of quitting (told once by a notification the first time).

## Home page

The `Home` page shows at a glance:

- the **status banner** on top. Its title is the verdict: `In session · Spa · Race · P3` while you are on track, else the game state or the most important check (`Ready`, `Game not running`, `Game running without data`...), with the button that fixes it. The other checks follow, most important first, each with its button: `Game running without data` (Le Mans Ultimate is open but sends nothing: enable `Settings > Gameplay > Enable plugins` in the game, then restart it), `Game not running` (game setup reminder of the selected game: display mode, plugin), `Active State Override is on`, `No overlay enabled`, `Spectate Mode Enabled`, `Lap recording is off` (the session debrief and the telemetry need recorded laps). Below them: the installed version, a `What's New` button (what's new in this version, readable offline, older versions from its version menu) and the update button (`Update Available · v1.2.3` when there is one);
- the game card with the circuit & car logos; click it for the API options of the game. On track it takes the whole row: position, lap (of the race laps) and time left in big type, with `Live Calculator` (Race Calculator on its `Live` tab), `Broadcast Director` (Le Mans Ultimate) and `Lock Overlay` / `Unlock Overlay` at hand;
- the **Overlays** card: locked or not (one-click `Lock Overlay` / `Unlock Overlay`), overlays and modules turned on, `Module` for the Module page (click the card for the Overlays page);
- the preset in use (`Switch Preset` loads one of your latest presets) and the last session you drove (click it to open the Driver Stats page on its track and car);
- in the last session card, its **session debrief** (`Show Details` for the corners and the goal), made from the laps recorded while you drove: best lap against your personal best (or `New personal best`), number of laps, pace and consistency (average and spread of the valid laps within 103 % of your best), theoretical best (best game sectors), fuel per lap, and `Work on`: the three corners where your best lap loses most time against your older personal best lap, with the likely cause (`Brakes 6 m earlier`, `Minimum speed 4 km/h lower`...). When the session is your new personal best, a typical lap of the session is compared with its best lap instead. **Click a corner** (or `Tab` to it, then `Enter`) to open the telemetry with both laps, the `Corners` tab and the charts zoomed on that corner; `Open Telemetry` opens both laps. The lap time goal of the track and car (set on the Driver Stats page) is shown with what is left to find and a progress bar;
- **This Week**, as on the Driver Stats page: sessions, driving time and laps of the last 7 days, with the goals reached, new personal bests and goals within reach (click it for the Driver Stats page). Not shown when you did not drive in the last 7 days;
- your **driver card**: Driver Rank & Safety Rank with their progress, change since the previous rank and a line of each rank over time, badge, team, race record of the results files. Cards read in background (driver card, debrief) keep their place with a spinner until read: the page never jumps;
- **Quick Access** buttons (by default: Lap Telemetry Viewer, Race Calculator, Driver Stats, Overlay Performance, Results & Replays, the Overlays, Module, Preset, Spectate, Hotkey and Tools pages, Create Bug Report, Check for Updates). The Module, Hotkey and Tools pages, not in the navigation bar by default, are one click away there. Use `Customize…` next to `Quick Access`, or right-click the buttons, to choose tools, pages and actions.

## When overlays are shown

Overlays appear when your car is on track and hide when you are in menus or not driving (`Auto Hide`, on by default in the tray menu). Each overlay can also be limited to some sessions or to the pits: see [Overlays](Overlays.md#visibility-by-session-and-pit).

## Move overlays

While the overlay is unlocked you can move overlays with the mouse; once locked, they stay in place and clicks go through to the game. The lock state is kept between starts.

1. **Unlock**: `Unlock Overlay` on the Home page, tray icon menu > uncheck `Lock Overlay`, the command palette or the `overlay_lock` hotkey. Overlays stay as they are: move the mouse over one to see its outline, name and corner handle. For the **edit mode**, right-click an overlay > `Edit Mode`: a toolbar shows up at the top of the game screen, and every overlay shows its outline and name, also the ones that draw nothing yet and the ones hidden by `Auto Hide` or their visibility context (so you can place them from the game menus too). To start the edit mode at each unlock, turn on `enable_edit_mode_on_unlock` (`Settings` > `Overlay Style` > `Overlay Editing`).
2. **Drag** an overlay to move it. It snaps to screen edges, screen center and the edges and centers of the other overlays; hold `Ctrl` to move freely, `Shift` to keep the move horizontal or vertical. Alignment guides and the position of the overlay show while dragging. `Grid Move` moves overlays on a grid.
3. **Fine-tune with the keyboard**: click an overlay to select it (solid outline), then arrow keys move it by one pixel (`Shift`: 10 pixels, one grid step with `Grid Move`). `Ctrl+Z` / `Ctrl+Y` undo and redo, `Delete` turns the overlay off, `Esc` unselects it.
4. **Resize** an overlay with its corner handle: its size options (font size, bar size...) are scaled.
5. Right-click an overlay for `Options…`, `Center Horizontally`, `Center Vertically`, `Move to Screen` (same place on another monitor), `Visibility`, `Opacity`, `Undo`, `Reload` and `Disable`.
6. **Lock** again when done: `Lock Overlay` in the right-click menu, tray menu or Home page (`Done` on the edit mode toolbar).

The toolbar has `Snap` (option `enable_magnetic_snap`), `Grid` and `Guides` toggles, `Undo` / `Redo`, `Overlays` (active overlays, uncheck one to turn it off, or open the Overlays page) and `Done`. Drag it by its grip. Its `✕` hides it and leaves the overlay unlocked; right-click an overlay > `Edit Mode` brings it back. Everything done while unlocked can be undone until the overlay is locked.

Without the edit mode (and for an overlay already unlocked when the app starts), the outline and corner handle only show under the mouse, so nothing stays on screen if you drive with the overlay unlocked.

![Overlay edit mode](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.22.0-overlay-edit-mode.png)

Positions are saved in the preset, and remembered per screen setup (screens plugged, resolution). To make every overlay bigger or smaller at once, set `overlay_scale` in `Settings` > `Overlay Style`.

### Layout editor

The screen view of the `Overlays` page (see below) places overlays without the game running: `Background` > `Capture Screen` shows a picture of the screen shown (the app window is hidden a moment), `Load Screenshot…` a game screenshot (placed on the screen of its size), `Remove Background` takes it away. The picture is kept until the app closes, never saved. The former `Tools` > `Layout Editor` is this view now.

## Configure an overlay

1. Open the `Overlays` page. Each overlay is a card with a preview drawn with your settings, its category and its switch; hover a card a moment and its overlay plays on a moving simulated race (a corner driven in a loop), and its tooltip says what it shows. The buttons at top right switch to a compact list (category and what each overlay shows, preview in a tooltip) or to the screen view (see below); the choice is kept (`show_overlay_previews` in `Settings` > `Application`).
2. Turn an overlay on or off with its switch. Type part of a name in the search box (accents and case ignored, several words allowed), choose `All`, `Active` or `Inactive` (each with its number of overlays), or click a chip: a category, `Favorites` (overlays you marked with the star of their card, `Ctrl+D` on the selected one, kept for every preset) or `Recently Edited` (overlays whose options you saved last, last first). Click a chip again to show all. The sort button sorts by name, enabled overlays first or category; a switched overlay stays where it is until you choose a sort again.
3. Click a card (or the gear button shown on its preview) to open its options in the **Overlay Options** page. Right-click a card for its menu: `Options…`, enable or disable, add to or remove from favorites, `Test on Screen` (the overlays on screen show a simulated race for 10 seconds), `Export Options…`, show only its category.
4. Change options, then `Apply` (`Ctrl+S`): the preset is saved and the edited overlays restart. See [The Overlay Options page](#the-overlay-options-page).

A card shows a small badge when its overlay is not always shown: the sessions or pit state of its `Visibility Context` option (`Race`, `In Pits`...), `Stream Only` or `Screen Only`. The loaded preset is named at top: click it to load another preset (most recent first) or open the `Presets` page.

The screen view shows the running overlays at their place on your screens, with their picture, one screen at a time (the main screen first; a choice per screen, or `All Screens`, when several are plugged). Overlays covering part of another one are outlined, with their number at top. Drag an overlay to move it: it snaps to the edges and centers of the other overlays and of the screens, with guide lines (`Snap` switch, or hold `Alt` to move it freely). Or press `Tab` to reach an overlay (focus ring), then the arrows move it by 1 pixel (`Shift`: 10 pixels) and `Enter` opens its options; a click opens them too. Every move is saved and can be undone (`Undo` in the message shown after, or `Ctrl+Z` on an unlocked overlay). Locked overlays (`Lock Overlay`) cannot be moved here either, as in game: `Overlays locked` says so, with `Unlock Overlay`. In a locked preset, moves are not saved (`Preset Locked`, with `Unlock Preset`): the message says it.

At the bottom, `Enable (12)` and `Disable (3)` switch at once the overlays shown that are off, or on (every overlay without a search or filter, which then also shows how many overlays are shown), with `Undo` in the message shown after. An overlay that is on but could not start shows an `Error` badge, with a notice at top to open the log. Every option is described in its tooltip and in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widgets).

Keyboard: type anywhere on the page to search, `Ctrl+F` or `/` jumps to the search box, arrows move between overlays, `Space` switches the selected overlay, `Enter` opens its options, `Ctrl+D` marks it as favorite, `Esc` clears the search.

### The Overlay Options page

One page holds the options of every overlay: the overlays on the left (by category, a filled dot when the overlay is on), the options of the selected one in the middle, and a live preview on the right drawn with the values you have not applied yet (on narrower windows, `Preview` at top shows it beside the options, `Esc` or its `✕` hides it). The switch at top turns the overlay on or off at once, as on the `Overlays` page (never a pending change); `Test on Screen` at top shows the race situation chosen under the preview on the overlays on screen. It also opens from a right-click on an overlay on screen, `Find Option` and the command palette (`Ctrl+K`).

- **Sections**: `General`, `Position & Layout`, `Font`, then one section per item the overlay shows (Speed, Time Gap, Fuel Level Bar...). The on/off switch of an item is in the title of its section; while it is off, its options are dimmed. Click a section title to fold it (`Collapse All` / `Expand All` at top), its `Reset` button puts its options back to default. `Display Order` is a list moved with the arrows. Relative, Standings and Rivals have a `Columns` list instead: the columns from left to right, each one with its on/off switch, moved by drag or arrows, and their live preview shows a sample race.
- **Only the options of the design in use** are shown: switch `Enable Classic Layout` and the options of the classic layout show up at once.
- **Search** (`Ctrl+F`): in `This overlay` or in `Every overlay`, for example `opacity` to set it for all overlays in one list. The `Filters` menu (number of filters on in its name): `Changed Only` lists the options changed from their default (in one overlay or in all of them; the overlay list shows how many options each overlay has changed), `Used Only` hides the options doing nothing with the current values (dimmed), `Advanced Options` for overlays with a simple mode.
- **Numbers have limits**: the tooltip of a number shows the values allowed (`Allowed: 0 - 4000`). A value out of range in a preset file is brought within the limits when the preset loads; `Check Preset` (Presets page menu) lists and repairs them.
- **Live preview**: the race situation menu (`Racing`, `Yellow & Blue Flags`, `In Pits`, `Damage`, `Rain`) shows what an overlay draws only then; `Test on Screen` (top of the page) shows it on the overlays on screen for 10 seconds; `Other Design` draws the same values with the other design (modern or classic).
- **`...` button of an option**: `Reset to Default`, `Apply to All Overlays` (the value goes to every overlay having this option: font, opacity, update interval, theme...), `Copy Option Name`.
- **Changes stay pending** until `Apply`, for as many overlays as you like: the overlay list shows how many changes each one has, `Undo` / `Redo` (`Ctrl+Z` / `Ctrl+Y`) and `Discard` are in the bar at the bottom. An invalid value is marked at once with the reason and blocks `Apply` (click the message to show it). `Apply` saves the preset once and restarts only the overlays you changed.
- **Dashboard HUD** (formerly Black box): its own sections, `Advanced Options` in `Filters` (simple mode shows the main items), the `Theme` menu (default or colorblind safe colors), display profile (options set by the profile say so; changing one switches to `Custom`) with the `Profile` menu to save the items shown as one of your own profiles, and a click on a part of the picture shows its options.

### Find any option

Press `Ctrl+F` (`Settings` > `Find Option…`) to search all options of all overlays, modules, the preset and the application, in English or in the current language (accents and case are ignored). Best matches come first, with the current value of each option; a dot marks options changed from their default.

- Click a result (or `Enter`) to open it: the `Overlay Options` page or the `Settings` page scrolled to the option, or a module page filtered on it.
- On / off options have a switch in the list (or `Space`): the change is saved and applied at once, with `Undo` in the notice; `Ctrl+Z` / `Ctrl+Y` undo and redo switches and resets of the page.
- The chips (`Overlays`, `Modules`, `Preset`, `Application`) narrow the results; `Changed Only` lists every option set apart from its default, even without search words.
- Right-click a result: `Reset to Default`, `Copy Option Key` (the name used in setting files and in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md)).

### Units

`Settings` > `Units` sets units for distance, fuel, speed, temperature, pressures, power and weight. Overlays, tools and the web dashboard follow them.

## Data modules

Modules compute the data that overlays show: lap times and deltas, fuel and energy, positions of every car, tyre and brake wear, track map... The `Module` page (command palette `Ctrl+K`, or add it to the navigation bar) shows each module as a card:

- what it computes, its state (`Running`, `Disabled`, or `Error` when it could not start: see the log) and its update interval;
- how many enabled overlays use its data (their names in the tooltip) and the modules using it. A module turned off that enabled overlays or modules need is flagged in orange, and `Enable Them` at the top of the page turns those modules back on;
- its switch and its `Options…` button (update intervals and options of the module). Right-click a card to reset its saved data: delta best (Delta), fuel and energy delta (Fuel), consumption history (Stint), sector best (Sectors), track map (Mapping).

Search, `All` / `Active` / `Inactive` and the keyboard work as on the `Overlays` page. Keep every module on unless you know an overlay does not need it.

## Presets

A preset stores the layout and options of all overlays and modules. You can keep several (one per car class, one for VR...), load one with a double-click on the `Preset` page, and have one loaded automatically per class or track. See [Presets and Settings](Presets-and-Settings.md).

## Hotkeys

The `Hotkey` page binds keys, mouse buttons and game controller buttons (wheel, button box, joystick, gamepad) to commands: show, hide or lock the overlay, reload or switch presets, restart the API, spectate the next driver, cycle the delta best source, show the next Dashboard HUD incident, bring the main window in front of the game and focus it, even from the tray (`show_main_window`), drive the [Broadcast Director](Broadcast-Director.md#hotkeys) (`director_*` commands), turn any overlay or module on or off, load a given preset, restart or quit the app.

1. Turn on the switch at the top to use global hotkeys (`Turn On` in the notice does the same).
2. Click the key button of a command (or `Enter` on its row) and press a key or key combination, a mouse button (middle, back, forward) or a controller button, then `Save`. `Clear` in the dialog empties it; preset commands also ask which preset to load. If the key is already used, the dialog names the command using it and its button becomes `Assign Anyway`.

Commands are in sections (`General`, `Spectate`, `Broadcast Director`, `Preset`, `Overlays`, `Module`) that fold, each with how many keys are assigned. `Search hotkeys` (`Ctrl+F`, `/` or just typing) finds a command, `Assigned only` lists bound commands only. Commands sharing a key are marked on both rows (`Same key as: …`). The cross of a row (or `Delete`) clears its key, `Clear All` every key: both at once, with `Undo` in the toast (`Ctrl+Z`).

Combinations with `Ctrl`, `Shift` and `Alt` work with any key, also the ones the app itself uses (`Ctrl+K`, `Ctrl+1`, `Ctrl+S`, `Alt`, `Enter`, `Space`...): while the key binding dialog is shown, keys only go to it (`Esc` still closes it), and held modifiers are shown (`Ctrl + Shift + …`) until you press the key. Modifiers must match exactly: a hotkey on `C` does not run with `Ctrl+C`, and `Ctrl+A` does not run with `Ctrl+Shift+A`.

Controller buttons are named after the device and the button (`Joy1 Button 5`, `Joy2 Pov Up` for the d-pad), and can be combined with `Ctrl`, `Shift` or `Alt`. Up to 16 devices with 128 buttons and a d-pad each are read, virtual controllers included: buttons of the SimHub Control Mapper (`SimHub Controller Remapper Bridge` or vJoy device) are bound like any other, and a short pulse (rotary encoder step) is still caught. A button held when the key binding dialog opens (a switch or rotary of a button box) is ignored until released. The device number follows the order Windows gives to controllers: if you plug or unplug a device, check the bindings again.

Hotkeys do not block the key or button for other programs (the game still sees it). On Linux, only controller buttons work (`/dev/input/js*`), keyboard hotkeys are not supported. The same commands can be run by other programs (Stream Deck, SimHub...): see [Connections](Connections.md#remote-control).

## Spectate

The `Spectate` page shows the data of another driver in your overlays (delta, fuel, timing, inputs...): in a replay, or while watching a session.

1. Turn on the switch at top right (or click any driver: spectate mode turns on).
2. Click a driver to follow it. The card on top shows the driver followed, with place, class, car and best lap; the arrows (`Alt+Left`, `Alt+Right`) go to the previous or next driver by place, `Stop` follows nobody.
3. Search by driver, car or class, keep one class with its chip, sort by position or name. Your own car is marked `You`.

Drivers are read only while the page is shown. The `spectate_mode`, `spectate_next_driver` and `spectate_previous_driver` hotkeys do the same from the game. The page is no longer in the navigation bar by default (open it from the command palette or the Home page quick access). To cast a whole race with cameras and graphics, use the [Broadcast Director](Broadcast-Director.md) (LMU).

## Next steps

- [Overlays](Overlays.md): designs, themes and the list of all overlays.
- [Telemetry Viewer](Telemetry-Viewer.md): analyze your laps.
- [Race Calculator](Race-Calculator.md): plan fuel, energy and tyres.
- [Troubleshooting](Troubleshooting.md) if something does not show up.
