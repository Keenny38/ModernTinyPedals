# Overlays

Modern Tiny Pedals has **86 overlays** (called widgets in the settings files). Turn them on and configure them on the `Overlays` page: see [Getting Started](Getting-Started.md#configure-an-overlay). Every option is described in the [settings reference](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widgets).

![Standings, before and after the modern design](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-classements.png)

## Modern design and classic layout

Every overlay except the Black box has a **modern design**:

- one rounded panel per overlay, the bundled **Barlow** font, short labels above the values, translated into the app language;
- values colored by meaning: gain, loss, warning, best time;
- standings as rows with a position badge, class pill and position in class, with selectable columns (`column_*` options of Relative, Standings and Rivals);
- fuel and energy with a gauge and markers, tyres and brakes as tiles in heatmap colors, LEDs as glowing dots.

The modern design reads fewer options than the classic layout: the config page only shows the options it uses. Display order options (`display_order_*`) apply to the modern rows and columns once you change one of them.

The **classic layout** is still available:

- for every overlay: turn off `enable_modern_style` in `Config` > `Overlay Style`;
- for one overlay: turn on its `enable_classic_layout` option (classic layout with modern colors).

Other options of `Config` > `Overlay Style` (they apply to all presets): `modern_design_font_name` (default `Barlow Semi Condensed`), `modern_font_name` (classic layout font, default `JetBrains Mono`, bundled), `corner_radius_scale`, `enable_depth_effects`, `minimum_bar_gap`, `overlay_scale` (scale of all overlays) and `enable_fade_animation`.

## Themes

`overlay_theme` in `Config` > `Overlay Style` sets the colors of all overlays:

| Theme | Use |
|---|---|
| `Modern Dark` | Default: slate neutrals, softer accent colors |
| `High Contrast` | Darker backgrounds and brighter text, for bright rooms or VR |
| `Colorblind Safe` | Okabe-Ito palette: red / green pairs become orange / blue |
| `Classic` | Original colors |

Each overlay has a `widget_theme` option: `Global` (default) follows `overlay_theme`, any other theme applies to this overlay only.

### Theme editor

`Tools` > `Overlay Theme Editor` creates your own themes:

1. `New` creates a theme from a base theme (`Based on`).
2. Double-click a color (or type a hex code) to change it. `Reset Color` restores the base color. The preview shows a few overlays with your theme.
3. `Apply` or `Save` applies the theme to every overlay using it. `Ctrl+Z` / `Ctrl+Y` undo and redo.
4. `Export` saves the selected theme to a file to share it, `Import` loads a theme shared by someone else.

Custom themes are stored in `overlay_themes.json` in the global config folder and appear in the theme lists.

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
| **Spotter** | Bars on the edges of the screen while a car is alongside, brighter when it is very close. |
| **Race Notifications** | Short messages: places gained or lost (overall and class), penalty, class fastest lap, blue flag, full course yellow, invalid lap. Each type can be turned off. |
| **Tyre Temp Trend** | Surface temperature of each tyre over the last seconds or per lap, with the optimal temperature given by LMU. |

![New race aid overlays](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-nouveaux-overlays-course.png)

## List of overlays

Overlays are grouped by the categories of the `Overlays` page filter. Names are as shown in the app.

### Timing

| Overlay | Shows |
|---|---|
| Delta Graph | Delta along the current lap, as a graph (race aid) |
| Deltabest | Delta to your best lap; optional official delta of LMU |
| Deltabest Extended | Delta against several lap time sources |
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

Track Map, Navigation and Elevation need at least one complete, valid lap on the track: the Mapping module records the map. Brand logos (column `column_brand_logo` of standings) need PNG files named after each brand in the `brandlogo` folder.

## Black box

The **Black box** is an all-in-one view of the four wheels and the car, with its own design (it has no separate modern or classic layout):

- tyres at each corner seen from above, with temperatures, pressures, wear, wheel lock and spin outlines, steering and suspension movement, without overlaps even at full lock;
- brakes, suspension, damage panel, fuel and energy gauges, battery, RPM LEDs, gear and speed;
- chips for ABS, TC, brake bias and engine map;
- an **event log and incident recorder**: contacts (with the name of the other driver, or the wall, in LMU), penalties and track limits.

Its config page is split into sections (profile, size and layout, tyres, brakes, incident recorder...) with a simple mode for the common options. Hotkeys `black_box_next_incident` (show older incidents) and `black_box_open_incident_folder` work with the incident recorder; incidents are saved in the `blackbox` folder of the global config folder. While incident file export is on, right-click the Black box (overlay unlocked) for `Open Incident Folder`.

## Widget plugins

You can add your own overlays as plugins: a folder in `plugins` (next to the app) with a `setting.json` and a `widget.py`. `Tools` > `Plugin Manager` shows their state, enables or disables them, reloads their code and installs plugins from a `.zip`. See `plugins/example_speed` and [Widget plugins](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#widget-plugins).

> [!WARNING]
> Plugins are normal Python code with full access to your computer. Only install plugins from sources you trust.
