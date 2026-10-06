<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/icon_dark.png">
    <img src="images/icon.png" alt="Modern Tiny Pedals logo" width="112">
  </picture>
</p>

<h1 align="center">Modern Tiny Pedals</h1>

<p align="center">
  <b>Telemetry overlays and analysis tools for Le Mans Ultimate and rFactor 2</b><br>
  86 overlays with a modern design, a telemetry viewer, race strategy and driver stats.<br>
  Free and open source, in English and French.
</p>

<p align="center">
  <a href="https://github.com/Keenny38/ModernTinyPedals/releases/latest"><img src="https://img.shields.io/github/v/release/Keenny38/ModernTinyPedals?label=version&color=c9a227" alt="Latest version"></a>
  <a href="https://github.com/Keenny38/ModernTinyPedals/releases"><img src="https://img.shields.io/github/downloads/Keenny38/ModernTinyPedals/total?label=downloads" alt="Downloads"></a>
  <a href="LICENSE.txt"><img src="https://img.shields.io/badge/license-GPL%20v3-blue" alt="GPL v3 license"></a>
  <img src="https://img.shields.io/badge/platforms-Windows%20%7C%20Linux-555" alt="Windows and Linux">
</p>

<p align="center">
  <a href="https://github.com/Keenny38/ModernTinyPedals/releases/latest"><b>Download</b></a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="https://github.com/Keenny38/ModernTinyPedals/wiki">Wiki</a> ·
  <a href="CHANGELOG.md">Changelog</a> ·
  <a href="docs/ROADMAP.md">Roadmap</a>
</p>

![The 86 overlays with the new design on a simulated race at Road Atlanta](images/readme_preview.png)

