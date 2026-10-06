# Changelog

All notable changes to **Modern Tiny Pedals**, newest version first. Version française : [CHANGELOG.fr.md](CHANGELOG.fr.md).
The full list of commits of each version is on the [Releases](https://github.com/Keenny38/ModernTinyPedals/releases) page.

## 0.22.2 (2026-10-06)

### Fixes

- **Update installed by the app also when run from source**: on Windows, `Download And Install` (or `Install Now`) of a copy run from source opened the download in the browser, and the setup ZIP had to be extracted and run by hand. It now downloads, checks and runs the installer like the installed app does: your installed copy is updated, or installed if there is none, then started. Its folder comes from the installer registry entry, else from the Start menu shortcut.
- The installed app now always updates its own folder.
- `Open Folder` of the `Replays` page showed no tooltip and stayed enabled without a replay folder.
- Closing the `Track Map Viewer` no longer logs a QML error.
- Settings saved from several threads at once (car brand names learned while driving) could stop the save of another settings file.

### Reliability

A full review of the code found and fixed about 90 issues, most of them rare.

- **Stream overlay access token and web dashboard access code kept across restarts**: they were reset at each start, so OBS browser sources stopped working after every restart of the app. Copy the source addresses once more after this update. Calculator collapsed sections, hidden Driver Stats columns and their widths were also forgotten at each start.
- **A language installed with a language pack** went back to English at each start.
- **Settings file held by another program at start** (antivirus, OneDrive): it was replaced with default settings and its backup deleted. The app now waits for it, and if it stays locked, uses default settings without ever saving over your file, and tells you so.
- **Recorded data no longer wrong after a pit stop or a cut lap**: a lap invalidated by the game (track limits) can no longer become your delta best or your best sector 1 and 2; the out lap no longer raises the reference pace used by the fuel module; a lap through the pit lane is not recorded as the track map; brake failure thickness is no longer saved under the next car; fuel and energy use is only recorded from the lap time of the lap just finished.
- **Online sessions**: when a driver leaves, the car taking their place in the game list no longer inherits their pit stops, stint laps, lap times, fuel use, speed trap or gap trend. A car whose telemetry is unknown shows no data instead of another car's.
- **Fuel module** with no known lap time (first laps on a new car and track): no more absurd laps and minutes remaining in time races.
- **Overlays**:
  - Modern overlays at 125 %, 150 % or 175 % Windows scaling redrew their whole background at every frame.
  - The impact cone of `Damage` stayed shown in the next session.
  - `Gear` froze during refuelling with a progressive consumption bar.
  - `Steering Meter` showed an angle of 0 with scale marks hidden.
  - `Pit Lane Helper` with `show_always` showed "–" for the distance to the pit box after the first stop.
  - `Elevation` showed the whole lap as driven at the start line.
  - `Delta Graph` could lose the previous lap trace at the line.
  - `Lap Time History` showed a wrong delta on its oldest lap.
  - `Race Notifications` could announce an old lap as fastest lap when a driver came back.
  - The classic `Delta Best` crashed with a bar range of 0.
  - `Black Box` no longer hides the "module off" notice when it could not start a required module.
  - Car brand logos: missing logos are no longer looked for on disk at every row change, and logos recolored for dark backgrounds are prepared about 50 times faster, no longer freezing overlays.
- **Car and circuit pictures from the game**: a car name with accents blocked every download for a minute, a server error marked a picture as missing for 7 days, and an empty catalog outside sessions was never read again.
- **Saved files**: one damaged line of the consumption history no longer drops the whole file, damaged driver stats values no longer stop the stats module, delta files of 10 to 12 lines are read again, track notes with invalid distances are skipped, and compressed telemetry laps are flushed to disk.
- **Presets**: renaming the loaded preset while a page had unsaved changes could create a second preset, renaming or duplicating right after a change could miss it, `Transfer` checks again that the destination is not loaded or locked, a name typed with `.json` is handled, and names reserved by Windows (`CON`, `NUL`...) are refused.
- **Connections**:
  - On Windows, a port already used by another program is now reported, instead of two programs sharing it.
  - Turning off the stream overlay or its LAN access now also disconnects browsers already connected.
  - A port out of range no longer stops the app from starting.
  - Idle web dashboard and remote control clients are disconnected after 15 seconds.
- **Updates**: an unsigned installer is only accepted from the official repository, checked against the repository where the update was found.
- **Plugins**: a damaged plugin `.zip` shows an error instead of failing silently, no half-installed plugin is left behind, and a plugin trusted after review is refused if its code changed meanwhile.
- **App**: closing the app after a failed restart works again, no more tray icon left after a restart, a locked `pid.log` or an invalid user path no longer stops the app from starting, the VR mirror keeps updating when SteamVR fails, pages reading from the game no longer stay busy after an error, `Replays` copies no longer stay stuck at "copying", Driver Stats reads its laps once when moving through the list, and the `Telemetry Viewer` reads the laps of a large track in the background.
- **Shortcuts** with modifiers typed in another order (`shift+ctrl+f1`) work, and the stream overlay access token is removed from bug reports.

### Performance

Less CPU used while driving, and smoother app pages.

- **Data modules** (delta, force, fuel, hybrid, mapping, notes, sectors, vehicles, wheels) skip their work when the game sent no new data since the last update, instead of computing again 100 times per second. Smoothing (G force, delta, average suspension position) now counts game samples as its option says: before, repeated samples made it react faster than set.
- **Map overlays** (track map, radar, navigation, spotter) only redraw when cars moved. Place numbers on the classic track map are drawn from a cache.
- **Stopping modules** (preset reload, quit, spectating another driver) asks every module to stop at once, then waits for all of them together.
- **VR overlay** and **stream overlay** capture only copy the overlays that changed since the last frame, and the VR overlay no longer draws every overlay twice.
- **Home page**: the last session is read from the end of the driver history instead of the whole file.
- **Stream page**: no network address lookup every second (addresses kept 30 seconds).
- **Driver Stats**: the page no longer waits while the stats file is being saved by a module.
- **App pages** stop their timers and animations while hidden behind another page, in the tray or minimized: replay map, race calculator, stream overlays, track map viewer playback, incident timeline. Status dots pulse three times instead of forever, and cars on the replay map glide between two game answers then rest.
- **Telemetry Viewer**: zooming, panning and playback do less work per frame (one view update per frame, cached lists, cursor values computed once, corner labels placed again only when the zoom changes), hidden side tabs no longer follow the cursor, and charts and maps are built 3 to 6 times faster.
- **Overlay pictures** of the `Overlays`, `Overlay Options` and setup pages are loaded in the background and only reloaded when they changed.
- **Overlay Options**: changing an option updates only its row instead of the whole page.
- **Search fields** search 120 ms after the last key instead of on every key (Enter searches at once).
- **Settings** and the lap list of the `Telemetry Viewer` reuse their rows while scrolling.
- **Race Results** positions chart and **Driver Stats** chart only redraw the highlighted lines on hover.
- **Replays page**: folder sizes computed once instead of on every copy progress step, and the incident timeline, standings and laps only updated when they changed.
- Lists sorted again (stats, replays, spectate) update in one step instead of moving rows one by one.

## 0.22.1 (2026-10-06)

### Fixes

- **Session best delta kept during the session**: restarting the app, reloading a preset (also the automatic preset of the car class), saving a global setting or changing screen setup no longer forgets the session best and stint best laps; the session delta then became the same as the stint delta. Both laps are saved next to the delta best file of the track and class (`.session`) and loaded again in the same session.
- **No delta on out laps**: in Le Mans Ultimate, going back to the garage starts a new lap whose time counts the time spent there, and the lap distance is negative in the garage and in the pit lane before the start line. Delta overlays showed `+0.000` everywhere, then a huge delta once on track. On an out lap and in the pit lane before the line, `Deltabest`, `Deltabest Extended`, `Delta Graph`, `Lap Time History`, `Black Box` and the web dashboard now show a dash (line interrupted on the graph), and the estimated lap time is left empty. A stint best not set yet, and a last lap with a pit stop, show a dash instead of `+0.000` too.
- A new session also starts a new stint: the stint best of the previous session was kept until the first pit stop.

## 0.22.0 (2026-10-06)

### Overlay edit mode

Placing the overlays on the game screen is now a real **edit mode**. Unlock the overlay (`Unlock Overlay` on the Home page, tray menu, command palette or `overlay_lock` hotkey) and a toolbar shows up at the top of the game screen.

- **Every overlay shows its outline and name**, also the ones that draw nothing yet and the ones hidden by `Auto Hide` or by their visibility context: each one can be found and moved, even from the game menus.
- **Toolbar**: `Snap`, `Grid` and `Guides` toggles, `Undo` / `Redo`, the active overlays (uncheck one to turn it off) and `Done` to lock the overlay. Drag it by its grip; the `✕` hides it and leaves the overlay unlocked.
- **Magnetic snapping**: a dragged overlay snaps to screen edges, screen center and the edges and centers of the other overlays (new `enable_magnetic_snap` option, on by default). Hold `Ctrl` to move freely, `Shift` to keep the move horizontal or vertical. The guides show the aligned lines and the position of the overlay.
- **Keyboard**: click an overlay to select it (solid outline), then arrow keys move it by one pixel (`Shift`: 10 pixels, one grid step with `Grid Move`), `Ctrl+Z` / `Ctrl+Y` undo and redo, `Delete` turns it off, `Esc` unselects it.
- **Undo** for moves, arrow keys, centering, resizing with the corner handle, opacity, visibility and turning an overlay off, until the overlay is locked.
- **Right-click menu**: `Move to Screen` (same place on another monitor), `Visibility` (Always, Race, Qualifying & Race, Practice & Qualifying, On Track, In Pits), `Opacity`, `Undo`, `Edit Mode` and `Lock Overlay`, next to `Config`, centering, `Reload` and `Disable`.

An overlay already unlocked at startup does not start edit mode: as before, its outline only shows under the mouse, so nothing stays on screen while driving with an unlocked overlay.

![Overlay edit mode: toolbar, selected overlay, alignment guide and position](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.22.0-overlay-edit-mode.png)

#### Fixes and performance

- `Center Horizontally` and `Center Vertically` center the overlay on its own screen: on a second monitor it was moved to the first one.
- An overlay left outside every screen (monitor unplugged, preset made on another computer) is shown on the nearest screen at startup, its saved position kept (`enable_window_position_correction`, off with the VR overlay).
- Locking and unlocking no longer hides and shows every overlay window: no flicker.
- Locked overlays no longer send each update and paint event through the edit outline (less work while driving), and the outline is only created the first time the overlay is unlocked.
- The alignment guides only redraw what changes on each mouse move instead of the whole screen, and free their screen-sized image once the drag ends.

### Modern design for every overlay

The ten graphic overlays get their own modern design, drawn for it instead of the classic drawing in modern colors. They read the game data the same way as the classic layout, so both show the same values.

- **Radar**: round, fading at its edge, with an amber then red glow toward a car alongside.
- **Track map**: cars as numbered dots in their class colors (or race status colors), checkered start line.
- **Navigation**: road with edge lines, view fading at its edge.
- **Friction circle**: G rings, a trace fading with age and the recent peaks.
- **Heading**: compass ring with yaw and front slip angle.
- **Steering wheel**, **instrument** and **weather forecast**: wheel and icons drawn as shapes in the theme colors.
- **Trailing**: soft areas under the throttle and brake lines.
- **Track notes**: note on a card.

![Radar, track map and navigation, before and after](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-06-map-overlays-design.png)

**Black box**, **chat**, **elevation**, **flag**, **steering meter**, **race notifications** and **RPM LED** get a new modern design too: every overlay has one now (`enable_classic_layout` or a Legacy theme bring the classic look back).

- **Black box**: same layout and options, drawn in the Barlow font with capital labels, theme colors (colors left at their default value follow the overlay theme and the colorblind option, your own colors are kept), cards with soft shading and a hairline border, capsule RPM LEDs.
- **Flag**: one chip per active item in its flag color (yellow, blue, green, red...), caption above the value: pit time, fuel left, speed with the limiter on, distance to the yellow flag, class and time of the blue flag, traffic gap, pit window, repair time, sectors under yellow, full course yellow phase. Inactive items take no room; `*_text` options you changed replace the captions.
- **Chat**: one card growing with the messages, each sender in its own color, new messages highlighted with an accent edge, messages fading out at the end of their display time.
- **Elevation**: elevation profile on a chart, the part of the lap already driven in accent color, the car as a dot on the profile, current elevation and scale above the chart.
- **Steering meter**: bar growing from the center toward the steering side with a thumb, scale marks, angle written on the other half.
- **Race notifications**: an icon for each message (arrow, flag, stopwatch, penalty, invalid lap), title above detail, a thin bar shrinking with the time left.
- **RPM LED**: unlit LEDs keep a faint tint of their color zone, so the green, yellow and red zones show before they light up.
- On the `Overlays` page, flag, chat, race notifications and spotter show a sample instead of an empty picture.

### Spotter

- **Clear signal**: a side bar flashes green once the car alongside is gone, like a spotter calling "clear" (`show_clear_signal`, `clear_signal_duration`; `bar_color_clear` in classic layout).
- **Car coming up behind**: the bottom of a side bar lights up while a car comes up behind on that side, brighter as it gets closer (`show_approaching_cars`, `approaching_distance`). A car right behind you in your lane is left out.
- Modern design: rounded bars glowing toward the screen center, going from amber to red as the car alongside gets closer sideways.

### Real logos and pictures from the game

With Le Mans Ultimate, the app shows the real **car brand logos**, **circuit logos**, **car pictures** and **circuit pictures** of the game menus. They are taken from the game running on your computer (`enable_restapi_access`, on by default) and kept in the new `gameimage` folder: nothing is shipped with the app, and they show up once the game was open with the app.

- **Overlays**: brand logo column of Relative, Standings and Rivals (`column_brand_logo`), now on by default and turned on once in existing presets, a bit wider. While a brand has no logo, its first letters are shown.
- **Pages**: circuit and brand logos, car and circuit pictures on the Home page and the Race Results, Driver Stats, Spectate, Replays, Race Calculator, Telemetry and Track Map Viewer pages.
- **Stream overlay**: the race results source shows the circuit logo and the car brand logos.
- A PNG logo of your own in the `brandlogo` folder still comes first (a word of the brand is enough: `Corvette.png` for "Chevrolet Corvette"). Logos get a readable copy on dark and light backgrounds and their empty margins trimmed. With rFactor 2, your own files are the only logos.

![Brand logo column on by default](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-06-brand-logo-column.png)

### Overlay Options

- **Relative, Standings and Rivals** list their columns in one `Columns` list, from left to right as the overlay draws them: switch each column on or off, drag it or use the arrows to move it. Sections follow for the rows, the classes and number of cars, then the options of each column, dimmed while the column is hidden.
- Their live preview shows a sample race with fictional drivers.

### Removed

- The **example speed plugin** is no longer shipped, and the installer removes the copy of earlier versions. Overlay plugins still work: [Widget plugins](docs/customization.md#widget-plugins) has a short example.

## 0.21.0 (2026-10-06)

### Race results

A new **Race Results** page (`Results` in the navigation bar, or `Tools` > `Race Results`) shows every session you played, online or single player, from the results files Le Mans Ultimate and rFactor 2 write at the end of each session. Nothing to set up: the results folder is found in your Steam libraries, and the game does not need to run.

- **Sessions** by day with the session kind, track, number of cars and your result (position, class position, `DNF`). Search, `Races` / `Qualifying` / `Practice` filter, sessions where nobody completed a lap hidden. A session that ends while the page is open shows up at once.
- **Your key figures**: position and class position, places gained or lost from the grid, best lap and its rank in your class, laps and pit stops, contacts with cars and walls, track limits points and penalties. Your car is found by the driver name of your game profile, also as a driver of a team car.
- **Classification**: position and places gained, class, number, driver and team, car, laps, race time then gaps (time or laps behind), best lap (fastest in purple), pit stops, contacts. Class chips show one class with class positions and gaps. A race left before its end is marked `Unfinished`, with gaps taken from the lap times.
- **Positions**: the place of every car lap by lap from the grid, your car and the car picked highlighted.
- **Laps** of any car: place, lap time, gap to its best, sectors (session and own bests colored), top speed, tyre compound, pit lane, and for your car the energy (or fuel) used and the tyre tread left. Best lap, average, consistency, theoretical best and top speed on top.
- **Events**: contacts (shown once when both cars report them), penalties, track limits and chat, with a filter by kind and the events of one car. Retirement reasons and penalties are shown in the app language.

| Classification of a multiclass race | Positions lap by lap |
|---|---|
| ![Race results](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-race-results.png) | ![Positions](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-race-results-positions.png) |

### Stream overlays (OBS Studio, Streamlabs, XSplit, vMix)

The overlays can now be added to your stream as **browser sources**: transparent background, no chroma key, drawn exactly as on screen, also while the game runs in exclusive fullscreen. Open the new **Stream Overlays** page (`Tools` > `Stream Overlays`), turn it on, and `Copy Address`.

- **Layout**: every overlay at its place on screen, in one source. **One source per overlay**, at the size shown on the page.
- **On screen, on stream or both**: each overlay is `Screen & Stream`, `Stream Only` (shown to your viewers, not on your screen while overlays are locked) or `Screen Only` (never on stream). Also the new `stream_visibility` option of every overlay.
- **Race results for your viewers**: the classification of the last race (or qualifying), all classes or class by class, pages cycling, refreshed when the game writes a new results file.
- Light on resources: images are only captured while a source is shown, copied from what is already on screen, and only sent again when they change (15, 30 or 60 images per second at most).
- Every address holds an access token (`New Access Token` if one was shown on stream by mistake), and `Another computer (LAN)` serves a streaming PC on your local network. The settings are also in the Config page (`Stream Overlay`).

![Stream Overlays page](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-stream-overlays.png)

![Race results as a browser source](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-stream-race-results.png)

### Telemetry Compare overlay

A new **Telemetry Compare** overlay (off by default, `Driver Inputs` category) shows the reference lap of the telemetry viewer while you drive.

- **Speed, throttle and brake** of your current lap over the reference lap (steering and gear as options), from `250` m behind the car to `150` m ahead (`distance_behind`, `distance_ahead`): the **next braking point of the reference lap shows ahead of the car**.
- **Speed difference** and **delta** to the reference lap at the same distance, with the reference lap time.
- `reference_lap_source`: `Viewer` (the lap set as reference in the telemetry viewer, else the fastest valid lap), `Best` or `Last` recorded lap. A new best lap, or a reference changed in the viewer, is used while you drive.

![Telemetry Compare overlay: braking point of the reference lap ahead of the car](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-telemetry-compare.png)

### Telemetry viewer

- **Only laps of the reference lap's circuit are compared**: a lap of another circuit stays in the list, greyed out, with a message telling why. Set it as reference lap to look at it.
- **`Live`**: a new best lap is compared with the previous best, a reference lap you picked stays the reference, and the viewer switches to the track you are driving.
- **Track map**: with LMU, the circuit path from the game is a racing line, not the track center. Track edges come from laps that recorded them, else from the spread of your laps. **Distance to Center** and **Track Position** are measured on the map when a lap did not record them.
- **Session**: stints split on pit stops (refuel, tyre change).
- **MoTeC import** (`.ld`): laps named with the log date, engine temperatures, inner / middle / outer tyre temperatures, brake bias, tyre load and track position imported too, a lap already imported is not copied again. `Import Folder...` again only adds the new laps, and `Imported Laps...` deletes to the trash with `Undo`.
- **`Use as Delta Best...`**: your first delta best is always kept as a backup, plus the 5 latest ones, and a teammate's lap of the same track and class can be used.
- **Faster**: tracks with hundreds of laps open quickly (lap details kept in an index), MoTeC imports run in the background process.
- **Keyboard**: in the large map, map keys go to the map and the others still reach the charts. On an AZERTY keyboard the digit row works without `Shift`. `Esc` never closes the viewer.

### Config page and redesigned pages

#### Config page

Every global option of the app in **one page**, `Config` in the navigation bar (also `Ctrl+,`, the gear button at the bottom of the bar, every `Config` menu entry and the command palette). It replaces the separate pages of Application, Overlay Style, Notification, Compatibility, Remote Control, Web Dashboard, VR Overlay and User Path.

- **Categories** on the left, options in groups with their description, and an editor made for each option: switch, choice list, number with its limits, color with a picker, folder with `Choose Folder...` and `Open Folder`.
- **Search through every category**, the number of matches shown next to each category.
- **Changes kept pending** until `Apply` (`Ctrl+S`): the bar at the bottom counts them, with `Undo`, `Redo` (`Ctrl+Z`, `Ctrl+Y`) and `Discard`. Invalid values are shown in red with the reason. Reset one option to default with its arrow, or the whole category with `Reset Section`.
- **Web dashboard addresses and access code** with copy buttons, remote control command and stream addresses, a preview of each notification with its colors.
- Units, global font override and API options (saved in the preset) one click away.

![Config page](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-config-page.png)

#### Presets page

- The loaded preset and `Auto Load Primary Preset` on top. Each preset shows its last change, the overlays and modules it turns on, its car class and track tags, its preset hotkeys and its lock.
- Search by preset, class or track name, sort by last change or by name.
- **Details of the selected preset** on wide windows: the overlays and modules it contains, the game it remembers, every action, car classes and tracks added or removed in one click.
- New, duplicate and rename in a box that **checks the name as you type** (characters not allowed in file names, existing preset). `Ctrl+N`, `F2`, `Del`, `Ctrl+Z` puts back the last deleted preset.
- Preset files are read again only when they changed, and only while the page is shown.

![Presets page](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-presets-page.png)

#### Spectate page

- The drivers of the session with place, class color, car, best lap and pit or garage state. Search, class chips, sort by position or by name. Your car is marked `You`.
- **Click a driver to follow it** (spectate mode turns on by itself). The card on top shows the driver followed, with previous and next driver by place (`Alt+Left`, `Alt+Right`) and `Stop`.
- Drivers are read only while the page is shown.

![Spectate page](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-spectate-page.png)

#### Modules page

- Each module is a **card that says what it computes** (lap times and deltas, fuel and energy, positions of every car...), with its state (`Running`, `Disabled`, `Error` when it could not start) and its update interval.
- **What depends on it**: the number of enabled overlays using its data (their names in the tooltip) and the modules using it, found in the code of each overlay. A module turned off that enabled overlays or modules need is flagged, with `Enable Them` at the top of the page; a module needing a module that is off says so.
- Search (accents and case ignored, in names and descriptions), `All` / `Active` / `Inactive`, `Enable Shown` / `Disable Shown` while filtered.
- Right-click a card: `Config...`, enable or disable, and **reset its saved data** (delta best, fuel and energy delta, consumption history, sector best, track map).
- Keyboard like the Overlays page: type to search, `/`, arrows, `Space`, `Enter`.

![Modules page](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-modules-page.png)

#### Find Option (`Ctrl+F`)

- **Best matches first**, accents and case ignored, with the **current value** of each option and a dot on options changed from their default.
- **On / off options switch right in the list** (or `Space`): saved and applied at once.
- `Changed only` lists every option you changed, even without search words. Chips narrow the results to overlays, modules, preset or application options.
- A result opens the Overlay Options page, the Config page or the module page at the option. Right click: `Reset to Default`, `Copy Option Key`.

![Find Option](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-find-option.png)

#### Setup wizard

- **Six steps** with progress on the left: Welcome, Game, Units, Appearance, Overlays, Ready. Click a step to go back to it, `Enter` goes to the next one. Nothing changes until `Finish Setup`: closing the wizard (`Esc` or the window close button, after a confirmation) keeps everything as it was.
- **The wizard switches language as soon as you pick one**, the app follows once setup is finished.
- **Game**: the game running now is marked `Running` and picked for you.
- **Units** (new): `Metric` or `Imperial` for speed, temperature, fuel, pressure and weight, saved in the preset. Mixed units of a preset can be kept.
- **Appearance**: the four window themes drawn in their colors, the four overlay themes with an overlay drawn in each, `Colorblind safe colors` and the modern font, and a preview of overlays in the chosen style.
- **Overlays**: new or existing preset (the name is checked as you type), and overlays shown as **pictures** to pick: `Recommended`, `All` or `None`. With an existing preset, its overlays already on are checked, and unchecking one turns it off. Every overlay a new preset turns on is listed.
- **Ready**: every choice with `Change` to go back to it, and tips for the first drive.
- Overlay pictures are drawn in the background, only from the Appearance step on, and kept per style.

| Appearance | Preset and overlays |
|---|---|
| ![Setup wizard appearance](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-setup-wizard-appearance.png) | ![Setup wizard overlays](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-setup-wizard-overlays.png) |

### Themes

The app and the overlays now have **four themes**, chosen separately: `Modern Dark` (default), `Modern Light`, `Legacy Dark` and `Legacy Light`.

- **Overlays** (`overlay_theme` in `Config` > `Overlay Style`): `Modern` themes use the modern design, `Legacy` themes bring back the original TinyPedal look (classic layout, colors and fonts) for every overlay. Light themes invert gray panels and text, keep flags and warnings in their colors and darken the colors drawn on panels (heatmap temperatures, gains and losses, tyre compounds) so they stay readable. Colors you customized are kept in every theme.
- **Colorblind safe colors** (`enable_colorblind_colors`): a variant of every overlay theme with the Okabe-Ito palette, red / green pairs become orange / blue. Also in the setup wizard.
- **Window** (`window_color_theme` in `Config` > `Application`, or the theme button of the status bar): `Modern` themes keep the current colors, `Legacy` themes use the colors of TinyPedal 2.50.
- **Removed**: the `High Contrast`, `Colorblind Safe` and `Classic` overlay themes, the theme of each overlay (`widget_theme`), the `Overlay Theme Editor` and its custom themes (`overlay_themes.json` is no longer read), and the `System` window theme. Black box `Color Theme...` keeps `Default` and `Colorblind Safe`.
- **Modern Dark for everyone** after this update, for the window and the overlays, whatever theme you used (the former `Colorblind Safe` overlay theme becomes `Modern Dark` with colorblind safe colors). Choose another theme afterwards, it is kept.

![Overlay themes](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-06-overlay-themes.png)

### Overlay options

The options of every overlay are now in **one page**, `Overlay Options`: the overlays on the left by category, the options of the one you pick in the middle, a live preview on the right. It opens from the gear of an overlay card, a right click on an overlay, Find Option and the command palette, and you switch overlays without closing anything.

- **Sections for every overlay**, not only the Black box: `General`, `Position & Layout`, `Font`, then one section per item the overlay shows (Speed, Time Gap, Fuel Level Bar...) with **its on/off switch in the section title**. Options of an item that is off are dimmed. Fold a section by clicking its title (`Collapse All`, `Expand All`), `Reset` beside it resets that section only.
- **Changes to several overlays** kept pending until `Apply` (`Ctrl+S`): the overlay list shows how many each one has, with `Undo`, `Redo` (`Ctrl+Z`, `Ctrl+Y`) and `Discard`. Invalid values are marked at once with the reason. `Apply` saves the preset once and restarts only the overlays you changed.
- **Search this overlay or every overlay**: type `opacity` and set it for all your overlays in one list. `Changed only` lists the options changed from their default, in one overlay or in all of them, and the overlay list shows how many options each overlay has changed.
- **Apply to All Overlays** (the `...` button of an option): its value goes to every overlay that has it, for example a font, the opacity or the update rate.
- **Display order** as a list moved with arrows, right in the page (it was a separate window).
- **Live preview** of the overlay with your unsaved values.
- Only the options of the design in use are shown, and switching `Enable Classic Layout` shows the options of the other design at once. The Black box keeps its own sections, simple mode, color themes and display profile (options set by the profile are locked and say so).

| An overlay in sections, preview with unsaved values | Opacity of every overlay in one search |
|---|---|
| ![Overlay Options page](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-overlay-options.png) | ![Search in every overlay](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.21.0-overlay-options-search.png) |

### Navigation bar and Home quick access

- **New navigation bar for everyone**: `Home`, `Overlays`, `Stats`, `Results`, `Replays`, `Telemetry`, `Spectate`, `Race`, `Preset`, `Config`. `Module`, `Hotkey`, `Tools` and `Pacenotes` leave the bar: open them from the command palette (`Ctrl+K`), the Home quick access, or add them back with `Customize Navigation Bar...`. A bar you had customized is reset too.
- **New Home quick access**: Lap Telemetry Viewer, Race Calculator, Driver Stats Viewer, Layout Editor, Widget Performance, Game Replays, Overlays, Module, Preset, Spectate, Hotkey, Tools, Config, Create Bug Report and Check for Updates.

### Main window size

- **Comfortable size at first launch**, centered on the screen (it opened at its smallest size).
- **Never too small**: the page area keeps a minimum size so pages never overlap or get cut, larger while the telemetry viewer (toolbar and three panels whole, in every language) or driver stats are shown. The navigation bar keeps its width (it could be squeezed until its entries vanished), and its selected entry stays in view when the window is short. On a small screen, the minimum is lowered so the window still fits.
- **Maximized window remembered**, and shown maximized again from the tray or the taskbar.
- **Size and position saved a moment after each change**, so a crash or a system shutdown keeps them too (they were saved only by `Quit`).
- **Wide tools** (race results, telemetry, layout editor...) grow the window only while they are open: it stays inside the screen (moved instead of going past its edge) and gets back its size and place once they close. Quitting with one open no longer keeps the grown size for good.
- **Window kept on screen**: brought back if it was left on a monitor that is no longer there, shrunk if larger than the screen, title bar never hidden.
- **`Window` > `Reset Window Size and Position`** (also in the command palette, `Ctrl+K`): back to the default size, centered.

### Lower memory use

The app uses about a third less memory: about 77 MB instead of 115 MB once started with the default preset, and 119 MB instead of 200 MB while the window waits in the tray after the Overlays page was opened.

- **Only what you use is loaded**: overlays turned off no longer load their code, and the pages of the main window are built the first time you open them. The pace notes audio player is only created while playback is on.
- **Window in the tray while racing**: once the main window stays hidden in the tray (or minimized) for a minute, its pages are released, and in the tray its graphics resources are freed too. Everything is built again when you open the window (the page shown takes a moment to appear).
- **Long races**: modern overlays keep cached texts in proportion to what they draw, so their memory no longer grows with every new lap time, gap or temperature.
- **Overlays page**: pictures of overlays drawn with the modern design no longer load the classic code of these overlays.
- The main window font is set on the app font instead of the style sheet: the icons of the Home page cards no longer search every installed font (about 20 MB), and the cards are slightly more compact.

### Fixes

- **Spectate hotkeys**: `spectate_next_driver` and `spectate_previous_driver` followed the wrong driver once a car had left the session (its position in the car list was saved instead of its slot), and `spectate_mode` only took effect at the next API restart.

## 0.20.2 (2026-10-06)

### Fixes

- **System performance**: the app CPU use is never shown over 100% (readings close together gave values like 1026.88%, too wide for the overlay).

## 0.20.1 (2026-10-06)

### Updates from the app

- **The Windows installer is published as an `.exe` again**: `ModernTinyPedals-<version>-windows-setup.exe`, with its `.sha256` file, beside `-setup.zip` and `-source.zip`. Apps up to 0.19 can update from the app again: they look for these files, missing from 0.20.0.

## 0.20.0 (2026-10-05)

A full audit of the app: more than 150 fixes, 7 new overlays, the modern design now on par with the classic one, new Le Mans Ultimate data in the overlays, redesigned Race calculator, Driver stats, Overlays and Game Replays pages, many more tools in the telemetry viewer, and release notes in the app language. More than 2,300 tests now cover 91% of the code.

### New overlays

All of them are disabled by default; enable them in the `Overlays` tab.

- **Delta graph**: the delta all along the lap (loss in red, gain in green) with the previous lap in the background. Reference of your choice: best lap, session, stint or last lap.
- **Gap trend**: gap to the car ahead and behind over the last laps, with what you gain or lose per lap. All classes or within your class.
- **Pit lane helper**: speed against the limit, pit limiter (warning if it is not on), distance to the pit box and planned services. Shown only when approaching and in the pit lane.
- **Stint timer**: stint time and laps, countdown to the maximum stint length, each driver's driving time against their fair share or the required minimum.
- **Spotter**: bars on the edges of the screen when a car is alongside you, brighter when it is very close.
- **Race notifications**: positions gained or lost (overall and in class), penalty, fastest lap in class, blue flag, full course yellow, lap invalidated. Each type can be turned off separately.
- **Tyre temp trend**: temperature of each tyre over the last seconds or per lap, with the ideal temperature given by LMU.

![New overlays](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-nouveaux-overlays-course.png)

![Pit lane helper](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-aide-voie-des-stands.png)

### Modern design: everything the classic one did

- **Standings**: average lap, speed trap, lift & coast and brand logo columns, tyre compounds wheel by wheel when they differ, custom texts (pit, garage, leader), class position in the class color.
- **Race plan**: live recalculation, check of the game's pit menu (`80>60L` in red if it differs from the plan), target fuel consumption per lap, and optionally what limits the stints and the consumption estimation method.
- **Row order**: the `display_order_*` options apply to the modern design as soon as you change one, and the `Display Order` button is back.
- Adjustable colors for the redesigned overlays (radar, map, flags…), center spring mark (suspension), pedal mark (brake pressure), RPM, battery and fuel consumption on the gear overlay, 100% pedal indicator, custom session names, inverted delta style, damage shown as integrity.

![Standings: new columns](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-classements-nouvelles-colonnes.png)

### Le Mans Ultimate: new data in the overlays

- **Official game delta** in delta best (option), **invalidated lap** flagged on the timing overlays.
- **Puncture** read from the game (instead of being estimated from wear), **engine overheating**.
- **Automatic tyre heatmap** centered on the ideal temperature given by the game (option).
- **Sector yellow flags** and full course yellow (FCY) phases, **wind** in the weather, front and rear **ride height**, **pit limiter reminder** in the pit lane.

![Race plan, weather and gear](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-overlays-nouvelles-tuiles.png)

### Telemetry viewer

#### Charts

- **Values fitted to the visible part**, panel by panel (right-click a panel).
- **Your own math channels**: a formula built from recorded channels (`+ - * /`, `abs`, `min`, `max`, derivative `d()`), with understeer angle, brake release rate and throttle application rate ready to use.
- **Align laps on braking**: the charts are shifted so that each lap's braking for a corner starts at the same spot.
- CSV export on a time base.

#### Map and views

- Keyboard zoom (`+` / `-`, arrows), zoom and lap filter in the G circle and the XY view.
- **Consistency per mini-sector**: each mini-sector colored by the spread of its times over the stint, the session or the shown laps.

#### Compare

- **Import a teammate's laps** from another folder (same track and same class), marked as foreign.
- **Best lap in similar conditions** (track temperature, tyre compound, wet track) as reference.
- **Setup differences** between two laps, and a **corner report** as HTML or PDF.

#### Fixes

- Exact delta and ideal lap: the ends of the lap were cut off (up to 0.19 s off on the delta, 0.4 s on the ideal lap).
- A damaged lap file no longer makes loading restart in a loop, laps from another track are flagged and left out of the ideal lap, the A/B markers follow the distance / time switch.
- The app's distance unit is respected, decimal comma in French, MoTeC import runs in the background.
- **Smooth lap playback**: the cursor moves on every frame (it used to stall one frame in four and jump the next), and the charts slide to the next part of the lap instead of jumping.

### Race calculator

#### Redesigned page

- **New modern page** (Qt Quick, like the `Overlays` page): race setup, key figures and the **strategy timeline always in view** above the `Fuel`, `Tyres` and `Team` tabs. The timeline now shows the **fuel in the tank** over the race, safety car and rain laps, and its stints slide into place when the plan changes.
- **Input sections that fold** (they stay folded, their main values shown in the title), switch of the `Safety Car` and `Rain` scenarios in their title, consumption history beside the plan or below it on a narrow window.
- **Faster to type**: `Up` / `Down` (or the mouse wheel in the selected field) step a value, `Shift` by ten steps, `Esc` cancels what you typed, lap time typed in one field (`1:59.950` or seconds).
- **Tyre plan**: drag a tyre from the stock onto a wheel or click a wheel to pick one, tread at the start and end of each stint as a colored bar, compound colors, `Delete` takes a tyre off. Stock and rules actions in compact menus.
- **Consumption history**: `Ctrl` / `Shift` selection, `Ctrl+A`, double click adds a lap, `Delete` deletes the selected laps.
- **Lighter**: the page is built when first shown, the `Tyres` and `Team` tabs when first opened, and only the parts of the results that change are redrawn. The plan picture (`Save Image...`, `Copy Picture`) is drawn at the same size whatever the window size.

![Race calculator: strategy, fuel in the tank and pit stop plan](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-race-calculator.png)

![Race calculator: tyre plan and stock](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-race-calculator-tyres.png)

#### Strategy

- **Stints limited by tyre life**: laps per set of tyres, tyre changes placed in the plan.
- **Driver of each stint** recorded at pit stops, shown in "Plan against Race".
- Fuel unit (L / gal) on the plan, **copy the plan as an image** for Discord.
- Share codes keep the fuel unit: a plan in gallons is no longer read as liters.
- Fixed: the pit stop counter went back to zero every second during a race, and the current stint was counted from the planned stop instead of the actual stop.

### Driver stats

#### Redesigned page

- **Track name as the page title** with what matters at a glance: number of vehicles and sessions, last driven date, a `Live` badge on the track of the running game session, and a back button to `All Tracks` (`Alt+←`).
- **Key figures with icons**: the level shown with its letter, valid laps with a share bar, values fading in when they change.
- **Level scale** of the selected vehicle: the six levels from `Offline` to `Alien`, where your personal best, qualifying and race bests stand, the gap to the reference and the time to find for the next level. The level list marks your bests with badges.
- **Wider progression chart** under the table, next to the sessions list: round lap time grid, personal best line over a shaded area, level letters at the end of the limit lines, drawn from left to right when you pick another vehicle. Sessions show their type (practice, qualifying, race) and the podium in color.
- **All Tracks**: a **daily activity calendar** of the last 12 months (driving time per day, days driven, longest streak) and the **recent sessions** of every track: click one to open its track and vehicle.
- **Table**: levels as colored badges, personal best in bold, missing values dimmed, selected row marked, rows sliding to their place when sorted. `Delete` removes the selected vehicle (or track), `Backspace` goes back to `All Tracks`, `F5` reloads, `/` searches a track.
- Clearer empty states, `Delete all stats of this track` and `Restore Backup` moved to the `⋯` menu, icons only for the menus when the window is narrow.

![Driver stats: level scale, progression and sessions](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-driver-stats.png)

![Driver stats, all tracks: activity calendar and recent sessions](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-driver-stats-career.png)

#### Faster

- Sorting no longer rebuilds the table (about 25 times faster), and the stats saved at each lap while you drive refresh the page 4 to 5 times faster: the session history is read again only when it changes.

#### Stints, export and friends

- **Pace and degradation per tyre compound** over recorded stints, **consistency index** per session and per track.
- **Export** of the session history as CSV or JSON, and **comparison with a friend's stats** (exported JSON file).

### Fuel and energy

- **Green-flag consumption** (option): median of the last green-flag laps, leaving out laps under FCY or safety car, pit laps and invalidated laps.
- The extra lap when the leader crosses the line before the time runs out now counts in the laps left.
- Fixed: "+664 laps" on the formation lap and the first lap.

### Interface

- **New home page**: version and **`Release Notes`** button for the installed version (readable offline), available update highlighted, game status with the current session (track, session, position, lap), overlay lock in one click, last session driven, game setup reminder as long as the game is not running, **customizable quick access** (tools, pages and actions of your choice, in the order you want, with `Customize...` or right-click). Clickable cards and a 1 to 3 column layout depending on the width.
- **Redesigned `Overlays` page**: each overlay is a card with a **preview drawn with your settings** (redrawn when you save its options), its category and its switch, or a compact list (preview in a tooltip); the view is remembered. Search ignores accents and case and accepts several words, category chips show how many overlays match, `All` / `Active` / `Inactive` filter, animated list. `Enable Shown` / `Disable Shown` switch only the filtered overlays. An overlay that is on but could not start shows an `Error` badge, with a link to the log. Right-click menu, keyboard (type to search, `/`, arrows, `Space`, `Enter`). Faster: the page is built when first shown and previews are drawn in the background, only while the page is visible.

![Overlays page: cards with preview, search and category chips](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-overlays-page.png)

- **Customize the navigation bar, quick access and display order**: new layout with the shown entries on the left (numbered, with their `Ctrl+1` to `Ctrl+9` shortcut for the bar) and the available entries on the right, sorted by type and with search. Drag and drop, move up / move down / remove buttons on each row, `Alt+↑` / `Alt+↓` and `Delete` on the keyboard, undo / redo, changes flagged until they are saved, `Ctrl+S` to save.
- **Unsaved changes** flagged with a dot on the page, the navigation bar and the list of open pages. **`Ctrl+S`** saves the page shown.
- **Pages no longer pile up**: a page you leave (settings, tool not in the navigation bar) closes by itself. Only those with unsaved changes stay open behind, listed by the `Open Pages` button. Navigation bar tools are still kept as you left them.
- **Values checked as you type** in the settings: an invalid box is outlined in red with the reason, no more error message on save.
- **Preset trash**: a deleted preset can be restored (`Undo` button for a few seconds, or `Trash` page).
- **Updates**: `Skip This Version`, download progress with `Cancel Download`. If the app is hidden in the notification area, a message appears there instead of opening the window over the game. The portable ZIP version opens the release page instead of installing a separate copy.
- **Keyboard**: focus outline on the navigation bar and the tools, overlay list usable with the keyboard, a single click on the notification area icon.
- Better contrast in light theme, message icons matching the theme, last remaining English texts translated into French.
- **Safe mode**: if the app crashed at launch, it offers to start without plugins or overlays (also with `--safe-mode`).

### Connections

- **Web dashboard** translated into French, in your units, with virtual energy for Hypercar and LMGT3, the official delta and the invalidated lap.
- **Game data status** in the performance monitor: age of the shared memory and status of each piece of data read through the LMU REST API.

### Game replays (Le Mans Ultimate)

- **Redesigned page** (`Tools` > `Game Replays`): game status at a glance (not running, in the menus, in a session, replay open), replays grouped by day with search, `All` / `Practice` / `Qualify` / `Race` filter, sort by date, size or track, replay folder in one click.
- **Replay files**: `Add` (or drop `.Vcr` files on the page) copies replays into the game replay folder, with a progress bar, a free disk space check and `Stop Copy`; `Export` copies them to a folder of your choice; `Rename`; `Delete` moves them to the Windows recycle bin, after confirmation. Several replays can be selected (`Ctrl` / `Shift` click, `Ctrl+A`). **Protect** replays with the star: they are never deleted. Folder clean up: delete replays older than a number of days, keep only the latest ones, delete the temporary files the game leaves behind. The replay folder is asked to the game, so it is known even without any replay.
- **Game camera & HUD**: the camera menu of the game (Cockpit, Swingman, Nose Camera, Bonnet Camera, the 7 onboard cameras, trackside `Cycle All` and groups 1 to 4) with the camera shown checked, previous / next angle, camera on the previous / next car, name of the camera shown; show or hide the whole game UI for clean pictures (top bar, standings, replay bar and HUD, as a middle click in the game does) or the HUD parts one by one (chat, car HUD, timing, MFD, track map). Works in a live session too.
- **Playback**: round buttons (`Space` play / pause), slow motion, rewind and fast forward, and every other speed of the game in a menu. Replay time read from the replay itself, with its speed (`1x`, `4x`...); `LIVE` and the session time in a live session. Lap of the car followed by the camera with previous / next lap, lap starts marked on the timeline.
- **Replay this moment** in a live session: an incident opens the replay of the session at that moment, `Back to Live` returns to the session.
- **Drivers**: standings of the session or replay (position and class position, number, driver and car, laps, best lap in purple when fastest of its class, last lap, gap as the game shows it (best lap behind the leader in practice and qualifying), pit stops, virtual energy of your team's cars, garage / in pits / finished / retired, incidents), class chips, your car highlighted, the car followed by the camera marked (cars sharing a driver name told apart); double-click a driver to put the camera on their car, right-click: `Go to Lap...`.
- **Track map**: the track and pit lane of the session or replay with every car (class color, number), gliding between updates; click a car to put the camera on it.
- **Incidents** instead of raw contacts: both sides of a contact merged into one incident, car number and class, your car highlighted, `Cars` / `Walls` filter, `My car`, driver chips with their incident count, copy or export to CSV. The incidents and standings of the session you just left stay shown. **Timeline** over the whole session: click an incident to jump to it, click anywhere else to move the replay there, mouse wheel to zoom.
- Settings kept (seconds before, sort, filters, tab, protected replays), replays list updated when a session ends, `Today` / `Yesterday` updated at midnight, screen reader names on buttons.
- Lighter on the game: asked only while the page is shown, on one connection per update and one background thread, less often when the game is not running, standings only when needed.

![Game Replays page: replays by day, playback, camera, track map with the cars](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-game-replays.png)

### Releases and documentation

- **Release notes in the app language**: the `Release Notes` page shows the changelog in French when the app is in French (available update and installed version alike), in English otherwise.
- **Simpler releases**: two files only, `ModernTinyPedals-<version>-setup.zip` (the Windows installer) and `ModernTinyPedals-<version>-source.zip`. Updating from the app downloads the ZIP, checks its SHA-256 hash and runs the installer inside. The portable ZIP is no longer published: to turn a portable copy into an installed one, install the setup into its folder (presets and data are kept).
- **Wiki**: a full guide (installation, game setup, overlays, telemetry viewer, race calculator, connections, troubleshooting, development) on the [project wiki](https://github.com/Keenny38/ModernTinyPedals/wiki).
- README, changelog and GitHub release notes in English, contributing guide rewritten for Modern Tiny Pedals.

### Reliability and security

- The app starts even if the game's shared memory has an unexpected size (old rF2 plugin, another tool).
- Replays: pausing no longer hides the overlays, replays from an older game version are cleanly rejected, damaged files are read up to their healthy part, export runs in the background.
- Presets and settings are written safely (no more empty file after a power cut), module data saved on shutdown, the lap being recorded is kept if you quit just after the line.
- Closing the window then choosing `Cancel` no longer leaves the app without a window, and changes on a settings page are no longer lost when switching presets.
- Plugins installed from a ZIP are checked (paths, executed code), web dashboard and remote control hardened.
- Overlay fixes: deltabest_extended, modern heatmaps, sizes at ×2 scale, truncated texts, °F, engine and pedal maximums, and many more (see [the audit history](docs/AUDIT.md)).
- The Windows version is now launched in test mode before each release.
- **Verifiable downloads**: each release file has a signed provenance attestation (proof that GitHub built it from the repository code, to check with `gh attestation verify`, see [SECURITY.md](SECURITY.md)), and a published release can no longer be modified. Security vulnerabilities are reported privately, as explained in the same file.

## 0.19.1 (2026-10-05)

Fix for the Windows version of 0.19.0.

- **The app did not start** in the Windows version (installer and ZIP): a Python module (`multiprocessing`, used at launch and by the telemetry viewer's background computations) was missing from the executable.

## 0.19.0 (2026-10-05)

The biggest update since the beginning: every overlay gets a new look, the driver stats page is rebuilt, the race calculator handles a safety car, rain and multiple drivers, and the app reads much more Le Mans Ultimate data (chat, contacts, replays, team stints).

### New overlay design

- **Every overlay except the Black box** has a new design: one rounded panel per overlay, **Barlow** font (included with the app), short labels above the values, translated into the app language.
- **Values colored by meaning**: gain in green, loss in red, warning in orange, best time in purple.
- **Standings** (relative, standings, rivals) as rows: position badge, class pill with the position in class, class color on the edge of the row, fastest lap of the class in purple. Columns of your choice (`column_*`), and for rivals the lap time gap and the interval.
- **Fuel and energy** with a gauge, the full-tank mark and the key values in tiles (laps, minutes, consumption per lap, saving, pit stops).
- **Tyres and brakes** in tiles with heatmap colors, **LEDs** as glowing dots, new gauges for gear, pedals and damage.
- **Simplified options**: the config window and the option search (`Ctrl+F`) only show the options the design uses.
- **The classic look is still available**: for all overlays (disable `enable_modern_style` in `Overlay Style`) or for a single one (`enable_classic_layout`).
- Adjustable design font (`modern_design_font_name`), overlay theme colors as before.

![New design: standings](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-classements.png)

![New design: fuel and energy](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-carburant.png)

![New design: car and tyres](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-voiture.png)

![New design: timing](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-chrono.png)

### New icon and interface

- New **gold and black** icon, and its **gold and white** version for the dark theme.
- The window, taskbar and notification area icon follows **Windows light / dark mode**, as do the logo of the `About` window and the shortcuts created by the installer.
- The `Widget` tab of the main window is now called **`Overlays`**.

### Telemetry viewer

#### Official layout and track limits (LMU)

- The viewer fetches the track's **official layout** and **pit lane** from the game, then keeps them: they remain available without the game.
- Game **track edges** on the map, with the **margin to the edge** at each key point (outside at braking, inside at the apex, outside at the exit) and a new **outside point** ■ after each apex.
- **Off-tracks** (2 or more wheels on grass, dirt or gravel) and **track limits exceeded** (4 wheels out) marked on the map and counted per lap (off-tracks: laps recorded with this version). For laps recorded before this version, the edges are inferred from the driving lines.
- Two new map colorings: **mini-sectors** (the reference line colored by the fastest lap in each mini-sector, with the **ideal lap of the shown laps**) and **delta per corner**.

![Map: official layout, track edges, mini-sectors and mini-map](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-track-map.png)

#### New Session and XY tabs

- **Session**: every lap of the session (shown laps in their color, best in gold, invalid laps hollow), fuel and tyre wear of each lap, off-tracks and track limits. Clicking a lap shows or hides it.
- **Long-run pace**: average of clean laps leaving out slow laps (traffic, mistakes), and lap time **trend** over the session (wear, fuel, track evolution), also per % of tyre wear.
- **XY**: one channel against another at the same spot on track, as a **scatter plot** (speed / lateral G, steering / lateral G, throttle / slip…) or as a **histogram** (share of the lap spent in each value range). Limited to the zoomed part of the charts when zoomed in.

![Session tab: long-run pace and trend](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-session.png)

![XY tab: speed / lateral G](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-xy.png)

#### Where time is lost

- At the top of the Corners tab, the corners that cost the most, with the **cause in plain words**: "Brakes 6 m earlier", "Minimum speed 7 km/h lower", "Coasting 0.7 s longer", "Full throttle 8 m later"…
- Option for the **delta to the ideal lap** (fastest clean lap in each mini-sector) instead of the reference lap.
- **Spread of braking points** from one lap to the next, to judge consistency.

![Corners tab: where time is lost](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-coaching.png)

#### New recorded channels

- **Inner / middle / outer** temperatures of each tyre (and their spread), tyre **load**, **slip angle**, **camber**.
- **Brake bias**, **TC** and **ABS** levels, **engine map**, **water** and **oil** temperatures, track position and distance from the center line.
- The name of the **setup** loaded in the game is kept with each lap (LMU), shown and searchable.

#### Lap list

- **Search**: vehicle, session, setup, note.
- **Trash**: deleted laps go to the trash and can be restored with `Ctrl+Z`. Session menus: show, hide, keep or move to the trash all laps of a session; the same actions for checked laps, and MoTeC export of checked laps.
- **Use as Delta Best**: a recorded lap becomes the delta best used on track (the previous one is kept as a backup copy).

#### Map, charts and playback

- **Ruler** (`M`) to measure a distance on the map, **pedal zones**, **cursor trail**, **distance markers**, colorblind-friendly colors.
- **Map image export** (file or clipboard), **A ↔ B section** as CSV or image.
- **Map zoom synced** with the charts (or independent), **previous / next zoom**, **mini-map** on the large map, **pin a position** in one click.
- Playback: **A-B section loop**, step back / forward 2 s (hold to rewind or fast-forward).
- **Keyboard and mouse help** (`?` button) and map shortcuts: `F` fit, `R` rotate, `1`-`8` coloring, `L` lock-ups, `Z` zones, `T` trail.

#### Viewer performance

- Each recorded lap has a **binary copy**: the viewer opens it without re-reading the CSV, so loading is much faster.
- Heavy computations (track limits, session values) run in a **separate process**: charts and map stay smooth during the computation.
- Exports run in the background; closing the viewer or quitting the app waits for them to finish.

### Race calculator

- **Live race**: during a race, the plan for the rest of the race is recalculated every lap and every pit stop from the car (laps and time done, fuel, energy, tyres, stops made).
- **Safety car scenario** (or full course yellow): from a given lap, for a few laps, with consumption, lap time and wear under safety car, and the option to pit under safety car. Compared with the plan without a safety car.
- **Rain scenario**: rain period with adjusted consumption and lap time, and pit stops for wet tyres then slicks.
- **Multiple drivers**: stints per driver, pace difference, minimum and maximum driving time for each, `Driving Time` card with unmet limits in red.
- **Strategy comparison**: the current plan against 1 or 2 fewer stops (fuel saving) and 1 more stop, with the **cost of saving** in lap time, pit time and gap at the finish. The saving target tells you whether the stop saved is **worth it**.
- **Pit stop plan**: **pit window** (first and last possible lap without changing the number of stops), **time of day** of each stop based on the start time, export as **text, for Discord, as CSV or as an image**.
- **Balanced stints** (no short top-up stint at the end), **leader finishes first (+1 lap)** in timed races, safety margin in **laps, fuel or %**, consumption of the pit **in and out laps**.
- **Estimate from history**: pit stop duration, fuel effect and track evolution taken from the consumption history.
- **Share code**: the whole plan on one line of text to paste in a chat, and **plan saved per car and track**, reopened automatically. **Undo / redo** (`Ctrl+Z` / `Ctrl+Y`) on all inputs.
- **Plan against race** (stints driven compared with the plan) and **class rivals** (laps, stops, next expected stop).
- **Team tab (LMU)**: stints of each driver of the car read from the game, teammates included, with fuel, energy and wear per lap to carry over into the calculator. **Allowed tyres** taken from the game session.

![Race calculator: safety car, 2 drivers, strategy comparison](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-race-calculator.png)

### Driver stats

- The page is **rebuilt in Qt Quick**, like the telemetry viewer.
- **All tracks**: your career on one page, the best lap of each class on each track colored by its level, and the count of your levels (Alien, Competitive, Good…).
- **Progression**: the best lap of each session and your record over time, with the level thresholds, filterable by practice, qualifying or race. List of **sessions** with the result of each race.
- **New columns**: **theoretical** best lap (sum of best sectors) and **potential**, starts, retirements, average position, win and podium rates, average speed, consumption per 100 km, last driven. Columns to show of your choice, adjustable widths.
- **Next level**: the time to find to move up to the next level.
- **Track search**, sort by last driven, CSV export, colorblind-friendly colors.
- **Undo / redo** deletions and resets, **automatic backup** before each change (the last 10, restorable).
- **`Telemetry`** button: opens the vehicle's recorded laps in the viewer, with your record as reference.

![Driver stats: level, progression and sessions](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-driver-stats.png)

![Driver stats: all tracks](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-career.png)

### Le Mans Ultimate: new game data

- New **Chat** widget: the game's chat messages as an overlay, handy in VR. Line wrapping, fading out after a few seconds, new messages highlighted, optional time.
- New **Game Replays** page (`Tools`): replays recorded by the game, opening in the game, playback controls, and the list of the session's **contacts** with **jump to the moment of contact**, camera on the car.
- **Black box**: the log records each **contact** with the name of the other driver, or the wall.
- **Race plan** widget: **distance to the pit entry**, plan recalculated every lap during the race, **pit menu check** (fuel set in the game against the plan) and **target consumption** to reach the next stop.
- **Game consumption estimate**: as long as no lap of the car is recorded on this track, the fuel and energy overlays and the calculator start from the per-lap consumption estimated by the game.

![Chat widget](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-chat.png)

### Fixes

- A corner that crosses the start line is no longer counted twice, and a brief brake tap before the real braking is no longer taken as the braking point.
- Changing units also updates the tooltips of the lap list.
- A failed viewer export is reported instead of failing silently.
- Driver stats: a change no longer loses the stats saved by the app in the meantime, and a reset time also disappears from the progression.

## 0.18.0 (2026-10-04)

### Telemetry viewer: analysis

- **Interactive legend** above the charts: hover to highlight a lap (charts, map, G circle), click to keep it highlighted, double-click to make it the reference, `×` to hide it, right-click for the menu.
- **Stable colors**: each lap keeps its color as long as it is shown, even when other laps are checked or unchecked, or the reference changes.
- **Gap to the reference** in the cursor tooltips (`237 +4`, `9 % −3 %`). When a lane is too small for its tooltip, the values are shown under its name.
- **A and B markers** (right-click or `A` / `B` keys) and a new **Range** tab: time of each lap between the markers, gap to the reference, and min / max / average of each shown lane.
- **Calculated channels**: slip of each wheel (lock-up under braking, wheelspin under acceleration), steering rate, fuel used, tyre temperature spread.
- **Combined panels**: all 4 wheels in a single lane (temperatures, pressures, wear, brakes, suspension…) and `Throttle & Brake` overlaid.
- **`Channels` menu**: search, presets (Pedals, Tyres, Brakes, Suspension), channels not recorded grayed out (and a message in the lane rather than an empty chart), **smoothing** of noisy lanes, time gain/loss **window** (20 to 150 m), **min / max band** of the shown laps to see consistency.
- **Lanes**: height adjustable by dragging their edge (double-click to reset), vertical zoom with `Ctrl` + wheel, scrolling when there are many lanes.
- **Lap playback** (▶ button or `Space`, from 0.25× to 4×): the cursor follows the reference lap in real time.
- **Keyboard**: `←` `→` move the cursor (`Shift`: the view), `[` `]` previous / next corner, `A` `B` markers, `Esc` clears them, `R` makes the highlighted lap the reference.
- **Right-click on the charts**: markers, zoom to the sector or between the markers, copy the values or the image, open the replay at this point.
- **Click on `S1`, `S2`, `S3`** in the charts, or on a sector time in the list: zoom to the sector.

![Telemetry viewer](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-telemetry-viewer.png)

### Corners tab

- **Compared lap of your choice** when several laps are shown, and **sort by time lost** to see first where to gain time.
- For each corner: **entry and exit speeds**, **gear** at minimum speed, maximum **brake pressure** and the **fastest lap** through that corner.
- **Ideal lap**: the best pass through each corner and each straight among the shown laps, with the gap to the reference lap.
- The detection sensitivity is shown in your speed unit, and corners are recalculated when the slider is released (3 times faster than before).

![Corners tab](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-corners.png)

### Track map

- **Driving points** of each lap in each corner: ◆ braking, ● apex (minimum speed), ▲ exit (back to full throttle, pointing in the direction of travel). On hover: corner, speed and distance, with the gap to the reference lap. A click zooms the charts to the corner. Option to show the speed next to each point.
- **7 colorings**: by lap, gain/loss, speed, pedals, **racing line** (the compared lap inside or outside the reference), **gear** and **elevation**.
- **Car tracking** during playback (or with the keyboard arrows): the map zooms in on the cars and keeps them centered, and zooms out if they move apart.
- **Cursor**: one arrow per lap, pointing in the direction of travel, with the gap to the reference (in seconds, or in meters on the time axis). Hovering over the track puts the chart cursor at the same spot.
- **Sector times** on the track with the gap of the compared lap, **direction arrows**, **front wheel lock-ups** and **rear wheelspin**.
- **Large map** over the charts (⤢ button), **auto orientation** to fill the map and rotation by quarter turns.
- Corner labels no longer overlap (biggest gaps first).

![Map: braking, apex and exit points](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-track-map.png)

![Map: racing line coloring](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-racing-line.png)

### Lap list and tools

- **Selection**: `Shift` + click checks all laps in between, quick selection menu (best lap vs last, best 3 or 5, uncheck all).
- **Gap to the best lap** on each lap, and conditions in a tooltip (track and air temperatures, humidity, fuel used).
- An unreadable lap is flagged in the list instead of silently disappearing.
- **`Live` mode**: a newly recorded lap shows up on its own and is compared with the best lap.
- **Open the replay** at the cursor position when a replay covers that lap.
- **Image export** (PNG) or copy to the clipboard, to share on Discord.
- The layout is remembered: column widths, right-hand tab, lane heights.

### G circle

- Braking is now at the bottom and a right-hand corner on the right (it was the other way around), with Left / Right / Acceleration / Braking labels.
- **Grip envelope** of each lap, and a scale that ignores spikes (curbs, contacts).

### Fixes

- **Qt Quick pages are finally in French**: the telemetry viewer and the Track Map Viewer stayed in English.
- The track map is no longer **mirrored**: it has the same orientation as the in-game map.
- The chart zoom is kept when a lap is checked.
- Smooth wheel zoom on touchpads (charts and map).
- On the time axis, the map and the G circle show where each lap is at that time (instead of all at the same spot).
- A lap imported from MoTeC with a slightly different distance is realigned for the delta.
- Viewer settings can no longer be lost if the app stops while writing them.
- Readable colors in light theme (best lap, best sectors, warnings, gain/loss).

### Performance

- Laps are now always loaded in the background, with progress, and reading files is faster.
- Checking a lap only recalculates that lap, and the MoTeC export of a whole track runs in the background.
- The cursor requests a single computation per mouse move for the charts, the map and the G circle.

## 0.17.0 (2026-10-04)

### Telemetry viewer rebuilt

The viewer is fully rebuilt in Qt Quick: charts, map and G circle are drawn by the graphics card.

- **Smooth**: animated zoom and pan, at the screen refresh rate. Before, each mouse wheel notch took about 160 ms to draw.
- **Navigation**: mini-chart of the whole lap under the charts to see and move the zoomed part, `Reset` button, `Shift` + drag to zoom into an area, drag a lane's name to move it.
- **Lap list**: collapsible sessions, color of each lap, `REF` badge, flag (or double-click) to pick the reference, `Clean only` to hide invalid laps, out laps and in laps.
- **Right-click on a lap**: reference, MoTeC export, keep, note, delete.
- **Toolbar**: lap legend, `Imported Laps...`, `Export` menu (MoTeC: reference lap, shown laps or all laps of the track; CSV for Excel).
- **Corners tab**: time gained/lost bar per corner and, under each corner, braking point, full throttle, trail braking, coasting and pedal overlap.
- **Memory**: loaded laps are released after 3 minutes in the background, then reloaded with the same zoom.

![Telemetry viewer](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-telemetry-viewer.png)

### Track map

- **4 colorings**: by lap, time gain/loss against the reference lap, speed (slowest to fastest, with the scale) or pedals (throttle, brake, both, coasting).
- **Follow zoom**: the map zooms in by itself on the part of the lap zoomed in the charts.
- **Braking points** of each lap.
- **Polished track drawing**: road with border, checkered start line, sector limits, scale and zoom buttons.
- **Clickable corners** with the time gained or lost by the compared lap: a click zooms the charts to the corner.

### Real corner numbers

Corners carry their official number (`T1`, `T10a`…, `V1` in French) on the charts, the map and the Corners tab, instead of a number in lap order.

- **Tracks**: Silverstone, Imola, Spa-Francorchamps, Circuit of the Americas, Interlagos, Paul Ricard (F1 layout), Monza, Bahrain, Portimão, Lusail, Road Atlanta, Laguna Seca and Long Beach. At Le Mans, which has no official numbering, the corners are named (Dunlop, Tertre Rouge, Mulsanne, Indianapolis, Arnage, Porsche Curves, Ford Chicanes).
- **Placed on the real layout**: each corner is aligned on the apex of the matching corner of your lap (or of the track map). The map shows every corner, even those taken flat out, and a detected corner that covers several is called `T2-4`.
- Other tracks and layouts keep the numbering in lap order.

![Corners tab](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-corners.png)

### Track Map Viewer rebuilt

- **Map drawn by the graphics card**: road at its real width, line colored by sector (length of S1, S2 and S3), start line, sector limits, official corners (a click moves the position there).
- **At the position**: curve section, osculating circle, distance circles and center mark; position info (corner, node, sector, XYZ), curve info ("Right 3", radius, length, angle) and slope info.
- **Elevation profile** of the whole lap, clickable, with the position.
- **Navigation**: click on the map, slider, keyboard arrows, `Play` button to run through the track, `Follow position` to keep the position centered.
- `Show` menu for each element; colors, widths and curve thresholds from the existing configuration kept.

![Track Map Viewer](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-track-map-viewer.png)

### Also

- Qt Quick adds only 20 MB to the app: only the modules in use are bundled (otherwise more than 300 MB).

## 0.16.0 (2026-10-04)

### Race calculator (new)

The fuel calculator and the tyre strategy are now a single tool, the **Race calculator** ("Race" entry of the navigation bar). The former bar entries and open pages redirect to it automatically.

- **One page, two tabs**: race settings and key figures at the top, shared, then **Fuel** and **Tyres** tabs. Everything is in French, fits small windows and is recalculated as soon as a value is confirmed (Enter or leaving the field).
- **Lap-by-lap pit stop plan**: for each stop, the lap, fuel and energy to add (full while more stints follow, just what is needed at the last one), tyres, driver and stop duration. `Copy` button to share it as text.
- **Strategy timeline**: one block per stint, pit laps above (in orange when tyres are changed), readable even for a 24-hour race.
- **Key figures**: race fuel and energy, pit stops (and what forces them: fuel, energy or stint length), longest stint, average refuel per stop (or fuel to load when there is no stop), tyres used out of the maximum allowed.
- **Timed races done right**: fuel and energy share the same stops, and the lap count really depends on the time lost in the pits (refueling, tyres, driver change).
- **Safety margin** in laps, kept at each stop and at the finish.
- **Realistic pit stops**: fuel and energy refueling rate (a top-up costs less than a full refuel), tyres changed during or after refueling, driver change time.
- **Rules**: mandatory stops, maximum stint length, drivers taking turns.
- **Pace**: fuel effect on lap time and track evolution over the hours.
- **Saving target**: consumption to hold to save a stop, or to do a given number of laps per stint.
- **Energy-only cars** planned on energy.
- **Smart fill** from live data or a file: average of the last 5 valid laps at race pace (pit laps left out). In live mode, the race length is taken from the session, the history updates on its own, and the `Follow Live` option also updates the inputs.
- **Consumption history**: sort by column, `Valid Laps Only` filter, selection by whole laps (invalid laps ignored), `Columns` button, and deletion of laps or of the whole history (`Delete Selected`, `Delete All`).
- **Tyre plan linked to the strategy**: one row per stint, tyre change time added to the stop, wear = wear per lap x stint laps, adjusted by compound (`Measured Compound`).
- **`Propose Changes`**: new tyres wheel by wheel at the stint where the tread would drop below the minimum (2 tyres when only one axle needs it), within the allowed tyres; if some are missing, the best used tyres are fitted again and the affected stints are flagged.
- **Tyre plan kept from one session to the next**, with undo / redo (`Ctrl+Z` / `Ctrl+Y`); rows are no longer lost while typing a value.
- **Race plan file** (`.race-plan`): settings, inputs and tyre plan in a single file, to keep or share with the team. All inputs are also restored on reopening, and `Reset to Zero` clears them.

### Race plan widget (new)

- **The next pit stop in game**: stop lap and laps left (highlighted when approaching), fuel and energy to add, tyres to change, stops left. The plan is rebuilt from the calculator inputs, even when the calculator is closed.

### Black box

- **No more overlap**: tyres, discs and suspensions that steer and move with the suspension no longer cover the RPM LEDs, the TC/BB/MAP pills or the brake temperatures. Room is reserved for full steering lock, the rear steering less, and the suspension travel drawn is capped.

### Driver stats

- **Modernized page**: key figures of the track (best lap and its car, level, distance, driving time, valid laps, races), readable table, reference card of the selected car.
- **Comparison with community times** (LMU sheet by [ohne_speed](https://www.youtube.com/@ohne_speed)): each record is placed on a scale of levels, from **Alien** to **Offline**, with its % gap to the class reference time and the fastest car. LMU track names and their variants are recognized automatically. The sheet is downloaded once a day and kept offline; `Reference` menu to refresh it, switch sheets or disable the comparison.

### Updates

- **Modernized "Release Notes" page**: version and release date in the header, one card per topic, technical details (commits, SHA256 hashes) collapsed, text fitted to the window size.
- **`Download And Install` button always available** (download in the browser when automatic installation is not possible). The prompt to install a new version uses the same page.
- **Translated update messages** ("New Updates: v…", "No Updates Available").

### Interface

- **Back to the last page on restart**, even after a crash or a Windows shutdown: the page shown is saved as soon as it changes, not only when quitting from the menu.
- **Command palette**: searching "fuel", "tyre strategy" or "fuel calculator" finds the Race calculator.

## 0.15.0 (2026-10-04)

### Telemetry viewer (Telemetry)

- **Units from your settings**: speed (km/h, mph), temperatures (°C, °F), pressures (kPa, psi, bar) and fuel (liters, gallons). Pedals and steering in percent.
- **Graduated axes**: distance under the charts, top and bottom values of each chart.
- **Cursor values in each chart**, one colored label per lap, and the top line colored like the laps.
- **Numbered corners (T1, T2…)** on the charts and on the map.
- **Click on the map** to put the cursor at that spot in the charts.
- **Gear drawn as stair steps.**
- **"Time Gain/Loss" chart**: where time is lost or gained against the reference lap, in seconds per 100 m.
- **Time axis** (instead of distance), the zoomed part of the lap is kept.
- **Per-corner driving analysis** (Corners tab): trail braking, coasting and throttle / brake overlap of both laps.
- **Clear lap names everywhere**: "Lap 12 · 1:11.525 · Race 03/10" in the legend.
- **Lap list**: star on the best lap of each session, option to hide invalid laps, out laps and in laps, added laps grouped by log.
- **Keep a lap** (never deleted by the recorder), **per-lap note** and **deletion** from the right-click menu.
- **Checked laps and reference lap remembered** per track.
- **CSV export for Excel** of the shown charts (decimal comma and semicolon if Windows is in French).
- **Smoother**: from 3 laps to read, loading in the background without freezing the window, and "Refresh" only re-reads modified laps.

## 0.14.0 (2026-10-04)

### Everything in the app window

- **Tools, editors and settings open as pages** in the main window, no longer in separate windows. The small inputs too (preset name, keyboard shortcut, share code, theme name).
- **Customizable navigation bar** (right-click > `Customize Navigation Bar...`): pages and tools of your choice, in the order you want, with `Ctrl+1` to `Ctrl+9` for the first 9 entries. By default: Pace Notes removed, Telemetry, Driver Stats Viewer, Fuel Calculator and Tyre Strategy Planner added.
- **Bar tools are pages like Widget or Module**: entry highlighted when you are on it, no Close button, you find them as you left them. Esc no longer closes them.
- **"Open Pages" button** at the bottom of the bar (shown only when there are some) to get back to or close the other pages (settings, tools not in the bar).
- **Bar icons keep their size**: if the window is small, the bar scrolls (mouse wheel or thin scroll bar), with a fade and an arrow when entries are hidden.
- **Back to the previous page** with `Alt+←` or the mouse back button. Closing a page goes back to the one before.
- **Pages reopened at startup**: tools left open come back at the next launch, after a restart or a language change (option `Window > Reopen Pages at Startup`). They reopen once the window is shown, without slowing down startup.
- **The window grows for a wide page** (within the screen limits), keeps that size while navigating and goes back to its previous size when the page is closed.
- **Settings are no longer lost**: closing a modified settings page asks whether to save, discard or cancel, and a save is only accepted when all values are valid. The app's internal options (window position and size, bar...) are no longer shown.
- **Language change without loss**: settings pages and pages with unsaved changes are kept as they are.
- **Color dots per category** in the widget list, and statuses in the plugin manager.

### Telemetry (lap viewer)

- **Laps grouped by session**: one collapsible row per session (type, start date and time, best lap, number of laps, car), newest at the top. Laps in order ("Lap 1, Lap 2..."), invalid laps, out laps and in laps grayed out. Laps recorded from this version on keep the session start time.
- **Corner-by-corner comparison** (Corners tab): time lost or gained, minimum speed, braking point and full throttle point for each corner, plus a row for the straights and the total. Click a corner to zoom in on it, adjustable detection sensitivity.
- **Racing line colored by time gained or lost** against the reference lap (red where you lose, green where you gain), with a legend.
- **Import of MoTeC `.ld` logs** (LMU's, for example) to compare yourself with another driver's lap: lap time computed at the line crossing, main channels imported.
- **Library of imported laps**: import, search (track, car, driver, date, time), show, rename, delete. An `.ld` file dropped on the app is imported directly and shown.
- **Sector limits** placed at the game's official sector times.
- **Less memory**: after 3 minutes in the background, loaded laps are released, then reloaded with the same zoom when you come back.

### Overlay

- **Black box**: target tyre pressures in psi or bar.
- **Standings and Relative faster to draw** (caching of text and cell backgrounds).
- **Transparent cells**: no more relief effect on cells with a fully transparent background.

### Fixes

- Pace notes playback no longer stops when the page is hidden.
- Migrating old presets no longer crashes when an option is missing.
- An SVG map that was not created by the app is reported as invalid instead of causing an error.
- The editor no longer goes back to old data after a reset.
- Next driver in spectator mode now correctly goes back to the leader after the last one.
- An already deleted widget preview window no longer causes an error.
- Missing translated texts: preset lock, shortcuts enabled/disabled, preset choice, Fuel Calculator history.
- Hidden pages pause their refreshes.

### Quality

- **1,200 automated tests**, 85% of the code covered (minimum threshold raised to 81%, the same on Linux and Windows).
- New tests for settings migration, the Relative and Wheels modules, the Track Map widget, the Preset and Hotkey pages, the Fuel Calculator, the REST API and rF2 connectors, and app startup.
- Release signing with Azure Artifact Signing when it is configured.
- The changelog of each version is shown at the top of the release notes and in the app's `What's New`.

## 0.13.0 (2026-10-03)

- **Black box**: ABS, TC, brake bias and engine map as pills between the right-hand wheels.
- Release notes with before / after images of overlay changes.
- Fixed type checking with mypy 2.4.

## 0.12.2 (2026-10-01)

- Fixed: the tools (Telemetry, editors, replay) did not open in the installed version.
- README preview image with all widgets on realistic race data.

## 0.12.1 (2026-10-01)

- Telemetry: improvements to the lap recorder, the viewer, the replay and the data feed.

## 0.12.0 (2026-10-01)

- VR mirror window for OpenXR games, through window capture overlays (OpenKneeboard...).
- Preset share code: copy a preset as text, import it with a preview.
- Track map in the lap viewer, comparing both laps at the cursor and the zoomed part.
- Telemetry replay for rFactor 2 and LMU, REST API data recorded in replays.
- JSON language packs and a template generator to add a language without code.
- Visual edit mode: outline, name and resize handle of unlocked widgets.
- Global overlay scale, undo / redo in settings.
- Home page (game, preset, widgets, overlay and version at a glance), command palette (`Ctrl+K`) and category filter.
- Notifications (toasts), import of presets, packages and plugins by drag and drop.
- Widgets shown depending on the session and pit context, with fading.
- Widget positions remembered per screen setup.
- Export and import of overlay themes, widget preview on hover in the list.
- System light / dark theme followed, maximizable window.
- Hidden widgets no longer updated, slower default refresh for widgets that change little.

## 0.11.0 (2026-10-01)

- Tools page and quick actions in the navigation bar, setup wizard shown only once.

## 0.10.2 (2026-10-01)

- Offer to install updates as soon as they are detected.

## 0.10.1 (2026-10-01)

- Black box visual style applied to all overlays, widget lists sorted alphabetically.

## 0.10.0 (2026-10-01)

First version of Modern Tiny Pedals, based on TinyPedal 2.50.0.

- Windows installer and installation of updates from the app.
- Layout editor to place widgets on a screenshot of the game.
- Black box: headlights and engine state, delta and pedal source, brake bias, settings, braking analysis, incident recorder, live suspension and real wheel angles.
- Updates and changelog through GitHub Releases.
- Fixes: local host probe, REST API crash, non-finite telemetry values, rejected text / boolean settings, access to deleted widgets.

TinyPedal changelog up to version 2.50.0: [docs/changelog.txt](docs/changelog.txt).
