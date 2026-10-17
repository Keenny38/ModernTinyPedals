# Changelog

All notable changes to **NeoPedal** (formerly Modern Tiny Pedals), newest version first. Version française : [CHANGELOG.fr.md](CHANGELOG.fr.md).
The full list of commits of each version is on the [Releases](https://github.com/Keenny38/ModernTinyPedals/releases) page.

## 0.25.0 (2026-10-17)

Safer options everywhere: every number has limits you can see, presets are repaired as they load, and the Overlay Options page shows race situations and both designs.

### New

#### Overlay Options

- **Race situations in the preview**: `Racing`, `Yellow & Blue Flags`, `In Pits`, `Damage` and `Rain` show flags, pit timer, limiter, damage or wet weather without driving.
- **Test on Screen**: the overlays on screen show the chosen situation for 10 seconds (saved values), to set their colors and thresholds.
- **Other Design**: the same values drawn by the other design (modern or classic), with the number of options of each design.
- **Used only** filter: hides the options doing nothing with the current values (greyed out).
- **Allowed values** in the tooltip of every number (`Allowed: 0 - 4000`).
- Options used by several parts (a Dashboard HUD label shown by its chip and by the setting pop-up) are greyed out only while every part is off: `Used only with one of: ...`.

#### New Tyre Overview overlay

- **Every tyre reading in one card per tyre** (off by default, `Tyres & Wheels` category), placed as on the car seen from above (modern design: car body in the middle, each tyre drawn at its corner): inner / center / outer surface temperatures on the tyre in heatmap colors, compound badge or alert (detached wheel, puncture, flat spot) with the tyre highlighted, carcass & inner layer temperatures, pressure in blue below and red above the target range with its place on a target scale (same ranges as the Dashboard HUD, per compound too), tread gauge, wear per lap and laps left. Every part has its own on/off option, the car body and tyre drawing too.

![Tyre Overview overlay](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-16-tyre-overview.png)

#### Presets and options

- **Check Preset** (Presets page menu): lists the unknown, invalid and out of range options of a preset, and repairs it.
- **Standings**: `show_class_column_with_class_header` keeps the class column with the class headers (off by default).
- **Flag**: `low_energy_percentage_threshold`, low energy alert at a percent of energy left (100 by default: laps threshold only, as before).

### Improvements

- **Every number option has limits**: a value out of range in a preset file, an imported preset or a package is brought within them as the preset loads (written in the log), instead of drawing an overlay of tens of thousands of pixels.
- **An overlay too big is cut** to 8192 pixels with a message, instead of freezing the computer.
- **Import Overlay Settings**: each option left out or corrected is listed with the reason, and numbers out of limits are brought within instead of skipped.
- **Import Settings**: tried again at the next start (up to 3 times) when files are in use (other instance closing, antivirus).
- **Broadcast Director**: closing the page no longer waits for the events log to be written.

### Fixes

- **Standings, Relative and Rivals**: column order and columns on or off follow the page every time; the classic design no longer lists the orders of modern only columns (gap trend, track limits, energy per lap).
- **Overlay Options**: `Undo` and `Redo` while a field is being edited show the restored value; options greyed out wrongly, or not greyed out, on many overlays.
- **Driver Rank**: ranks saved before 0.24.0 (without their Steam account) are shown again while the game menu file has none: they go to the account in use when no other account has saved ranks, never to a second account.
- **French translation reviewed in full**: the app speaks to you with « vous » everywhere, one word for vehicle classes (« catégorie »), about 200 labels, help texts and messages corrected (agreements, power/weight ratio, missing words), and texts still in English translated (Flag, Engine, Force, System Performance overlays, error messages).
- **Overlays**, found by reviewing every option: radar fade radius, brake average temperature and Speedometer top speed reset with the session, Dashboard HUD impact cone after a restart, overlay brought back on screen staying there, low fuel or energy alert with an unknown consumption, global scale no longer turning on options set to 0, `100%` no longer cut, lap times like `1:60.0`, Sectors after a reset, Trailing time scale, Heading decimals, Tyre Pressure average, Track Notes timers, Steering Meter marks, and many more.

## 0.24.0 (2026-10-14)

Your Driver Rank and Safety Rank everywhere, Standings like a timing tower, the Black box renamed **Dashboard HUD** with a setting pop-up, Results & Replays in one page, one look per meaning in every overlay and page, and a lighter app.

### New

#### Driver Rank & Safety Rank (Le Mans Ultimate)

- **New `Driver Rank` overlay** (off by default, `Timing` category): your Driver Rank (DR) and Safety Rank (SR) as the game menu shows them (`Silver 2`, progress to the next tier `40%`), and your track limits points against the session limit (`1.25/5`).
- **On your driver cards**: `Driver Stats Viewer`, the Home page and the `Broadcast Director` (you and your teammates, those of the events you registered for included). Each rank in its color, with the progress to the next tier and the change since your previous rank (`▲ +10%`), and your **badge** with its icon, name and description as in the game menu.
- **Last ranks kept**: when the game rewrites its menu file without your ranks (it did with its update of October 13), your last ranks are shown with their date instead of nothing. Every change is kept in `driver_ranks.history`.
- **Several Steam accounts on one computer**: ranks and badge are kept per account, the account signed in to Steam is followed live, and your other accounts are shown below your driver card. The ranks of one account are never shown as those of another.
- Ranks are only read from the game folder (`coherent_local_storage.json`): nothing is sent anywhere, no sign-in.

![Driver Rank overlay](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-12-driver-rank-overlay.png)

![Driver Stats: ranks on the driver card](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-12-driver-card-ranks.png)

#### Home: driver card

- **New `Driver` card on the Home page**: your name, ranks, badge, country, team and number, and your race record from the game results files (races, wins, podiums, average finish, clean races). Click it to open `Driver Stats Viewer`.

![Home: driver card](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-home-driver-card.png)

#### Standings, Relative and Rivals like a timing tower

- **Time column like on TV** (modern design, each part can be turned off): the running lap time, then the completed lap with its colors and the gap to the driver's best (`+0.345`), `OUT` / `IN` laps, invalid lap in red and a trend arrow. Three **sector bars** under the time, colored like the game live timing: purple best of the class, green personal best, orange slower.
- **Real penalties** (Le Mans Ultimate, both designs): `DT` drive through, `SG10` stop & go, `+10s` time penalty, `SG×2` several to serve, `DQ` disqualified, instead of `PEN` or `-1`.
- **Pit status and pit stops in one column**: the `PIT`, `GAR`, `SLOW`, `FIN` pill, then the stops count or the penalty.
- **Column labels** above the cars (`Pos`, `Driver`, `Tyres`, `Pit`, `Time`, `Gap`...), on by default.
- **New `Energy per Lap` column** (Le Mans Ultimate, off by default): virtual energy each driver used in the last lap, or the average of the last 5 laps.
- **New `Track limits` column** (Le Mans Ultimate, off by default): track limits points of each driver, amber once any, red one point before the penalty.
- Race gap with its sign (`+12.3`, `+1L`), last lap in green when it is the driver's personal best.

![Standings: lap time like a timing tower, pit & stops column, real penalties](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-13-standings-timing.png)

![Standings: column labels, track limits column, race gap sign](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-12-standings-column-labels.png)

![Relative & Rivals: lap time like a timing tower, pit stops, real penalties, compound badges](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-relative-rivals-timing.png)

#### Dashboard HUD (formerly Black box): setting pop-up, new readings, your own profiles

- **The Black box overlay is now called `Dashboard HUD`** everywhere in the app. Your settings, presets and incidents are kept.
- **Setting change pop-up** (on by default): change TC, ABS, brake bias, brake migration, engine map or an anti-roll bar in the car and the center column shows it for 2 seconds (`TC 4/9 ▲`), green going up, red going down. Pit limiter, headlights and wipers too (`LIM ON`). Position, duration and colors can be set.
- **New readings** (Le Mans Ultimate, off by default): track limits points (`LIMITS 1.25/5`), gap to the car ahead and behind (`GAP 1.2 | 3.0`), a lift & coast bar, and a **wipers icon** next to the headlights.
- **Tyre compound and wear together**: the compound badge is drawn next to the wear (`[M] 91%`), so turning on `show_tyre_compound` no longer hides the wear, or the compound, for lack of room.
- **Your own display profiles**: `User 1`, `User 2` and `User 3`, saved with `Save as Profile...`. Changing an option of a profile now switches it to `Custom` instead of locking the option.
- **Overlay Options**: click a part of the Dashboard HUD picture (tyre, center column, damage, trace...) to jump to its options. Simple mode shows the main items only (46 options instead of 89).

![Dashboard HUD: setting change pop-up](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-13-black-box-setting-popup.png)

![Dashboard HUD: track limits points, gaps, lift & coast bar and wipers icon](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-13-black-box-new-items.png)

![Dashboard HUD: Overlay Options with Save as Profile and live preview](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-dashboard-hud-options.png)

![Dashboard HUD: tyre compound badge next to wear](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-dashboard-hud-compound-wear.png)

#### Results & Replays: one page

- **`Race Results` and `Game Replays` are now one page**, `Results & Replays` (`Results` in the navigation bar). The switch at the top of the list shows the sessions of the results files or the replays saved by Le Mans Ultimate; the `Replay` tab has everything the replays page had.
- **Each replay is linked to its results**: a flag on replays that have a results file, `Show Results` in their menu, and the replay of a session picked with it.
- **Watch an event or a lap**: the play button of an event (contact, penalty, track limits) opens the replay a few seconds before it, camera on the car concerned; the play button of a lap opens the replay at the start of that lap.

![Results & Replays: replays linked to their results](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-results-replays.png)

#### On / off switch for the Broadcast Director and the Race Calculator

- **Switch at the top left of both pages** (on by default, remembered): off, the page asks the game nothing, cuts no camera, and is freed after 10 minutes hidden. Turn it back on with the switch or the button in the page.
- **Dot on their navigation bar entry**: green on, grey off. New `director_toggle` and `race_calculator_toggle` hotkeys (remote control too) and command palette entries (`Ctrl+K`). New `Broadcast Director On` notice at the bottom of the main window.

![On / off switch: Broadcast Director & Race Calculator](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-director-calculator-switch.png)

#### Broadcast Director: standings tower carousel and game HUD

- **Standings tower carousel**: up to 70 cars (was 30), the tower slides page after page every 10 seconds, class after class if you want, with a bar showing which part of the field is on screen.
- **Game HUD menu on the camera desk**: hide the whole game UI for clean pictures (`middle click`), or each part (chat, MFD, car HUD, timing, track map).

#### Trailing: pedal bars

- **Pedal bars beside the plots** (off by default): throttle, brake, clutch and force feedback, raw and filtered side by side, with peak marker and optional readings.

![Trailing: pedal bars](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-13-trailing-pedal-bars.png)

#### Share overlay settings

- **Share the settings of one overlay or of several you pick**, as a `.zip` file: `Share` > `Export Overlay Settings...` on the `Overlays` and `Overlay Options` pages (or `Export Settings...` in the menu of an overlay card), tick the overlays, save. Only options changed from default are written, so your friend gets exactly your look.
- **Import** with `Share` > `Import Overlay Settings...` or by dropping the file on the window: untick the overlays you do not want, `Keep my positions` is ticked by default (else positions are scaled to your screen). Settings are applied as pending changes of `Overlay Options`, kept with `Apply`, undone with `Ctrl+Z`.

![Share overlay settings](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-share-overlay-settings.png)

#### Import Settings

- **New `Config` > `Import Settings...`**: copies the global settings of another copy of the app (options, hotkeys, driver stats, language packs, Dashboard HUD incidents) from the folder you choose, after a restart. Your current settings are set aside in a backup folder. Coming straight from 0.22 or older, choose `%APPDATA%\TinyPedal` there.

### Improvements

#### One look per meaning, everywhere

- **Same status colors in overlays, app pages and stream sources**: purple best, green gain or personal best, red loss or penalty, orange pit, yellow slower sector, gray garage. The OBS standings tower shows `GAR`, `DNF` and `DQ` too.
- **Tyre compound badges like the Standings** (letter on a square of the compound color): modern `Stint History`, Dashboard HUD tyres and the app pages. Classic overlays keep their colored letters.
- **Same compound colors everywhere**: soft white, medium yellow, hard red, wet blue, intermediate green. Compounds still at the former default colors change once; colors you chose are kept.
- **Class badges, short driver names (`L. Hartmann`) and race gaps (`+1 lap`)** written the same way on every page, in the language of the app.

![Same status colors everywhere](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-status-colors.png)

![Modern overlays: one palette for best, gain, loss and warning](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-overlay-status-palette.png)

![Tyre compound badges](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-tyre-compound-badges.png)

![Tyre compound colors](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-12-compound-colors.png)

#### Track map and track limits

- **Track map sectors colored like the game live timing**: purple best of your class in the session, green your best, orange slower, same as the Standings sector bars.
- **Track limits points shown the same way everywhere** (`1.25`, `1.5`, `3`): `Laps & Position` in both designs, Driver Rank, Standings and Dashboard HUD. The limit (`1.25/5`) is shown in races only, as practice and qualifying have no penalty.

![Track map: sector colors like the game live timing](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-14-track-map-sector-colors.png)

#### Driver Stats Viewer

- **Opens on `All Tracks`**, and goes back to it after 2 minutes away.
- **About three times faster** to switch tracks, holding an arrow key in the table no longer stutters, and `Stints & Consistency` no longer reloads every lap while you drive.
- **Levels match the community lap time sheet**: `Good` covers 102 and 103 %, `Midpack` 104 and 105 %, `Tail-ender` 106 %, `Offline` 107 % and slower.
- Numbers in the language of the app (`101,50 %` in French), readable level letters, `% Ref.` and `Level` columns hidden while the comparison is off, `Live` badge following the game within 5 seconds, units and classification changes shown at once.

#### App pages

- **Keyboard**: `Tab` reaches every button and switch with a blue focus outline (`Space` or `Enter` presses it), arrow keys, `Home` and `End` change segmented choices.
- **Easier to read**: darker secondary text in light themes, darker blue and red behind white text, visible button hover in Modern Dark.
- **Same look on every page**: one scale of text sizes, corners and spacing, one search box (`Esc` clears then leaves), one list row style, same chart colors.
- **Asks first** before removing a championship or a math channel. Pages no longer animate when Windows animation effects are off.

#### Lighter on memory, CPU and GPU

- **Pages**: tool pages hidden for 10 minutes are closed and give their memory back, smoothing is applied only where needed, and slow work (files, game answers) never runs on the window thread.
- **Overlays**: an overlay repaints only when what it shows moves by a pixel (tables cell by cell, track map up to 25 times a second, Dashboard HUD recording drawn in 1 ms instead of 9.5 ms), background modules sleep until the game sends new data, and modules, chat and incidents run only while an overlay needs them.
- **Broadcast Director hidden**: the game is asked every 5 seconds instead of every second when nothing needs fresh answers.
- **VR and stream**: SteamVR overlay at most 15 times a second and slowed down off track, OpenXR layer uploads only the changed part, OBS capture only while a source is watched.

#### NeoPedal name everywhere

- **Windows**: executable renamed `neopedal.exe` (Start menu and desktop shortcuts follow, pin a taskbar shortcut again), `NeoPedal` as publisher, old `ModernPedal` and `Modern Tiny Pedals` shortcuts removed.
- **Linux**: `install.sh` installs in `/usr/local/share/NeoPedal` with a `NeoPedal` command, and windows are no longer grouped with TinyPedal's.
- **Files**: `neopedal.log`, `neopedal-errors.log`, `neopedal-bug-report-….zip`, VR layer `NeoPedalXrLayer`. Older plugins, preset packages, language packs and remote control tools keep working.

### Fixes

- **NeoPedal and the original TinyPedal run together**: NeoPedal could refuse to start ("NeoPedal is already running") or stop TinyPedal from starting.
- **Gaps in class**: timed like a timing screen in races (they came from a game estimate, a few percent off for cars much slower or faster), and measured within the class with `enable_single_class_exclusive_mode` too.
- **Interval in practice and qualifying**: best lap difference to the car ahead, instead of a meaningless distance on track.
- **Dashboard HUD**: a new incident was not shown once 10 were kept, the previous incident's speed line could run out of the trace, an option of a display profile could look unchangeable.
- **Driver Stats**: Qatar (`Losail International Circuit`) compared again with the community times; a lap equal to a level limit counted in the level below.
- **Race Calculator**: with no race length, the formation lap was planned as a 1 lap race.
- **OBS standings tower**: soft and hard tyres were swapped.
- An overlay turned off or reloaded just as the game paused could log an error; `Ctrl+C` in the console now quits cleanly.
- **About 60 more fixes** found by reviewing the whole app: `Esc` closes every page cleanly, page shortcuts no longer fire while another page is shown, damaged settings files are refused cleanly, errors of the app are written to `neopedal-errors.log`, and many small display fixes.

### Removed

- **Share codes**: presets and overlay settings are shared as `.zip` files only (`Presets` page: `Export Package...`, and `Import` > `Preset Package (.zip)...` or the file dropped on the window). Text codes of presets (`MTP1:`) and race plans (`TPRP1:`) are no longer read.
- **`column_pitstop_count`** of Relative, Standings and Rivals: `column_pit_status` shows the pit status and the stops.

## 0.23.0 (2026-10-11)

### New name: NeoPedal

- **The app is now called NeoPedal**, everywhere: window, menus, installer, Start menu, Task Manager, web dashboard, VR overlay and documentation. It stays a modified version of TinyPedal, with the same license and credits.
- **Settings separate from the original TinyPedal**: the global config folder is now `%APPDATA%\NeoPedal` (Linux: `~/.config/NeoPedal` and `~/.local/share/NeoPedal`). Until now the app shared `%APPDATA%\TinyPedal` with the original TinyPedal, so each app could change the other's settings, and both can now be used side by side.
- **Your settings come along**: update from the app as usual. On first start, your `TinyPedal` folder (config, shortcuts, driver stats, language packs, Black box incidents) is copied once to the new one and left unchanged, so the original TinyPedal keeps working. If the copy fails, the app uses the old folder for this run and tries again next time. Presets and data next to the executable do not move, the install folder is kept and the shortcuts are renamed.
- **Your choice**: after the copy, the app asks once whether to keep the imported settings or start with default settings (the imported ones are set aside, never deleted). Later, `Config` > `TinyPedal Settings` imports them again or starts over with default settings, each time keeping a backup of the current settings.

### New overlay, new columns and track map colors

- **New `Speed Delta` overlay**: your speed difference to four reference laps at the same place of the lap (all time best, session best, stint best and last lap), positive when you are faster, smoothed (`speed_delta_smoothing_samples`). Each reference can be shown or hidden, with its own prefix and colors. A dash while there is no reference lap yet, on an out lap or in the pit lane before the start line. Off by default: turn it on in the `Overlays` page.

![New Speed Delta overlay](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-11-speed-delta-overlay.png)

- **Relative: `Gap Trend` column** (modern design, `column_gap_trend`, on): how the gap to each car changes per lap, averaged over about 30 s. Green arrow when you gain (closing on the car ahead, pulling away from the car behind), red when you lose, a dash when steady (under 0.05 s per lap) or for a car in the pits.
- **Standings: class header** (modern design, `show_class_header`, on): in multi-class split mode, or with one class shown, each class starts with its name in a colored pill; the class column goes and the position badge shows the place in class.
- **Standings: class order** (`class_order`, both designs): classes of multi-class split mode in the order you choose (Hypercar, LMP2, LMP3, GT3... by default), set in `Overlay Options` by dragging them or with the arrows (`Default Order` puts the default back). Classes found in no list come after, fastest first, as before. `maximum_vehicles_per_split_others` now takes any value, `0` hides the other classes.

![Standings: class header and class order](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-11-standings-class-header.png)

- **Track map: sector performance and nearby cars** (modern design): each sector of the road is colored by your last time there (purple session best, green faster than your best lap, amber slower; `show_sector_performance`), and cars less than 1 s ahead or behind get a ring (`show_nearby_vehicle_highlight`, `nearby_vehicle_threshold`). Both on by default.

![Track map: sector performance colors and nearby cars](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-11-track-map-sectors-nearby.png)

- **Black box**: suspension motion is magnified 8 times by default (`suspension_motion_scale`) so it can be seen; presets still at 1 get 8 once, another value you chose is kept. The overlay is a bit taller (about 15 %) to leave room for the wheel travel; set the scale back to 1 for the previous size.

![Black box: suspension motion 8x by default](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-11-black-box-suspension-scale.png)

- **Chat**: messages fade out at the end of their display time also in the garage and menus (they stayed on screen while overlays were paused). Modern design: your own name in the accent color, game notices dimmed.

### Race results, replays and driver stats

- **Watch the replay of a session**: `Race Results` shows a `Watch Replay` button when LMU saved the replay of the session, and a camera icon in the session list. The replay opens in the game through `Game Replays` (game state checked, confirmation, playback controls there). The replay is found from the time it was saved next to the results file, so the icons show even while the game is closed.
- **Game version of your lap times**: every session recorded in `Driver Stats Viewer` now keeps the game version (LMU). The personal best line shows it (`PB 1:09.984 set on 03/10/2026 · Version 1.42`), and so does each session of the list. Older sessions take it from the game results file of the session.
- **Race results in `Driver Stats Viewer`**: sessions are linked to the game results files. The list shows your class position (`P3/12`) and a mark when you had contacts or penalties; the tooltip adds position, gap, contacts, penalties, track limits points, online or single player and the server. Click a session to open it in `Race Results`.
- **Driver card** (All Tracks): name, country, team and number of your game profile, your Steam profile picture (read from Steam's own cache, nothing downloaded), and your races in the results files: wins, podiums, average class finish, clean races, contacts per race.
- **Complete your lap times**: personal, qualifying and race bests that are missing from your stats, or slower than a best lap in an LMU results file, are offered with `Complete...`. The confirmation lists every change, a backup is made first and Ctrl+Z undoes it. Laps invalidated by track limits have no time in LMU results, and in team races only your own laps count.
- **`Game Replays` track map follows the cars like the Broadcast Director**: with the game on this computer, cars are placed where the game shows them, 10 times a second, and glide smoothly from one place to the next, in a session or a replay (paused, slow motion, fast forward). Before, they moved by estimate along the track between game answers every 2 to 5 seconds, which is still the case when the game data can't be read.

### Telemetry viewer

- **New `Simple View`**: a `Simple View` / `Advanced View` switch in the toolbar shows, in place of the charts, every shown channel at the cursor drawn like overlays. A `Pedals & Steering Wheel` card per lap, side by side (throttle, brake, clutch, steering wheel turned by its real angle, gear, speed), then `Timing`, `Engine`, `Tyres` (four wheels colored cold to hot), `Brakes`, `Chassis`, `Electronics`, `Track` and `Math Channels`. Values of the main lap (click its card), other laps as marks of their color. The chosen view is kept per folder.
- **Same channels in both views**: one `Show` menu, in place of `Channels`, picks what both views show (a channel charted in the advanced view is a gauge or tile in the simple view), by group or channel, with search, presets and every chart option (smoothing, gain/loss window, min / max band, delta vs ideal lap, math channels). Channels of one wheel are found with the search.
- **One playback bar under both views**: back, play, forward, A-B loop and speed moved under the charts, with a bar to drag along the lap and the cursor position. It stays at the same place in the simple view, where the charts are hidden.

![Lap viewer: Simple / Advanced view switch, one Show menu and one playback bar](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-11-lap-viewer-simple-advanced-views.png)

- Recorded laps now keep the steering wheel rotation, so the wheel turns by its real angle.
- Long laps no longer freeze the page: charts, map, delta best and MoTeC export are made in the background, side tabs open without a stall.

### Race calculator

- **New `Live` tab: every value the game gives**, next to the value of the calculator, with where it comes from: race length, formation laps and start time of day (LMU session settings or the track clock), number of drivers (LMU team), lap time, fuel, energy and tyre wear per lap, tank capacity, compound on the car, fuel, energy and tread on the grid, pit lane time from the stops of the session, **refuel and energy rates, tyre and driver change times and what is done while refuelling** (LMU pit stop times of the series), tyre allocation and rain from the forecast (as a rain scenario). Fill a value in with its arrow, or `Fill In All`; a switch per row leaves a value out.
- **`Load Live` and `Follow Live` take every followed value**, not only the laps: pit stop times, tyre rules, drivers, formation, start time, rain forecast... LMU garage screens are read in the background (every 10 s while the tab is shown or inputs follow live).
- **Race in progress** read from the game: lap, race time and time left, fuel, energy, tread, stops, safety car or full course yellow (also in the `Live Race` status), penalties, class position, pending repair and the game's next stop time.
- **Tyres available**: the tyres the LMU pit menu offers, new compounds and used tyres of each wheel with their tread. `Add Used Tyres to Stock` puts them in the tyre plan stock with their own tread (a used tyre starts the stint at 84 %, not as new).
- **`Driver Change While Refuelling`**: the driver change counts only when longer than the service, as in LMU.
- **Faster**: a pit stop plan of a 10 hour race with safety car, rain and fuel effect is calculated about 2.5 times faster (saving target and strategy comparison included), and a saving target the calculator used to miss is now found.

### Broadcast Director (LMU)

![Broadcast Director: cars, camera desk with the director queue, race events and car sheet](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.23.0-broadcast-director.png)

- **In the navigation bar for everyone** (`Broadcast`), in place of `Spectate`: the bar of every user is set once to the new default (Home, Overlays, Stats, Results, Replays, Broadcast, Telemetry, Race, Preset). `Spectate` stays in the command palette, `Config` in the gear button under the bar and `Ctrl+,`; both can be put back with `Customize Navigation Bar...`.
- **New `Broadcast Director` tool** to cast a race, live (driving or spectating an online race) or in a replay. Three columns:
  - **Cars**: every car by place, with class place, number, team, interval to the car ahead in class (`+0.8`, `+2 Laps`, measured on track, so it also works for cars laps behind), and marks for battles, contacts and pit lane. A double click (or the camera button) puts a car on air.
  - **Camera desk**: the car on air, why it was chosen and for how long, and every camera of the game (driving, onboard, trackside groups) in one click. Replay controls come up while a replay is open.
  - **Commentator screen**: race events with their time, battles with gap and trend, class leaders and best laps, pit stops with time in the pit lane and stint length, and a sheet of the selected car with intervals ahead and behind, contacts, penalties and your own notes on the driver (kept between sessions).
- **Director**: battles (two cars of a class within 1 s, adjustable), overtakes, lead changes, contacts, stopped cars, pit stops, fastest laps, finishes, retirements and penalties are found for every car. In `Assisted` mode they are listed by interest and taken in one click (or Enter). In `Automatic` mode the director cuts by itself, with a camera suited to each story: a shortest and longest shot, urgent events first, a car just shown not shown again at once, cars in turn when nothing happens. A car chosen by hand (or in the game) holds the director for 20 s. Automatic mode is never on when the page opens.
- Click an event in a replay: the replay goes there a few seconds before, with the camera on the car.
- Optional: overlays (and stream sources) follow the car on air, through spectate mode.
- **More stories**: slow cars (much slower than usual at that place of the track, learned from the other cars), yellow flags in a sector (with the slowest car there), full course yellow and green flag, and the race start (leader followed through the first lap).
- **Live timing**: intervals and battle gaps turn amber under 0.5 s and red under 0.3 s, sectors of each car colored as on TV (purple best of the class, green personal best, yellow slower), places gained or lost in the class since the start, time stopped in the pit box next to the time in the pit lane, weather in the header (full course yellow, air and track temperatures, rain, wet track).
- **Lap history** of any car (right-click, or `Laps` in its sheet): every lap seen with its sectors colored, pit laps, energy used and class place. The sheet adds the energy used per lap over 3 and 5 laps and the laps left.
- **Incidents not seen yet** are marked and counted until shown on air or looked at; **instant replay** of an event in a live session (replay a few seconds before, then back to live by itself), also as online spectator; **CSV export** of every event.
- **Lock** the car on air so the automatic director waits.
- **Broadcast graphics made for the director**: one browser source (1920 x 1080) for OBS, Streamlabs, XSplit or vMix, given by the page (`Graphics`, `Copy Address`) and fed by it only: standings tower (overall, each class in turn, or the class of the car on air), driver card on each cut, battle card, banners (fastest lap, penalties, flags, lead changes, heavy contacts...), pit lane radar, replay mark, session clock and weather. Each graphic on or off, `Hide Graphics` at once.

![Broadcast graphics: standings tower, fastest lap banner, battle card, pit lane radar, session clock](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.23.0-broadcast-graphics.png)

- **Pit radar**: while the car on air is in the pit lane, the cars near it show with their distance, `Alongside` in red, on the page and on the graphics.
- **Contact severity**: a contact that costs a car most of its speed (or stops it) comes first, a touch both cars drive away from is a minor story. Measured from the speed of the cars, so it also works as online spectator, in replays and from another computer.
- **Car logos and pictures** of the game in the car list, on air card and car sheet; **tyres** of every car (front and rear, colored as on TV) with the game on this computer; **weather forecast** of the session (click the weather in the header).
- **Direct from another computer** (`Game computer` in the settings), and an optional **events log**: every event written to a CSV file as it happens, for race control.
- **Faster**: an answer of the game costs about 3 ms of the interface instead of 40 ms after hours of racing (0.5 ms while the page is hidden), with one connection to the game kept open.
- **Find a car** by number or name (`Enter` puts it on air), `1` to `6` take that suggestion, a bar shows when the automatic director may cut, battle gaps tell their change per lap, cars in the pit lane show their time there as it goes, and a setting keeps the director cutting when another app also moves the game camera.
- New hotkeys, also for the remote control and Stream Deck: `director_next_car`, `director_previous_car` (with the page closed they move the game camera), `director_auto`, `director_take_best`, `director_lock`.

#### More broadcast graphics, layout editor and timing table

- **Instant replay graphics**: a contact replayed shows both cars, a flag or a stopped car shows the driver card all along the replay, and banners (fastest lap, penalty...) wait until 5 s after the replay so viewers see them live.
- **Onboard**: speed, gear, rpm, throttle and brake of the car on air, ten times a second (game on this computer: shared memory, also as online spectator), energy left, in three styles (`Dash`, `Cockpit`, `Helmet`).
- **Qualifying lap**: outside races, the lap of the car on air with its time running, sectors colored, gap to the pole of its class at the last sector and its state (out lap, improving, in pits).
- **Battle train**: up to 6 cars of a class following each other, as cards, kept 10 s after the train breaks up.
- **Track map**: the circuit of the game with every car in its class color, the car on air bigger with its number, the car of a yellow flag in gold.
- **On demand** (`Graphics` > `On Demand`, one at a time until clicked again): **starting grid** (pages of 8 cars with their qualifying lap and car picture), **event card** (track, conditions, forecast, session length), **classification** captured when you want (gap to the leader, laps, best lap, pit stops, retired cars) and **championship standings** imported from a CSV file (driver, points, and team, class if you want; several championships, one class or all, medals for the first three).
- **Standings tower**: lap times shown a few seconds as each car completes a lap (purple for the fastest of its class), tyres and penalties.
- **Style**: panel opacity and °C / °F for the graphics.
- **Layout editor**: `Graphics` > `Style & Layout` > `Edit Layout` opens the graphics in your browser with sample data: drag a graphic to move it, mouse wheel to resize it, double click to put it back, chips to show the graphics sharing a place, then `Save`: every graphics source of this computer follows at once. `Reset Layout` puts them all back.
- **Timing table** (`Timing` above the car list): race, qualifying and pits views, each with its own columns (drag a title to move it, right click to show or hide columns), sectors and laps colored, battles with their trend, car on air in red, slow cars in amber, tyres, energy and penalties.

#### Broadcast graphics, part 3

- **Faster sources**: the graphics source gets only what changed since its last answer, the standings tower moves each row (overtakes slide) instead of drawing it again, and onboard and map positions come ten times a second, the onboard values easing and cars gliding between them. Qualifying times of the grid are read in background, the championship graphic is made once.
- **Automatic graphics**: starting grid during the formation lap, event card at the start of each session, classification at the chequered flag (kept up to date while cars finish), each one on or off; your own choice always wins.
- **New hotkeys** for the graphics (Stream Deck, remote control): `director_starting_grid`, `director_event_card`, `director_classification`, `director_championship`, `director_hide_graphics`, `director_next_layout`.
- **Banners**: the most important first, the same news never twice in 30 seconds, 4 waiting at most.
- **Track map**: no panel any more (a shadow keeps it readable), sectors under yellow drawn in gold, cars in the pit lane faded, rotation and dot size.
- **Onboard**: shift lights and the car ahead with its gap.
- **Standings tower**: gaps to the car ahead or to the leader, classes apart in overall, fastest lap tag, pit stops.
- **Layout editor**: snapping to the other graphics and to the middle with guides, arrows to move by one pixel, `Ctrl+Z` to undo, position and size shown; the stream layout editor gets undo, arrows and position too.
- **Director**: incidents already shown are less wanted, an overtake coming (very close and closing fast) is shown from the bonnet camera of the car behind, cars climbing through the field are followed more.
- **Sources with some graphics only** (`only=tower,map`) to split the graphics over several OBS scenes or sources, each with its own **layout preset** (`Default`, `Pre-race`, `Race`, `Post-race`), switched in one click or with a hotkey.
- **League branding**: accent color, event or league name, league logo and sponsors pictures shown in turn.
- **Message** of race control or commentators as a lower third, and a **countdown** before the start.
- **Driver history** in the car sheet: races, class wins and podiums, best finish on this track, last races, and races with the cars ahead and behind, from the race results files.

### Smoother and lighter

- **Preset load without a freeze**: loading or reloading a preset (also the auto-load when entering the track) no longer blocks the window and the overlays while modules stop and save (laps, replays): it ends in the background, a load asked meanwhile waits its turn, and quitting during a load is clean.
- **Overlays react to the game sooner, with less CPU**: data modules wake when the game writes new data (100 ms at most) instead of checking at a fixed rate, and do nearly nothing while the game is paused or in menus (LMU and rFactor 2).
- **Less drawing while you drive**: Black box and the modern driver tables (Relative, Standings, Rivals) redraw only what changed; the VR overlay sends only the overlays that changed since the last frame; saving a recorded lap is written in small steps instead of freezing overlays for 100 ms or more; brand logos are read in the background (initials meanwhile), so a new car never stutters a table.
- **No more stalls in pages**: reading files and heavy work moved off the interface in `Driver Stats Viewer` (an action on a 50,000 session history took 0.15 to 1 s, now under 50 ms), `Race Results`, the telemetry viewer, `Track Map Viewer`, presets, preset backups and comparison, the `Overlays` page previews, modules and bug report. Heavy pages build in steps instead of freezing when they open.
- **Faster lists**: each telemetry folder keeps an index of its laps, so lap files are opened only when they changed; `Driver Stats Viewer` reads only what was added to the history since last time; race results files are read once for `Race Results` and `Driver Stats Viewer`; `Overlay Options` lists and the search across every overlay scroll and open faster.
- **Started hidden in the tray**: pages reopened at startup are built when you first show the window, and tool pages you did not open yourself are released while it stays hidden.
- Shorter memory cleanup pauses while driving: what is loaded at startup is set aside from Python's garbage collection, and the cleanup after a preset load waits until you stop driving.
- `Race Results` position charts are smoother (drawn by the graphics card, with smooth edges).
- The performance monitor also shows interface stalls (over 50 ms) and garbage collection pauses.

### For scripts and tools

- Release files are now named `NeoPedal-<version>-…`: older versions still find their update. The GitHub repository keeps its address.
- The executable now carries its Windows file details (NeoPedal, version, copyright), shown in Task Manager and the file properties.
- Linux: `TinyPedal.sh` reads `~/.config/NeoPedal/launcher.conf`, and `~/.config/TinyPedal/launcher.conf` when there is none.
- The update check now also follows GitHub redirects, so the repository can be renamed later without stopping updates.
- The remote control accepts the new `X-NeoPedal` header; `X-TinyPedal` still works.

### Recorded data

- **Pit lane data kept on preset load**: pit entry, pit exit and pit speed limit measured while driving were lost when a preset was loaded afterwards (also by auto-load when entering the track), and the next save wrote the old values back to `tracks.json`. Your corrections in `Track Info Editor` are no longer overwritten by values kept from your last stint either: only values measured again are saved.
- **Saved while you drive**: fuel and virtual energy reference laps, best sectors and consumption history are also saved every 5 minutes on track, not only when you go back to the garage, so a crash or power cut during a long stint no longer loses them.
- Starting a replay recording again within the same second no longer overwrites the previous one (`-2` is added to the name).
- Hybrid: battery drain down to 0% and regen from 0% are counted. Driven distance in driver stats ignores position jumps again. Recorded lap names never show `1m60.000s`.
- Track notes saved as `CSV UTF-8` by Excel are read.

### Overlays

- **Previews with real-looking values**: the pictures of the `Overlays` page, of `Overlay Options` and of the setup wizard now show a simulated race (a GT3 mid race at Road Atlanta, in a 20 car multi-class field) instead of empty overlays, so you see what each overlay really shows: speed, gear, fuel, tyres, delta, map, radar... Your game data, presets and running overlays are never touched, even while you race.
- **Bigger preview in `Overlay Options`**: zoom the live preview from 50 % to 300 % (buttons, Ctrl+wheel, double click for actual size or fit), and widen the preview panel with the button at its bottom right. A zoomed overlay is drawn at that size, as the global overlay scale does, so text and lines stay sharp.
- **No more fake chat in game**: modern `Chat` drew a sample conversation ("N. Fischer joined the session"...) whenever overlays were unlocked, the default, so it showed in the garage and when joining a server as if it were real. The sample, like those of `Spotter`, `Race Notifications` and `Pit Lane Helper`, is now drawn only in edit mode (right-click an overlay > `Edit Mode`), to place the overlay. Modern `Flag`, `Race Notifications` and `Spotter` no longer show their picture sample (every flag, sample messages) while waiting for game data either.
- **Chat scroll direction**: the `show_newest_message_at_top` switch is replaced by a `scroll_direction` choice: `Upward` (newest message at bottom, the default) or `Downward` (newest message at top). Your presets keep their current order.
- **Black box**: `enable_required_modules` turns on the needed modules only when the overlay starts, no longer when its preview is drawn in `Overlay Options` (it could start modules and save them as enabled before you applied anything). Color fades end on the right color, and long incident recordings draw faster.
- Brake wear, aero damage and suspension damage of your own car are no longer shown while you spectate another car.
- A car taking another car's place is no longer drawn far away for a moment (radar, relative).
- Virtual energy readings no longer switch to fuel for a moment on each reset.
- Classic `RPM LEDs`: blinking no longer depends on how often the overlay is drawn, and it now also blinks while the RPM stays above the critical value, like the modern design.
- Brand logos loaded while the game is paused show at once in driver tables.

### Stream overlay

- **Stream a race you spectate**: while you spectate a session or watch a replay (no car driven), overlays were hidden by auto hide, so every stream source stayed empty. They are now shown and updated as long as a `Layout` or overlay source is on air (`Show overlays while spectating`, on by default), and hidden again a few seconds after the last source stops. Laps, fuel and stats are still only recorded while you drive.
- **Layout in 16:9 for ultrawide and triple screens**: the `Layout` source now shows the centre of your screen in 16:9 by default (`Format` on the `Stream Overlays` page), for a 1920 x 1080 browser source. On a 5120 x 1440 screen the whole screen was squeezed into the top of the source. `Whole screen` keeps the previous layout (copy the address again after changing the format).
- The `Stream Overlays` page tells why sources are empty when no overlay is shown (auto hide outside sessions, visibility options).
- **Layout editor**: `Edit Layout` next to the `Layout` source opens it in your browser, the whole screen shown with the 16:9 frame: drag overlays where you want them on the stream (for example those on the sides of an ultrawide screen), resize them with the mouse wheel, `Save`. Their place on your screen does not change; each format (16:9, whole screen) has its own places.

### VR overlay

- The app's heartbeat could be read as "app closed" by the OpenXR layer, so the overlay could vanish for one frame. After an error while writing a frame, the layer no longer stays on the last frame.
- OpenXR layer (experimental): a frame error of the game itself (tracking loss) no longer turns the overlay off for the whole session, and a game quitting without closing its VR session no longer risks a hang or crash on exit.

### App

- **New hotkey `show_main_window`**: brings the main window in front of the game and focuses it, even when it is hidden in the tray or minimized (`Hotkey` page; also a remote control command).
- **Pages already open**: `View Map` in `Driver Stats Viewer` and `Compare with Loaded Preset` showed the open page on the previous track or preset; they now show the one you asked for. `Overlay Options` opens faster when it is already open.
- `Overlay Options` and `Config` follow a language change while they are open (their texts stayed in the previous language).
- After a failed restart, quitting asks again to save pages with unsaved changes.
- A page could be released (window hidden or minimized for a minute) while one of its confirmation dialogs was still open: possible crash.
- Changes in `Driver Stats Viewer` waiting for a reload to finish are saved even if you close the page.
- No more short freeze about 5 seconds after a preset auto-load on track.
- Editors (brakes, tyre compounds, brands, classes, track info): adding from the session and `Batch Replace` are one undo step, and the last added row is selected.
- `Driver Stats Viewer`: `Undo` and `Redo` wait while an edit is being saved. Race calculator timeline: stints and stops slide to their new place when the plan changes.

### Web dashboard, updates and files

- **Updates checked while the app runs**: besides the check at startup, the app checks again every 12 hours (`number_of_hours_between_update_checks` in `Config` > `Application`, `0` = startup only), never while driving. A version found this way opens what's new only if the main window is the active window; otherwise the notice waits in the window (or a tray message), and a notice you dismissed does not come back for the same version.
- HTTPS certificate files are written safely and made again if they don't match, instead of HTTPS failing until you delete them by hand.
- The downloaded installer is deleted when you decline the install or it fails to start.
- A damaged or encrypted `Preset Package (.zip)` is reported as invalid instead of doing nothing, and an oversized package description is never read.
- Errors of the web dashboard, stream overlay and `Race Results` are now written to the log file (they were hidden).
- Game data: out of range values from the game (`1e999`) no longer stop reading standings, chat, replays or tyre usage. rFactor 2: a copy of shared memory taken while the game was writing it is no longer used. Game data requests that stop late no longer reset the new data.

## 0.22.4 (2026-10-09)

### VR overlay

- **OpenXR layer off by default**: in 0.22.3, turning on `enable_vr_overlay` registered the app's OpenXR layer, which every OpenXR game loads. Le Mans Ultimate is one of them (its VR goes through OpenXR with the built-in OpenComposite), and it could fail to start in VR ("Unable to start the game in VR mode"). The layer is now experimental, behind its own `enable_openxr_layer` option (off by default). Every start removes a layer left registered by 0.22.3, also in safe mode, and closing the app removes it too: games started without the app never load it.
- **SteamVR no longer stuck on a dark grey screen when you quit it**: the SteamVR overlay of the app never answered SteamVR's quit request, so SteamVR waited for it before closing. The app now answers at once, releases its overlay and only connects again once SteamVR has fully closed and started again.

## 0.22.3 (2026-10-08)

### Overlays

- **Unlocking no longer starts the edit mode**: as before 0.22.0, `Unlock Overlay` only makes overlays movable. Move the mouse over an overlay to see its outline, name and corner handle, then drag it; arrow keys and `Ctrl+Z` still work. The edit mode toolbar is in the right-click menu of an overlay (`Edit Mode`). To get it at each unlock, turn on `enable_edit_mode_on_unlock` in `Config` > `Application` > `Overlay Editing`.
- **Gear**: the speed limiter pill (and its pit lane reminder) sat over the top edge and the speed digits. It now takes the place of the speed unit under the speed.
- **Overlay Style fonts in modern overlays**: with `enable_modern_font`, labels and names keep `modern_design_font_name` and values (times, gaps, speeds, temperatures, fuel) use `modern_font_name` (JetBrains Mono: digits stay in place). Turned off, every modern overlay draws its text in its own `font_name`. Gear widens to fit its bar readings.
- Overlays no longer freeze for 5 seconds on every settings `Apply` or when an overlay is turned off.
- Classic `Acceleration` failed to start with one or no speed range enabled. Classic track map and elevation no longer fail on sectors beyond the map.
- Classic radar fade drawn correctly; background cache limited to 32 MB.

### VR overlay

- **VR overlay in OpenXR games**, on any OpenXR runtime (not only SteamVR): a bundled OpenXR layer (D3D11, D3D12, Vulkan) draws the overlays in the game. The app registers it for your Windows user while the VR overlay is enabled, and the uninstaller removes it. Nearby overlays are sent as tiles, not as one large image. Not tested on a headset yet: tell us how it works for you.
- The SteamVR overlay starts once SteamVR runs and hides while the OpenXR layer draws. Two OpenXR games at once are handled.
- The VR overlay was never shown in the installed app (OpenVR library missing). Also fixed: Windows user names with accents, app run as administrator, broken layer entries that stopped OpenXR games from starting.

### Telemetry viewer and replays

- **Lap of another circuit**: opening one (file, drop, lap library, MoTeC import) switches the viewer to that circuit instead of refusing it. Laps of two circuits are never compared, also when a lap of another layout has a similar length (driving line shape is checked).
- Imported laps (MoTeC) were shifted along the distance, and an imported reference lap shifted the recorded laps. Its delta best export is aligned and scaled to the track length.
- Laps with invalid positions no longer stop the viewer. Multi lap MoTeC export never overwrites a file.
- **Long replays**: a 3-hour replay opens in 0.4 s instead of 14 s and uses 1 MB instead of 400 MB of memory. Replays load in the background with progress. Opening a replay no longer stops recording before it is loaded, and a recording error is reported, then retried after 30 s.
- `Replays` page track map was shown upside down.

### Recorded data

- **Best lap kept when you press Esc right after the line**: delta best, fuel, stats and sectors wait for the game lap time (up to 10 s), also in the garage.
- Data files held by another program (antivirus, OneDrive) when the app reads them are never saved over: settings, driver stats, history, lap marks, delta best, sectors and consumption history. They are merged once readable, and a corrupt file is backed up.
- Best S3 and personal best sectors never come from an invalid lap.

### Stream overlay, web dashboard and remote control

- They stayed off after a settings `Apply` or a preset load on Windows: servers now keep listening across reloads and retry when the address is busy. Web dashboard sessions stay open unless the access code changes.
- A slow or hostile client on your network can no longer freeze the dashboards: connections are limited and must send their request within 10 s. No more GUI freeze on a slow DNS, nor start error with a non ASCII computer name.

### Fixes

- Language change: no more crash with `Widget Performance` or `Recorder` open, pages and dialogs reopened by it are closed properly, brand logos follow the light/dark theme.
- No QML errors when quitting with `Spectate` or `Preset` open.
- A hotkey that reloads the preset no longer runs again while it is still held.
- Number fields accept a decimal typed in a whole number.
- `Layout Editor` screenshot and snapping work on each screen of a multi monitor setup.
- Language packs with invalid messages, corrupt packages, invalid heatmap files and setup files saved at 1000 ms are handled.
- Game replay temporary files deleted by the game during a scan are no longer listed.

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