Modern Tiny Pedals is a modernized version of [TinyPedal](https://github.com/TinyPedal/TinyPedal): the same solid base, with a new design, a redesigned interface, new tools and a lot of work on reliability.

> [!NOTE]
> **New in 0.21.0**: about a third less memory used (overlays and pages loaded when used, freed while the window waits in the tray). All the details in the [changelog](CHANGELOG.md).

---

## Quick start

1. **Download** `ModernTinyPedals-<version>-windows-setup.exe` from the [Releases](https://github.com/Keenny38/ModernTinyPedals/releases/latest) page and run it. No administrator rights needed: the app installs in your profile (`%LOCALAPPDATA%\Programs\Modern Tiny Pedals`).
2. **Prepare the game**: `Borderless` or `Windowed` display mode (exclusive fullscreen hides the overlay), then the setting of your game below.
3. **On first launch**, the setup wizard asks for the language, the game, the theme and the overlays to start with.
4. **Start a session**: the overlay shows up as soon as the car is on track and hides otherwise.

Then:

- **Move the overlays**: unlock the overlay (notification area icon menu > `Lock Overlay`) and drag them, or use `Tools > Layout Editor` on a screenshot of the game.
- **Configure an overlay**: `Overlays` tab of the main window, or `Ctrl+F` to search for an option by name.
- **Updates**: the app tells you about a new version, shows its release notes in your language and can download and install it (`Download And Install`).

Each release has the Windows installer (`-windows-setup.exe`, also zipped as `-setup.zip`) and the source code (`-source.zip`). The portable ZIP is no longer published: to turn an older portable copy into an installed one, install the setup into its folder, your presets and data are kept. See [Installation](https://github.com/Keenny38/ModernTinyPedals/wiki/Installation) for details and for verifying your download.

### Game setup

| Game | Windows | Linux |
|---|---|---|
| **Le Mans Ultimate** | Nothing to install. Enable `Settings > Gameplay > Enable Plugins`. | Needs a third-party plugin, see [this discussion](https://github.com/TinyPedal/TinyPedal/issues/9). |
| **rFactor 2** | [rF2SharedMemoryMapPlugin](https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin#download) plugin. | [Wine version of the plugin](https://github.com/schlegp/rF2SharedMemoryMapPlugin_Wine/blob/master/build). |

For rFactor 2: copy `rFactor2SharedMemoryMapPlugin64.dll` into `rFactor 2\Bin64\Plugins` (create the folder if it is missing), enable it in `Settings > Gameplay > Plugins`, then restart the game. If the plugin does not show up, install the `Visual C++ 2013` runtime found in the game's `Support\Runtimes` folder.

With Le Mans Ultimate, the app also reads the game's local REST API (nothing to set up): chat, contacts, replays, team stints, fuel consumption estimate, official track layouts.

---

## Features

### Overlays with a modern design

86 configurable overlays: tyres, brakes, fuel and energy, delta, timing, standings, radar, map, weather, engine, suspension, chat…

- **One rounded panel per overlay**, Barlow font, short translated labels above the values.
- **Values colored by meaning**: gain, loss, warning, best time.
- **Standings** as rows with position badge, class pill and position in class, columns of your choice.
- **Fuel and energy** with gauge and marks, **tyres and brakes** as tiles in the heatmap colors, **LEDs** as glowing dots.
- **Simplified options**: the configuration only shows what the design uses. The classic look is still available, for every overlay or just one.
- **Themes** (dark, high contrast, color-blind friendly, classic), theme editor, per-overlay theme, export and import.
- **Visibility by session** (practice, qualifying, race) and pit lane, with fade.
- **Race aids**: delta graph over the lap, gap trend ahead and behind, pit lane helper (speed limit, pit limiter, distance to the box), stint timer and driving time per driver, spotter on the screen edges, race notifications, tyre temperature trend.

![New standings design, before and after](docs/changes/2026-10-05-design-classements.png)

**Black box**: tyres, brakes, suspension, damage, fuel and energy gauges, incident log (contacts with the other driver's name, penalties, track limits) and ABS, TC, brake bias and engine map chips, with no overlap even when the wheels turn.

### Telemetry viewer

Every lap is recorded and analyzed in a GPU-drawn viewer: smooth zoom, laps grouped by session, several laps overlaid.

![Telemetry viewer: gap to reference, A and B markers, range statistics](docs/changelog/0.18.0-telemetry-viewer.png)

- **Charts**: gap to reference at the cursor, A/B markers and range statistics, computed channels (wheel slip, steering speed, fuel used), 4-wheel panels, min/max band, smoothing, animated lap playback, Live mode.
- **Track map**: official layout and track edges from the game (LMU), braking, apex, exit and outside points of each lap, off-tracks and track limits, 9 colorings (by lap, gain/loss, speed, pedals, racing line, gear, altitude, gap per corner, mini-sectors), ruler, mini-map.
- **Corners**: time, entry, minimum and exit speeds, gear, brake pressure, ideal lap, and **where the time is lost** with the reason in plain words ("Brakes 6 m earlier").
- **Session**: long run pace and lap time trend, fuel and wear of each lap. **XY**: scatter plot or histogram of any channels.
- **Tools**: search, trash with undo, lap used as delta best, open the replay at the cursor, **MoTeC `.ld`**, CSV and image export, MoTeC log import to compare with another driver's lap.
- **In-depth analysis**: values fitted to the visible part, math channels from a formula, laps aligned on braking, consistency per mini-sector, teammate laps, best lap in similar conditions, setup differences, corner report as HTML or PDF.

| Official layout, track edges and mini-sectors | Where the time is lost |
|---|---|
| ![Track map](docs/changelog/0.19.0-track-map.png) | ![Corners tab](docs/changelog/0.19.0-coaching.png) |
| **Session: long run and trend** | **XY: speed / lateral G** |
| ![Session tab](docs/changelog/0.19.0-session.png) | ![XY tab](docs/changelog/0.19.0-xy.png) |

The **track map viewer** also shows each track by sectors with the real corner numbers, the curvature and slope at each point, the altitude profile and an animated run.

### Race calculator

Fuel, energy and tyres on one page, to prepare a race and follow it live.

- **Modern page**: key figures and the strategy timeline (with the fuel in the tank) always in view, input sections that fold, tyres dragged from the stock onto the wheels of the tyre plan, values stepped with the arrow keys, and only what changes is redrawn.
- **Pit stop plan** lap by lap: full tank or just what is needed, tyres, driver, stop duration, pit window, time of each stop. Stints limited by tyre life if you want.
- **Safety car and rain scenarios**, compared with the normal plan. **Strategy comparison** with one stop less (fuel saving) or more, and the cost of saving.
- **Several drivers** with minimum and maximum driving time, balanced stints, mandatory stops, maximum stint, fuel effect.
- **Live race**: the plan for the rest of the race is recalculated every lap from the car, with the driver of each stint.
- **Team tab (LMU)**: stints of each driver of the car read from the game, teammates included.
- **Sharing**: one-line share code, export for Discord, CSV or image, plan saved per car and track.
- The **Race plan** overlay shows the next stop of the plan on track, the distance to the pit entry and the target consumption.

<p align="center"><img src="docs/changelog/0.20.0-race-calculator.png" alt="Race calculator: safety car, 2 drivers, strategy and pit stop plan" width="820"></p>

### Driver stats

Your numbers per track and per car, compared with the LMU community times (sheet by [ohne_speed](https://www.youtube.com/@ohne_speed)), with a level from Alien to Offline.

- **Level scale** of each vehicle: where your personal best, qualifying and race bests stand, and the time to find for the **next level**.
- **Progress** of your session best, session after session, next to the list of **sessions** with race results.
- **All tracks**: your career on one page, with the level of each best lap, a **daily activity calendar** and your **recent sessions**.
- **Theoretical** best lap and potential, starts, wins, podiums, retirements, consumption per 100 km.
- **Telemetry** button to open the vehicle's recorded laps in the viewer.
- **Pace and degradation per tyre compound**, consistency index, CSV / JSON export and **comparison with a friend**.

| Track: level scale, progress, sessions | All tracks: activity, recent sessions |
|---|---|
| ![Driver stats](docs/changelog/0.20.0-driver-stats.png) | ![Career](docs/changelog/0.20.0-driver-stats-career.png) |

### Le Mans Ultimate: game data

<img src="docs/changelog/0.19.0-chat.png" alt="Chat overlay" width="383" align="right">

- In-game **chat** as an overlay, handy in VR.
- **Game replays**: replays by day with search and filters, add / export / rename / protect / delete replays and clean the folder up, open in the game, playback, camera and HUD controls, drivers standings, track map with the cars, incident timeline with a jump to each incident (also from a live session).
- **Contacts** written to the Black box log, with the other driver's name.
- **Fuel consumption estimated by the game** until a lap is recorded on the track.
- **Setup name** kept with each recorded lap.
- **Allowed tyres** and **team stints** used by the race calculator.
- **In the overlays**: official delta, invalidated lap, puncture, ideal tyre temperature, sector yellow flags and full course yellow, wind, ride height, pit limiter, engine overheating.

<br clear="right">

### Interface

- Qt 6 interface in **English or French** (switch without restarting), translated option names and tooltips, **release notes in the app language**.
- **Home page**: game and current session status, overlay lock, last session, customizable quick access (tools, pages, actions) and **release notes of the installed version**.
- **Overlays page**: every overlay as a card with a preview drawn with your settings (or a compact list), search ignoring accents, category chips with counts, enable / disable the filtered overlays, start errors flagged.
- **Everything opens inside the app window**: tools, editors and settings are pages, with back navigation (`Alt+←` or the mouse back button). A page you leave closes by itself (unless it has unsaved changes), so pages never pile up. Navigation bar tools stay as you left them and come back on next start, even after a crash.
- **Customizable navigation bar**, global option search (`Ctrl+F`), live overlay preview, undo / redo in editors.
- **Layout editor** with alignment guides and snapping, global scale, positions remembered per screen setup.
- **Preset share code**: copy a preset as text, import it with a preview. **Preset trash** with undo.
- **Unsaved changes** flagged on each page, `Ctrl+S` to save, values checked as you type.
- **Telemetry replay**: record a session and replay it in every overlay, without the game.
- Gold and black or gold and white icon, following the Windows light or dark mode.

### Connections

- **Remote control** for Stream Deck, Companion or SimHub, and live telemetry stream over WebSocket.
- **Web dashboard** for phone or tablet, in your units and language, with access code and optional HTTPS.
- **VR**: experimental SteamVR overlay, and a mirror window for OpenXR games (to show in the headset with OpenKneeboard, OVR Toolkit, XSOverlay or Desktop+).

### Reliability

- Windows installer and **updates from the app**, with a check of the downloaded file (SHA-256, and signature when the installer is signed).
- Automatic backups of presets and stats, atomic file writes, automatic restart of crashed threads.
- Overlay plugins with a manager, one-click bug report, performance monitor with the game data status.
- **Light on memory**: overlays turned off and pages not opened are never loaded, and the main window frees its pages and graphics while it waits in the tray.
- **Safe mode** offered after a crash at launch (no plugins nor overlays).
- **More than 2,300 automated tests** (91% of the code covered), type checking and lint in continuous integration, the executable is started in test mode before each release.

---

## Documentation

The [wiki](https://github.com/Keenny38/ModernTinyPedals/wiki) is the user and developer guide:

| Use | Develop |
|---|---|
| [Installation](https://github.com/Keenny38/ModernTinyPedals/wiki/Installation) · [Game setup](https://github.com/Keenny38/ModernTinyPedals/wiki/Game-Setup) · [Getting started](https://github.com/Keenny38/ModernTinyPedals/wiki/Getting-Started) | [Development](https://github.com/Keenny38/ModernTinyPedals/wiki/Development): run from source, checks, architecture, Windows build, release process |
| [Overlays](https://github.com/Keenny38/ModernTinyPedals/wiki/Overlays) · [Presets and settings](https://github.com/Keenny38/ModernTinyPedals/wiki/Presets-and-Settings) | [Contributing guide](CONTRIBUTING.md) |
| [Telemetry viewer](https://github.com/Keenny38/ModernTinyPedals/wiki/Telemetry-Viewer) · [Race calculator](https://github.com/Keenny38/ModernTinyPedals/wiki/Race-Calculator) · [Driver stats](https://github.com/Keenny38/ModernTinyPedals/wiki/Driver-Stats) | [Roadmap](docs/ROADMAP.md) |
| [Connections](https://github.com/Keenny38/ModernTinyPedals/wiki/Connections) · [Updates and security](https://github.com/Keenny38/ModernTinyPedals/wiki/Updates-and-Security) · [Troubleshooting](https://github.com/Keenny38/ModernTinyPedals/wiki/Troubleshooting) | [Security policy](SECURITY.md) |

Every option is described in the [settings reference](docs/customization.md) (also bundled with the app), and what changed in each version in the [changelog](CHANGELOG.md) ([en français](CHANGELOG.fr.md)). The wiki is generated from [docs/wiki](docs/wiki): edit it there.

## Run from source

Requires [Python](https://www.python.org/) 3.11 or newer.

```bash
git clone https://github.com/Keenny38/ModernTinyPedals.git
```

```bash
cd ModernTinyPedals
```

Create a virtual environment, activate it, then install the dependencies (PySide6, psutil, cryptography):

```bash
py -3.12 -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

```bash
python run.py
```

The shared memory libraries (`pyLMUSharedMemory`, `pyRfactor2SharedMemory`) are included in the repository: no submodule to fetch. For exact tested versions, use `requirements-lock.txt`.

On **Linux**, run the app from source the same way (no executable). Needed packages: `PySide6`, `psutil`, `cryptography` and `pyxdg`. `sudo ./install.sh` installs a launcher and the `TinyPedal` command in `/usr/local/`. Settings are in `$HOME/.config/TinyPedal/` and data in `$HOME/.local/share/TinyPedal/`. See [Installation](https://github.com/Keenny38/ModernTinyPedals/wiki/Installation#linux) for distribution packages and known issues (KDE, compositing).

> The display name is "Modern Tiny Pedals", but the internal name stays `TinyPedal` (configuration folder `%APPDATA%\TinyPedal`, `tinypedal.exe`, `X-TinyPedal` remote control header), to keep existing settings and tool compatibility.

## Contributing

Report a problem or suggest an idea in the [issues](https://github.com/Keenny38/ModernTinyPedals/issues). The contribution rules (development setup, checks, project rules) are in [CONTRIBUTING.md](CONTRIBUTING.md), and what is left to do in the [roadmap](docs/ROADMAP.md). A security vulnerability is reported privately, not in an issue: see [SECURITY.md](SECURITY.md).

## License and credits

Modern Tiny Pedals is derived from [TinyPedal](https://github.com/TinyPedal/TinyPedal), Copyright (C) 2022-2026 TinyPedal developers. See [docs/contributors.md](docs/contributors.md) for the list of developers and contributors.

Free software under the [GNU GPL v3](LICENSE.txt) or any later version, distributed WITHOUT ANY WARRANTY. The icon and the images of the `images` folder are under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The [Barlow](https://github.com/jpt/barlow) font is under the SIL Open Font License 1.1 (`fonts/OFL-Barlow.txt`). Third-party software licenses are in [docs/licenses](docs/licenses/THIRDPARTYNOTICES.txt).
