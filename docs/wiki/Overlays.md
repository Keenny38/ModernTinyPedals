# Overlays

Modern Tiny Pedals has **87 overlays** (called widgets in the settings files). Turn them on and configure them on the `Overlays` page: see [Getting Started](Getting-Started.md#configure-an-overlay). Every option is described in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widgets).

![Standings, before and after the modern design](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-classements.png)

![Radar, track map and navigation, before and after the modern design](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-06-map-overlays-design.png)

## Modern design and classic layout

Every overlay has a **modern design**:

- one rounded panel per overlay, the bundled **Barlow** font, short labels above the values, translated into the app language;
- values colored by meaning: gain, loss, warning, best time;
- standings as rows with a position badge, class pill and position in class, with selectable columns (`column_*` options of Relative, Standings and Rivals);
- fuel and energy with a gauge and markers, tyres and brakes as tiles in heatmap colors, LEDs as glowing dots.
- graphic overlays drawn for the design: round **radar** fading at its edge (amber, then red glow toward a car alongside), **track map** with cars as numbered dots in class colors (or race status colors) and a checkered start line, **navigation** view with road edge lines, **friction circle** with G rings, a trace fading with age and recent peaks, **heading** compass ring with yaw and front slip angle, drawn **steering wheel**, **instrument** and **weather forecast** icons drawn as shapes, **trailing** inputs with soft areas under throttle and brake, **track notes** card.
- **flag** items as chips in flag colors (caption above value, only while active), **chat** feed with a color per sender and new messages highlighted, **elevation** profile with the driven part in accent color and the car as a dot, **race notifications** with an icon per message and a bar shrinking with the time left, **steering meter** growing from center with a thumb, **RPM LEDs** keeping a faint tint of their color zone while unlit, **spotter** bars glowing toward the screen center.
- **Black box** keeping its layout and options, in the Barlow font, theme colors and cards with a hairline border.

The modern design reads fewer options than the classic layout: the Overlay Options page only shows the options it uses. Display order options (`display_order_*`) apply to the modern rows and columns once you change one of them. In the Overlay Options page, Relative, Standings and Rivals list their columns in one `Columns` list, from left to right as the overlay draws them: switch each column on or off there, drag it or use the arrows to move it. Sections follow for the rows, the classes and number of cars (Standings), then the options of each column, dimmed while the column is hidden. The live preview shows a sample race with fictional drivers.

The **classic layout** is still available:

- for every overlay: choose a `Legacy` theme (see below), the original TinyPedal look;
- for one overlay: turn on its `enable_classic_layout` option (classic layout with modern colors).

Other options of `Config` > `Overlay Style` (they apply to all presets): `modern_design_font_name` (default `Barlow Semi Condensed`), `modern_font_name` (classic layout font, default `JetBrains Mono`, bundled), `corner_radius_scale`, `enable_depth_effects`, `minimum_bar_gap`, `overlay_scale` (scale of all overlays) and `enable_fade_animation`.

## Themes

`overlay_theme` in `Config` > `Overlay Style` sets the look of all overlays:

| Theme | Look |
|---|---|
| `Modern Dark` | Default: modern design, slate neutrals, softer accent colors |
| `Modern Light` | Modern design, light panels and dark text |
| `Legacy Dark` | Original TinyPedal look: classic layout, colors and fonts |
| `Legacy Light` | Original TinyPedal look with light panels and dark text |

`enable_colorblind_colors` turns on the colorblind safe variant of any theme (Okabe-Ito palette: red / green pairs become orange / blue).

Light themes invert gray panels and text, keep colored backgrounds (flags, warnings) and darken the colors drawn on panels (heatmap temperatures, gains and losses) so they stay readable. Themes only change options that still have their default value: a color you customized is kept in every theme.

The window of the app has the same four themes (`window_color_theme` in `Config` > `Application`, or the theme button of the status bar). Window and overlays have separate themes.

![Overlay themes](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-06-overlay-themes.png)

## Visibility by session and pit

- **Auto hide** (tray menu `Auto Hide`, on by default) hides every overlay when you are not driving.
- Each overlay has a `visibility_context` option: `Always` (default), `Race`, `Qualifying & Race`, `Practice & Qualifying`, `On Track` or `In Pits`.
- Overlays fade in and out when they appear or hide (`enable_fade_animation` in `Config` > `Overlay Style`).

## Race aid overlays

Seven overlays added in 0.20.0 help during a race. They are off by default: turn them on on the `Overlays` page.

| Overlay | What it shows |
|---|---|
| **Delta Graph** | Delta along the current lap (loss in red, gain in green), previous lap in the background. Reference: best lap, session, stint or last lap. |
| **Gap Trend** | Gap to the car ahead and behind over the last laps, and what you gain or lose per lap. All classes or your class. |
| **Pit Lane Helper** | Speed against the pit limit, speed limiter (warning if it is off), distance to your pit box and planned services. Shown only near and in the pit lane. |
| **Stint Timer** | Stint time and laps, countdown to the maximum stint, driving time of each driver against the fair share or the required minimum. |
| **Spotter** | Bars on the edges of the screen while a car is alongside, brighter when it is very close. A side flashes green ("clear") once the car is gone, and the bottom of a bar lights up while a car comes up behind on that side (`show_clear_signal`, `show_approaching_cars`). |
| **Race Notifications** | Short messages: places gained or lost (overall and class), penalty, class fastest lap, blue flag, full course yellow, invalid lap. Each type can be turned off. |
| **Tyre Temp Trend** | Surface temperature of each tyre over the last seconds or per lap, with the optimal temperature given by LMU. |

![New race aid overlays](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-nouveaux-overlays-course.png)

## Telemetry Compare

The **Telemetry Compare** overlay (off by default, `Driver Inputs` category) compares your live telemetry with the reference lap of the [Telemetry Viewer](Telemetry-Viewer.md), on track:

- Charts of speed, throttle and brake (on by default), steering and gear (off by default), over a window of distance around the car: `250` m behind and `150` m ahead by default (`distance_behind`, `distance_ahead`).
- The reference lap is drawn over the whole window, so its **next braking point shows ahead of the car**. Your current lap is drawn behind the car, up to the position mark. With the modern design, the reference lap is a soft area with a faint line, your lap a bright line.
- At the top: reference lap time, **speed difference** (green when you are faster) and **delta** to the reference lap at the same distance (red when you are slower).
- `reference_lap_source`: `Viewer` (default) uses the lap set as reference in the Telemetry Viewer for the track and class (with a double-click or the flag button), `Best` the fastest valid recorded lap, `Last` the last recorded lap. Without a lap set in the viewer, the fastest valid lap is used. The reference lap is checked again every few seconds: a new best lap, or a reference changed in the viewer, is used while you drive.
- Laps come from the [Recorder module](Telemetry-Viewer.md#lap-recording): drive a few laps first, `No reference lap` is shown until the track and class have one. The `Delta` module (on by default) keeps the charts moving smoothly between position updates of the game.

## List of overlays

Overlays are grouped by the categories of the `Overlays` page filter. Names are as shown in the app.

### Timing

| Overlay | Shows |
|---|---|
| Delta Graph | Delta along the current lap, as a graph (race aid) |
| Deltabest | Delta to your best lap; optional official delta of LMU; a dash on out laps (pit lane, back to garage) |
| Deltabest Extended | Delta against several lap time sources; session best kept when the app restarts in the same session |
| Gap Trend | Gap to cars ahead and behind, lap after lap (race aid) |
| Laps And Position | Lap number, overall position, position in class |
| Lap Time History | Recent lap times |
| Pit Stop Estimate | Estimated pit stop duration and refuelling |
| Race Plan | Next stop of the [Race Calculator](Race-Calculator.md#race-plan-overlay) plan |
| Relative | Cars around you on track, with class, tyres, pit status and gaps |
| Relative Finish Order | Estimated finish order between the leader and you, with refuelling estimate |
| Rivals | Cars ahead and behind you in your class |
| Sectors | Sector times and gaps |
| Session | Clock, session name, time left, lap, position |
| Standings | Classification with selectable columns |
| Stint History | Previous stints |
| Stint Timer | Stint time and driving time of each driver (race aid) |
| Timing | Lap times, invalid lap indicator |
| Track Clock | Time of day on track, time scale, sunlight phase |

### Tyres & Wheels

| Overlay | Shows |
|---|---|
| Friction Circle | G forces in a circle diagram |
| Slip Angle | Tyre slip angle |
| Slip Ratio | Tyre slip ratio |
| Tyre Carcass | Tyre carcass temperature |
| Tyre Deflection | Tyre vertical deflection |
| Tyre Inner Layer | Tyre inner layer temperature |
| Tyre Load | Tyre load and ratio |
| Tyre Pressure | Tyre pressure |
| Tyre Temp Trend | Tyre surface temperature over time (race aid) |
| Tyre Temperature | Tyre surface temperature; optional heatmap centered on the LMU optimal temperature |
| Tyre Wear | Tyre wear |
| Wheel Camber | Wheel camber angle |
| Wheel Toe | Wheel toe angle |

### Brakes

| Overlay | Shows |
|---|---|
| Brake Bias | Brake bias |
| Brake Performance | Braking performance |
| Brake Pressure | Brake pressure per wheel |
| Brake Temperature | Brake temperature |
| Brake Wear | Brake wear |

### Driver Inputs

| Overlay | Shows |
|---|---|
| Pedal | Pedal inputs and force feedback |
| Telemetry Compare | Speed, pedals, steering and gear against the reference lap of the Telemetry Viewer, with delta |
| Steering Angle | Steering and wheel angle |
| Steering Meter | Steering input |
| Steering Wheel | Virtual steering wheel |
| Trailing | Pedal, steering and force feedback plots |

### Engine & Energy

| Overlay | Shows |
|---|---|
| Battery | Battery usage |
| Cruise | Compass, elevation, odometer |
| DRS | DRS (rear flap) usage |
| Electric Motor | Electric motor usage |
| Engine | Engine usage; engine overheating warning of LMU |
| Engine Temperature | Engine temperatures |
| Fuel | Fuel usage, laps and minutes left, refuelling |
| Fuel Energy Saver | Fuel or virtual energy saving targets |
| Gear | Gear, RPM, speed, battery; speed limiter reminder |
| Instrument | Vehicle instruments: headlights, ignition, clutch |
| Lift And Coast LED | Lift and coast, TC and ABS activation, wheel slip and lock |
| Push To Pass | Push to pass (P2P) usage |
| RPM LED | Shift lights |
| Speedometer | Speed |
| Virtual Energy | Virtual energy usage (LMU Hypercar, LMGT3) |

### Chassis

| Overlay | Shows |
|---|---|
| Acceleration | Acceleration timing |
| Damage | Vehicle damage |
| Damage Stats | Damage figures |
| Differential | Differential locking |
| Force | G forces and downforce |
| Rake Angle | Rake angle |
| Ride Height | Ride height, front and rear axle |
| Roll Angle | Front and rear roll angle |
| Suspension Force | Suspension force and ratio |
| Suspension Position | Suspension position |
| Suspension Travel | Suspension travel |
| Weight Distribution | Weight distribution |

### Track & Traffic

| Overlay | Shows |
|---|---|
| Black Box | All-in-one view of the car, see [below](#black-box) |
| Chat | In-game chat of LMU, newest messages at the bottom |
| Elevation | Elevation profile of the track |
| Flag | Flags, pit state, warnings, start lights |
| Heading | Yaw angle, slip angle, heading |
| Navigation | Zoomed map centered on your car |
| Pace Notes | Pace notes and comments |
| Pit Lane Helper | Pit limit, speed limiter, distance to pit box (race aid) |
| Race Notifications | Short race messages (race aid) |
| Radar | Cars around you, seen from above |
| Spotter | Side bars while a car is alongside (race aid) |
| Track Map | Track map with every car |
| Track Notes | Corner and section names, notes |
| Traffic | Nearest cars closing in: slower car ahead, faster car behind |
| Weather | Weather; wind in LMU |
| Weather Forecast | Weather forecast |

### Other

| Overlay | Shows |
|---|---|
| Onboard Setting | ABS and TC levels (LMU) |
| System Performance | CPU and memory usage of the system and of the app |

Track Map, Navigation and Elevation need at least one complete, valid lap on the track: the Mapping module records the map. Brand logos (column `column_brand_logo` of Relative, Standings and Rivals, on by default and turned on once in existing presets) are the real logos of Le Mans Ultimate: the app takes them from the game running on your computer (Rest API access of `Config` > `Le Mans Ultimate API` on, the default) and keeps them in the `gameimage` folder, so they show up after the game was open once with the app. A PNG file of your own named after a brand in the `brandlogo` folder is shown instead; with rFactor 2, own files are the only logos. While a brand has no logo, its first letters are shown.

## Black box

The **Black box** is an all-in-one view of the four wheels and the car. Its modern design keeps the same layout and options, drawn in the Barlow font and the theme colors (`enable_classic_layout` brings the classic look back):

- tyres at each corner seen from above, with temperatures, pressures, wear, wheel lock and spin outlines, steering and suspension movement, without overlaps even at full lock;
- brakes, suspension, damage panel, fuel and energy gauges, battery, RPM LEDs, gear and speed;
- chips for ABS, TC, brake bias and engine map;
- an **event log and incident recorder**: contacts (with the name of the other driver, or the wall, in LMU), penalties and track limits.

In the Overlay Options page its options are in its own sections (profile, size and layout, tyres, brakes, incident recorder...), with a simple mode for the common options (`Advanced Options` shows them all), default or colorblind safe colors, and the options set by the display profile locked. Hotkeys `black_box_next_incident` (show older incidents) and `black_box_open_incident_folder` work with the incident recorder; incidents are saved in the `blackbox` folder of the global config folder. While incident file export is on, right-click the Black box (overlay unlocked) for `Open Incident Folder`.

## Widget plugins

You can add your own overlays as plugins: a folder in `plugins` (next to the app) with a `setting.json` and a `widget.py`. `Tools` > `Plugin Manager` shows their state, enables or disables them, reloads their code and installs plugins from a `.zip`. See [Widget plugins](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widget-plugins).

> [!WARNING]
> Plugins are normal Python code with full access to your computer. Only install plugins from sources you trust.
