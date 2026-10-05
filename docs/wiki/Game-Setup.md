# Game Setup

Modern Tiny Pedals reads telemetry from the game's shared memory, and for Le Mans Ultimate also from the game's local REST API. Set up your game once, then select it in the app.

## Summary

| Game | Windows | Linux |
|---|---|---|
| **Le Mans Ultimate** | Nothing to install. Turn on `Enable Plugins` in the game. | Requires a third-party plugin, see [TinyPedal discussion #9](https://github.com/TinyPedal/TinyPedal/issues/9). |
| **rFactor 2** | [rF2SharedMemoryMapPlugin](https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin#download) | [Wine version of the plugin](https://github.com/schlegp/rF2SharedMemoryMapPlugin_Wine/blob/master/build) |

## Display mode

Set the game display mode to **Borderless** or **Windowed**. In exclusive fullscreen, the game draws over every other window and the overlays are hidden.

## Select the game in the app

The [setup wizard](Getting-Started.md#first-launch) asks for your game on first launch. To change it later, open the `API` menu of the main window and select `Le Mans Ultimate` or `rFactor 2`.

- The status bar at the bottom of the main window shows the selected game and its connection state (click it to refresh). Game options are in `API` > `Options`.
- `API` > `Restart API` reconnects to the game.
- `API` > `Remember API Selection from Preset` stores the game in each preset (on by default), so a preset made for rFactor 2 selects rFactor 2 when loaded.
- `Le Mans Ultimate (legacy)` (LMU through the rFactor 2 plugin) is only listed after `API` > `Enable Legacy API Selection`. It is deprecated and not recommended.

Overlays appear once your car is on track and hide otherwise (`Auto Hide`, see [Getting Started](Getting-Started.md#when-overlays-are-shown)).

## Le Mans Ultimate

### Windows

1. In the game, open `Settings` > `Gameplay` and turn `Enable Plugins` **on**.
2. Select `Le Mans Ultimate` in the app (default on Windows).

No plugin needs to be installed: LMU has its own shared memory API.

### Linux

LMU's built-in API can be selected on Linux, but may need a third-party plugin to be readable from Linux. See [TinyPedal discussion #9](https://github.com/TinyPedal/TinyPedal/issues/9) for the current state.

### LMU REST API (automatic)

With Le Mans Ultimate, the app also reads the game's local REST API. It is enabled by default and needs no setup. It provides:

- the in-game **chat** (Chat overlay) and **contacts** between cars (Black box event log, Game Replays page);
- the **replays** saved by the game, which the Game Replays page can open and control;
- **team stints** (fuel, energy and tyre wear of each driver of your car) and the **allowed tyres** of the session, used by the [Race Calculator](Race-Calculator.md);
- the game's **fuel and energy estimate** per lap, used until a lap of the car is recorded on the track;
- the **official track layout**, track edges and pit lane, used by the [Telemetry Viewer](Telemetry-Viewer.md);
- in overlays: official delta, invalid lap, puncture, optimal tyre temperature, yellow flags per sector and full course yellow, wind, ride height, speed limiter reminder, engine overheating;
- the **setup name** loaded in the game, kept with each recorded lap.

The app only reads data. Commands are sent to the game only when you ask for them (for example opening a replay), never automatically.

If REST data does not show up, check `API` > `Options` (with `Le Mans Ultimate` selected):

- `enable_restapi_access` must be on.
- `url_port` (default `6397`) must match the `WebUI port` value of the game file `UserData\player\Settings.JSON`. This value can change in some situations.
- `enable_vehicle_info`, `enable_race_info`, `enable_garage_setup_info`, `enable_session_info` and `enable_weather_info` turn individual data groups on or off.

The performance monitor (`Help` > `Widget Performance`, `Game data` section) shows the age of the shared memory data and the state of each REST data group. Details of each option: [Le Mans Ultimate API](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#le-mans-ultimate-api).

## rFactor 2

### Windows

1. Download `rFactor2SharedMemoryMapPlugin64.dll` from the [rF2SharedMemoryMapPlugin page](https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin#download).
2. Copy it to `rFactor 2\Bin64\Plugins` (create the `Plugins` folder if it is missing).
3. In the game, open `Settings` > `Gameplay`, find the `Plugins` section and turn on `rFactor2SharedMemoryMapPlugin64.dll`.
4. Restart the game.
5. Select `rFactor 2` in the app.

If the plugin does not appear in the game (no `rFactor2SharedMemoryMapPlugin64.dll` entry in `CustomPluginVariables.JSON`), install the `Visual C++ 2013` runtime provided in the game's `Support\Runtimes` folder.

### Linux

Use the [Wine build of the plugin](https://github.com/schlegp/rF2SharedMemoryMapPlugin_Wine/blob/master/build), installed and enabled the same way.

### rFactor 2 REST API

rFactor 2 also has a REST API (port `5397` by default, `WebUI port` in `UserData\player\player.JSON`), used for garage setup, session and weather data. See [rFactor 2 API](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#rfactor-2-api).

## Auto backup of car setups

`API` > `Enable Auto Backup Car Setup` (LMU and rFactor 2) saves a copy of your car setup in the `carsetups` folder each time you leave the pit lane with a changed setup. It needs the Stats module and the `enable_restapi_access` and `enable_garage_setup_info` API options.

## Still not working?

See [Troubleshooting](Troubleshooting.md#game-not-detected).
