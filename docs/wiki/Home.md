# Modern Tiny Pedals

Modern Tiny Pedals is a free, open-source telemetry overlay and analysis app for **Le Mans Ultimate** (LMU) and **rFactor 2**, on Windows and Linux. It is a modernized fork of [TinyPedal](https://github.com/TinyPedal/TinyPedal): the same data engine, with a new overlay design, a reworked interface, new tools and a lot of reliability work.

The app is built with PySide6 (Qt 6) and runs in English or French.

![86 overlays with the modern design, on a simulated race at Road Atlanta](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/images/readme_preview.png)

## Key features

- **86 configurable overlays** with a modern design (rounded panels, short labels, values colored by meaning), themes, a theme editor, and visibility per session type or pit state. The classic look is still available.
- **Race aids**: delta graph, gap trend, pit lane helper, stint timer, spotter, race notifications, tyre temperature trend.
- **Black box**: an all-in-one view of the four wheels, brakes, suspension, damage, fuel and energy, with an incident log.
- **Telemetry viewer** drawn by the graphics card: every lap is recorded and can be compared, with a racing line map, corner analysis ("where time is lost"), session pace, XY plots, MoTeC import and export.
- **Race calculator**: fuel, virtual energy and tyre strategy in one page, safety car and rain scenarios, several drivers, live race replanning, share codes.
- **Driver stats**: your lap times per track and car, compared with community LMU lap times, with progression and session history.
- **Le Mans Ultimate data**: chat overlay, game replays and contacts, official delta, invalid lap, team stints and more, read from the game REST API with nothing to configure.
- **Connections**: remote control (Stream Deck, Companion, SimHub), WebSocket telemetry stream, web dashboard for a phone or tablet, SteamVR overlay and VR mirror window, telemetry replays.
- **Reliable updates**: Windows installer, in-app updates with SHA-256 check, signed build provenance for every release file.
- **Extensible**: widget plugins and JSON language packs.

## Wiki pages

| Page | What you will find |
|---|---|
| [Installation](Installation.md) | Windows installer, moving from a portable copy, Linux, running from source, uninstalling |
| [Game Setup](Game-Setup.md) | Le Mans Ultimate and rFactor 2 setup on Windows and Linux |
| [Getting Started](Getting-Started.md) | First launch, moving overlays, layout editor, configuring overlays, hotkeys |
| [Overlays](Overlays.md) | Modern and classic design, themes, visibility, the list of all overlays, Black box |
| [Presets and Settings](Presets-and-Settings.md) | Presets, share codes, trash, backups, global config, languages |
| [Telemetry Viewer](Telemetry-Viewer.md) | Lap recording and analysis, track map viewer |
| [Race Calculator](Race-Calculator.md) | Fuel, energy and tyre strategy, live race, Race plan overlay |
| [Driver Stats](Driver-Stats.md) | Career, levels, progression, sessions |
| [Connections](Connections.md) | Remote control, WebSocket, web dashboard, VR, replays |
| [Updates and Security](Updates-and-Security.md) | In-app updates, release files, verifying downloads, reporting a vulnerability |
| [Troubleshooting](Troubleshooting.md) | FAQ: overlay not visible, game not detected, safe mode, logs, bug reports |
| [Development](Development.md) | Running from source, checks, architecture, Windows build, release process |

Every option of every overlay, module and tool is described in the [settings reference (customization.md)](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md), which is also bundled with the app.

## Links

- [Download the latest release](https://github.com/Keenny38/ModernTinyPedals/releases/latest) and [all releases](https://github.com/Keenny38/ModernTinyPedals/releases)
- [Issues](https://github.com/Keenny38/ModernTinyPedals/issues): bug reports and ideas
- [Changelog](https://github.com/Keenny38/ModernTinyPedals/blob/master/CHANGELOG.md) (English) and [CHANGELOG.fr.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/CHANGELOG.fr.md) (French)
- [Roadmap](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/ROADMAP.md)
- [Contributing](https://github.com/Keenny38/ModernTinyPedals/blob/master/CONTRIBUTING.md)
- [Security policy](https://github.com/Keenny38/ModernTinyPedals/blob/master/SECURITY.md): report vulnerabilities privately, never in a public issue
- [Upstream TinyPedal](https://github.com/TinyPedal/TinyPedal)

## License and credits

Modern Tiny Pedals is a modified version of TinyPedal, Copyright (C) 2022-2026 TinyPedal developers (see [contributors](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/contributors.md) and [NOTICE.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/NOTICE.md)).

It is free software under the [GNU GPL v3](https://github.com/Keenny38/ModernTinyPedals/blob/master/LICENSE.txt) or any later version, distributed WITHOUT ANY WARRANTY. The icon and images of the `images` folder are under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), the [Barlow](https://github.com/jpt/barlow) font under the SIL Open Font License 1.1. Third-party licenses are listed in [docs/licenses](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/licenses/THIRDPARTYNOTICES.txt).
