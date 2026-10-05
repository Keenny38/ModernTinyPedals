# Driver Stats

The **Driver Stats Viewer** shows your numbers per track and per car: personal bests, distance, races, results. With Le Mans Ultimate, your lap times are compared with community lap times and placed on a level ladder, from **Alien** to **Offline**.

Open it with the `Stats` entry of the navigation bar, or `Tools` > `Driver Stats Viewer`.

| Track: level scale, progression, sessions | All tracks: activity, recent sessions |
|---|---|
| ![Driver stats](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-driver-stats.png) | ![Career](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-driver-stats-career.png) |

## How stats are recorded

The **Stats** module (`Module` page) records your stats and saves them when you return to the garage. Each driving stint is also added to the session history. Stats are stored in the global config folder (`.stats` files and `driver.history`).

Stats are **not** recorded while:

- `enable_player_index_override` or `enable_active_state_override` is on in the API options (spectating, overrides);
- the app runs with several instances allowed (`--single-instance 0`).

The `vehicle_classification` option of the Stats module sets how cars are grouped: `Class - Brand` (default), `Class` or `Vehicle` (not recommended: every car has its own name). Community comparison needs the class (`Class - Brand` or `Class`). `enable_podium_by_class` counts finish positions in your class.

## Track view

The track name is the page title: click it to pick another track (type to search, `Up` / `Down` and `Enter` to choose, or press `/`). Below it: number of vehicles and sessions, last driven date, and a `Live` badge when it is the track of the running game session. The arrow on the left (`Alt+←`) goes back to `All Tracks`.

The key figures add up all cars: best lap and its car, its level (with its letter), distance, driving time, valid laps (with their share), races, wins and podiums.

The vehicle table lists each car or class with, among others:

- personal best, gap to the community reference (`% Ref.`) and **level**;
- **theoretical best** (sum of your best sectors) and **potential** (personal best minus theoretical best);
- qualifying and race bests, distance, driving time, fuel used, valid and invalid laps;
- race starts, finishes, wins, podiums, DNF, win and podium rates, average finish position, penalties;
- average speed, fuel consumption per 100 km, last driven date.

Click a column name to sort (rows slide to their new place). `View` > `Columns` (or right-click the column names) shows or hides columns; drag a column edge to resize it. Missing values are dimmed, levels shown as colored badges.

Keyboard in the table: `Up` / `Down`, `Page Up` / `Page Down`, `Home` / `End` to move, `Enter` to open a track, `Delete` to remove the selected car (or track), `Backspace` to go back to `All Tracks`, `Menu` for the right-click menu. `F5` reloads the stats.

The **Lap Time Reference** card on the right shows the **level scale** of the selected car: the six levels from `Offline` (left) to `Alien` (right), your personal best (round mark) and your qualifying and race bests (diamonds) placed on it. Hover a level for its lap time limit, a mark for its lap time. Below: the reference lap time, your gap, the **time to find for the next level**, the fastest car, and the list of levels with the lap time of each one and badges where your bests stand.

## All Tracks (career)

`All Tracks`, first entry of the track selector, shows your career on one page: each track with the best lap of each class, colored by its level, track totals and last driven date, plus the count of your best laps per level. Double-click a track to open it. `View` > `Sort Tracks by Last Driven` lists recent tracks first.

- **Activity**: a calendar of the last 12 months, one square per day colored by your driving time (all tracks), with the days driven, the total time and your longest streak. Hover a day for its sessions.
- **Recent Sessions**: your latest sessions on every track, with the best lap (★ when it was your personal best), the race result and the session type. Click one to open its track with its car selected.

## Community levels

Personal bests are compared with the community LMU lap time sheet of [ohne_speed](https://www.youtube.com/@ohne_speed) (a published Google Sheet: reference hotlap per track and class, ladder up to 107 %):

| Level | Personal best vs class reference |
|---|---|
| `Alien` | about 100 % |
| `Competitive` | 101 % |
| `Good` | 102 % |
| `Midpack` | 103-104 % |
| `Tail-ender` | 105-106 % |
| `Offline` | slower |

The sheet is downloaded once a day when the page opens and kept for offline use. The `Reference` menu has `Update Reference`, `Change Sheet Address...` (another sheet with the same layout) and `Compare With Community Lap Times` (on or off). `View` > `Colorblind colors` uses colors easier to tell apart.

## Progression and sessions

Under the table, side by side (one at a time with the list button when the window is narrow):

- **Progression**: best lap of each session (dots, new personal bests highlighted) and your personal best over time (line over a shaded area), with round lap time grid lines and the level limits (dashed, level letter at the end). Filter by `All`, `Practice`, `Qualifying` or `Race`; the filter applies to the sessions list too.
- **Sessions**: sessions of the selected car, newest first: date, session type, best lap (★ personal best), valid laps, race result (position, podium in color, DNF or DQ).
- **Stints & Consistency**: pace and lap time change per lap **by tyre compound** over your recorded stints, and a **consistency index** per session and per track (lap time spread of clean laps; lower is more consistent).

## Compare with a friend

1. Your friend exports their history: `Export` > `Session History for a Friend (JSON)...`.
2. You load that file with `Reference` > `Compare With a Friend's Stats...`. Their times show next to yours.
3. `Reference` > `Stop Comparing With Friend` returns to your stats only.

## Export

The `Export` menu saves:

- `Export CSV...`: the table as shown (visible columns);
- `Export Raw Values (CSV)...`: base units without formatting (lap times in seconds, distance in meters, fuel in liters), for spreadsheets;
- `Session History (CSV)...` and `Session History for a Friend (JSON)...`.

## Open the telemetry

The `Telemetry` button (or right-click > `Open Recorded Laps`) opens the recorded laps of the selected car class in the [Telemetry Viewer](Telemetry-Viewer.md), with your personal best lap as reference. `View Map` shows the track map.

## Edit and backups

The viewer never lets you edit a value, only reset or remove:

- right-click a lap time > `Reset Lap Time`;
- right-click a car > `Remove Vehicle`;
- `⋯` > `Delete all stats of this track` removes all stats of the track (or `Delete` on a track of `All Tracks`).

Before each change, the stats file is backed up (the last 10 are kept): `⋯` > `Restore Backup`. `Undo` / `Redo` (`Ctrl+Z` / `Ctrl+Y`) work while the page is open, and stats recorded meanwhile are kept. `⋯` > `Reload` (`F5`) reads the stats file again (the page also reloads by itself when the Stats module saves).

All options: [Driver stats viewer](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#driver-stats-viewer) and [Stats module](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#stats-module).
