# Connections

Modern Tiny Pedals can be driven by other programs, stream live telemetry, show a dashboard on a phone or tablet, display overlays in VR, and replay sessions without the game. Everything on this page is **off by default**.

## Remote control

Remote control lets Stream Deck, Bitfocus Companion, SimHub or any button box software run app commands through a small local HTTP server.

1. Open `Config` > `Remote Control`.
2. Turn on `enable_remote_control`. The default port is `8337` (`remote_control_port`).

The server only listens on `127.0.0.1` (this computer):

| Request | Effect |
|---|---|
| `GET http://127.0.0.1:8337/commands` | Lists the available commands (JSON) |
| `POST http://127.0.0.1:8337/command/<name>` | Runs a command. The request must include an `X-TinyPedal` header (any value) |

Commands are the same as the hotkeys: `overlay_visibility`, `overlay_lock`, `overlay_auto_hide`, `reload_preset`, `load_next_preset`, `restart_api`, `spectate_next_driver`, `cycle_deltabest_source`, `black_box_next_incident`, `preset_1` to `preset_10`, `widget_<name>` to toggle an overlay (for example `widget_relative`), `module_<name>` to toggle a module, and more. Example:

```bash
curl -X POST -H "X-TinyPedal: 1" http://127.0.0.1:8337/command/overlay_lock
```

Requests without the header, or with another host name than `127.0.0.1` or `localhost`, are refused, so web pages cannot send commands from your browser.

## WebSocket telemetry stream

With remote control on, `ws://127.0.0.1:8337/stream` pushes live telemetry as JSON: speed, gear, RPM, pedals, position, lap times, delta, fuel, tyre and brake temperatures and more (the same fields as the web dashboard).

| Parameter | Effect |
|---|---|
| `?interval=<ms>` | Push interval, `20` to `5000` ms, default `100` |
| `?fields=speed,gear,rpm` | Send only these fields |
| `?changes=1` | Send only fields that changed since the last message |

A client can change fields and changes at any time by sending a text message such as `{"fields": ["speed", "gear"], "changes": true}` (`"fields": null` for every field). Values keep base units (`km/h`, `°C`, liters); values in your units are under `display`. Browser pages must be served from `http://localhost` or `http://127.0.0.1`: other origins, local files and sandboxed frames are refused.

## Web dashboard

The web dashboard shows live data in a browser, for example on a phone or tablet next to your screen: gear, speed, RPM, delta, lap times, position, fuel (or virtual energy for LMU Hypercar and LMGT3), pedals, tyre and brake temperatures, time left. With LMU it also shows the official delta and marks invalid laps. The page uses the app language and your units.

1. Open `Config` > `Web Dashboard` and turn on `enable_web_dashboard` (port `8338` by default, `web_dashboard_port`).
2. To open it from another device, turn on `enable_lan_access`. Windows Firewall may ask you to allow the app the first time.
3. `Config` > `Web Dashboard Address...` shows the address to open, with the access code.

Security:

- An **access code** is always required (`access_code`, a random code is generated if empty). After 10 wrong codes, the device is blocked for 60 seconds. The code is exchanged for a session cookie, so it does not stay in the page address.
- Without HTTPS, traffic is plain HTTP: only enable LAN access on a network you trust.
- `enable_https` serves the dashboard over HTTPS with a self-signed certificate created in the config folder. The browser warns once about it: check the SHA-256 fingerprint shown by `Web Dashboard Address...` before accepting it.

## VR

### SteamVR overlay (experimental)

`Config` > `VR Overlay (Experimental)` > `enable_vr_overlay` shows all visible overlays, with the same layout as on your desktop, as one SteamVR overlay.

- It needs SteamVR running and the `openvr` Python package (included in the Windows release; from source: `pip install openvr`).
- `enable_attach_to_headset` makes it follow your head; otherwise it is fixed in seated space.
- `overlay_width_meters`, `distance_meters`, `vertical_offset_meters` and `horizontal_offset_meters` place it. `update_interval` sets the refresh (default `50` ms).

### VR mirror window (OpenXR games)

For OpenXR games on any runtime (Meta, Virtual Desktop, WMR...), turn on `enable_vr_mirror_window` in the same page. A desktop window shows all visible overlays as one image. Display it in your headset with a window capture tool such as OpenKneeboard, OVR Toolkit, XSOverlay or Desktop+. `mirror_background_color` sets its background; its position is remembered. Closing the window turns the mirror off until the next reload.

### VR Compatibility mode

`VR Compatibility` (tray or `Overlay` menu) shows each overlay as a separate window on the taskbar, so tools like OpenKneeboard can capture overlays one by one. Do not use it if you do not play in VR.

## Replays

### Telemetry replay

`Tools` > `Telemetry Replay` records the game's shared memory while you drive and plays it back through every overlay and module, without the game. Useful to set up overlays, test settings, or review an incident.

- `Start Recording` / `Stop Recording` while in game, or turn on `enable_auto_replay_recording` in the Recorder module to record each time you drive (`number_of_saved_replays` automatic recordings kept, default `20`; manual recordings are never removed).
- Recordings are `.tpreplay` files in the `telemetry` folder (about 7 MB per minute). REST API data of LMU is recorded too.
- Double-click a replay (or `Open Replay...`) to play it: the app reads from the file until you click `Back to Game`.
- Play, pause, speed, loop, position slider with lap changes and incidents, `Go to lap`, `◀ Incident` / `Incident ▶`, frame by frame. Keys: `Space` play / pause, `Left` / `Right` 5 seconds, `Shift` + `Left` / `Right` one frame.
- `Set Start`, `Set End` and `Save Section...` save part of a replay to a new file, for example to share an incident.

