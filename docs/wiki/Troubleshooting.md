# Troubleshooting

Answers to common problems. If yours is not here, create a bug report (see [Report a bug](#report-a-bug)) and open an [issue](https://github.com/Keenny38/ModernTinyPedals/issues).

## Overlay not visible

Check, in this order:

1. **Display mode**: the game must run in **Borderless** or **Windowed** mode. Exclusive fullscreen hides every overlay.
2. **On track**: overlays appear only while your car is on track (`Auto Hide`, tray menu). Uncheck `Auto Hide` to see them in menus too. To place them, unlock the overlay, then right-click one > `Edit Mode`: the edit mode shows every overlay, also in menus.
3. **Game connection**: the status bar of the main window must show your game as connected. If not, see [Game not detected](#game-not-detected).
4. **Overlay turned on**: on the `Overlays` page, its switch must be on. Its `visibility_context` option may limit it to some sessions or to the pits.
5. **Off screen**: an overlay left outside every screen (monitor unplugged, preset made on another computer) is shown on the nearest screen at startup, its saved position kept (`Config` > `Compatibility` > `enable_window_position_correction`). You can also use `Tools` > `Layout Editor`, or right-click an overlay > `Move to Screen`. Positions are remembered per screen setup.
6. **Maps**: Track Map, Navigation and Elevation need one complete, valid lap of the track (recorded by the Mapping module) before they draw anything.
7. **Overlay shown but empty**: a data module it needs may be off. The `Module` page flags in orange the modules turned off that enabled overlays need: `Enable Them` turns them back on.

### Linux

- **KDE**: if overlays do not stay above the game, make sure `enable_bypass_window_manager` is on in `Config` > `Compatibility` (on by default on Linux). With it, OBS may not capture the overlays.
- **No transparency**: transparent backgrounds need window compositing. Turn on compositing in your desktop environment, or turn off `enable_translucent_background` (overlays then use `background_color_global`).
- **Wayland**: `enable_x11_platform_plugin_override` (on by default on Linux, restart needed) runs the app through X11, which avoids dragging and position issues.

### VR

Overlays on the desktop are not visible in a VR headset. Use the SteamVR overlay or the VR mirror window: see [Connections](Connections.md#vr).

## Game not detected

- **Game selected**: check the game in the `API` menu (or the status bar). `API` > `Restart API` reconnects.
- **Le Mans Ultimate**: `Settings` > `Gameplay` > `Enable Plugins` must be on in the game.
- **rFactor 2**: the shared memory plugin must be in `Bin64\Plugins`, turned on in the game, and the game restarted. If it does not appear in the game, install the `Visual C++ 2013` runtime from the game's `Support\Runtimes` folder.
- **Linux**: see the plugin notes of [Game Setup](Game-Setup.md#summary).
- **Overrides**: `enable_active_state_override` and `enable_player_index_override` (`API` > `Options`) change what is shown; turn them off unless you need them. Spectate mode also sets the player index.
- **LMU REST data missing** (chat, team stints, official delta...): `url_port` in `API` > `Options` must match `WebUI port` in the game file `UserData\player\Settings.JSON` (default `6397`). See [LMU REST API](Game-Setup.md#lmu-rest-api-automatic).

`Help` > `Widget Performance` > `Game data` shows the age of the shared memory data and the state of each REST data group: useful to see what the app receives.

## The app does not start

### Already running

"Modern Tiny Pedals is already running": only one copy runs at a time. Look for its icon in the tray (it may be hidden in the tray overflow).

### Safe mode

If a start did not finish (crash, or app killed before the window and overlays were up for a few seconds), the next start asks whether to start in **safe mode**: plugins are not loaded and overlays are not started, so you can fix the settings that caused the problem (turn off an overlay or a plugin, for example).

- The window title shows `Safe Mode`. Click `Restart Normally` in the notice, or `Window` > `Restart Modern Tiny Pedals`, to start normally again.
- You can force safe mode from the command line:

```bash
tinypedal.exe --safe-mode
```

```bash
python run.py --safe-mode
```

### Settings file locked at start

If another program (antivirus, OneDrive or another sync tool, a backup tool) holds a settings file while the app starts, the app waits up to 2 seconds for it. If the file is still locked, the app starts with default settings for that file and **never saves over it** during this session: a notice says so, and changes made in this session to that file are not kept. Restart the app once the other program released the file to get your settings back. A file that is really damaged (not valid JSON) is still backed up with a date and replaced with default settings.

## Logs

- `Help` > `Show Log` shows the log of the running app: `Save`, `Copy`, `Clear`, `Refresh`, `Auto Refresh`.
- To write the log to a file, start the app with `--log-level 2`: the log is written to `tinypedal.log` in the global config folder. The Windows executable has no console, so this is the way to keep a log there. On Linux, put permanent arguments in `~/.config/TinyPedal/launcher.conf` (see [Installation](Installation.md#install-a-launcher)).

### Command line arguments

| Argument | Effect |
|---|---|
| `-h`, `--help` | List the arguments (from source) |
| `-l`, `--log-level 0` / `1` / `2` | Warnings and errors only / all messages (default) / all messages, also to `tinypedal.log` |
| `-s`, `--single-instance 0` / `1` | Allow several copies at once / single instance (default). Driver stats are not recorded with `0`. |
| `--safe-mode` | Start without plugins and overlays |

## Report a bug

1. `Help` > `Create Bug Report...`, describe what you did, what happened and what you expected, then `Save Report...`. The ZIP contains logs, settings and system info; your user folder name, access codes, stream overlay access token and repository names are removed.
2. Open an [issue](https://github.com/Keenny38/ModernTinyPedals/issues/new): one problem per issue, with the app version (`Help` > `About`), the game, your system, the steps, and the report attached.

Many problems come from other apps or plugins: turn them off to rule them out first. Security problems must be reported privately: see [Updates and Security](Updates-and-Security.md#reporting-a-vulnerability).

## Performance

`Help` > `Widget Performance` (also in `Tools`) measures the app. Click `Enable Monitoring`, then drive a few laps:

- `Widgets`: update and paint time of each overlay;
- `App & modules`: CPU and memory of the app, its modules and the game connection;
- `Game data`: game data freshness.

To lower CPU use, turn off overlays and modules you do not use, or raise the `update_interval` of an overlay (in milliseconds). Hidden overlays are not updated. Data modules skip their work while the game sends no new data (paused replay, menus), and map overlays only redraw when cars moved. App pages hidden behind another page, in the tray or minimized stop their timers and animations.

Memory: overlays turned off and pages you have not opened take no memory (their code and widgets are loaded when used). Once the main window stays hidden in the tray (or minimized) for a minute, its pages are released and, in the tray, its graphics resources freed: everything is built again when you open the window. Keep the window in the tray while racing for the lowest memory use.

## Size and scaling

- Overlays and the window follow the Windows display scale (`enable_high_dpi_scaling`, `Scale` button of the status bar, restart needed).
- `overlay_scale` in `Config` > `Overlay Style` scales every overlay. Resize a single overlay with its corner handle while unlocked.
- Main window too large, too small or out of sight: `Window` > `Reset Window Size and Position` (or `Ctrl+K`, then type `reset window`) brings it back to its default size, centered on its screen.
- The main window cannot be made smaller than a minimum size, so pages never overlap or get cut. On a small screen, the minimum is lowered so the window still fits.

## Where files are

| Files | Windows (installed) | Linux |
|---|---|---|
| Global config: `config.json`, `shortcuts.json`, `tinypedal.log`, driver stats (`.stats`, `driver.history`), `languages`, `blackbox` | `%APPDATA%\TinyPedal` | `~/.config/TinyPedal/` |
| Presets and style presets (`settings`), `brandlogo`, `pacenotes`, `tracknotes` | Program folder, `%LOCALAPPDATA%\Programs\Modern Tiny Pedals` | `~/.config/TinyPedal/` |
| `deltabest` (delta, fuel, energy, sectors, consumption), `trackmap`, `carsetups`, `telemetry` (laps and replays) | Program folder | `~/.local/share/TinyPedal/` |

`Config` > `Open Folder` opens any of them. `Config` > `User Path` moves the data folders.

## Reset the app

- **Setup**: run `Help` > `Setup Wizard` again.
- **One preset**: create a default preset with `New` on the `Preset` page and load it, or restore a backup with `Restore`.
- **Recorded data** of the current track and class: `Overlay` > `Reset Data`.
- **A deleted preset**: `Trash` on the `Preset` page.
- **Everything**: quit the app, then **rename** (rather than delete) the global config folder and the `settings` folder. At the next start, the app creates default settings and shows the setup wizard. Rename the folders back to return to your old settings.

## Updates

- **Download refused** ("does not match its sha256 hash"): the download was corrupted or altered. Try again later, or download the setup from the [Releases page](https://github.com/Keenny38/ModernTinyPedals/releases/latest) and verify it (see [Updates and Security](Updates-and-Security.md#verifying-a-download)).
- **No `Download And Install`**: the app only installs updates itself in the Windows installed version. See [Updates and Security](Updates-and-Security.md#when-the-app-cannot-install-the-update).
- **SmartScreen warning**: see [Installation](Installation.md#smartscreen-warning).
