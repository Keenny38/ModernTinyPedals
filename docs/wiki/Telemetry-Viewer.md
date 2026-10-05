# Telemetry Viewer

Every lap you drive is recorded, and the **Lap Telemetry Viewer** compares them: charts, racing line map, corner analysis, session pace and XY plots. It is drawn by the graphics card (Qt Quick), so zooming and moving stay smooth.

Open it with the `Telemetry` entry of the navigation bar, or `Tools` > `Lap Telemetry Viewer`.

![Telemetry viewer: gap to reference, markers A and B, range statistics](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-telemetry-viewer.png)

## Lap recording

The **Recorder** module (on by default, `Module` page) saves each complete lap as a CSV file in the `telemetry` folder, one subfolder per track and car class. Laps are checked against the game lap time; laps that are not confirmed (track limits, invalid lap) are marked `invalid`.

Main options of the Recorder module:

| Option | Default |
|---|---|
| `number_of_saved_laps_per_track` | `50` laps kept per track and class, oldest removed |
| `number_of_best_laps_kept_per_track` | `3` fastest valid laps never removed |
| `save_invalid_laps` | On |
| `enable_out_and_in_lap_recording` | Off |
| `enable_compressed_lap_files` | Off (`.csv.gz`, about 5 times smaller) |

Recorded channels include pedals, steering, speed, gear, RPM, fuel, position, G forces, TC and ABS activity, battery, and per wheel: tyre temperatures (inner, middle, outer), pressures, wear, load, brake temperature, wheel speed, ride height, suspension, slip angle and camber. Brake bias, TC and ABS levels, engine map, water and oil temperatures are recorded too, and with LMU the name of the setup loaded in the game. Each lap also gets a binary copy, so the viewer opens it without reading the CSV again.

## Choose and compare laps

1. Select the track at the top.
2. In the lap list, laps are grouped by session (newest first). Check laps to show them: each lap keeps its own color.
3. The fastest valid lap is the **reference** (`REF` badge). Double-click a lap, or use its flag button, to make it the reference.

Lap list tools:

- `Clean only` hides invalid, out and in laps. The search field finds laps by vehicle, session, setup or note.
- The quick selection menu checks `Best vs Last Lap`, `3 Best Laps`, `5 Best Laps` or `Best Lap in Similar Conditions` (track temperature, compound, wet track), or `Uncheck All`. `Shift` + click checks every lap between two.
- Right-click a lap: `Set as Reference`, `Export MoTeC...`, `Keep Lap` (never removed by the recorder), `Note...`, `Use as Delta Best...` (the lap becomes the delta best used on track, the previous one is kept as a backup), `Setup Differences with Reference...`, `Move to Trash`. Session rows have the same actions for all their laps.
- Deleted laps go to a trash: `Ctrl+Z` restores them.
- `Live` lists new laps as soon as they are recorded and compares the newest lap with the best one.

## Charts

- **Channels**: the `Channels` menu picks the charts, with a search field and presets (Pedals, Tyres, Brakes, Suspension). Channels not recorded in the shown laps are greyed out. Four-wheel channels share one panel.
- **Delta and time gain/loss**: delta to the reference along the lap, and where time is gained or lost (`Gain/Loss window` from 20 to 150 m). `Delta vs ideal lap` compares with the fastest clean lap in each mini-sector instead.
- **Cursor**: move the mouse to read every lap's value and its gap to the reference.
- **Markers A and B** (right-click, or `A` / `B` keys) and the `Range` tab: time of each lap between the markers, gap to the reference, minimum, maximum and mean of each channel.
- **Calculated channels**: wheel slip (lock under braking, spin on throttle), steering rate, fuel used, tyre temperature spread. `Math Channels...` adds your own formulas (`+ - * /`, `abs`, `min`, `max`, `d()` change per second) and has built-in understeer angle, brake release rate and throttle application rate.
- **Display**: `Smoothing` for noisy channels, `Min / max band` of the shown laps (3 laps or more), `Time axis` (charts along lap time instead of distance).
- **Align on braking**: right-click > `Align Laps on Braking Point Here` shifts laps so their braking starts line up with the reference.
- **Playback**: `Space` plays the reference lap at real speed (0.25x to 4x), with optional loop between markers A and B.
- **Right-click menu**: markers, zoom to sector or between markers, copy values or picture, `Open Replay Here` when a telemetry replay covers the lap.

Zoom with the mouse wheel, `Shift` + drag to zoom an area, double-click or `Reset` to reset. Click `S1`, `S2`, `S3` to zoom on a sector. Drag a channel name to reorder channels, drag a panel edge to resize it. Right-click a panel and choose `Fit Values to Visible Part` to scale its values to the zoomed part.

## Right panel tabs

### Track Map