The telemetry viewer can open the replay at the cursor position (`Open Replay Here`) when a replay covers that lap.

### Game replays (Le Mans Ultimate)

`Tools` > `Game Replays` controls replays saved by Le Mans Ultimate, through the game REST API (the game must be running). The pill at the top tells what the game is doing: not answering, in the menus, in a session, or replay open.

- **Replays**: the replays of `UserData/Replays` grouped by day (newest first), with track, session, event, time and size. Search by track or event, `All` / `Practice` / `Qualify` / `Race` filter, sort by date, size or track. `Watch` (or double-click, or `Enter`) opens one in the game, after confirmation (with a warning in a live session). `Open Folder` opens the replay folder.
- **Replay files**: `Add` copies replay files (`.Vcr`) into the game replay folder (you can also drop them on the page), with a progress bar and `Stop Copy`; a file with the same name gets a number, `Name (2)`; nothing is copied if the disk lacks space. Right-click a replay (or the `...` menu for the selected replays) to `Export` it to another folder, `Rename` it, `Protect From Deletion` (star) or `Delete` it: deleted replays go to the Windows recycle bin, after confirmation; protected ones are always kept. Select several replays with `Ctrl` + click, a range with `Shift` + click, all with `Ctrl+A`. The `...` menu also cleans the folder up: delete replays older than a number of days, keep only the latest ones, delete the temporary files (`_vcr*.tmp`) the game leaves behind. A replay open in the game cannot be deleted or renamed.
- **Replay Playback** (replay open in the game): rewind, play backwards, play / pause (`Space`), slow motion (`½`), fast forward, and every speed of the game in the `...` menu; replay time and speed (`1x`). `Lap` with previous / next goes to a lap start of the car followed by the camera; lap starts seen are marked on the timeline. In a live session: `LIVE` and the session time.
- **Camera** (in a session or a replay): camera on the previous or next car, name of the car followed by the camera, and the camera menu of the game: `Driving` (Cockpit, Swingman, Nose Camera, Bonnet Camera), `Onboard` (7 cameras fixed on the car) and `Trackside` (`Cycle All`, groups 1 to 4), the camera shown checked; the arrows step to the previous or next angle of the group shown. The eye button shows or hides the game UI: `Show / Hide Game UI` hides or shows everything for clean pictures (top bar, standings, replay bar and HUD), as a middle click in the game does (the click is sent to the game window, your mouse and the window in front are left alone); or the HUD parts one at a time (chat, car HUD, timing, MFD, track map).
- **Incidents**: contacts between cars of the session, or with a wall. The game lists a contact from both cars: they are merged into one incident (`×2` when several contacts of the same cars follow each other). Car number and class, your car marked in blue, `All` / `Cars` / `Walls` filter, `My car`, and driver chips (most incidents first) to see one driver's incidents. The export button copies the incidents shown to the clipboard or saves them as CSV. Once you leave a session, its incidents and standings stay shown (`Last Session`).
- **Timeline**: every incident on a line covering the whole session, with the replay position. Click an incident to jump to it, click anywhere else to move the replay there. Mouse wheel zooms, drag moves the zoomed part, double-click or `Whole session` shows everything again.
- **Jump to Incident** (or double-click, `Enter`, the arrows of the panel for the previous / next incident) moves the replay `Seconds Before` the incident, camera on your car if it is involved, else on the first car. Right-click an incident to choose the car or to see only one driver's incidents. In a live session the button becomes **Replay This Moment**: the replay of the session opens at that moment, and `Back to Live` returns to the session.
- **Drivers**: standings of the session or replay, by position: class position, car number, driver and car, laps, best lap (purple: fastest of its class), last lap, gap to the leader (practice & qualifying: best lap behind the best lap of the leader, as in game), pit stops, virtual energy (cars of your team only), status (garage, in pits, finished, retired) and number of incidents (click it to see that driver's incidents). Class chips show one class only, your car is highlighted, the car followed by the camera is marked. Double-click a driver (or its camera button) to put the camera on their car. Right-click: `Go to Lap...` moves the replay to the start of a lap of that car.
- **Map**: the track and pit lane of the session or replay with every car (class color and number, your car with a white ring, the car followed by the camera with a blue one); cars glide between updates. Click a car to put the camera on it. Mouse wheel zooms, drag moves, double-click shows the whole track.

The page asks the game only while it is shown, on one connection per update: every 2 seconds with a replay open, 5 seconds otherwise, 15 seconds when the game is not running; standings only while `Drivers` or `Map` is shown, while a replay is open, or when the incidents change. `Refresh` (`F5`) asks again at once. Seconds before, sort, filters, the tab shown and protected replays are kept for next time.

All options: [Remote Control](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#remote-control), [Web Dashboard](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#web-dashboard), [VR Overlay](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#vr-overlay), [Telemetry replay](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#telemetry-replay) and [Game replays](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#game-replays).