![Track map: official layout, track edges, mini-sectors and minimap](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-track-map.png)

- Driving line of each lap over the circuit. With LMU, the **official track layout**, track edges and pit lane come from the game and are kept for offline use.
- **Driving points** of each lap in each corner: braking, apex (minimum speed), exit (back to full throttle) and track-out, with the margin to the track edge.
- **Off track** (2 wheels or more on grass, dirt or gravel) and **track limits exceeded** (4 wheels out), counted per lap.
- **Line coloring**: `Laps`, `Gain / Loss`, `Speed`, `Pedals`, `Racing Line`, `Gear`, `Elevation`, `Delta per corner`, `Mini-sectors` (with the ideal lap of the shown laps) and `Consistency` (spread of mini-sector times over the stint, session or shown laps).
- Sector times, direction arrows, front lockups and rear wheelspin, pedal zones, cursor trail, distance marks, ruler (`M`), colorblind colors.
- Zoom synchronized with the charts (or separate), large map over the charts, minimap, follow the cars during playback, `Export Map Picture...` and `Copy Map Picture`.

### Corners

![Corners tab: where time is lost](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-coaching.png)

- **Where time is lost**: the corners that cost the most, with the cause in plain words (brakes earlier, lower minimum speed, longer coasting, later full throttle).
- For each corner: time lost or gained, entry, minimum and exit speed, gear, brake pressure, braking point, full throttle point, trail braking, coasting and pedal overlap, and the fastest lap in that corner (ideal lap).
- Official corner numbers (`T1`, `T10a`...) for Silverstone, Imola, Spa-Francorchamps, Circuit of the Americas, Interlagos, Paul Ricard (F1 layout), Monza, Bahrain, Portimão, Lusail, Road Atlanta, Laguna Seca and Long Beach; named corners at Le Mans. Other tracks number corners in lap order.
- `Corner detection` sets how big a speed drop counts as a corner. `Report...` exports a corner report (table, deltas, coaching notes and map) as HTML or PDF.

### G Circle, Session and XY

- **G Circle**: lateral against longitudinal acceleration of each lap, with the grip envelope.
- **Session**: every lap of the session with fuel and tyre wear per lap, off tracks and track limits, **long-run pace** (clean laps, slow laps left out), lap time **trend** (also per % of tyre wear) and consistency. Click a lap to show or hide it.
- **XY**: one channel against another as a scatter plot (presets: speed / lateral G, steering / lateral G, throttle / wheel slip...) or a histogram. Limited to the zoomed part when zoomed.

## Compare with other drivers

- `Add File...` adds laps from another folder or track, or imports a **MoTeC i2 log** (`.ld`), for example one from the LMU built-in logger or a lap shared by another driver. You can also drop a `.ld` file on the main window.
- `Imported Laps...` opens the library of imported laps: search, add to the viewer, rename, delete.
- `Import Folder...` imports laps of the same track and class from another folder (a teammate, a shared folder). They are marked as foreign.

## Export

The `Export` menu saves:

- MoTeC i2 logs (`.ld`): `Reference Lap...`, `Displayed Laps...` or `All Laps of Track...`;
- `Reference Lap as Delta Best...`;
- CSV for spreadsheets: `CSV, Displayed Laps...`, `CSV, Displayed Laps on Time Base...`, `CSV, Passage A ↔ B...`;
- pictures: `Picture (PNG)...`, `Copy Picture` (to paste in Discord), `Picture of Passage A ↔ B...`.

## Keyboard

Click the `?` button for the full list. Main keys: `Space` play / pause, `Left` / `Right` move the cursor (`Shift`: the view), `[` / `]` previous / next corner, `A` / `B` markers, `Esc` clears them, `R` sets the highlighted lap as reference, `+` / `-` zoom, `Home` resets. On the map: `F` fit, `R` turn, `1`-`9` coloring, `L` lockups, `Z` zones, `T` trail, `M` ruler.

## Performance notes

- Laps load in the background with a progress bar. Heavy computations (track limits, session values) run in a separate process, so the page stays fluid.
- When the page stays in the background for 3 minutes, loaded laps are released from memory, then reloaded with the same zoom when you come back.

## Track Map Viewer

`Tools` > `Track Map Viewer` shows the track maps recorded by the Mapping module (`Load Map`):

- road at its real width, line colored by sector, start and sector lines, official corner numbers (click one to go there);
- at the current position: curve section, osculating circle, distance circles, curve radius and angle, slope, XYZ position;
- elevation profile of the whole lap;
- `Play` (or `Space`) drives around the track, `Follow position` keeps the position centered.

![Track Map Viewer](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-track-map-viewer.png)

All options: [Lap telemetry viewer](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#lap-telemetry-viewer), [Track map viewer](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#track-map-viewer) and [Recorder module](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#recorder-module).
