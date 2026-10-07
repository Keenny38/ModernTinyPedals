**Note: following guide is updated to match latest released version.**

Modern Tiny Pedals offers a wide range of customization options for `widget` and `module` controls, which can be accessed from corresponding tabs in main window.

# Global user configuration
Modern Tiny Pedals stores global user configuration in `config.json` file, which is used for none-preset specific options.

* For Windows, `config.json` is stored under `username\AppData\Roaming\TinyPedal` folder.
* For Linux, `config.json` is stored under `home/username/.config/TinyPedal` folder.

Available settings:

* `Application`, can be accessed from `Config` menu in main window, see [Application](#application) section for details.
* `Telemetry API`, can be accessed from `API` menu in main window, see [Telemetry API](#telemetry-api) section for details.
* `Compatibility`, can be accessed from `Config` menu in main window, see [Compatibility](#compatibility) section for details.
* `Overlay Style`, can be accessed from `Config` menu in main window, see [Overlay Style](#overlay-style) section for details.
* `User path`, can be accessed from `Config` menu in main window, see [User Path](#user-path) section for details.
* `Auto load preset`, can be accessed from `Preset` tab in main window, see [Preset Management](#preset-management) section for details.

Reload or Restart:

* To reload all presets, select `Reload` from `Overlay` menu in main window.
* To restart game API, select `Restart API` from `API` menu in main window.
* To restart Modern Tiny Pedals, select `Restart TinyPedal` from `Window` menu in main window.

[**`Back to Top`**](#)


# Preset management
Modern Tiny Pedals stores all customization options in `JSON` format preset files, and can be managed from `Preset` tab in main window.

All user preset files, by default, are located in `TinyPedal\settings` folder. Those `JSON` files can also be manually edited with text editor.

`Double-Click` on a preset name in `Preset` tab to load selected preset.

Click `New` button to create a new default preset.

Click `Transfer` button to transfer settings from currently loaded preset to another preset. See [Preset Transfer](#preset-transfer) section for details.

Click `Restore` button to restore preset from backups. see [Restore Backup](#restore-backup) section for details.

Click `Trash` button to restore or permanently delete deleted presets. See [Preset Trash](#preset-trash) section for details.

`Right-Click` on a preset name in `Preset` tab opens up a context menu that provides additional preset file management options:

* Lock Preset

    Lock selected preset, which prevents any changes that made through Modern Tiny Pedals from saving to locked preset file. APP `version` tag will be attached to the preset that is locked with.

    Note, this feature does not prevent user from modifying or deleting locked preset file by other means. Locked preset file info is stored in `config.lock` file in [Global User Configuration](#global-user-configuration) folder.

* Unlock Preset

    Unlock selected preset.

* Backup Preset

    Create a backup file for selected preset, which can be restored later via [Restore Backup](#restore-backup) dialog.

* Set Primary for Class

    Add primary `class` tag to selected preset, which will be auto loaded by `Auto load preset` system. Class tags and colors are defined in `classes.json` file, which can be modified in [Vehicle Class Editor](#vehicle-class-editor).

    Note, a single preset can have tags from multiple classes. Auto loading `primary class` preset (if available) always takes priority over `primary sim`.

* Set Primary for Track

    Set selected preset as primary preset for a track, which will be auto loaded by `Auto load preset` system. Track primary preset has priority over class primary preset. Tracks are listed from `tracks.json` file, which can be modified in [Track Info Editor](#track-info-editor).

* Export Package...

    Export selected preset, style presets and notes into a single `.zip` package, for sharing or backup. Packages can be imported with `Import` button in `Preset` tab. Imported presets never overwrite existing presets (renamed if needed).

* Compare with Loaded Preset

    Open [Preset Comparison](#preset-comparison) to list different options between selected preset and loaded preset.

* Clear Primary Tag

    Clear all primary tags from selected preset.

* Duplicate

    Duplicate selected preset with a new name.

* Rename

    Rename selected preset with a new name. This option is not available for locked preset.

* Delete

    Move selected preset (and its layout profiles) to [Preset Trash](#preset-trash). Primary class & track tags and preset keybindings using it are cleared. `Undo` in the message shown at bottom of window for a few seconds (or `Ctrl+Z` while preset list has focus) puts it back with its tags and keybindings. The loaded preset cannot be deleted, load another preset first. This option is not available for locked preset.

[**`Back to Top`**](#)


## Saving JSON file
Modern Tiny Pedals automatically saves setting when user makes changes to widget position, or has toggled widget visibility, auto-hide, overlay-lock, etc. Changes will only take effect after `Reload` preset, or clicked `Save` or `Apply` button in `Config` dialog, or `Restart` APP.

[**`Back to Top`**](#)


## Backup JSON file
Modern Tiny Pedals will automatically create backup file with time stamp suffix if old setting file fails to load, and new default `JSON` with same filename will be generated.

A newer released version will auto-update old setting and add new setting after loading. It may still be a good idea to manually backup files before upgrading to newer version.

### How to restore your preset from backups
The recommended way to restore your preset is by using [Restore Backup](#restore-backup) dialog, which can be accessed from `Preset` Tab.

You can also restore backups manually via file explorer:

To restore preset from backups, open `Settings` folder in file explorer, find any preset file that ended with `backup-XXXX` name in the end of file extension, and rename the file extension to `json`.

For example, if a backup file named:

    LMGT3.json.backup-2026-07-29-11-41-12-586471

Just rename it to:

    LMGT3.json

[**`Back to Top`**](#)


## Editing JSON file
Customization can be done through various configuration dialogs and menus from main window. Manual editing `JSON` file is not recommended.

[**`Back to Top`**](#)


## Restore Backup
**Restore backup dialog is used for restoring preset from backups, which can be accessed from Preset Tab**

Note, only valid backup file can be restored.

File that highlighted in red is invalid and cannot be restored.

File that highlighted in blue is style preset, which can only be restored by overwriting existing style preset. A confirmation dialog will be shown before overwriting.

To restore a backup file, select a backup file from list and click `Restore` button, then enter a new name for this restored preset.

To delete a backup file, select a backup file from list and click `Delete` button.


## Preset Trash
**Preset trash dialog lists deleted presets, which can be accessed from Preset Tab with `Trash` button**

Deleted presets are moved to `trash` folder inside presets folder (one folder per deleted preset, named by deletion time), and removed for good after `number_of_days_to_keep_deleted_presets` days (default `30`), see [Application](#application).

To restore a preset, select it and click `Restore` (or double click it). Restored preset gets its primary class & track tags and preset keybindings back, unless they were set to another preset meanwhile. If a preset with the same name was created meanwhile, restored preset is renamed (`name (2)`).

To delete a preset for good, select it and click `Delete Permanently`. `Empty Trash` deletes every preset in trash for good. Both ask for confirmation and cannot be undone.


## Preset Transfer
**Preset transfer dialog is used for transferring settings from one preset to another, which can be accessed from Preset Tab**

Note, you can only transfer settings from a currently loaded preset to another preset, this is done to ensure one-way transfer.

**A confirmation dialog will be shown before transfer.**

It is recommended to first load a preset, then unhide the preset and double-check if you wish to transfer its settings to another preset.

**For important preset, it is recommended to make a backup copy, and/or lock the preset.**

To transfer settings from currently loaded preset to another specific preset, select a preset name from preset selector on the top right. Locked presets are not available from preset selector.

To select one or more settings, select and check setting name from `Setting` list on the left side. Only selected settings will be transferred.

To select one or more option types, select and check option type name from `Option Type` list on the right side. Only selected options will be transferred.

To select or deselect all settings or option types from list, click `All` or `None` button on list header.

Option types:
- Enable State: widget or module enable state.
- Feature Toggle: widget or module feature enable state, such as `enable_XXX` or `show_XXX`.
- Update Interval: widget or module update interval and idle update interval.
- Position: widget position.
- Opacity: widget opacity.
- Layout: widget layout.
- Color: color options.
- Font: font name, font weight, font size options.
- Column Index: column index options.
- Decimal Places: decimal places options.
- Other Options: all other options that are not part of above option types.

For example, to only transfer all widgets `position` setting to another preset, select and check all settings from `Setting` list on the left side, then select only `position` from `Option Type` list on the right side, and click `Transfer` button.

[**`Back to Top`**](#)


## Brands preset
**Brands preset is used for customizing brand name that matches specific vehicle name.**

Brands preset can be customized by accessing `Vehicle brand editor` from `Tools` menu in main window. See [Vehicle Brand Editor](#vehicle-brand-editor) section for complete editing guide.

`brands.json` preset will be generated and saved in `TinyPedal\settings` folder after first time launch of the APP.

[**`Back to Top`**](#)


## Classes preset
**Classes preset is used for customizing class name and color that matches specific vehicle class.**

Classes preset can be customized by accessing `Vehicle class editor` from `Tools` menu in main window. See [Vehicle Class Editor](#vehicle-class-editor) section for complete editing guide.

`classes.json` preset will be generated and saved in `TinyPedal\settings` folder after first time launch of the APP.

[**`Back to Top`**](#)


## Brakes preset
**Brakes preset is used for customizing brake failure thickness and heatmap style that matches specific vehicle class.**

Brakes preset can be customized by accessing `Brake editor` from `Tools` menu in main window. See [Brake Editor](#brake-editor) section for complete editing guide.

`brakes.json` preset will be generated and saved in `TinyPedal\settings` folder after first time launch of the APP.

[**`Back to Top`**](#)


## Compounds preset
**Compounds preset is used for customizing tyre compound symbol and heatmap style that matches specific tyre compound.**

Compounds preset can be customized by accessing `Tyre compound editor` from `Tools` menu in main window. See [Tyre Compound Editor](#tyre-compound-editor) section for complete editing guide.

`compounds.json` preset will be generated and saved in `TinyPedal\settings` folder after first time launch of the APP.

[**`Back to Top`**](#)


## Heatmap preset
**Heatmap preset is used for customizing heatmap color that matches specific value range of telemetry data, such as brake and tyre temperature.**

Heatmap preset can be customized by accessing `Heatmap editor` from `Tools` menu in main window. See [Heatmap Editor](#heatmap-editor) section for complete editing guide.

`heatmap.json` preset will be generated and saved in `TinyPedal\settings` folder after first time launch of the APP.

[**`Back to Top`**](#)


## Tracks preset
**Tracks preset is used for storing and customizing track info for various track-related calculation.**

Tracks preset can be customized by accessing `Track info editor` from `Tools` menu in main window. See [Track Info Editor](#track-info-editor) section for complete editing guide.

Track info recording is handled by [Mapping Module](#mapping-module).

`tracks.json` preset will be generated and saved in `TinyPedal\settings` folder after first time launch of the APP.

[**`Back to Top`**](#)


## Shortcuts preset
**Shortcuts preset is used for customizing global hotkey binding.**

Shortcuts preset can be customized by accessing [Hotkey Tab](#hotkey) in main window.

`shortcuts.json` preset will be generated and saved in [Global User Configuration](#global-user-configuration) folder after first time launch of the APP.

[**`Back to Top`**](#)


# User files
Modern Tiny Pedals generates and saves user session data in specific folders defined in `User path`. Session data can be reset by accessing `Reset data` menu from `Overlay` menu in main window; or, delete data file from corresponding folder.

[**`Back to Top`**](#)


## Driver stats
Driver stats data is stored as `JSON` format (.stats extension) under [Global User Configuration](#global-user-configuration) folder. Driver stats can be viewed with [Driver Stats Viewer](#driver-stats-viewer) from `Tools` menu in main window.

Session history is stored next to it in `driver.history` file (one `JSON` line per driving stint: end time, track, vehicle, game class, session type, best lap time, valid & invalid laps, distance, driving time, finish position & state), used by viewer for last driven date and personal best progression.

Data recording is handled by [Stats Module](#stats-module).

[**`Back to Top`**](#)


## Delta best
Delta best data is stored as `CSV` format (.csv extension) under `TinyPedal\deltabest` folder (default). Those files can be opened in spreadsheet or notepad programs.

Session best and stint best laps of last session are stored as `JSON` format (.session extension) in the same folder, so they are kept when Modern Tiny Pedals restarts or preset is reloaded during the session.

Data recording is handled by [Delta Module](#delta-module).

[**`Back to Top`**](#)


## Energy delta
Energy delta data is stored as `CSV` format (.energy extension) under `TinyPedal\deltabest` folder (default). Those files can be opened in spreadsheet or notepad programs.

Data recording is handled by [Fuel Module](#fuel-module).

[**`Back to Top`**](#)


## Fuel delta
Fuel delta data is stored as `CSV` format (.fuel extension) under `TinyPedal\deltabest` folder (default). Those files can be opened in spreadsheet or notepad programs.

Data recording is handled by [Fuel Module](#fuel-module).

[**`Back to Top`**](#)


## Consumption history
Consumption history data is stored as `CSV` format (.consumption extension) under `TinyPedal\deltabest` folder (default). Those files can be opened in spreadsheet or notepad programs.

Consumption history data stores lap time, fuel consumption, battery charge, tyre wear usage data per `track and vehicle class`, which can be loaded in [Race Calculator](#race-calculator). Up to 100 most recent lap entries are saved per `track and vehicle class`. Data recording is handled by [Fuel Module](#fuel-module).

[**`Back to Top`**](#)


## Sector best
Sector best data is stored as `CSV` format (.sector extension) under `TinyPedal\deltabest` folder (default). Those files can be opened in spreadsheet or notepad programs.

Data recording is handled by [Sectors Module](#sectors-module).

[**`Back to Top`**](#)


## Track map
Track map is stored as `SVG` vector image format (.svg extension) under `TinyPedal\trackmap` folder (default). Track map can be viewed with [Track Map Viewer](#track-map-viewer) from `Tools` menu in main window.

Data recording is handled by [Mapping Module](#mapping-module).

The SVG vector map data contains two coordinate paths:
* First is global x,y position path, used for drawing track map.
* Second is corresponding track distance and elevation path, used for drawing elevation plot.

Each sector position index is also stored in SVG file for finding sector coordinates.

[**`Back to Top`**](#)


## Pace notes
`TinyPedal Pace Notes` data is stored as `TPPN` format (.tppn extension) under `TinyPedal\pacenotes` folder (default). Pace notes can be created or edited with [Track Notes Editor](#track-notes-editor) from `Tools` menu in main window.

Pace notes data is mainly used for [Pace Notes Playback](#pace-notes-playback) for specific tracks.

To allow `auto notes loading` function to work, pace notes file name must match same track map file name.

[**`Back to Top`**](#)


## Track notes
`TinyPedal Track Notes` data is stored as `TPTN` format (.tptn extension) under `TinyPedal\tracknotes` folder (default). Track notes can be created or edited with [Track Notes Editor](#track-notes-editor) from `Tools` menu in main window.

Track notes data is mainly used for displaying corner and section names for specific tracks, or providing additional info at specific track location while driving.

To allow `auto notes loading` function to work, track notes file name must match same track map file name.

[**`Back to Top`**](#)


## Tyre strategy
`TinyPedal Tyre Strategy` file is stored as `JSON` format (.tyre-strategy extension). Tyre strategy file can be created or edited in the tyre tab of [Race Calculator](#race-calculator).

[**`Back to Top`**](#)


## Brand logo
Modern Tiny Pedals supports user-defined brand logo image in `PNG` format (.png extension) which is placed under `TinyPedal\brandlogo` folder (default).

With Le Mans Ultimate, real car brand logos, circuit logos, car pictures and circuit pictures are taken from the game itself: the app asks them to the game running on your computer (its local web server, same address as the [Le Mans Ultimate API](#le-mans-ultimate-api) Rest API access, which must be enabled) and keeps them in the `game_image_path` folder, so they are shown everywhere (brand logo column of Relative, Standings & Rivals, Home, Race Results, Driver Stats, Spectate, Replays, Race Calculator, Telemetry Viewer, Track Map Viewer and stream overlay of race results), also while the game is not running. Nothing is shipped with the app. A brand logo of your own in the brand logo folder is always shown first; its file name may be one word of a longer brand name (`Corvette.png` for `Chevrolet Corvette`, `Ford.png` for `Ford Mustang`). Logos too close to the background color are shown with a readable copy (kept in `game_image_path`): black logos get light on dark overlays and pages, white logos get dark on light themes, colored parts are kept.

Note: Modern Tiny Pedals does not provide brand logo image assets, it is up to user to prepare images (or to run Le Mans Ultimate once with the app open, see above). Maximum `PNG` file size is limited to `5MB`.

How to prepare brand logo image:
1. Brand logo image should have all transparent borders cropped. For example, in `GIMP` this can be done by selecting `Image` > `Crop to Content`.
2. Make sure image dimension is not too big, usually around 100 pixel width or height is good enough. Bigger dimension may consume more RAM or exceed maximum supported file size.
3. Save image to `TinyPedal\brandlogo` folder, image filename must match corresponding `brand name` that defined in [Vehicle Brand Editor](#vehicle-brand-editor). For cross-platform compatibility, filename matching is set to be case-sensitive, make sure filename has the same upper or lower case as set in `brand name`.
4. `Reload` preset to load newly added brand logo images for displaying in overlay (logos of the game show up by themselves once fetched).

[**`Back to Top`**](#)


## Car setup
Car setup files for specific games are stored under `TinyPedal\carsetups` folder (default). Those files are auto generated backups via `Auto Backup Car Setup` function.

See [Telemetry API](#telemetry-api) section for details about `Auto Backup Car Setup` function.

[**`Back to Top`**](#)


# Command line arguments
**Command line arguments can be passed to script or executable to enable additional features.**

    -h, --help
List all available command line arguments.

Usage: `python .\run.py -h`

Note, the Windows executable (`tinypedal.exe`) is a windowed app without console: arguments work the same, but nothing is printed. Use `--log-level 2` to write log to file, or the `Show Log` dialog.

    -l, --log-level
Set logging output level. Supported values are:
  * `--log-level 0` outputs only warning or error log to `console`.
  * `--log-level 1` outputs all log to `console`.
  * `--log-level 2` outputs all log to both `console` and `tinypedal.log` file.

Log location:
  * On windows, `tinypedal.log` is located under `username\AppData\Roaming\TinyPedal` folder.
  * On Linux, `tinypedal.log` is located under `home/username/.config/TinyPedal` folder.

Default logging output level is set on `1` if argument is not set.

Usage: `python .\run.py -l 2` or `.\tinypedal.exe --log-level 2`

    -s, --single-instance
Set running mode. `0` allows running multiple instances (copies) of Modern Tiny Pedals. `1` allows only single instance (default).

To run multiple copies of Modern Tiny Pedals at same time: `python .\run.py -s 0` or `.\tinypedal.exe --single-instance 0`

Single instance mode saves `pid.log` file in the same folder as `tinypedal.log`, which is used for instance identification.

    --safe-mode
Start in safe mode: plugins are not loaded, overlays (widgets & VR overlay) are not started, so settings can be fixed in the main window (a widget can still be turned on by hand). Window title and a notice show safe mode; `Restart Normally` in the notice, or `Restart Modern Tiny Pedals` in `Window` menu, starts normally again.

Usage: `python .\run.py --safe-mode` or `.\tinypedal.exe --safe-mode`

When a start did not finish (crash or app killed before the main window and overlays were up for a few seconds), the next start asks whether to start in safe mode. A `startup.marker` file is kept in the same folder as `tinypedal.log` while starting, and removed once started or when quitting; a normal start never asks.

[**`Back to Top`**](#)


## Console Log
**Console log can be accessed in `Show Log` dialog from `Help` menu in main window.**

To save all log, click `Save` button.

To copy all log to clipboard, click `Copy` button.

To clear all log, click `Clear` button.

To refresh log, click `Refresh` button.

To enable auto-refreshing, toggle on `Auto Refresh` check box.

[**`Back to Top`**](#)


# Telemetry API
**Telemetry API options can be accessed from `API` menu in main window.**

See [Réglage du jeu](../README.md#réglage-du-jeu) section of README for list of supported API and setup info.

    api_name
Set API name for accessing data from supported API.

    enable_api_selection_from_preset
Set `true` to remember and load API selection from preset; set `false` to select API globally for all presets.

    enable_legacy_api_selection
Enable legacy API selection. This option is disabled by default.

Important note, legacy APIs are deprecated and no longer maintained or supported, and will be removed in the future. It is not recommended to use them.

    enable_auto_backup_car_setup
Enable `Auto Backup Car Setup` function, currently support `LMU` and `RF2`.

This option allows to auto backup [Car Setup](#car-setup) file whenever exits pit lane with new adjustment to setup, which can be handy in various situations, especially in the event such as unexpectedly disconnected from server.

To allow `Auto Backup Car Setup` function to work, following additional options must be enabled:
- `Stats Module` from `Module` tab.
- `Enable RestAPI Access` & `Enable Garage Setup Info` from `API` option dialog.

Additional notes:
- Auto backup car setup function is disabled while in `spectate mode` or `state overriding`, or not running in `single instance mode`.
- Backup file is only generated after leaving pit lane. Stint best lap time (if available) will be auto-appended to backup file name after back to garage.
- Only one backup file of the most recent setup will be generated if no changes were made.
- Backup file name format:\
    `[game name]` - `[date & time]` - `[track name]` - `[class name]` - `[brand name]` - `[stint best lap time]`\
    **If brand name is not available, vehicle name will be used instead.*

[**`Back to Top`**](#)


## Le Mans Ultimate API
**Le Mans Ultimate API options can be accessed from `Options` while this API is enabled in `API` menu in main window.**

    access_mode
Set access mode for API. Mode value `0` uses copy access and additional data check to avoid data desynchronized or interruption issues. Mode value `1` uses direct access, which may result data desynchronized or interruption issues. Default mode is copy access.

    enable_active_state_override
Set `true` to enable `active state` manual override. While enabled, `overriding` notification will be shown on API status bar from main window.

    active_state
This option overrides local player on-track status check, and updates or stops overlay and data processing accordingly. Set `true` to activate state. Set `false` to deactivate state. This option works only when `enable_active_state_override` enabled.

    enable_player_index_override
Set `true` to enable `player index` manual override.

    player_index
Set `player index` override for displaying data from specific player. Set value to `-1` for unspecified player.

Note, this option works only when `enable_player_index_override` enabled. This option is automatically set while [Spectate Mode](#spectate-mode) enabled, and should not be set manually.

    character_encoding
Set character encoding for displaying text in correct encoding. Available encoding: `UTF-8`, `ISO-8859-1`. Default encoding is `UTF-8`.

    enable_restapi_access
Enable Rest API accessing, which connects to game's Rest API for accessing additional data that is not available through sharedmemory API.

    restapi_update_interval
Set update interval (in milliseconds) for requesting data from Rest API.

Note, minimum update interval is hard-limited to `200` milliseconds or higher, and some data are accessed `only once` per garage-exit. Update interval is auto-delayed up to `5` seconds if has not received new data recently. See individual data description for details.

    url_host
Set Rest API host address. Host address must match `WebUI bind` value that sets in `LMU` (UserData\player\Settings.JSON) setting file in order to successfully connect to Rest API and receive data. The default host value for `LMU` is `localhost`, which is equivalent to `127.0.0.1`.

    url_port
Set port for Rest API host address. Port value must match `WebUI port` value that sets in `LMU` (UserData\player\Settings.JSON) setting file in order to successfully connect to Rest API and receive data. The default port value for `LMU` is `6397`.

Note, `WebUI port` value from game setting file may change in some situations, and would require manual correction to match `WebUI port` value.

    connection_timeout
Set connection timeout duration in seconds for Rest API. Value range in `0.5` to `10`. Default is `1` second.

    connection_retry
Set number of attempts to retry connection for Rest API. Value range in `0` to `10`. Default is `3` retries.

    connection_retry_delay
Set time delay in seconds to retry connection for Rest API. Value range in `0` to `60`. Default is `1` second.

    enable_garage_setup_info
Enable access to `garage setup` data from Rest API. This is required for accessing various vehicle setup data, and the name of the setup loaded in game (LMU), recorded with each lap for [Lap telemetry viewer](#lap-telemetry-viewer). This data is requested `only once` when player exited garage each time.

    enable_session_info
Enable access to `session` data from Rest API. This is required for accessing various session data, such as time-scale. This data is requested `only once` when player exited garage each time.

    enable_vehicle_info
Enable access to `vehicle` data from Rest API. This is essential for accessing `brake wear`, `vehicle damage`, `pit stop timing` data, and the game estimate of `fuel & energy per lap` (used until a lap of the car & track is recorded). Minimum request interval is hard-limited to `0.2` second (5 requests per second) for this data.

    enable_weather_info
Enable access to `weather` data from Rest API. This is required for showing weather forecast. This data is requested `only once` when player exited garage each time.

    enable_race_info
Enable access to `race` data from Rest API (LMU): chat messages for [Chat](#chat) widget, contacts between cars for contact events of [Black box](#black-box) event log, pit lane entry for [Race plan](#race-plan) widget. Requested while driving, again only when data changes.

[**`Back to Top`**](#)


## rFactor 2 API
**rFactor 2 API options can be accessed from `Options` while this API is enabled in `API` menu in main window.**

    access_mode
Set access mode for API. Mode value `0` uses copy access and additional data check to avoid data desynchronized or interruption issues. Mode value `1` uses direct access, which may result data desynchronized or interruption issues. Default mode is copy access.

    process_id
Set process ID string for accessing API from server. This option is for server use only.

    enable_active_state_override
Set `true` to enable `active state` manual override. While enabled, `overriding` notification will be shown on API status bar from main window.

    active_state
This option overrides local player on-track status check, and updates or stops overlay and data processing accordingly. Set `true` to activate state. Set `false` to deactivate state. This option works only when `enable_active_state_override` enabled.

    enable_player_index_override
Set `true` to enable `player index` manual override.

    player_index
Set `player index` override for displaying data from specific player. Valid player index range starts from `0` to maximum number players minus one, and must not exceed `127`. Set value to `-1` for unspecified player, which can be useful for display general standings and trackmap data (ex. broadcasting). This option works only when `enable_player_index_override` enabled.

    character_encoding
Set character encoding for displaying text in correct encoding. Available encoding: `UTF-8`, `ISO-8859-1`. Default encoding is `UTF-8`. Note, `UTF-8` may not work well for some Latin characters in `RF2`, try use `ISO-8859-1` instead.

    enable_restapi_access
Enable Rest API accessing, which connects to game's Rest API for accessing additional data that is not available through sharedmemory API.

    restapi_update_interval
Set update interval (in milliseconds) for requesting data from Rest API.

Note, minimum update interval is hard-limited to `200` milliseconds or higher, and some data are accessed `only once` per garage-exit. Update interval is auto-delayed up to `5` seconds if has not received new data recently. See individual data description for details.

    url_host
Set Rest API host address. The default host value for `RF2` is `localhost`, which is equivalent to `127.0.0.1`.

    url_port
Set port for Rest API host address. Port value must match `WebUI port` value that sets in `RF2` (UserData\player\player.JSON) setting file in order to successfully connect to Rest API and receive data. The default port value for `RF2` is `5397`.

Note, `WebUI port` value from game setting file may change in some situations, and would require manual correction to match `WebUI port` value.

    connection_timeout
Set connection timeout duration in seconds for Rest API. Value range in `0.5` to `10`. Default is `1` second.

    connection_retry
Set number of attempts to retry connection for Rest API. Value range in `0` to `10`. Default is `3` retries.

    connection_retry_delay
Set time delay in seconds to retry connection for Rest API. Value range in `0` to `60`. Default is `1` second.

    enable_garage_setup_info
Enable access to `garage setup` data from Rest API. This is required for accessing various vehicle setup data. This data is requested `only once` when player exited garage each time.

    enable_session_info
Enable access to `session` data from Rest API. This is required for accessing various session data, such as time-scale. This data is requested `only once` when player exited garage each time.

    enable_weather_info
Enable access to `weather` data from Rest API. This is required for showing weather forecast. This data is requested `only once` when player exited garage each time.

[**`Back to Top`**](#)


# General options
**General options can be accessed from main window menu.**

[**`Back to Top`**](#)


## Common terms and keywords
**These are the commonly used setting terms and keywords.**

    enable
Check whether a widget or module will be loaded at startup.

    update_interval
Set refresh rate for widget or module in milliseconds. A value of `20` means refreshing every 20ms, which equals 50fps. Since most data from sharedmemory plugin is capped at 50fps, and most operation system has a roughly 15ms minimum sleep time, setting value less than `10` has no benefit, and extreme low value may result significant increase of CPU usage.

    idle_update_interval
Set refresh rate for module while idling for conserving resources.

    position_x, position_y
Define widget position on screen in pixels. Those values will be auto updated and saved.

    enable_classic_layout
Every widget has a modern design, used with `Modern Dark` and `Modern Light` overlay themes. Enable this option to keep classic layout of this widget (with modern colors) instead. Default is disabled.

    opacity
Set opacity for entire widget. By default, all widgets have a 90% opacity setting, which equals value `0.9`. Lower value adds more transparency to widget. Acceptable value range in `0.0` to `1.0`. Note, opacity can also be set by adjusting alpha value in `color` options for individual elements.

    stream_visibility
Where the widget is shown when [Stream Overlay](#stream-overlay) is enabled: `Screen & Stream` (default), `Stream Only` (window fully transparent on screen while widgets are locked, still sent to streaming software; visible while unlocked, to move it), or `Screen Only` (never sent to streaming software). Can also be set for every widget from `Stream Overlays` page.

    bar_gap, inner_gap
Set gap (screen pixel) between elements in a widget, only accept integer, `1` = 1 pixel.

    font_name
Select a font to be displayed in widget. Mono type font is highly recommended.

Note, selected font must be already installed in operation system; if not, manually install required font. Default fallback font will be used if font is not found or installed in operation system.

    font_size
Set font size in pixel, increase or decrease font size will also apply to widget size.

    font_weight
Acceptable values: `Thin`, `Extra Light`, `Light`, `Normal`, `Medium`, `Semi Bold`, `Bold`, `Extra Bold`, `Black`.

Note, not every weight may be available for selected font.

    enable_auto_font_offset
Automatically adjust font vertical offset based on font geometry for better vertical alignment, and should give good result in most case. This option is enabled by default, and only available to certain widgets. Set `false` to disable.

    font_offset_vertical
Manually set font vertical offset. Default is `0`. Negative value will offset font upward, and position value for downward. This option only takes effect when `enable_auto_font_offset` is set to `false`.

    *_offset_x, *_offset_y
Set text offset position (percentage), value range in `0.0` to `1.0`.

    bar_padding
Set widget edge padding value that multiplies and scales with `font_size`. Default is `0.2` for most widgets. Increase padding value will further increase each element width in widget.

    color
Set color in hexadecimal color codes with alpha value (opacity). The color code format starts with `#`, then follows by two-digit hexadecimal numbers for each channel in the order of `alpha`, `red`, `green`, `blue`. Note, `alpha` is optional and can be omitted. User can select a new color without manual editing, by double-clicking on color entry box in `Config` dialog.

    text_alignment
Set text alignment. Acceptable value: `Left`, `Center`, `Right`.

    prefix
Set prefix text that displayed beside corresponding data. Set to `""` to hide prefix text.

    show_caption
Show short caption description on widget.

    display_order
Set display order of each info column or row.

    decimal_places
Set amount decimal places to keep.

[**`Back to Top`**](#)


## Application
**Application options can be accessed from `Config` and `Window` menu in main window.**

Tools, editors and config dialogs opened from main window (tools page, navigation bar, menus, widget gear button) are shown as pages inside main window, with title and `Close` button on top, scrolled when larger than the window. Closing one goes back to previous page. Opening one already open shows its page again. Tools of the navigation bar are pages like `Overlays` or `Module`: their entry is selected while shown, no `Close` button (neither on top nor in the tool), and they are kept as left when coming back. Other pages (config dialogs, tools outside the bar) are closed once left for another page, so they never pile up: only pages with unsaved changes stay open behind (closing them would ask to save), and a page stays open while a page opened from it (input, lap library) is shown. Those are listed by the open pages button at bottom of the bar (shown while any page is kept behind the shown one), with `Close All`. `Esc` closes pages that have a `Close` button only. `Alt+Left` or mouse back button shows the page shown before (again to go further back). When a page needs more room, main window grows to fit it (within screen): size is kept while browsing other pages, and restored once every page needing it is closed (unless window was resized meanwhile). Changing language keeps open config pages and pages with unsaved changes as they are, tool pages are reopened translated. Inputs (preset name, key binding, share code, theme name) are pages too, also when opened from a tool page (back to it when done). Other dialogs opened from a tool (offset, replace, notes info), confirmations and file selection stay small popups. Tool page shown and navigation bar tools left open at quit (or restart, or language change) are opened again at next startup, see `remember_open_pages`.

Pages with unsaved changes (editors, config dialogs, notes, theme editor) show a dot (`•`) before their title, on their navigation bar entry, and in the open pages menu (the open pages button dot changes to warning color). The dot clears once changes are saved or undone. `Ctrl+S` saves the page shown (like `Apply`: page kept open; track notes ask for a file name), on pages that have something to save.

Config dialogs check values while typing: an invalid value (not a number, decimal where a whole number is needed, out of range such as opacity above `1` or port above `65535`, invalid color or clock format, missing image file) is outlined in red with a short reason next to it, and `Apply` & `Save` are disabled until it is fixed (saving with `Ctrl+S` or when closing shows the first invalid option). Folder paths are checked when saving.

    show_at_startup
Show main window at startup, otherwise hides to tray icon.

    check_for_updates_on_startup
Enable automatically checking for updates on startup, and display notification message in main window. This option is enabled by default.

Click on the notification message will bring up a menu, where user can click `View Updates On GitHub` to open `Latest Releases` page in web browser, show what is new in the update (release notes page), or `Dismiss` the message.

Note, this option is checked only once per startup, and notification message will only be displayed if new updates is available. If main window is hidden in tray at startup, a tray message is shown instead of opening the window over the game.

With the Windows installer version, notification menu also offers `Download And Install`, which downloads the setup ZIP of the new version, checks its SHA256 hash (detects a corrupt download; the hash comes from the same release page, so it does not prove who published the file), extracts the installer, checks its digital signature when the installer is signed (an invalid signature is refused), then installs it. A portable copy (ZIP published until version 0.19) opens the release page instead, as the installer would install a separate copy without your presets and data: install the setup into the folder of the portable copy to keep them, later updates then install from the app. What's new notes are shown in the app language when translated (French), in English otherwise.

While downloading, notification message and what's new page show progress (percent and size), and `Cancel Download` (notification menu, or what's new page) stops it, partial download removed.

`Skip This Version` (notification menu, or what's new page) hides the notice of this version: it is not shown again at startup, a newer version is. `Check for Updates` from `Help` menu still shows it. See `skipped_update_version`.

User can also manually check for updates any time by accessing `Check for Updates` option from `Help` menu in main window.

    minimize_to_tray
Minimize to tray when user clicks `X` close button.

    remember_position
Remember main window last position.

    remember_size
Remember main window last size, and whether it was maximized.

    enable_high_dpi_scaling
Enable window dialog and overlay widget auto-scaling under high DPI screen resolution. This option requires restarting Modern Tiny Pedals to take effect. This option is enabled by default.

High DPI scaling mode can be quickly toggled via `Scale` button on main window status bar.

On Windows, scaling is determined by percentage value set in `Display` > `Scale and Layout` setting. For example, `200%` scale in windows setting will double the size of main window dialog and also every widget.

On Linux, DPI scaling may already be forced `ON` in some system, which this option may not have effect.

    enable_auto_load_preset
Enable `Auto load preset` system to allow auto loading user-defined game-specific preset depends on active game (currently supports `RF2` and `LMU`).

Auto loading preset is triggered when a new or different game is started and active. Auto loading will only trigger once per game change. A preset must be tagged as `primary` for specific game before it can be auto loaded. See [Preset Management](#preset-management) section for details.

This option is disabled by default.

    enable_global_hotkey
Enable `Global Hotkey` support. This option can be toggled from [Hotkey Tab](#hotkey) in main window.

    show_option_group_title
Show option group title in `Config` dialog.

    show_confirmation_for_batch_toggle
Show confirmation dialog for enabling or disabling all widgets or modules. This option is enabled by default.

    show_overlay_previews
Show overlays on `Overlays` page as cards with a preview of each overlay, or as a compact list with the preview in a tooltip if disabled. Also switched by the view buttons at top right of `Overlays` page. Previews are drawn only while the page is shown. This option is enabled by default.

    enable_edit_mode_on_unlock
Start the edit mode when overlays are unlocked: toolbar (snapping, grid, guides, undo, `Done` locks overlays again), every overlay outlined, auto hidden overlays shown. Disabled: unlocking only makes overlays movable, the outline and resize handle of an overlay show when the mouse is over it; drag it to move it, arrow keys and `Ctrl+Z` still work, and the edit mode can still be started from the right-click menu of an overlay (`Edit Mode`). Default is disabled.

    enable_magnetic_snap
Snap overlays while dragging them (`Snap` button of the edit mode toolbar): their edges and center line up with screen edges, screen center and other overlays. Hold `Ctrl` to move freely, `Shift` to keep the move horizontal or vertical. Disabled: overlays move freely, hold `Ctrl` to snap. Default is enabled.

    snap_distance
The distance (in pixels) at which the overlay snaps to screen edges, screen center and edges or centers of other overlays. Default `10`. See `enable_magnetic_snap`.

    snap_gap
The gap (in pixels) to leave between the widget and the snapped widget edges. Default `0`.

    grid_move_size
Set grid size for grid move, value in pixel. Default is `8` pixel. Minimum value is limited to `1`.

    minimum_update_interval
Set minimum refresh rate limit for widget and module in milliseconds. This option is used for preventing extremely low refresh rate that may cause performance issues in case user incorrectly sets `update_interval` and `idle_update_interval` values. Default value is `10`, and should not be modified.

    maximum_loading_attempts
Set maximum retry attempts for preset loading. Default value is `5`. Minimum value is limited to `1` maximum attempt.

Note, each attempt has a roughly 50ms delay. If all loading attempts failed, a backup copy will be created in `settings` folder, and preset will be reset to default. See [How to restore your preset from backups](#how-to-restore-your-preset-from-backups) for details.

This option does not affect global config preset, which always has `5` maximum loading attempts.

    maximum_saving_attempts
Set maximum retry attempts for preset saving. Default value is `10`. Minimum value is limited to `3` maximum attempts.

Note, each attempt has a roughly 50ms delay. If all saving attempts failed, saving will be aborted, and old preset file will be restored to avoid preset file corruption.

    position_x, position_y
Define main window position on screen in pixels. Those values will be auto updated and saved while `remember_position` option is enabled.

    window_width, window_height
Define main window size on screen in pixels. Those values will be auto updated and saved while `remember_size` option is enabled.

    window_maximized
Whether main window was maximized at last quit, shown maximized again at startup. This value will be auto updated and saved while `remember_size` option is enabled.

    window_color_theme
Set color theme for main window and dialog: `Modern Dark` (default), `Modern Light`, `Legacy Dark` or `Legacy Light` (colors of TinyPedal 2.50). This option does not affect overlay widget, see `overlay_theme` in Overlay Style.

Color theme can be quickly toggled via `UI` button on main window status bar.

    language
Set user interface language: `English` or `Français`. Main window, menus and dialogs are rebuilt immediately after saving, no restart needed. Option names and descriptions (tooltips) in config dialogs are also translated.

    show_setup_wizard_at_startup
Show setup wizard at next startup. The wizard asks for language, game, units, window & overlay theme, starting preset and overlays. It is shown once on first launch, and can be opened any time from `Help` menu.

    update_repository
Set GitHub repository (`owner/name`) used by `Check for Updates`. Empty value disables update checks. Default is `Keenny38/ModernTinyPedals` (this fork), so updates never offer the upstream releases.

    number_of_automatic_backups
Set number of automatic backups kept per preset file. A backup is created before saving a preset, at most once every 10 minutes. Backups can be restored from `Restore Backup` dialog. Set `0` to disable. Default is `10`.

    number_of_days_to_keep_deleted_presets
Set number of days deleted presets are kept in preset trash (`trash` folder inside presets folder), where they can be restored from `Trash` button of `Preset` tab. Older ones are removed for good (checked at startup and when deleting a preset). Value range is `1` to `3650`. Default is `30`.

    skipped_update_version
Update version hidden by `Skip This Version` (kept by app, not shown in config dialog): its notice is not shown again at startup, a newer version is. Stored as one number (major * 1000000 + minor * 1000 + patch), `0` if none.

    rail_items
Entries of the navigation bar of main window, in order, separated by comma: pages (`home`, `widget`, `module`, `preset`, `spectate`, `pacenotes`, `hotkey`, `tools`) and tools (dialog module name, for example `lap_viewer`, `driver_stats_viewer`, `race_calculator`; former `fuel_calculator` & `tyre_strategy_planner` entries open race calculator). Easier to set by right-clicking the navigation bar, `Customize Navigation Bar...`: check entries to show, drag or `Up` / `Down` to reorder, `Reset` for default. `Ctrl+1` to `Ctrl+9` open the first 9 entries. Entries keep their size: when window is too short, they scroll (mouse wheel or thin scroll bar) above the quick buttons, selected entry scrolled into view, a fade with an arrow shows that entries are hidden above or below. Pages left out stay in command palette (`Ctrl+K`). Default: Home, Overlays, Driver Stats Viewer, Race Results, Game Replays, Telemetry, Spectate, Race Calculator and Preset (`home,widget,driver_stats_viewer,race_results_viewer,game_replays,lap_viewer,spectate,race_calculator,preset`). Existing configs were set to this default once, by the update that introduced it (setting version 2.50.3).

    home_quick_access
Quick access buttons of home page, in order, separated by comma: tools (dialog module name, for example `lap_viewer`, `race_calculator`), pages (`widget`, `module`, `preset`, `spectate`, `pacenotes`, `hotkey`, `tools`) and actions (`command_palette`, `bug_report`, `check_updates`). Easier to set with `Customize...` next to `Quick Access` on home page (or right-click the buttons): check entries to show, drag or `Up` / `Down` to reorder, `Reset` for default. Empty: no quick access button. Default: Telemetry viewer, Race calculator, Driver stats viewer, Layout editor, Widget performance, Game replays, then the Overlays, Module, Preset, Spectate, Hotkey and Tools pages, Config, then Create bug report and Check for updates (`lap_viewer,race_calculator,driver_stats_viewer,layout_editor,perf_view,game_replays,widget,module,preset,spectate,hotkey,tools,app_settings,bug_report,check_updates`). Existing configs were set to this default once, by the update that introduced it (setting version 2.50.3).

    remember_open_pages
Reopen tool pages left open at quit or restart (navigation bar tools like race calculator or telemetry viewer, and tool page shown last, shown again) (saved as soon as it is shown, so a crash or a system shutdown keeps it too). Pages are reopened once main window is shown, so startup is not slowed down. Config dialogs are not reopened. Also in `Window` menu, `Reopen Pages at Startup`. Default is enabled.

    show_layout_guides
Show alignment guides (grid, lines where edges or centers line up with other overlays or screen center) and the position of the overlay while dragging it (`Guides` button of the edit mode toolbar). Default is enabled.

[**`Back to Top`**](#)


## Compatibility
**Compatibility options can be accessed from `Config` menu in main window.**

    enable_bypass_window_manager
Set `true` to bypass window manager on Linux. This option does not affect windows system. This option is enabled by default on Linux. Note, while this option is enabled, OBS may not be able to capture overlay widgets in streaming on Linux.

    enable_translucent_background
Set `false` to disable translucent background.

    enable_window_position_correction
Set `true` to enable main application window position correction, which is used to correct window-off-screen issue with multi-screen. Overlays left outside every screen (monitor unplugged, preset made on another computer) are also shown on the nearest screen at startup, their saved position kept (not done while VR overlay is enabled). This option is enabled by default.

    enable_x11_platform_plugin_override
Set Qt platform plugin type to `X11` via environment variable on Linux. This option may help work around some issues with overlay dragging and position on `Wayland`. This option requires restarting Modern Tiny Pedals to take effect. This option is enabled by default on Linux.

    background_color_global
Sets global background color for all widgets.

Note, global background color will only be visible when `enable_translucent_background` option is disabled or translucent background is not supported. Some widgets with own background setting may override this option.

[**`Back to Top`**](#)


## Overlay Style
**Overlay style options can be accessed from `Config` menu in main window. Changes apply to all widgets in all presets.**

Themes only restyle options that still use their default value, any customized font, color or gap in widget preset is kept as it is. Styled values are never saved to preset file, so changing theme never changes presets. Modern themes use modern design, rounded corners, minimum gap between bars, fixed width digits, and auto font vertical offset that is independent of font leading. Legacy themes keep classic TinyPedal look: modern font, corner, depth and bar gap options do not apply.

    overlay_theme
Set overlay theme, applied to default colors only (alpha channel is kept):

* `Modern Dark`: modern design, slate neutrals with softer accent colors (default).
* `Modern Light`: modern design, light panels and dark text.
* `Legacy Dark`: classic TinyPedal look: classic layout, colors and fonts.
* `Legacy Light`: classic TinyPedal look with light panels and dark text.

Light themes invert gray panels and text, keep colored backgrounds (flags, warnings) and darken colors drawn on panels so they stay readable.

    enable_colorblind_colors
Colorblind safe variant of overlay theme (Okabe-Ito palette): red / green pairs become orange / blue, on every theme. Default is disabled.

    enable_modern_font
Use modern fonts while a `Modern` overlay theme is selected. Modern design widgets draw labels and names in `modern_design_font_name`, and values (times, gaps, speeds, temperatures, fuel...) in `modern_font_name`, a monospace font that keeps digits steady and aligned. Classic layout widgets (`enable_classic_layout` enabled) replace their default font with `modern_font_name`; width of text bar is calculated from digit width to avoid clipping numbers. Disable to draw every widget, modern design included, in its own `font_name` option. Default is enabled.

    modern_font_name
Set font of values (numbers) of modern design widgets, and of every text of classic layout widgets, see `enable_modern_font`. Default is `JetBrains Mono`, which is bundled with Modern Tiny Pedals (`fonts` folder), and works on all platforms. Values are sized to the height of the text beside them. Ligatures are disabled.

    modern_design_font_name
Set font of labels, names and other text of modern design widgets (see [Modern design](#modern-design)), while `enable_modern_font` is enabled (values use `modern_font_name`). Default is `Barlow Semi Condensed`, which is bundled with Modern Tiny Pedals (`fonts` folder) along with `Barlow`.

    corner_radius_scale
Set bar corner radius, relative to shorter side of each bar. Value range in `0.0` to `0.5`, `0` for square corners. Default is `0.05`.

    enable_depth_effects
Apply black box visual style to all widgets: lighter top, darker bottom and thin highlight edge on panels and bars, so they read as slightly raised. Elements smaller than 6 pixels stay flat. Default is enabled.

    minimum_bar_gap
Set minimum gap between bars in pixels of classic layout widgets (modern design sets its own gaps), only applies to widget `bar_gap` option that uses default value. Default is `2`.

[**`Back to Top`**](#)


## User path
**User path options can be accessed from `Config` menu in main window.**

User path dialog allows customization to global user path for storing different user data.

To change user path, double-clicking on edit box to open `Select folder` dialog; or manually editing path text. Folder will be automatically created if does not exist.

Click `Apply` or `Save` button to verify and apply new paths. Invalid path will not be applied.

User folders can be opened in File Manager via `Open Folder` sub-menu from `Config` menu.

**Notes to relative and absolute path**

User path that sets inside Modern Tiny Pedals root folder will be automatically converted to relative path. Relative path is not considered global path, and does not share data between multiple copies of Modern Tiny Pedals. This is done to retain portability and compatibility with old version.

To share user path across multiple copies of Modern Tiny Pedals, user must set path to place outside Modern Tiny Pedals APP root folder.

**Default user path**

* On windows, all user paths are set inside Modern Tiny Pedals root folder as relative paths:

        brandlogo/
        deltabest/
        settings/
        trackmap/
        pacenotes/
        tracknotes/
        carsetups/
        telemetry/
        gameimage/

* On Linux, all user paths are set outside Modern Tiny Pedals root folder as absolute paths:

        home/username/.config/TinyPedal/brandlogo/
        home/username/.config/TinyPedal/settings/
        home/username/.config/TinyPedal/pacenotes/
        home/username/.config/TinyPedal/tracknotes/
        home/username/.local/share/TinyPedal/deltabest/
        home/username/.local/share/TinyPedal/trackmap/
        home/username/.local/share/TinyPedal/carsetups/
        home/username/.local/share/TinyPedal/telemetry/
        home/username/.local/share/TinyPedal/gameimage/

**Telemetry path**

`telemetry_path` sets the folder where [Recorder module](#recorder-module) saves recorded laps (default `telemetry/`).

**Game image path**

`game_image_path` sets the folder where car brand logos, circuit logos, car pictures and circuit pictures taken from Le Mans Ultimate are kept (default `gameimage/`, see [Brand logo](#brand-logo)). Its `catalog.json` file lists the cars (with their brand) and circuits of the game. Deleting the folder is safe: pictures are fetched again from the game.

[**`Back to Top`**](#)


## Remote Control
**Remote control options can be accessed from `Config` menu in main window. Disabled by default.**

Remote control allows other programs (Stream Deck, Companion, SimHub, button box software) to run any hotkey command through a local HTTP server that only listens on `127.0.0.1`:

* `GET http://127.0.0.1:8337/commands` lists available commands.
* `POST http://127.0.0.1:8337/command/<name>` runs a command, request must include `X-TinyPedal` header (any value).
* `ws://127.0.0.1:8337/stream` is a WebSocket that pushes live telemetry as JSON (same fields as web dashboard: speed, gear, rpm, pedals, position, lap times, delta, fuel, tyre & brake temperatures...). Push interval is set with `?interval=<ms>` (20 to 5000, default 100). `?fields=speed,gear,rpm` only sends these fields, `?changes=1` only sends fields changed since last message (nothing if none changed). Client can change both at any time by sending a text message such as `{"fields": ["speed", "gear"], "changes": true}` (`"fields": null` for every field). Browser pages from other sites are refused (`Origin` check).

Requests without the header, or with a host name other than `127.0.0.1` or `localhost`, are refused. This protects against web pages trying to send commands from a browser.

A browser page reading the telemetry stream must be served from `http://localhost` or `http://127.0.0.1`: pages opened from a local file or shown in a sandboxed frame (`null` origin) are refused too.

    enable_remote_control
Enable remote control server.

    remote_control_port
Set server port. Default is `8337`.

[**`Back to Top`**](#)


## Web Dashboard
**Web dashboard options can be accessed from `Config` menu in main window. Disabled by default.**

Web dashboard shows live data (gear, speed, RPM, delta, lap times, position, fuel, pedals, tyre & brake temperatures, time left) in a web browser, for example on a phone or tablet placed next to the screen. Select `Web Dashboard Address...` from `Config` menu to see the address to open, including the access code.

The page is in the app language, and shows speed, temperatures and fuel in the units of [Units](#units) config dialog. A car using virtual energy (LMU Hypercar, LMGT3) shows virtual energy (%) instead of fuel, as fuel widgets do. With LMU, the official delta of the game is shown next to the delta best, and the current lap is marked invalid when the game invalidated it (track limits). Telemetry fields of the stream keep their units (`km/h`, `°C`, liters), values in units of the user are in `display` (with their unit symbols), plus `delta_official` (`null` when not available) and `lap_invalid`.

    enable_web_dashboard
Enable web dashboard server.

    enable_lan_access
Allow devices on local network (phone, tablet) to open the dashboard. When disabled, the dashboard is only available on this computer (`127.0.0.1`). Windows firewall may ask to allow Modern Tiny Pedals the first time.

    enable_https
Serve the dashboard over HTTPS with a self-signed certificate, so the access code and data are encrypted on the local network. The certificate is created in the config folder and reused (a new one is made when this computer gets a new address). The browser warns once about the self-signed certificate: `Web Dashboard Address...` shows its SHA-256 fingerprint to check before accepting it. Disabled by default.

    web_dashboard_port
Set server port. Default is `8338`.

    access_code
Access code required to open the dashboard. A random code is generated if empty. After 10 wrong codes, the device is blocked for 60 seconds.

[**`Back to Top`**](#)


## Stream Overlay
**Stream overlay options can be accessed from `Stream Overlays` page (`Tools` page, or command palette), or `Stream Overlay` category of `Config` page. Disabled by default.**

Shows widgets in streaming software (OBS Studio, Streamlabs, XSplit, vMix, Twitch Studio...) as browser sources: a transparent page, no chroma key needed, drawn exactly as on screen (also while the game runs in exclusive fullscreen). `Stream Overlays` page gives the addresses to copy into a `Browser` source:

* `Layout`: every widget shown on stream, at its place on screen. Set the browser source size to the screen size shown on the page (smaller sizes are scaled to fit).
* One address per widget: the widget alone, at top left. Set the browser source size to the widget size shown on the page (`&scale=1.5` in the address enlarges it).
* `Race Results`: classification of the last race (from game results files, see [Race results](#race-results)), cars of every class (`&class=all`), one class after another (`&class=cycle`) or one class (`&class=<name>`), `&rows=` cars per page and `&cycle=` seconds per page, `&session=qualifying` or `&session=any` for other sessions. A 1920 x 1080 source fits it.

Widget images are only captured while a browser source is shown, copied from what is already drawn on screen (no extra drawing), and only sent again when they change. Each widget can be shown on screen and stream, on stream only, or on screen only, see `stream_visibility` in [Common terms and keywords](#common-terms-and-keywords).

    enable_stream_overlay
Enable stream overlay server.

    enable_lan_access
Allow another computer on local network (dual PC streaming setup) to show browser sources. When disabled, sources are only available on this computer (`127.0.0.1`). Windows firewall may ask to allow Modern Tiny Pedals the first time.

    stream_overlay_port
Set server port. Default is `8339`.

    frame_rate
Set maximum frame rate of widget images sent to browser sources. Default is `30`. Widgets not changing are not sent again.

    access_token
Access token included in every source address. A random token is generated if empty. Generate a new one from `Stream Overlays` page when an address has been shared by mistake (shown on stream): addresses copied before stop working.

[**`Back to Top`**](#)


## VR Overlay
**VR overlay options can be accessed from `Config` menu in main window. Disabled by default, not yet tested on every headset.**

Shows all visible widgets (same layout as on desktop) in your VR headset, with nothing else to install:
- **OpenXR games** (any runtime: SteamVR, Meta Quest Link / Air Link, Virtual Desktop, Windows Mixed Reality, Pimax, Varjo...): drawn by the app's own OpenXR layer, loaded by the game (Windows, games using Direct3D 11, Direct3D 12 or Vulkan; OpenGL games are not supported). Start the app before or after the game, either works.
- **SteamVR games** (OpenVR): shown as a SteamVR overlay once SteamVR runs. The app never starts SteamVR itself.

The VR overlay is hidden automatically when all widgets are hidden, and only sends a new image when widgets have changed.

    enable_vr_overlay
Enable VR overlay in OpenXR and SteamVR games. On Windows, this registers the app's OpenXR layer for your user account (no admin rights). It does nothing while the app is closed, and is removed when this option is turned off or the app is uninstalled. To turn it off for one game, set the `DISABLE_TINYPEDAL_XR_LAYER` environment variable to `1`. Games run as administrator do not load it.

    enable_attach_to_headset
Attach overlay to headset (follows head movement), otherwise overlay is fixed in seated space.

    update_interval
Set refresh interval in milliseconds. Default is `50`.

    overlay_width_meters
Set overlay width in meters. Default is `0.8`.

    distance_meters, vertical_offset_meters, horizontal_offset_meters
Set overlay position in meters, relative to seated position or headset.

    mirror_position_x, mirror_position_y
VR mirror window position on desktop, saved when the window is moved.

[**`Back to Top`**](#)


## Notification
**Notification options can be accessed from `Config` menu in main window.**

Note, notifications are displayed in main window. Click on any notification to quickly switch to corresponding tab. It's recommended to keep all notifications enabled.

    notify_locked_preset
Show notification for loading locked preset.

    notify_spectate_mode
Show notification while spectate mode is enabled.

    notify_pace_notes_playback
Show notification while pace notes playback is enabled.

    notify_global_hotkey
Show notification while global hotkey is enabled.

[**`Back to Top`**](#)


## Overlay
**Overlay options can be accessed from `Overlay` menu in main window, or from tray icon menu.**

    fixed_position
Check whether widget is locked at startup. This setting can be toggled from tray icon menu.

    auto_hide
Check whether auto hide is enabled. This setting can be toggled from tray icon menu.

    enable_grid_move
Enable grid-snap effect while moving widget for easy alignment and repositioning.

    vr_compatibility
Enable widget visibility as windows on taskbar in order to be used in VR via APPs such as `OpenKneeboard`. Non-VR user should not enable this option.

Note, you will still need a third party program (such as `OpenKneeboard`) to project overlay windows (widgets) into VR.

[**`Back to Top`**](#)


## Units
**Units options can be accessed from `Config` menu in main window.**

    distance_unit
Available units: `Meter`, `Feet`.

    fuel_unit
Available units: `Liter`, `Gallon`.

    odometer_unit
Available units: `Kilometer`, `Mile`, `Meter`.

    power_unit
Available units: `Kilowatt`, `Horsepower`, `Metric Horsepower`.

    speed_unit
Available units: `KPH`, `MPH`, `m/s`.

    temperature_unit
Available units: `Celsius`, `Fahrenheit`.

    turbo_pressure_unit
Available units: `bar`, `psi`, `kPa`.

    tyre_pressure_unit
Available units: `kPa`, `psi`, `bar`.

    weight_unit
Available units: `Kilogram`, `Pound`.

[**`Back to Top`**](#)


## Global font override
**Global font override options can be accessed from `Config` menu in main window, which allow changing font setting globally for all widgets.**

    Font Name
Select a font name to replace `font_name` setting of all widgets. Default selection is `no change`, which no changes will be applied.

    Font Size Addend
Set a value that will be added (or subtracted if negative) to `font_size` value of all widgets. Default is `0`, which no changes will be applied.

    Font Weight
Set font weight to replace `font_weight` setting of all widgets. Default selection is `no change`, which no changes will be applied.

    Enable Auto Font Offset
Enable or disable auto font offset for all widgets. Default selection is `no change`, which no changes will be applied.

    Font Offset Vertical Addend
Set a value that will be added (or subtracted if negative) to `font_offset_vertical` value of all widgets. Default is `0`, which no changes will be applied.

[**`Back to Top`**](#)


## Spectate mode
**Spectate mode can be accessed from `Spectate` tab in main window.**

Click `Enabled` or `Disabled` button to toggle spectate mode on and off. Note, spectate mode can also be enabled by setting `enable_player_index_override` option to `true` in [Telemetry API](#telemetry-api) dialog.

While Spectate mode is enabled, `double-click` on a player name in the list to access telemetry data and overlay readings from selected player; alternatively, select a player name and click `Spectate` button. Current spectating player name is displayed on top of player name list. Player names are listed in alphabetical order.

Select `Anonymous` for unspecified player, which is equivalent to player index `-1` in JSON file.

Click `Refresh` button to manually refresh player name list.

[**`Back to Top`**](#)


## Pace notes playback
**Pace notes playback control panel can be accessed from `Pacenotes` tab in main window.**

Note, [Notes Module](#notes-module) must be enabled to allow pace notes playback. Pace notes can be created or edited using [Track Notes Editor](#track-notes-editor).

Click `Playback Enabled` or `Playback Disabled` button to quickly enable or disable pace notes playback. Disabling this option does not affect `Notes Module` or `Pace notes Widget`.

Click `Enable Playback While in Pit Lane` check box to enable or disable pace notes (that tagged with `#pit`) playback while in pit lane. This option takes immediate effect when changed.

Enable `Manually Select Pace Notes File` check box to disable auto-file-name matching, and manually select a pace notes file that can be played on any track. By default, pace notes file is automatically loaded from `pace_notes_path` if a file that matches current track name is found. This option takes immediate effect when changed.

`Sound file path` sets path for loading pace notes sound files that matches name value (exclude file extension) from `pace note` column found in pace notes file. If no sound file found, sound won't be played. This option takes immediate effect when changed.

`Sound format` sets sound format for loading sound file, which should match sound file extension. This option only takes effect after clicked `Apply` button.

`Global offset` adds global position offset (in meters) to current vehicle position on track, which affects when next pace note line will be played. This option only takes effect after clicked `Apply` button.

`Maximum duration` sets maximum playback duration for each sound file, which can be used to limit sound file maximum playing duration. Default duration is `10` seconds. This option only takes effect after clicked `Apply` button.

`Maximum Queue` sets maximum number of sound files in playback queues. Default is `5` sound files. This option only takes effect after clicked `Apply` button.

`Playback volume` sets output volume for sound file. This option takes immediate effect when adjusted.

[**`Back to Top`**](#)


## Hotkey
**Hotkey control panel can be accessed from `Hotkey` tab in main window.**

Note, hotkey bindings are non-exclusive in Modern Tiny Pedals, which means they will not interfere with other programs. Hotkey history can be view in [Show Log](#console-log) dialog from `Help` menu. Currently global hotkey feature is not supported on Linux.

Click `Enabled` or `Disabled` button to toggle global hotkey on and off. Note, global hotkey can also be enabled by setting `enable_global_hotkey` option to `true` in [Application](#application) dialog.

To change key binding, click key button on right side of each hotkey option, then in `Key Binding` dialog, press a `key` or `key combination` to register new key binding.

Note, assign same key for multiple options will cause those options to be toggled at the same time. However, each option's toggle state is still handled individually.

To clear key binding, click `Clear` button from `Key Binding` dialog.

To clear all key bindings, click `Clear All` from `Hotkey Tab`.

### General keybinding

    overlay_visibility
Show or hide overlay.

    overlay_lock
Lock or unlock overlay.

    overlay_auto_hide
Enable or disable overlay auto hide function.

    vr_compatibility
Enable or disable VR Compatibility.

    restart_api
Restart current Telemetry API.

    select_next_api, select_previous_api
Select next or previous Telemetry API from available API list.

    reload_preset
Reload current preset.

    load_next_preset, load_previous_preset
Load next or previous preset relative to current preset (by preset name in ascending order).

    spectate_mode
Enable or disable spectate mode.

    spectate_next_driver, spectate_previous_driver
Spectate next or previous driver relative to current driver (by driver's overall standing).

    pace_notes_playback
Enable or disable pace notes playback.

    cycle_deltabest_source
Cycle deltabest source for displaying in [Deltabest](#deltabest) Widget.

    black_box_next_incident
Show the next older incident in the Black box incident recorder (back to the newest after the oldest). The trace freezes on it for `incident_display_duration` seconds, its caption tells which one it is (`2/5`).

    black_box_open_incident_folder
Open the `blackbox` folder of the configuration folder, where the Black box incident recorder saves incidents. Also in the Black box right click menu (`Open Incident Folder`) while incident file export is enabled.

    restart_application
Restart Modern Tiny Pedals.

    quit_application
Quit Modern Tiny Pedals.

### Preset keybinding

    preset_*
Load assigned preset. Note, if assigned preset file is not found (such as deleted), it will not be loaded, and its name will be auto unassigned from list.

### Widget keybinding

    widget_*
Enable or disable widget.

### Module keybinding

    module_*
Enable or disable module.

[**`Back to Top`**](#)


# Tools
**Tools can be accessed from main window menu.**

[**`Back to Top`**](#)


## Race calculator
**Race calculator plans fuel, virtual energy and tyres of a race in one page, which can be accessed from `Race` button of navigation bar, or `Tools` menu in main window.** It replaces the former fuel calculator and tyre strategy planner (their navigation bar entries and open pages now open the race calculator). The next stop of the plan can be shown in game with [Race plan](#race-plan) widget.

Fuel value and unit symbol depend on `Fuel Unit` setting from [Units](#units) config dialog, `L` = liter, `gal` = gallon. Virtual energy unit is `%` = percentage. Note, after changed `Fuel Unit` setting, it is required to close and reopen `Race calculator` in order to update units info for calculation. A typed value is applied when pressing `Enter` or leaving the box (arrows & mouse wheel apply at once), then everything is calculated again. Inputs and tyre plan are kept for next time, `Reset to Zero` clears inputs (starting tread back to 100%).

    Top of page (shared by both tabs)
- Data source: live session (`Load Live`) or consumption history file (`Load File`, `.consumption` or `.csv`, tank capacity of its laps), with track and class name. An invalid file is reported and current data kept. `Follow Live`: inputs follow each new lap of the live session (saved). When the page opens, live laps fill the inputs, except after a race plan was opened (its inputs are kept, live laps only shown, until `Load Live` or `Load File`).
- `Live Race`: during a race, plan of the rest of the race from now (laps & race time done, fuel, energy & tyres of the car, stops done), planned again at each lap & stop (not while in the pits). Timeline & pit stop plan start at the lap of now (`Now` row), stops keep their race number, the tyre plan of the race is kept (saved). Status next to it (waiting for the race or lap 1, from lap, in the pits); its tooltip shows the values read from the game (laps & lap progress, race time & time left, fuel, energy, tread, stops counted & game count) to check them. Race time is session time minus race start time of the game; a stop is counted when the car stood still in the pits or got fuel, energy or tyres there (drive-through penalties left out), a stop not seen (page closed) is taken from the game count.
- `Race Plan` menu: `Save Race Plan As...` saves race setup, every input and tyre plan in one `.race-plan` file to keep or share, `Open Race Plan...` opens one (tyre plan replaced can be undone). `Save for Current Car & Track` keeps the plan for the car & track driven, `Open Plan of Car & Track Automatically` opens it again once when that car & track are driven (saved). `Copy Share Code` copies the whole plan as one line of text (to paste in a chat), `Paste Share Code...` opens the plan of a code (line breaks of a chat left out). `Undo` / `Redo` (`Ctrl+Z` / `Ctrl+Y`) undo inputs and tyre plan edits.
- Race: `Time` or `Laps` race (only the field of the selected type is shown), formation or rolling start laps (driven before race clock starts, 0.5 = half a lap of fuel), pit stop time (time lost per stop in pit lane, service time added: refuelling, tyre & driver change), safety margin kept in the tank at every stop and at the finish: in laps of fuel, in fuel (energy: same laps) or in % more consumption per lap.
- Key figures: race fuel & energy (safety margin included), pit stops (what limits stints: fuel, energy, stint length, tyre life or mandatory stops; stops with tyres), longest stint, average refill per stop (or fuel to load at start when no stop is needed), tyres used by the tyre plan / maximum allowed. A tank too small for one lap, or a starting fuel or energy below one lap, is reported in red.
- On a narrow window, race setup & key figures wrap on two rows, consumption history moves below calculator and tyre stock below tyre plan.

    Fuel tab
- Lap & consumption: lap time (`minutes` : `seconds` . `milliseconds`, carried over between boxes, at half tank), fuel & energy per lap, tank capacity, fuel ratio (fuel used per 1% of virtual energy). `Load Live` and `Load File` fill them with the average of the 5 latest valid laps at race pace (laps over 105% of median lap time, as in & out laps, left out), and `Load Live` also sets race length from a live race session. A car using energy only (no fuel per lap) is planned on energy.
- Start: starting fuel & energy, `0` = full tank, or exactly what the race needs when it needs no stop. Start time (checked): time of day of the race start, midnight included, pit stops then shown at their time of day (unchecked: race time).
- Pit stop: refuel rate and energy rate (amount added per second, `0` = refuelling inside pit stop time), so a splash costs less time than a full tank; driver change time; `Tyres Changed While Refuelling` (longest of refuelling and tyre change counts, not both); in & out laps consumption (% of race pace, pit lane speed limit: a stint can last one lap more).
- Race rules: mandatory stops (race laps spread evenly over one stint more than stops), maximum stint time (driver limit, real lap times counted: a heavier car is slower), drivers taking turns, `Balanced Stints` (race laps spread evenly over the stints, same stops: no short splash stint at the end), `Leader Finishes First (+1 Lap)` (time race: the race ends when the leader crosses the line after the timer, so a car behind may drive one lap more: fuel planned for it).
- Drivers (2 drivers or more): stints driven before the next driver takes over, and for each driver lap time difference (pace), minimum & maximum total driving time. A driver with too little time left for a whole stint is skipped; drivers short of their minimum drive next, stints of the others shortened to leave them the time. Driving time card: stints & time of each driver, limits not met in red.
- Pace: fuel effect (lap time lost per 10 fuel units in the tank, from half tank) and track evolution (lap time change per hour, negative when the track gets faster), used for stint durations and laps of a time race. Saving cost: lap time lost per 10% less consumption (lift & coast), counted by saving target & strategy comparison. `Estimate from History`: pit stop time (in & out laps against race pace), fuel effect (lap time against fuel burned over stints, tyre wear trend included) and track evolution (2 stints or more) from laps of the consumption history.
- Safety car: `Safety Car Scenario` plans a safety car (or full course yellow) period from a lap for some laps, with consumption, lap time & tyre wear in % of race pace, and optionally a stop at the end of its first lap (part of pit lane time not lost under safety car). Compared with the plan without safety car (a safety car after the finish has no effect); shown in yellow on the timeline, `SC` stops in pit stop plan.
- Rain: `Rain Scenario` plans a wet period from a lap for some laps (`0` = until the finish), with consumption & lap time in % of race pace, and optionally `Wet Tyres`: stop for wet tyres at the end of the first lap in the wet and for slicks at the end of the last one (4 tyres). Compared with the plan without rain; shown in blue on the timeline, `Wet` & `Dry` stops in pit stop plan.
- Strategy: timeline of the race, one block per stint with its laps (one color per driver when drivers take turns), pit laps above (in orange when tyres are changed, shortened or left out when stops are too close to read), mouse over a stint or stop shows its details, with a summary line (stints, race laps, stop laps, tyres, time spent in the pits, safety car).
- Pit stop plan: start load, then each stop with its lap, pit window (earliest & latest lap keeping the same number of stops, stint time limit counted with real lap times of the slowest driver), time (race time, or time of day with start time), fuel & energy to add (full tank while more stints follow, only what is needed for the last one), tyre change (number of tyres), driver and stop time. Fuel unit badge (`L` or `gal`) next to `Export`, in the plan image too. `Export`: copy as text, copy for Discord (table in a code block), export CSV, save image (strategy & plan), in the folder of last export, and `Copy Picture` (strategy & plan picture in the clipboard, to paste in Discord).
- Details: total needed (exact ≈ rounded up), refuel stops each resource alone needs (the plan may stop more often: driver limit, mandatory stops), laps & minutes total amounts last, laps & minutes a full tank lasts (safety margin kept), amount left at stint end, consumption per lap to save one stop (same as saving target, `-` without stop), average refill of the pit stop plan.
- Saving target: laps per stint (on a full tank) and consumption per lap (difference with current one) for one stop less, planned with the starting fuel; with a saving cost, lap time lost and race time gained or lost (worth it or not). Consumption & stops for laps per stint to aim for.
- Strategy comparison: plan of now against plans with up to 2 stops less (fuel saving) and one stop more: consumption, lap time lost to saving, time in the pits, laps, race time and gap, best one in bold. Saving target & comparison are calculated at once after a pause, or once quick changes settle (arrow held).
- Plan against race (race session): stints driven (stint history) against the plan of the race: laps, lap time, fuel & energy per lap (race value / plan value), tyre wear. Driver of each stint when known: driver in the car (game scoring, it changes on a driver swap) at pit entry of the stop ending the stint, else leaving the stop before; stops seen while the app runs (page open or not). In `Live Race`, driver in the car shown on the summary line.
- Class rivals (live race): cars of your class by place, laps, stops (in the pits), laps since last stop and next stop expected (last stop seen while the page is open, plus your full tank laps; `~` when the last stop was not seen).
- Consumption history: `lap number`, `lap time`, `fuel`, `virtual energy`, `fuel ratio`, `battery drain`, `battery regen`, `battery net change`, `average tyre tread wear`, `tank capacity` of [Consumption History](#consumption-history) data, invalid laps in red. Live history follows new laps while the page is shown. Click a column header to sort (numbers by value), `Valid Laps Only` hides invalid laps (saved). Select laps (whole rows) and click `Add Selected Data`: their average goes to the calculator, invalid laps are left out. `Delete Selected` and `Delete All` remove laps from consumption history (live session or loaded file, asks first, cannot be undone). `Columns` button (or right click on table header) shows or hides optional columns.

How stints are planned: a car pits at the end of a lap, so stints are whole laps; a stint lasts until fuel or energy (whichever runs out first) cannot cover one more lap plus the safety margin, or until driver limit (stint time, total driving time). In a time race, laps that fit in race time follow lap times and stop times, and fuel & energy share the same stops, so both are calculated for the same race length (when lengths go back and forth, the longest of them is kept). Tyres are changed at the stop before the stint actually driven next would wear them below minimum tread. With tyre life (laps per tyre set, or `Stints Cut by Tyre Life`), tyres are changed at the stop when they cannot last the next stint, and no stint lasts longer than its tyres (together with fuel, energy & driver limits).

    Tyre tab
- Tyre wear: starting tread (when the tyre plan has no tyre at start, else starting tread of its compound), wear per lap (filled from history like other inputs), measured compound (compound the wear per lap was measured on, saved), minimum tread: the strategy proposes tyre changes at the stop before tread would go below it. `Laps per Tyre Set` (`0` = none): stints never longer than a set of tyres lasts (laps at race pace wear, safety car laps counted at their wear), tyres changed when needed. `Stints Cut by Tyre Life`: stints also never wear tyres below the minimum tread (wear per lap), so a stint is shortened when the tyres would not last it. Tyre changes show in the plan (`Tyres` column, orange stop marks on the timeline), and `limited by tyre life` under pit stops when tyres end stints. During a live race, laps on the tyres of now count from the last stop with tyres of the plan.
- Tyre rules: maximum tyres allowed for race (`From Game`: tyre allocation of the session in `LMU`), tyre change time by number of tyres changed (default values match `LMU` tyre change rule), restricted allocation (an already used tyre cannot be allocated on a different wheel in later stint, which matches `LMU` tyre allocation rule), highlight new tyres.
- Tyre life: lifespan in laps, minutes and longest stints, tread used over longest stint.
- Tyre plan: one row per stint, columns `Front Left`, `Front Right`, `Rear Left`, `Rear Right` (tyre installed on each wheel, with remaining tread at start - end of stint) and `Change` (tyre change time of that stop). Once the fuel strategy is ready, rows follow its stints (stint number and laps shown on each row); rows taken out by a shorter strategy are kept aside and come back when it grows again, added rows keep the tyres of the stint before. Tyre wear of a stint = wear per lap x stint laps x compound factor (wear per stint of compound relative to measured compound; wear per stint of compound without wear per lap), and the tyre change time of each stop is added to that stop. Without strategy, rows are edited by hand (`Duplicate Row`, `New Row`, `Insert Below`, `Insert Above`, `Delete Row`). `Propose Changes` fills the plan with tyres of the compound selected in tyre stock, wheel by wheel at the stint it would go below minimum tread (2 tyres when only one axle needs it), within maximum tyres: short of tyres, the best worn tyre that wheel used before (any wheel without restricted allocation) is fitted again, else tyres are kept and the stints short of tyres are reported. Tyres a previous proposal added are reused or removed, so proposing again adds no stock. `Undo` / `Redo` (`Ctrl+Z` / `Ctrl+Y`) undo tyre plan edits (and inputs). Status line: stock (`invalid` when over maximum tyres, tyres without limited stock not counted), used tyres, stints, pit stops, tyre changes and total tyre change time.
- Tyre stock: compound selector (tyre name starting with `Q` is a tyre reused from qualifying session), `Add` adds a tyre with a unique number and a label showing the stints it runs, `Config` sets compound setting (`Enable Limited Stock`: counts towards maximum tyres, enabled for dry compounds by default; `Starting Tread`; `Wear Per Stint`), `Sort By` compound type or number of stints, `Remove Unused` removes tyres the plan does not use, `Remove`, `Clear All` (corresponding tyres removed from tyre plan too).
- File menu of tyre plan: `New File`, `Open File` and `Save As` in [Tyre strategy](#tyre-strategy) format, `Export As` spreadsheet (CSV). Tyre plan is also kept automatically between sessions (nothing asked on close).
- To add a tyre to the plan, drag it from tyre stock onto a wheel (tyres can be dragged & copied in the plan too). Hold `Ctrl` or `Shift` to select several tyres (drag is disabled then). Right click on tyre stock or plan opens a menu, `Delete` removes selected tyres from the plan (asks first).

    Team tab
- Stints of every driver of the car read from the game (`LMU` strategy data), teammates included, also from the monitor while a teammate drives: driver, stint, laps, laps counted, fuel, virtual energy and tyre wear per lap (out laps, pit laps and laps with refuelling or new tyres left out), and usage per lap of each driver. Asked to the game when the tab is shown, then every 15 seconds (`Refresh` asks at once).
- `Fill In Calculator`: average per lap of selected stints (all stints if none selected) goes to fuel, energy & tyre wear inputs, tank capacity of the car from the game.
- `Load Live` with no valid lap at race pace yet (`LMU`, while driving): fuel & energy per lap estimated by the game are filled in.

[**`Back to Top`**](#)


## Driver stats viewer
**Driver stats viewer can be accessed from `Tools` menu in main window.**

Driver stats viewer is used for viewing [Driver Stats](#driver-stats). Note, the viewer only allows limited reset or removal, stat value cannot be edited by design. Changes are applied to stats file read again at that time (stats saved meanwhile by stats module are kept), and can be undone or redone with `Undo` & `Redo` buttons (`Ctrl+Z`, `Ctrl+Y`) while the page is open: undo keeps stats recorded since (laps, distance added, faster lap time kept). Removing a vehicle or deleting a track also removes its session history; resetting a lap time removes it from session bests (progression). Before each change, stats file is saved as automatic backup (last 10 kept): `View` menu, `Restore Backup` puts back stats of a backup (can be undone too). Stats saved by stats module (back to garage) are shown at once without `Reload`, sort, selection & scroll kept (when page is shown again if hidden meanwhile).

Driver stats are grouped under specific track name, which can be switched from track name selector on the top (type to search a track, part of name is enough; `Up` / `Down` & `Enter` to choose, last driven date of each track, flag on track of running session). Key figures of the track sum all vehicles: best lap (and its vehicle), its level, distance, driving time, valid laps (and share of all laps), races (wins & podiums).

`All Tracks`, first entry of track selector, shows the career: each track with best lap of each class (colored by its level on community lap times), totals of track and last driven date; key figures of all tracks (tracks driven & most driven one, median level of best laps); the card on the right counts best laps of each level. Each best lap shows the first letter of its level, so levels are told without colors. Double click a track (or `Enter`) to show its vehicles, right click: `Show Track`, `Delete Track`, `Open Recorded Laps`. When stats are saved under vehicle name (`vehicle_classification` option of [Stats Module](#stats-module)), vehicles are grouped by game class recorded in session history.

Vehicle table columns: personal best, gap to community reference & level, theoretical best (sum of all time best sectors of the class from [Sectors Module](#sectors-module), all brands) & potential (personal best minus theoretical best), qualifying & race best, distance, driving time, fuel, valid & invalid laps, share of valid laps, average speed, fuel consumption per 100 km (or miles), penalties (and per race), race starts, finishes, wins, podiums, DNF (not finished or disqualified), win & podium rates, average finish position, last driven date. Race starts, DNF, average finish position and last driven date are recorded since version adding them. Rates are per start (finishes & DNF for older stats). `View` menu: `Columns` shows or hides columns (also right click on column names, `hidden_columns` option of `driver_stats_viewer` in config file), `Reset Column Widths` (columns are resized by dragging the edge of column names, `column_widths` option), `Sort Tracks by Last Driven` lists tracks driven lately first (`enable_sort_by_last_driven` option), `Colorblind colors` shows levels in colors easier to tell apart with color vision deficiency (`enable_colorblind_colors` option). `Export` saves the table shown (visible columns) to a CSV file, number format of system language: `Export CSV...` as shown, `Export Raw Values (CSV)...` in base units without formatting (lap times in seconds, distance in meters, fuel in liters...) for spreadsheets.

To sort by specific stat, click on corresponding column name (again for reverse order, values not recorded always last). Stats are sorted by `personal best lap time` by default. `Up` / `Down` keys change selected vehicle.

`Telemetry` button (or `Open Recorded Laps` from right click menu) opens recorded laps of selected vehicle class in [Lap Telemetry Viewer](#lap-telemetry-viewer), when [Recorder Module](#recorder-module) recorded laps on this track & class: recorded lap of personal best of selected vehicle (else its fastest lap) is set as reference.

Community lap times: personal best of each vehicle is compared with community LMU lap times of a published Google Sheet (by default the lap time sheet of [ohne_speed](https://www.youtube.com/@ohne_speed): class reference hotlap of each track & class, race pace ladder from ~100% to 107% of it, fastest car). `% Ref.` column shows personal best in percent of class reference, `Level` column its level: `Alien` (~100%), `Competitive` (101%), `Good` (102%), `Midpack` (103-104%), `Tail-ender` (105-106%), `Offline` (slower). The card on the right shows the ladder of selected vehicle with lap time limit of each level, where personal, qualifying and race best stand, gap to class reference, time to find for next level and fastest car. Below it, `Progression` chart shows best lap of each session (dots) and personal best so far (line, faster higher), with lap time limits of levels (dashed lines), dates of first, middle & last session, date of personal best and last session; hover a dot for its date, session & lap time. `All`, `Practice` (test day, practice, warmup), `Qualifying` & `Race` show sessions of that type only. `Sessions` lists sessions of selected vehicle, newest first: date, session, best lap (personal best highlighted), valid / all laps, race result (finish position, DNF or DQ); hover for driving time & distance. Stints shorter than a minute without a lap (garage exit) are not recorded. LMU track names are matched to sheet tracks by name & layout (Spa-Francorchamps Endurance as Spa, Monza Curva Grande as Monza (curvagrande)...), vehicle class from vehicle name (Hyper, LMP2_ELMS, LMP2, LMP3, GT3, GTE): `vehicle_classification` must include class (`Class - Brand` or `Class`) to compare. The sheet is downloaded once a day when page opens and kept in config folder (works offline). `Reference` menu: `Update Reference` downloads again, `Change Sheet Address...` sets another published Google Sheet of same layout, `Compare With Community Lap Times` turns comparison on or off (`enable_lap_reference` and `lap_reference_sheet_url` options of `driver_stats_viewer` in config file).

To view corresponding track map, click `View Map` button.

To reload stats data, click `Reload` button.

To delete all stats from a specific track, click `Delete` button.

To remove all stats from a specific vehicle, right-click on vehicle name and select `Remove Vehicle`.

To reset personal best lap time to default, right-click on personal best lap time and select `Reset Lap Time`.

`Vehicle` column is vehicle classification info, which is determined by `vehicle_classification` option in [Stats Module](#stats-module).

`PB` column is personal best lap time. This value can be reset via right-click menu.

`Qualifying` column is personal best lap time from qualifying session only. This value can be reset via right-click menu.

`Race` column is personal best lap time from race session only. This value can be reset via right-click menu.

`Km` column is total driven distance in kilometers. Note, `odometer_unit` setting from [Units](#units) affects how this column is displayed.

`Hours` column is total time spent in driving (only counts when vehicle speed higher than 1 m/s).

`Liter` column is total fuel consumed. Note, `fuel_unit` setting from [Units](#units) affects how this column is displayed.

`Valid` column is total valid laps completed.

`Invalid` column is total invalid laps completed.

`Penalties` column is total penalties received in race. Non-race penalties are not recorded.

`Finishes` column is total races completed.

`Wins` column is total races won.

`Podiums` column is total podiums from race.

Note, race completion and final standings stats are retrieved at the moment when local driver crossed finish line on final lap, it does not concern any post-race penalties or finish state from team mate.

[**`Back to Top`**](#)


## Vehicle brand editor
**Vehicle brand editor can be accessed from `Tools` menu in main window.**

Vehicle brand editor is used for editing [Brands Preset](#brands-preset). Note, any changes will only be saved and take effect after clicking `Apply` or `Save` Button.

For brand logo image preparation, see [Brand Logo](#brand-logo) section.

`Vehicle name` is full vehicle name that must match in-game vehicle name.

`Brand name` is custom brand name.

Note, brands data are automatically imported for `LMU` while driving, there is no need to manually import them. However it is required to manually import for `RF2`.

To import vehicle brand data from `Rest API`, click `Import from` menu, and select either `RF2 Rest API` or `LMU Rest API`. Note, game updates may introduce new vehicles, it is recommended to re-import after each game update to keep brand info updated.

Note, there are currently two sources for importing from `LMU Rest API`:
- Primary: allows to import brands from both original and custom vehicle skins.
- Alternative: may allow to import some brands that are missing from Primary source. This is normally not required.

**Important notes**

Game must be running in order to import from `Rest API`. Newly imported data will be appended on top of existing data, existing data will not be changed.

If importing fails while game is running, check if `URL Port` option in `RestAPI` module that matches `WebUI port` value that sets in `LMU` (UserData\player\Settings.JSON) or `RF2` (UserData\player\player.JSON) setting file. See [Telemetry API](#telemetry-api) section for details.

Alternatively, to import vehicle brand data from vehicle `JSON` file, click `Import from` menu, and select `JSON file`.

    How to manually export vehicle brand data from RF2 Rest API:
    1. Start RF2, then open following link in web browser:
    localhost:5397/rest/race/car
    2. Click "Save" button which saves vehicle data to JSON file.

    How to manually export vehicle brand data from LMU Rest API:
    1. Start LMU, then open following link in web browser:
    localhost:6397/rest/race/car
    localhost:6397/rest/sessions/getAllVehicles
    2. Click "Save" button which saves vehicle data to JSON file.

    Note: importing feature is experimental. Maximum acceptable JSON file size is limited to "5MB".

To add new brand name, click `Add` button. Note, the editor can auto-detect and fill-in missing vehicle names found from current active session, existing data will not be changed.

To sort brand name in orders, click `Sort` button.

To remove a brand name, select a vehicle name and click `Delete` button.

To batch replace name, click `Replace` button.

To reset all brands setting to default, click `Reset` button; or manually delete `brands.json` preset.

[**`Back to Top`**](#)


## Vehicle class editor
**Vehicle class editor can be accessed from `Tools` menu in main window.**

Vehicle class editor is used for editing [Classes Preset](#classes-preset). Note, any changes will only be saved and take effect after clicking `Apply` or `Save` Button.

`Class name` column is full vehicle class name that must match in-game vehicle.

`Alias name` column is alternative name that replaces class name for displaying.

`Color` column is class color style (HEX code). Double-click on color to open color dialog.

To add new class, click `Add` button. Note, the editor can auto-detect and fill-in missing vehicle classes found from current active session, existing data will not be changed.

To sort class name in orders, click `Sort` button.

To remove class, select one or more rows and click `Delete`.

To reset all classes setting to default, click `Reset` button; or manually delete `classes.json` preset.

[**`Back to Top`**](#)


## Brake editor
**Brake editor can be accessed from `Tools` menu in main window.**

Brake editor is used for editing [Brakes Preset](#brakes-preset). Note, any changes will only be saved and take effect after clicking `Apply` or `Save` Button.

`Brake name` column is full vehicle class name plus brake name that must match in-game vehicle. Brand name may also be added if vehicle brand data is available.

`Failure (mm)` column is millimeter thickness threshold at brake failure and affects brake wear calculation. See [Brake Wear](#brake-wear) widget for details.

`Heatmap name` column is heatmap style name selector. Click on heatmap selector to open drop down list and select a heatmap style.

To add new brake, click `Add` button. Note, the editor can auto-detect and fill-in missing brakes found from running vehicles in current active session, existing data will not be changed.

To sort brake name in orders, click `Sort` button.

To remove brake, select one or more rows and click `Delete`.

To reset all brakes setting to default, click `Reset` button; or manually delete `brakes.json` preset.

[**`Back to Top`**](#)


## Track info editor
**Track info editor can be accessed from `Tools` menu in main window.**

Track info editor is used for editing [Tracks Preset](#tracks-preset). Note, any changes will only be saved and take effect after clicking `Apply` or `Save` Button.

`Track name` column is full track name that must match in-game track.

`Pit entry (m)` column is pit entry position (in meters) relative to track length. This value is automatically recorded or updated by [Mapping Module](#mapping-module).

`Pit exit (m)` column is pit exit position (in meters) relative to track length. This value is automatically recorded or updated by [Mapping Module](#mapping-module).

`Pit speed (m/s)` column is pit lane speed limit (in meters per second). This value is automatically recorded or updated by [Mapping Module](#mapping-module). Note, vehicle pit limiter must be activated while in pit lane to allow recording speed limit.

`Speed trap (m)` column is speed trap position (in meters) relative to track length. To manually set speed trap position at your current on-track position, `Right-Click` on corresponding track's speed trap column and select `Set from Telemetry`.

`Sunrise` column is sunrise hour in `Hour:Minute` format. This value has to be manually defined.

`Sunset` column is sunset hour in `Hour:Minute` format. This value has to be manually defined.

To add new track, click `Add` button. Note, the editor can auto-detect and fill-in missing track found from current active session, existing data will not be changed.

To sort track name in orders, click `Sort` button.

To remove track, select one or more rows and click `Delete`.

To reset all tracks setting to default, click `Reset` button; or manually delete `tracks.json` preset.

[**`Back to Top`**](#)


## Tyre compound editor
**Tyre compound editor can be accessed from `Tools` menu in main window.**

Tyre compound editor is used for editing [Compounds Preset](#compounds-preset). Note, any changes will only be saved and take effect after clicking `Apply` or `Save` Button.

`Compound name` column is full vehicle class name plus full tyre compound name that must match in-game vehicle.

`Symbol` column is alternative symbol character that replaces full tyre compound name for displaying.

`Color` column is custom compound color for each different compound type.

`Heatmap name` column is heatmap style name selector. Click on heatmap selector to open drop down list and select a heatmap style.

To add new tyre compound, click `Add` button. Note, the editor can auto-detect and fill-in missing tyre compounds found from running vehicles in current active session, existing data will not be changed.

To sort tyre compound name in orders, click `Sort` button.

To remove tyre compound, select one or more rows and click `Delete`.

To batch replace name, click `Replace` button.

To reset all tyre compounds setting to default, click `Reset` button; or manually delete `compounds.json` preset.

[**`Back to Top`**](#)


## Heatmap editor
**Heatmap editor can be accessed from `Tools` menu in main window.**

Heatmap editor is used for editing [Heatmap Preset](#heatmap-preset). Note, any changes will only be saved and take effect after clicking `Apply` or `Save` Button.

Each row represents a target temperature and corresponding color. First column is temperature degree value in `Celsius`, and up to one decimal place is kept. Second column is corresponding color (HEX code). Double-click on color to open color dialog.

To add temperature, click `Add` button.

To sort temperature list in orders, click `Sort` button.

To batch offset temperature values, select one or more temperature from `temperature` column, then click `Offset` button. Click `Scale Mode` check box to scale temperature values. Note, offset option will be reset to `0` each time after applying. Last applied offset value is displayed on top of dialog.

To remove a temperature, select one or more temperature and click `Remove` button.

To select a different heatmap preset, click `drop-down list` at top, and select a preset name. Note: by selecting a different preset, any changes to previously selected heatmap will be saved in cache, and only be saved to file after clicking `Apply` or `Save` Button.

To create a new heatmap preset, click `New` button. Note: only alphabetic characters, numbers, underscores are accepted in preset name, and renaming preset is not supported.

To duplicate a heatmap preset, click `Copy` button.

To delete selected heatmap preset, click `Delete` button. Note: built-in presets cannot be deleted.

To reset selected heatmap preset, click `Reset` button. Note: only built-in presets can be reset.

To assign a heatmap preset to specific widget, select corresponding `heatmap name` in widget config dialog.

In case of errors found in `heatmap.json` preset, the APP will automatically fall back to built-in default heatmap preset.

To restore all heatmap settings back to default, just delete `heatmap.json` preset.

[**`Back to Top`**](#)


## Track map viewer
**Track map viewer can be accessed from `Tools` menu in main window.**

To load a track map, click `Load Map` button. Map file name, length and number of nodes are displayed alongside if file is successfully loaded. Note, only track map files (.svg extension) that generated from Modern Tiny Pedals [Mapping Module](#mapping-module) are supported. Map is drawn by the graphics card: road (map width in meters, never thinner than a few pixels), road outline, a line colored by sector (`S1`, `S2`, `S3`, with their length above map), start line and sector lines.

To customize map display, click `Config` button (widths are meters on map, colors of start & sector lines, curve section, osculating circle, distance circles, center mark and position marker).

To zoom map in or out, scroll mouse wheel over map (around mouse), or use `+`, `-` and whole map buttons at top right of map; drag to move zoomed map, double-click to show whole map. A scale bar is shown at bottom right. `Follow position` zooms on current position and keeps it centered.

To move current position, click the map near the track, use position slider or arrows below elevation profile (step of `position_increment_step`), keyboard `Left` / `Right`, or click / drag the elevation profile. `Play` (or `Space`) drives around the track.

Official corner numbers (or names at Le Mans) are shown on map for known circuits (see [Lap telemetry viewer](#lap-telemetry-viewer)), click one to move position there. Info panel shows, at current position: position (official corner, distance, node, sector, XYZ coordinates, Z is elevation), curve (grade and direction, radius, section length and grade, angle) and slope (percent, grade, angle, height delta). `Section nodes` sets the number of map nodes measured from position for curve & slope (minimum `3`, cannot exceed total map nodes). Elevation profile of whole track is shown at bottom, sectors tinted, current position marked.

To toggle on or off specific map display, click `Show`:
* Map info - Show map length, total map nodes.
* Position info - Show current node position and global XYZ coordinates (Z is elevation).
* Curve info - Show curve section length, grade, radius, angle.
* Slope info - Show slope grade, percent, angle, height delta.
* Center mark - Cross along driving direction at current position.
* Distance circle - Show reference distance circles around current position.
* Osculating circle - Show osculating circle that calculated from curve section.
* Curve section - Show curve section from current nodes selection.
* Highlighted coordinates - Show current position marker.
* Elevation profile - Show elevation profile below map.

Track notes editor keeps its own map (right-click context menu, marked & highlighted coordinates).

---

    inner_margin
Set inner margin for info display.

    position_increment_step
Set single increment step for position slider and spin box. Default is `5` meters.

    curve_grade_*
Set corner curve classification by radius (meters). Set value to `-1` to exclude from grade selection.

    length_grade_*
Set corner length classification by meters.

    slope_grade_*
Set road slope classification by slope percent.

[**`Back to Top`**](#)


## Track notes editor
**Track notes editor allows to create and edit track or pace notes, which can be accessed from `Tools` menu in main window.**

Note, by default the editor starts in `Pace Notes` edit mode as displayed in status bar.

**Important notes:** The editor does not provide `undo` function, it is recommended to save file before doing heavy modification.

The editor consists of two panel views:
* Left panel is the `Track Map Viewer`, which can be used to visualize track map and providing analytic info for assisting notes creation. See [Track Map Viewer](#track-map-viewer) section for details.

* Right panel is the track and pace notes editor, which allows to create, open, and save track or pace notes file.

The table view consists of multiple columns:
* `distance` column defines track position (in meters) of a note line.

* `pace note` column (in Pace Notes edit mode) defines `pace note` name that is used to match pace note sound file name.\
Note, DO NOT write file extension (format) in `pace note` column. File extension should be set in `Pace Notes` control panel tab from main window.

* `track note` column (in Track Notes edit mode) defines track-specific notes, such as `corner name` or `section name`.

* `tags` column attaches tags to specific notes, which will only be displayed or played under specific scenario. Currently the available tag is `#pit`. Notes that without `#pit` tag will not be displayed in pit lane.

* `comment` column defines optional extra info for `pace note` or `track note` column for user. Note, a comment can be broken into multiple lines by adding `\n` to any part of the comment.

To create or open pace notes, click `File` and select `New Pace Notes` or `Open Pace Notes`.

To create or open track notes, click `File` and select `New Track Notes` or `Open Track Notes`.

To save notes file, click `Save`. Note, notes file name should exactly match with track name from track map file name for `auto notes loading` function to work. The editor will try to retrieve track name automatically in an active session, or from an opened track map in `Track Map Viewer`.

To save notes file to other formats or for used in other games, select a file format name from `save type` in save dialog, such as `GPL Pace Notes (*.ini)` which saves pace notes in GPL pace notes file format. Note, only `TinyPedal` notes file formats are supported for used in Modern Tiny Pedals.

To hide map viewer, click `Hide Map`. To show map viewer, click `Show Map`.

To edit metadata info, click `Info`. Metadata info provides optional info to notes:
* `Title` of notes.
* `Author` of notes.
* `Date` when notes created or modified.
* `Description` about notes.

To set `distance` (position) value, first select one cell from `distance` column, then click `Set Pos` and click either `From Map` or `From Telemetry`. Note, `From Map` retrieves `distance` data from track map that opened in `Track Map Viewer`; `From Telemetry` retrieves `distance` data from current on-track vehicle position.

To add a note line, click `Add`, which adds a new note line at the end of notes table.

To insert a note line, first select a note line from notes table, then click `Insert` to insert a new note line `above` selected note line. To insert below selected note line, right-click on selected note line and click `Insert Row Below` from context menu.

To sort notes table, click `Sort`.

To delete notes, first select one or multiple note lines from notes table, then click `Delete`.

To replace words, click `Replace` and select a column, then use `Find` and `Replace` to find and replace words.

To batch offset `distance` (position) values, first select one or multiple note lines from `distance` column, then click `Offset` button. Click `Scale Mode` check box to scale distance values. Note, offset option will be reset to `0` each time after applying. Last applied offset value is displayed on top of dialog.

To highlight a `distance` value on `Track Map Viewer`, right-click on a note line and click `Highlight on Map`.

To add tag to specific notes, select one or more notes, right-click and click `Add Tag`, then select a tag name.

To remove all tags from specific notes, select one or more notes, right-click and select `Clear Tag`.

[**`Back to Top`**](#)


## Lap telemetry viewer
**Lap telemetry viewer compares laps recorded by [Recorder module](#recorder-module), which can be accessed from `Telemetry` button of navigation bar (`Ctrl+6`), or `Tools` menu in main window.**

Select track, then check laps to compare in lap list (one color per lap). Fastest valid lap is the reference lap by default, double-click a lap (or right click, `Set as Reference`) to change it. Lap list is grouped by session, newest first: each session row shows session type, start date & time, best lap, number of laps and vehicle, and can be collapsed (sessions with compared laps are expanded). Laps of a session are listed in driving order (`Lap 1`, `Lap 2`...) with lap time, sector times (fastest sector of track in purple) and lap info (invalid, out lap, in lap, other vehicle); invalid, out and in laps are dimmed. Laps recorded by this version keep the session start time, so a session is found even after a garage visit; older laps are grouped by session type, lap number and time between laps. Laps added from other folders or imported are grouped on top. Theoretical best (sum of fastest sectors) is shown below the list, and a warning appears when compared laps come from different vehicles. `Add File...` adds laps from another folder or track. It also imports a MoTeC i2 log (`.ld`), for example one from the built-in logger of Le Mans Ultimate or a lap shared by another driver: every complete lap of the log is converted to a lap file (lap time from start line crossing, between lap distance samples) (in the hidden `.imported` folder of the telemetry folder) and the fastest one becomes the reference lap. Pedals, speed, gear, steering, RPM, lap distance, tyres, brakes, ride height and G forces are imported when the log has them (worn tyre percent is turned into remaining percent), positions are not (no track map line).

`Imported Laps...` opens the library of imported laps, grouped by imported log: best lap time, track, vehicle, driver and import date of each lap. `Import MoTeC...` imports more logs (new logs shown expanded), a MoTeC log dropped on main window is imported too and its laps shown in lap viewer. The search field keeps logs and laps matching every typed word (log name, track, vehicle, driver, date, or lap time to find a lap). `Add to Viewer` (or double-click) shows selected laps (every lap of a selected log) in lap list, fastest one as reference. `Rename...` renames the selected log (lap files keep their name, lap time is read from it), `Delete` removes selected laps or logs from disk after confirmation. Laps already shown in lap list follow renames and deletions.

When the lap viewer page stays in background for 3 minutes, loaded laps are released from memory (several MB each), and loaded again with the same zoom when the page is shown.

Charts show values along lap distance, time delta of each lap against reference lap, and sector limits of reference lap. `Channels` selects shown charts: delta, speed, pedals, gear, steering, RPM, fuel, accelerations, TC & ABS activity, battery, elevation, and per wheel tyre temperature, pressure & wear, brake temperature, wheel speed, ride height and suspension (laps recorded by older versions only have the first channels). Speed, temperatures, tyre pressures and fuel follow the units setting (km/h or mph, °C or °F, kPa, psi or bar, liters or gallons); pedals and steering are shown in percent. `Time Gain/Loss` chart shows where time is lost (positive) or gained against reference lap, in seconds per 100 m (delta slope over 40 m). Distance (or time) is marked below charts, and each chart shows its highest & lowest values. Gear is drawn as steps. Corners are named with official corner numbers of the circuit (`T1`, `T10a`..., `V1` in French) on charts, track map and `Corners` tab, for Silverstone, Imola, Spa-Francorchamps, Circuit of the Americas, Interlagos, Paul Ricard (F1 layout), Monza, Bahrain, Portimão, Lusail, Road Atlanta, Laguna Seca and Long Beach; Le Mans corners are named (Dunlop, Tertre Rouge, Mulsanne, Arnage, Porsche Curves...). Official corners are placed on the apex of matching bends of the track (reference lap line, or track map file), every one is shown on track map, even flat out ones, and a corner found on speed covering several of them is named `T5-6`. Other circuits and layouts (other length) keep corners numbered in lap order (`T1`, `T2`...) from `Corners` tab. `Time axis` (saved) draws charts along lap time instead of lap distance, the zoomed part of lap is kept. Move mouse over charts to read values at a given distance: values of each lap are shown next to cursor in each chart, and above charts, colored like their lap. Charts are drawn by the graphics card: zoom & move are smooth and animated. Mouse wheel zooms, drag moves, `Shift` + drag zooms to selected area, and double-click (or `Reset`) resets zoom. Whole lap navigator below charts (reference lap speed) shows zoomed part: click or drag it to move. Keyboard: `+` / `-` zoom, `Left` / `Right` move, `Home` resets. Drag a channel name (left of charts) up or down to reorder channels, order is kept.

`Track Map` tab shows driving line of each lap and car position of each lap at cursor, over the circuit (from track map file of [Mapping module](#mapping-module) when recorded, else from reference lap line, start line checkered, sector limits marked). Line colors (saved): `Laps` (color of each lap, zoomed part highlighted), `Gain / Loss` (first compared lap against reference lap: red where it loses time, green where it gains, grey where even, rate of time difference over 40 meters, full color at 0.2 s per 100 m), `Speed` (reference lap, slowest blue to fastest red, scale below map) or `Pedals` (reference lap: throttle green, brake red, both amber, coasting grey). `Follow zoom` (saved) zooms map on the part of lap zoomed in charts. `Braking points` (saved) marks where each lap starts braking. Corner labels show time lost or gained by first compared lap in each corner, click one to zoom charts on it. Mouse wheel zooms track map around mouse (`+`, `-` and whole map buttons too, scale bar at bottom right), drag moves zoomed view, double-click resets. Click the driving line to show that point in charts (cursor moved there, view moved if it was outside). `G Circle` tab shows lateral vs longitudinal acceleration of each lap (zoomed part only when zoomed). `Corners` tab compares first compared lap with reference lap, corner by corner: corners are found on reference lap speed (speed minimum between two speed peaks, at least 10 km/h apart), each row shows time lost (red) or gained (green) from braking to top speed with a bar, minimum speed of both laps, and below: braking point (positive = brakes later) full throttle point (negative = full throttle earlier), and driving: seconds of trail braking (braking while turning), coasting (no pedal) and throttle & brake overlap of both laps (red when compared lap coasts or overlaps more). Click a corner to zoom charts on it. Two last rows show time lost on straights (between corners) and total lap difference, corners and straights add up to it. `Corner detection` sets the speed drop & rise counted as a corner (default 10 km/h, lower finds more corners), saved for next time. With reference lap only, the rows show its own corner times, minimum speeds and points.

`Export` > `MoTeC i2 (.ld)` saves reference lap, displayed laps, or every lap of track as MoTeC i2 log files (`.ld`), resampled at recording rate, with every recorded channel (pedals in percent), and vehicle, track & session from lap info. `Export` > `CSV, Displayed Laps...` saves displayed charts of displayed laps every meter in a CSV file for Excel (decimal comma and semicolon separator when system uses decimal comma).

Lap list: fastest valid lap of each session is starred, `Clean only` (saved) hides invalid, out & in laps (unless checked). Click a lap to show it, flag button or double-click to set it as reference. Right click a lap: `Set as Reference`, `Export MoTeC...`, and for recorded laps `Keep Lap` (a kept lap is never removed by the recorder when laps over `number_of_saved_laps_per_track` are deleted), `Note...` (free text shown in lap list), `Delete Lap` (asks first). Laps added from another folder or imported are grouped by folder. Checked laps and reference lap of each track are remembered. When 3 laps or more must be read, they load in background (window stays responsive), and `Refresh` only reads laps whose file changed.

[**`Back to Top`**](#)


## Session recorder
**Session recorder records Le Mans Ultimate shared memory while driving, and plays it back through every widget and module without the game, which can be accessed from `Advanced` section of `Tools` menu in main window.** Mostly useful to test overlays without the game, or to reproduce an issue (a recorded section can be attached to a bug report).

Requires `Le Mans Ultimate`, `rFactor 2` or `Le Mans Ultimate (legacy)` API. Click `Start Recording` while in game, and `Stop Recording` when done, or enable `enable_auto_replay_recording` in [Recorder module](#recorder-module). Recordings are saved as `.tpreplay` files in `telemetry` user path (roughly 7 MB per minute). Frames outside driving are skipped (see `enable_replay_skip_inactive_frames`). Recordings keep track, vehicle and session, lap changes, and incidents detected by Black box incident recorder. REST API data is recorded when it changes.

Replays of telemetry folder are listed with date, track, vehicle, session, duration and size. Double-click one (or `Open`), or use `Open Replay...` to pick a file elsewhere: Modern Tiny Pedals reads from it instead of the game until `Back to Game` is clicked. Frames are read from file when needed, so long replays use little memory.

Replay can be paused, sped up or slowed down, looped, and moved with the position slider, which shows lap changes (top ticks) and incidents (red bottom ticks). `Go to lap` jumps to a lap, `◀ Incident` / `Incident ▶` jump to 3 seconds before previous or next incident, and `|◀` / `▶|` move one frame. Keyboard: `Space` play/pause, `Left` / `Right` 5 seconds, `Shift` + `Left` / `Right` one frame.

`Set Start` and `Set End` select part of replay at current position, `Save Section...` saves it to a new replay file, to share an incident for example.

[**`Back to Top`**](#)


## Game replays
**Game replays lists replays saved by Le Mans Ultimate, adds and deletes replay files, opens them in the game, controls their playback and the game camera, shows the standings and jumps to incidents between cars, which can be accessed from `Tools` menu in main window.** Everything goes through the game Rest API: the game must be running, with Rest API access enabled in [Le Mans Ultimate API](#le-mans-ultimate-api).

- Game state: not answering, in the menus, in a session, or replay open, with the time of the last answer.
- Replays: each replay of `UserData/Replays` grouped by day, with track, session (game code such as `P1`, `Q1`, `R1`), event, event type, time and size. Search (every word must match track, event or session), session filter, sort by date, size or track. `Watch` (or double-click, `Enter`) opens the selected replay in the game, after confirmation. `Open Folder` opens the replay folder of the game.
- Replay files: `Add` (or files dropped on the page) copies `.Vcr` replay files to the replay folder of the game in background (under a temporary name until copied, a name already used gets a number, nothing copied without enough free disk space, `Stop Copy`), the game lists them at once. Row menu (right-click) and `...` menu: `Export` (copy to a chosen folder), `Rename`, `Protect From Deletion` (star: never deleted nor cleaned up), `Delete` (selected replays to the recycle bin, after confirmation; a replay open in the game is left in place). Clean up: replays older than a number of days, keep only the latest ones, temporary files of the game (`_vcr*.tmp`, older than 10 minutes). `Ctrl` + click adds a replay to the selection, `Shift` + click selects a range, `Ctrl+A` all, `Escape` clears. The replay folder is asked to the game (known even without any replay).
- Replay playback (enabled while a replay is open): rewind, play backwards, play / pause (`Space`, not while typing), play slowly (`½`), fast forward, other speeds in the `...` menu (fast rewind, slow backwards, very fast). Replay time read from the standings of the replay, moving between answers at the measured playback speed.
- Camera (in a session or a replay): camera on the previous or next car, car followed by the camera (by car slot: several cars can share a driver name). Camera groups of the game: `Driving`, `Onboard`, `Trackside`; a group button shows that group (again: next angle), arrows step to the previous or next angle of the group shown. Camera angle name shown. Eye button: game HUD shown or hidden, all of it or each part (chat, MFD, speedometer, timing, track map).
- Drivers: standings of the session or replay open in the game: position (class position with several classes), car number, driver, team or car, class color, laps, best lap (purple when fastest of its class), last lap, gap to leader (time or laps), pit stops, status (garage, in pits, finished, retired, disqualified), penalties, incidents of the driver (click: incidents panel with that driver only). Class chips show one class. Double-click, `Enter` or the camera button puts the camera on the car, right-click: camera, `Go to Lap...` (replay moved until the car is in that lap, from its lap times), incidents of the driver.
- Map: track & pit lane of the session or replay (game track map), cars at their position (class color, number, white ring: your car, accent ring: car followed by the camera, faded: in pits), gliding between answers. Click a car: camera on it. Wheel: zoom, drag: move, double-click: whole track.
- Incidents: contacts between cars of the session, or with track objects (`Wall`). Both sides of a contact, and contacts of the same cars less than 2 seconds apart, are merged into one incident. Car number and class from the game standings, player car marked, `All` / `Cars` / `Walls` filter, `My car`, driver chips (click again to see all drivers).
- Timeline: incidents along the whole session (session length from the game), replay position, drawn at once (long races). Click an incident to jump to it, click elsewhere to move the replay to that time; wheel: zoom, drag: move, double-click: whole session.
- `Jump to Incident` (or double-click, `Enter`, previous / next incident arrows) moves the replay open in the game `Seconds Before` the incident, camera on the player car if involved, else on the first car. Right-click: camera on the other car, or incidents of one driver only. In a live session: `Replay This Moment` opens the replay of the session there (game toggle, state read first), `Back to Live` returns. Export button: incidents shown copied to the clipboard (tab separated) or saved as CSV. Incidents & standings of the session left stay shown (`Last Session`).
- The game is asked only while the page is shown: every 2 seconds while a replay is open, 5 seconds otherwise, 15 seconds while the game does not answer. One connection per answer, one background thread. Standings are asked with each answer while `Drivers` or `Map` is shown or a replay is open, otherwise only when incidents change; track map once per track. Replays list asked again when a session ends (replay saved). `Refresh` (`F5`) asks everything at once. Seconds before, sort, filters, tab and protected replays are kept (`game_replays.json` in the config folder).

[**`Back to Top`**](#)


## Race results
**Race results shows the results of every session played, read from the results files the game writes at the end of each session (Le Mans Ultimate and rFactor 2: `UserData/Log/Results`), which can be accessed from `Tools` page in main window.** The game does not need to run.

- Sessions: newest first, grouped by day, with session kind (`R` race, `Q` qualifying, `P` practice, `W` warmup), track, time, car count, online or single player, and your result (overall position, class position with several classes, `DNF`). Search (every word must match track, layout, server, car or class), `All` / `Races` / `Qualifying` / `Practice` filter, sessions where nobody completed a lap hidden by default. `Up` / `Down` keys move between sessions. A session ending while the page is open is added at once (shown if the newest one was shown).
- Your car is found by the driver name of the game profile (`UserData/player/Settings.JSON`, also as one of the drivers of a team car), else as the only car driven by a person (single player). Every person online is a player for the game.
- Header: track, layout, date, online server or single player, session length, car count, track length. `Unfinished`: no car had finished when the file was written (race left before its end): classification and gaps of that moment, gaps from the lap times.
- Key figures: your position (class position and car count of your class), places gained from the grid, best lap (rank in your class, purple when fastest), laps and pit stops, contacts (with cars and walls), track limits points and penalties. Winner (or fastest car) and fastest lap when you were not in the session.
- `Classification`: position (places gained or lost from the grid in races), class & class position, number, driver & team (drivers of a team car in the tooltip), car, laps, race time of winner then gap (time, or laps behind; best lap gap in practice & qualifying), best lap (fastest in purple), pit stops, contacts (warning sign: penalties). Your row is tinted. Class chips show one class (class positions). Click a car to pick it, double-click to see its laps.
- `Positions` (races): place of every car at the end of each lap, grid at lap 0 (class places when a class is shown). Your car in accent color, car picked in text color, others in their class color. Hover: name of the nearest car, click: pick it.
- `Laps`: laps of the car picked (or picked in the list): place, lap time (session best purple, own best green), gap to own best, sectors (same colors), top speed (speed unit of [Units](#units)), front tyre compound, pit lane, energy (else fuel) used and tyre tread left for your car. Best lap, average & consistency of clean laps (no pit lane, not lap 1), theoretical best (best sectors), top speed, laps through pit lane.
- `Events`: contacts (both reports of a contact shown once, impact strength), penalties (kind, time, reason), track limits (warnings, invalidated laps, points) and chat, by session time, `All` / `Contacts` / `Penalties` / `Track Limits` / `Chat` filter with counts, `Car picked only`. Game texts (retirement reasons, penalties) are shown in app language.
- Results folder: found in every Steam library (Le Mans Ultimate, rFactor 2). Folder button: open it, choose another folder (game not installed with Steam, results copied elsewhere), or back to game folders. Files are read in background, only new or changed ones again (`F5`). Filters, tab and folder are kept (`race_results.json` in the config folder). The last race can also be shown on stream, see [Stream Overlay](#stream-overlay).

[**`Back to Top`**](#)


## Layout editor
**Layout editor places and aligns overlay widgets on a game screenshot, which can be accessed from `Tools` menu in main window.**

Enabled widgets are shown as boxes over the whole desktop. `Load Screenshot...` uses a game screenshot as background, `Capture Screen` grabs primary screen. Drag a box to move it: edges and centers snap to other widgets, screen edges and screen center (turn off with `Snap`, or hold `Alt`). Arrow keys nudge selected widget by 1 pixel (`Shift`: 10 pixels). `Apply` moves widgets and saves positions to preset, `Reset` reloads current positions.

[**`Back to Top`**](#)


## Overlay theme editor
**Overlay theme editor creates custom overlay color themes, which can be accessed from `Tools` menu in main window.**

Click `New` to create a theme (copy of current theme), and select `Based on` theme. Double-click a color in `Theme color` column to change it, or type a hex color code. `Reset Color` restores base theme color. Preview shows a few widgets with edited theme. `Apply` or `Save` applies theme to all widgets using it. Undo & redo are available (`Ctrl+Z`, `Ctrl+Y`).

[**`Back to Top`**](#)


## Preset comparison
**Preset comparison lists different options between two presets, which can be accessed from `Tools` menu in main window, or from `Preset` tab context menu.**

Select `Preset A` and `Preset B`. Widget positions can be ignored. Select one or more rows, then click `Copy B → A` or `Copy A → B` to copy option values, and `Save` to write changes to preset files.

[**`Back to Top`**](#)


## Plugin manager
**Plugin manager lists widget plugins, which can be accessed from `Tools` menu in main window.**

Shows each plugin loading status and error message. Plugins can be enabled or disabled, code can be reloaded without restarting Modern Tiny Pedals (`Reload Code`), and new plugins can be installed from `.zip` package (`Install...`). See [Widget plugins](#widget-plugins) section for details.

[**`Back to Top`**](#)


## Other tools
* `Find Option...` (`Config` menu, `Ctrl+F`): search any option in all widgets, modules and global settings, in English or in current language. Double-click a result to open its page: Overlay Options page at a widget option, config dialog filtered on a module option.
* `Setup Wizard` (`Help` menu): first launch setup (language, game, units, themes, preset, starter overlays).
* `Widget Performance` (`Help` menu): update & paint time of each widget, and CPU & memory usage of Modern Tiny Pedals, modules and game connection.
* `Create Bug Report...` (`Help` menu): creates a `.zip` file with logs, settings and system info to attach to a bug report. User folder name, access codes and repository names are removed.

[**`Back to Top`**](#)


# Modules
Modules provide important data that updated in real-time for other widgets. Widgets may stop updating or receiving readings if corresponding modules were turned off. Each module can be configured by accessing `Config` button from `Module` tab in main window.

[**`Back to Top`**](#)


## Delta module
**This module provides deltabest and timing data.**

On an out lap (lap started in pit lane or garage: back to garage starts a new lap, and time spent there counts) and while in pit lane before start line, delta is not comparable to reference laps: delta overlays (Deltabest, Deltabest extended, Black box, web dashboard) show a dash, Delta graph line is interrupted, estimated lap time (Timing, Lap time history) is left empty, and delta to last lap of Lap time history shows a dash until a lap without pit lane is completed.

    module_delta
Enable delta module.

    minimum_delta_distance
Set minimum recording distance (in meters) between each lap time sample. Default value is `5` meters. Lower value may result more samples recorded and bigger file size; higher value may result less samples recorded and inaccuracy. Recommended value range in `5` to `10` meters.

    delta_smoothing_samples
Set number of samples for reducing data fluctuation. Higher value results more smoothness, but may lose accuracy. Default is `30` samples. Set to `1` to disable smoothing.

    laptime_pace_samples
Set number of samples for average laptime pace calculation. Default is `6` samples. Set `1` to disable averaging. Note, initial laptime pace is always based on player's all time personal best laptime if available. If a new laptime is faster than current laptime pace, it will replace current laptime pace without calculating average. Invalid lap, pit-in/out laps are always excluded from laptime pace calculation.

    laptime_pace_margin
Set additional margin for laptime pace that cannot exceed the sum of previous `laptime pace` and `margin`. This option is used to minimize the impact of unusually slow laptime. Default value is `5` seconds. Minimum value is limited to `0.1`.

[**`Back to Top`**](#)


## Force module
**This module provides vehicle g force, downforce, braking rate data.**

    module_force
Enable force module.

    gravitational_acceleration
Set gravitational acceleration value on earth.

    maximum_g_force_reset_delay
Set time delay in seconds for resetting maximum g force reading.

    maximum_average_g_force_samples
Set amount samples for calculating maximum average g force. Minimum value is limited to `3`.

    maximum_average_g_force_difference
Set maximum average g force difference threshold which compares with the standard deviation calculated from maximum average g force samples. Default is `0.2` g.

    maximum_average_g_force_reset_delay
Set time delay in seconds for resetting maximum average g force. Default is `30` seconds.

    maximum_braking_rate_reset_delay
Set time delay in seconds for resetting maximum braking rate. Default is `60` seconds.

[**`Back to Top`**](#)


## Fuel module
**This module provides vehicle fuel and virtual energy usage data.**

In a time race, laps left (fuel & energy needed to finish, pit stops) include the lap a car behind the leader drives once the timer ended (the race ends when the leader crosses the line after the timer, from `Vehicles module`), as the race calculator plans it.

    module_fuel
Enable fuel module.

    minimum_delta_distance
Set minimum recording distance (in meters) between each fuel usage sample. Default value is `5` meters. Lower value may result more samples recorded and bigger file size; higher value may result less samples recorded and inaccuracy. Recommended value range in `5` to `10` meters.

    fuel_density
Set fuel density (kg/liter), which affects the accuracy of fuel weight calculation. Fuel density may vary depending on the type of fuel used. Default is `0.75` kg/liter. Note, for pure electric vehicle, set density to `0`, such as Formula E.

    enable_green_flag_consumption
Estimate fuel and virtual energy consumption per lap from the median of the last valid green flag laps, instead of the last valid lap. Laps under full course yellow or safety car, pit in and out laps, and invalid laps (no lap time, or track limits in LMU) are left out, so a neutralisation never makes the estimate drop. The last valid lap is used until 3 green flag laps are driven. A real change of consumption (fuel map, fuel saving) shows a few laps later than with the last lap. Default is disabled.

    number_of_green_flag_laps
Set number of last valid green flag laps the median consumption is taken from. Default is `5` laps.

[**`Back to Top`**](#)


## Hybrid module
**This module provides vehicle battery usage and electric motor data.**

    module_hybrid
Enable hybrid module.

    minimum_delta_distance
Set minimum recording distance (in meters) between each battery charge usage sample. Default value is `5` meters. Lower value may result more samples recorded and bigger file size; higher value may result less samples recorded and inaccuracy. Recommended value range in `5` to `10` meters.

[**`Back to Top`**](#)


## Mapping module
**This module records and processes track map data.**

    module_mapping
Enable mapping module.

[**`Back to Top`**](#)


## Notes module
**This module processes track and pace notes data.**

    module_notes
Enable notes module.

[**`Back to Top`**](#)


## Recorder module
**This module records player telemetry of each complete lap to CSV file. Enabled by default.**

Files are saved in `telemetry_path` folder, one sub folder per track & class: `<date time> lap<number> <lap time>.csv`. Laps are verified with game lap time 1 to 10 seconds after crossing start line; laps that are not confirmed (track limits, invalid lap) are marked `invalid` in file name. Recorded laps can be compared in [Lap telemetry viewer](#lap-telemetry-viewer).

First line of each file is lap info (`# ` followed by JSON): track, vehicle, class, session, track length, track & air temperature, wetness, fuel at start & end, official sector times, lap kind (`lap`, `out` or `in`) and app version. Then comes the CSV header and one row per sample: time, lap time, distance, speed, pedals, steering, gear, RPM, fuel, tyre temperatures & pressures, position (X, Y, Z), lateral & longitudinal acceleration (G), sector, TC & ABS activity, battery charge, and per wheel brake temperature, tyre wear (remaining percentage, 100 = new tyre), wheel speed (requires Wheels module, which learns wheel radius), ride height & suspension deflection (millimeters). Throttle & brake are unfiltered pedal positions (driver input, without throttle blip or cut from car electronics on gear shifts). Samples are only added when game data has changed. A lap is dropped if game time goes backward (replay looping or rewound).

The module can also record [Session recorder](#session-recorder) replays automatically while driving.

    enable_lap_recording
Record laps to CSV files. Default is enabled.

    enable_lap_recording_during_replay
Record laps while a telemetry replay is playing. Laps are named after the time they were driven, and lap info tells which replay they come from. Default is disabled, as replayed laps were already recorded while driving.

    minimum_lap_distance_percentage
Minimum lap distance (percentage of track length) that must be recorded for a lap to be saved. Default is `90`.

    number_of_saved_laps_per_track
Maximum number of laps kept per track & class folder, oldest laps are removed. Default is `50`.

    number_of_best_laps_kept_per_track
Number of fastest valid laps never removed from track & class folder, even when they are the oldest. Default is `3`.

    save_invalid_laps
Save laps that are not confirmed as valid (marked `invalid`). Default is enabled.

    enable_out_and_in_lap_recording
Also save out laps (started in pit lane) and in laps (ended in pit lane), marked as such in lap info. Out laps are saved when start line is crossed in pit lane. Default is disabled.

    enable_compressed_lap_files
Save laps as compressed CSV files (`.csv.gz`, about 5 times smaller). Lap telemetry viewer reads both. Default is disabled.

    enable_auto_replay_recording
Start recording a telemetry replay when driving starts, and stop it 10 seconds after leaving driving (requires `Le Mans Ultimate` or `rFactor 2` API). Automatic recordings are named `replay-auto-<date time>.tpreplay`. A recording stopped from Session recorder window is not restarted until next driving. Default is disabled.

    enable_replay_skip_inactive_frames
Do not record replay frames outside driving (menus, garage, monitor), so replays only contain driving. Also applies to recordings started from Session recorder window. Default is enabled.

    number_of_saved_replays
Maximum number of automatic replay recordings kept, oldest are removed. Manual recordings are never removed. Default is `20`.

[**`Back to Top`**](#)


## Relative module
**This module provides vehicle relative and standings data.**

    module_relative
Enable relative module.

[**`Back to Top`**](#)


## Sectors module
**This module provides sectors timing data.**

    module_sectors
Enable sectors module.

[**`Back to Top`**](#)


## Stats module
**This module records driver stats data.**

**Important notes:** Driver stats will not be recorded while:
- `enable_player_index_override` or `enable_active_state_override` option is enabled in [Telemetry API](#telemetry-api).
- `Single instance mode` is disabled via [Command Line Arguments](#command-line-arguments).

Stats are only saved when driver returned to garage. Each driving stint is also added to session history (`driver.history`). Race sessions count a start once driven after green flag, a DNF when not finished or disqualified, and finish positions for average finish position.

    module_stats
Enable stats module.

    vehicle_classification
Set one of the three vehicle classifications where stats will be saved.

`Class - Brand` saves corresponding stats under class and brand name. Make sure to use [Vehicle Brand Editor](#vehicle-brand-editor) to import brand name. If brand name does not exist, only class name will be used instead.

`Class` saves corresponding stats under class name only.

`Vehicle` saves corresponding stats under vehicle name only. Saving stats under vehicle name is not recommended, because each single vehicle in `RF2` or `LMU` uses unique vehicle name, which will result multiple records of the same vehicle.

    enable_podium_by_class
Enable to count race finish position by class instead of overall position.

[**`Back to Top`**](#)


## Stint module
**This module provides lap and stint history data.**

    module_stint
Enable stint module.

    minimum_stint_threshold_minutes
Set the minimum stint time threshold in minutes for concluding current stint. This only affects ESC.

    minimum_pitstop_threshold_seconds
Set the minimum pit stop time threshold in seconds for concluding current stint. Default is `3` seconds.

This option is useful for detecting pit stop that does not refuel or change tyres. It also allows to detect pit stop while spectating other player with [Spectate Mode](#spectate-mode).

    minimum_tyre_temperature_threshold
Set the minimum tyre carcass temperature (Celsius) threshold for calculating lap time delta and consistency. Default is `55` degrees.

This option helps to exclude slow lap time due to cold tyres from calculation.

[**`Back to Top`**](#)


## Vehicles module
**This module provides additional processed vehicles data.**

    module_vehicles
Enable vehicles module.

    lap_difference_ahead_threshold
Lap difference (percentage) threshold for tagging opponents as ahead. Default is `0.9` lap.

    lap_difference_behind_threshold
Lap difference (percentage) threshold for tagging opponents as behind. Default is `0.9` lap.

    finish_time_difference_threshold
Set estimated finish time difference threshold between race leader and local player for determine the shortest race length (either in laps or time). Default threshold is `200` seconds (roughly a lap at LeMans).

- When finish time difference is lower than threshold, shortest race length is determined by player's lap time pace. This is useful for compensating strategy difference within the same leading class, and potentially catching up with leader.
- When finish time difference is higher than threshold, shortest race length is determined by leader's lap time pace. This is useful for much slower classes to align their finish time towards the leading class.

This option is used for adaptive race length and fuel calculation for `Lap` or `Laps & Time` finish criteria based race, which automatically determines the shortest race length and calculates fuel usage accordingly for increased accuracy and efficiency. This option only affects `Lap` or `Laps & Time` based race. `Time` based race is not affected by this option.

Unlike `Time` based race, finish criteria in `Laps & Time` based race is determined by both `remaining laps` and `remaining time` (whichever reaches zero first), such as seen from Qatar 1812km event.

[**`Back to Top`**](#)


## Wheels module
**This module provides wheel radius, slip ratio, tyre wear, brake wear, suspension travel, vehicle weight data.**

    minimum_axle_rotation
Set minimum axle rotation (radians per second) for calculating wheel radius and differential locking percent. Default value is `4`.

    maximum_rotation_difference_front, maximum_rotation_difference_rear
Set maximum rotation difference between left or right wheel rotation and same axle rotation for limiting wheel radius calculation. Default value is `0.002` (0.2%). Setting higher difference value may result inaccurate wheel radius reading.

    wheel_lock_threshold
Set percentage threshold for counting wheel lock duration under braking. `0.3` means 30% of tyre slip ratio.

    minimum_delta_distance
Set minimum recording distance (in meters) between each tyre wear sample. Default value is `5` meters. Lower value may result more samples recorded and bigger file size; higher value may result less samples recorded and inaccuracy. Recommended value range in `5` to `10` meters.

    enable_suspension_measurement_while_offroad
Enable suspension travel measurement while vehicle is offroad. This option should be disabled for road racing for more accurate suspension measurement. This option is disabled by default.

    average_suspension_position_samples
Set amount samples for calculating average suspension position, which helps to filter out unusual data. Default is `20`. Minimum value is limited to `3`.

    average_suspension_position_margin
Set additional margin that cannot exceed the sum of previous `average suspension position` and `margin`. This option is used to minimize the impact of unusual data. Default value is `1` millimeter. Minimum value is limited to `0.1`.

    wheel_lift_off_threshold
Set millimeter threshold of tyre vertical deflection for detecting lifted wheels. Suspension travel is not calculated from wheel that is lifted off the ground (as below the threshold). Default threshold is `1` millimeter. Set to `-1` to always calculate suspension travel even if wheel is lifted off.

    estimated_unsprung_weight
Set estimated total unsprung weight (in kilograms), which will be added to auto-estimated sprung weight for calculating estimated weight. This option is only used if weight cannot be measured from tyre load. Default is `200` kilograms (rough estimate).

    minimum_static_weight_override
Manually set minimum static weight (in kilograms) excluding fuel, which overrides any estimated weight measurement. Set to `-1` to disable override.

This option may be used if weight cannot be automatically measured or inaccurate due to lack of weight data from game API.

[**`Back to Top`**](#)


# Widgets
Each widget can be configured by accessing `Config` button from `Overlays` tab in main window.

## Modern design
With `Modern Dark` or `Modern Light` overlay theme in [Overlay Style](#overlay-style), every widget uses its modern design: one panel with rounded corners, short labels above or beside values, values colored by meaning (gain, loss, warning, best), gauges, tyre & brake tiles in heatmap colors, class colored pills. Labels follow application language. Colors follow `overlay_theme` and `enable_colorblind_colors`.

Modern design reads fewer options than classic layout: per cell colors, fonts and paddings are set by design, so Overlay Options page shows only the options the design reads. Fonts follow `enable_modern_font`: labels in `modern_design_font_name` and values in `modern_font_name` while enabled, else every text in widget `font_name` (then shown in Overlay Options page). Relative, standings and rivals choose their columns with `column_*` options. Each widget keeps its classic options: select a `Legacy` overlay theme (all widgets) or enable `enable_classic_layout` (one widget) to use classic layout again.

Display order options (`display_order_*`) apply where modern layout has the same rows, tiles, bars or columns: design order is kept while every display order option of a widget is at default value, and display order options set the order once one of them is changed. Fuel, virtual energy, pit stop estimate, acceleration, sectors and brake temperature keep design order (their modern layout has no matching rows). Classic text options (pit status texts, leader texts, session names, speed limiter text) replace design labels once changed from default value.

Black box and pace notes keep their own drawing with design font (widget `font_name` while `enable_modern_font` is disabled) & theme colors; their options other than fonts and the colors set by design (background, colors left at default value) are shown, so other colors can still be customized.

Widget context menu can be accessed by `Right-Click` on widget, which provides additional options:
- Center horizontally: align widget to the center of active screen horizontally.
- Center vertically: align widget to the center of active screen vertically.

[**`Back to Top`**](#)


## Acceleration
**This widget displays acceleration timing info.**

This widget shows active, last, best, and delta acceleration time (in seconds) that measured from customizable target speed range. To reset best acceleration time, shift gear into reverse, or reload widget.

Note, timing precision is limited by `game API` and `update_interval`, which may not provide high decimal precision.

    layout
Set column horizontal display order. Set `0` to show from left to right. Set `1` to show from right to left instead.

    speed_range_*_start, speed_range_*_end
Set the start and end target speed values for measuring acceleration time. Speed value is defined in meter per second, and displayed according [Speed Units](#units) setting. To hide specific slot, set both target speed values to `0`.

Note, to properly count acceleration from `0` start speed, set slightly higher value such as `0.6` instead of '0', because vehicle in game will not be sitting perfectly still at 0 speed while stopped.

    speed_drop_threshold
Set threshold for detecting speed drop during acceleration timing, which cancels timing when speed dropped below threshold. Default is `1` m/s.

[**`Back to Top`**](#)


## Battery
**This widget displays battery usage info.**

Note, there are some electric vehicles in `RF2` that are not based on the new electric motor and battery charge system, which there is no battery usage info available.

    show_battery_charge
Show percentage available battery charge.

    show_battery_drain
Show percentage battery charge drained in current lap.

    show_battery_regen
Show percentage battery charge regenerated in current lap.

    show_estimated_net_change
Show estimated battery charge net change from current lap. Positive value indicates net gain (regen higher than drain); negative indicates net loss (drain higher than regen).

Total net change reading is more accurate for vehicles that constantly consume battery charge, such as `FE` or `Hypercar` class. It is less useful for vehicles that only utilize electric motor for a short duration, such as `Push to pass`.

Note, at least one full lap (excludes pit-out or first lap) is required to generate estimated net change data.

    show_activation_timer
Show electric boost motor activation timer.

    show_state_of_charge
Modern design: show battery state of charge as shown by game (`LMU`), or battery charge (`RF2`), while electric motor is available. Off by default.

    high_battery_threshold, low_battery_threshold
Set percentage threshold for displaying low or high battery charge warning indicator. Default high threshold is `95` percent (default color purple), low threshold is `10` percent (default color red).

    show_battery_charge_warning_flash
Show battery charge warning flash effect when battery charge decreased below `low_battery_threshold` or increased above `high_battery_threshold`.

    number_of_warning_flashes
Set number of warning flashes that will be played for a limited number of times. Default is `10` flashes. Minimum value is limited to `3`.

    warning_flash_highlight_duration
Set color highlight duration for each warning flash. Default is `0.4` seconds. Minimum value is limited to `0.2`.

    warning_flash_interval
Set minimum time interval between each warning flash. Default is `0.4` seconds. Minimum value is limited to `0.2`.

    freeze_duration
Set freeze duration (seconds) for displaying previous lap total drained/regenerated battery charge after crossing finish line. Value range in `0` to `30` seconds. Default is `10` seconds.

[**`Back to Top`**](#)


## Brake bias
**This widget displays brake bias info.**

    show_front_and_rear
Show both front and rear bias. Default is `false`.

    show_percentage_sign
Set `true` to show percentage sign for brake bias value.

    show_baseline_bias_delta
Show delta between current and baseline brake bias, which can be useful for keeping track of brake bias changes easier during a long race. Baseline brake bias is automatically set (and reset) while vehicle is stationary in pit lane or stationary during formation lap.

    show_brake_migration
Show real-time brake migration change, as commonly seen in LMH and LMDh classes.

Note, brake migration is calculated based on brake input and brake pressure telemetry data, and is affected by pedal force setting from car setup and electric braking allocation of specific vehicle.

To get accurate brake migration reading, it is necessary for brake pedal to reach fully pressed state for at least once while entering track to recalibrate brake pressure scaling for brake migration calculation. It is normally not required to do manually, as game's auto-hold brake assist is on by default. However if auto-hold brake assist is off, or the APP was reloaded while player was already on track, then it is required to do a full braking for at least once to get accurate brake migration reading.

    electric_braking_allocation
Set allocation for calculating brake migration under different electric braking allocation from specific vehicle. Note, vehicle that has not electric braking, or has disabled regeneration, is not affected by this option. Incorrect allocation value will result wrong brake migration reading from vehicle that has electric braking activated.

Set value to `-1` to enable auto-detection, which automatically checks whether electric braking is activated on either axles while braking, and sets allocation accordingly. This is enabled by default. Note, it may take a few brakes to detect correct allocation.

Set value to `0` to manual override and use front allocation, which is commonly seen in LMH class.

Set value to `1` to manual override and use rear allocation, which is commonly seen in LMDh class.

[**`Back to Top`**](#)


## Brake performance
**This widget displays brake performance info.**

    show_transient_maximum_braking_rate
Show transient maximum braking rate (g) from last braking input, and resets after 3 seconds.

    show_maximum_braking_rate
Show maximum braking rate (g), and resets after a set period of time that defined by `maximum_braking_rate_reset_delay` value in Force Module.

    show_delta_braking_rate
Show maximum braking rate difference (g) against transient maximum braking rate, and resets on the next braking.

    show_delta_braking_rate_in_percentage
Show maximum braking rate difference (g) in percentage (%) instead.

    show_front_wheel_lock_duration, show_rear_wheel_lock_duration
Show maximum front and rear wheel lock duration (seconds) per lap under braking. Duration increases when tyre slip ratio has exceeded `wheel_lock_threshold` value that set in [Wheels Module](#wheels-module), and resets on first braking input of a new lap.

[**`Back to Top`**](#)


## Brake pressure
**This widget displays visualized percentage brake pressure info.**

    show_brake_input
Show raw brake input on each brake. This option can be useful to check amount difference between brake input and applied brake pressure.

[**`Back to Top`**](#)


## Brake temperature
**This widget displays brake temperature info.**

Note, if temperature drops below `-100` degrees Celsius, temperature readings will be replaced by unavailable sign as `-`. This usually indicates brake failure, or brake is not available on one of the wheels.

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    enable_heatmap_auto_matching
Enable automatically heatmap style matching for specific brakes defined in `brakes.json` preset. This option applies matching heatmap style to front and rear brakes separately.

    heatmap_name
Set heatmap preset name that is defined in `heatmap.json` preset. Note, this option has no effect while `enable_heatmap_auto_matching` is enabled.

    swap_style
Swap heatmap color between font and background color.

    show_degree_sign
Set `true` to show degree sign for each temperature value.

    leading_zero
Set amount leading zeros for each temperature value. Default is `2`. Minimum value is limited to `1`.

    show_average
Show average brake temperature calculated from most recent braking period. The braking period is defined by `average_sampling_duration` and `off_brake_duration` options.

    average_sampling_duration
Set duration (seconds) for calculating average brake temperature from most recent braking period. Default is `10` seconds. Maximum duration is limited to `600` seconds.

    off_brake_duration
Set duration (seconds) for continuously updating average brake temperature for a short period after fully released brakes. Default is `1` seconds.

[**`Back to Top`**](#)


## Brake wear
**This widget displays brake wear info.**

**Important notes:** Brake wear data is currently only available on `LMU`. `RF2` currently doesn't provide brake wear data. Depends on vehicle, brake may or may not have noticeable wear.

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_thickness
Show brake thickness (millimeter) instead of percentage, which also affects wear difference readings.

Note, brake maximum thickness (for percentage wear calculation) is retrieved at the moment when car leaves garage or has brake repaired or changed. Reloading a preset or restarting APP in the middle of a running stint could result wrong maximum thickness and percentage wear calculation, which should be avoided.

**Notes to brake failure thickness:**

Brake failure thickness is millimeter thickness threshold at brake failure, which affects brake wear calculation accuracy, and can be customized for specific vehicle class in [Brake Editor](#brake-editor).

For example, if `brake thickness` is `40`mm, and `failure thickness` is `25`mm, then `effective thickness` is `40 - 25 = 15mm`. And brake fails upon reaching `25`mm thickness. Note, each installed brake may have a random failure thickness variation of `±0.1`mm.

Since brake failure thickness threshold data is not available from game API, it requires testing to find out, and may vary from vehicle to vehicle. Front brake failure thickness threshold can be different from rear brake. Thickness threshold value should not exceed brake maximum thickness, otherwise brake wear readings will not be displayed correctly.

Note, failure thickness values are automatically saved to `brakes.json` preset when brakes failed, and most recent brake failures are logged and can be found in [Show Log](#console-log) dialog from `Help` menu.

**Tips for testing failure thickness:**

Before start, make sure vehicle brand data is imported via [Vehicle Brand Editor](#vehicle-brand-editor). This is necessary to save brake failure thickness settings per vehicle brand.

First, set all `brake duct` settings to `closed` in car setup, then keeps brakes on while driving at around 100kph speed until brakes failed (use brake bias to control front and rear wear rate), and failure thickness value will be automatically saved for this vehicle. Be aware that testing may take a very long time for some vehicles.

    show_remaining
Show total remaining brake in percentage that changes color according to wear. A `FAIL` text will be shown on failed brakes.

    show_wear_difference
Show estimated brake wear difference per lap (at least one valid lap is required).

    show_live_wear_difference
Show current lap brake wear difference.

    show_lifespan_laps
Show estimated brake lifespan in laps.

    show_lifespan_minutes
Show estimated brake lifespan in minutes.

    warning_threshold_remaining
Set warning threshold for total remaining brake in percentage. Default is `30` percent.

    warning_threshold_wear
Set warning threshold for total amount brake wear of last lap in percentage. Default is `1` percent.

    warning_threshold_laps
Set warning threshold for estimated brake lifespan in laps. Default is `5` laps.

    warning_threshold_minutes
Set warning threshold for estimated brake lifespan in minutes. Default is `5` laps.

[**`Back to Top`**](#)


## Chat
**This widget displays chat messages of the game (LMU, Rest API `enable_race_info` option), newest at bottom.** Long messages are wrapped on several lines, newest messages kept when lines run out.

Modern design: one card growing with lines shown, sender name in its own color (same color for a sender all race), messages just sent highlighted with an accent edge, messages fading out at the end of `maximum_display_duration`. While overlay is unlocked, an empty card is shown so it can be placed.

    number_of_lines
Set number of message lines. Value range in `1` to `20`. Default is `5`.

    line_width
Set width of message lines, value in chars. Longer messages are wrapped. Default is `40`.

    maximum_display_duration
Set duration (seconds) each message stays shown after it was sent. Set to `0` to always show last messages. Default is `30`.

    new_message_duration
Set duration (seconds) a new message is shown in `font_color_new_message`. Default is `5`.

    show_message_time
Show time of day each message was sent.

[**`Back to Top`**](#)


## Cruise
**This widget displays compass, elevation, odometer info.**

    show_compass
Show compass directions with three-figure bearings that matches game's cardinal directions.

    show_elevation
Show elevation difference in game's coordinate system.

    show_odometer
Show odometer that displays total driven distance of local player.

    odometer_maximum_digits
Set maximum number of display digits.

    show_distance_into_lap
Show distance into current lap.

[**`Back to Top`**](#)


## Damage
**This widget displays visualized vehicle damage info.**

**Wheel (suspension) damage levels**

1. No damage to suspension or wheel (default color: green).
2. Light suspension damage (default damage range: 2% - 15%, default color: yellow).
3. Medium suspension damage (default damage range: 15% - 40%, default color: orange).
4. Heavy suspension damage (default damage range: 40% - 80%, default color: purple).
5. Totaled suspension (default damage range: 80% - 100%, default color: blue).
6. Wheel detached (default color: black).

Note, body aero integrity and suspension damage display is only available for `LMU`.

    display_margin
Set display margin in pixels.

    inner_gap
Set body parts inner gap in pixels.

    part_width
Set body parts width in pixels. Minimum value is limited to `1`.

    parts_width_ratio
Set width ratio between side and center body parts. Value range in `0.1` to `1.0`.

    parts_maximum_width, parts_maximum_height
Set maximum body parts width, height in pixels. Minimum value is limited to `4`.

    wheel_width, wheel_height
Set wheel width, height in pixels. Minimum value is limited to `1`.

    puncture_outline_width
Set outline width for drawing tyre puncture indication.

    show_background
Show widget background.

    suspension_damage_*_threshold
Set suspension damage level percentage threshold for suspension damage color indication, which better reflects severity of suspension damage that would affect handling.

    show_detached_warning_flash
Show warning flash for detached parts, such as wings and wheels.

    warning_flash_highlight_duration
Set color highlight duration for each warning flash. Default is `0.5` seconds. Minimum value is limited to `0.2`.

    warning_flash_interval
Set minimum time interval between each warning flash. Default is `0.5` seconds. Minimum value is limited to `0.2`.

    show_last_impact_cone
Show cone indicator towards last known impact (collision) position.

    last_impact_cone_angle
Set cone angle (size) in degrees. Value range in `2` to `90`. Default is `15`.

    last_impact_cone_duration
Set cone indicator display duration (seconds) for last known impact. Default is `15` seconds.

    show_integrity_reading
Show vehicle bodywork integrity reading in percentage. Note, bodywork damage may not necessarily affect aero or handling.

    show_aero_integrity_if_available
Show vehicle body aero integrity reading in percentage if available, which better reflects severity of bodywork damage that would affect performance.

    show_inverted_integrity
Invert integrity reading.

[**`Back to Top`**](#)


## Damage stats
**This widget displays vehicle damage stats info.**

    show_integrity_prefix
Show prefix for each integrity reading.

    show_aero_integrity
Show body aero integrity reading.

    show_body_integrity
Show bodywork integrity reading.

    show_suspension_integrity
Show suspension integrity reading, measured from the wheel with the lowest suspension integrity.

    show_tyre_integrity
Show tyre integrity reading, measured from the wheel with the lowest tread depth.

    low_*_integrity_threshold
Set low integrity threshold for displaying warning indication.

[**`Back to Top`**](#)


## Delta graph
**This widget displays delta to reference lap along current lap distance, as a graph.**

The graph spans one lap, from start/finish line on the left to end of lap on the right. Time lost against reference lap is drawn above zero line in loss color, time gained below zero line in gain color. Previous lap is drawn as a faint line behind current lap, and a position mark follows the car along the lap. Delta is the same as in [Deltabest](#deltabest) widget, `Delta module` must be enabled.

    display_width, display_height
Set graph width and height in pixels.

    deltabest_source
Set lap time source for delta graph. Available values are: `Best` = all time best lap time, `Session` = session best lap time, `Stint` = stint best lap time, `Last` = last lap time.

    delta_display_range
Set maximum delta (gain or loss) in seconds shown at top and bottom of graph, accepts decimal place. Larger delta is drawn at graph edge. Default is `2` seconds.

    show_delta_reading
Show current delta reading above graph.

    show_previous_lap
Show delta of previous lap as a faint line behind current lap.

    show_position_mark
Show current position along the lap as a vertical line, with a dot at current delta.

[**`Back to Top`**](#)


## Deltabest
**This widget displays deltabest info.**

No delta is shown (a dash) on an out lap, that is a lap started in pit lane or garage (back to garage starts a new lap, time spent there counts), while in pit lane before start line, or while the reference lap does not exist yet (stint best before first lap of stint, last lap after an out lap). See [Delta module](#delta-module).

    layout
2 layouts are available: `0` = delta bar above deltabest text, `1` = delta bar below deltabest text.

    swap_style
Swap time gain and loss color between font and background color.

    deltabest_source
Set lap time source for deltabest display. Available values are: `Best` = all time best lap time, `Session` = session best lap time, `Stint` = stint best lap time, `Last` = last lap time. This option can be changed on fly via [global hotkey](#hotkey).

    show_game_deltabest_if_available
Show delta to best lap computed by game (`LMU`) instead of delta computed by APP, when game provides it. Game delta compares against best lap as defined by game (as shown in game), whatever `deltabest_source` is. Delta computed by APP is used when game delta is unavailable (`RF2`). Default is disabled.

    show_delta_bar
Show visualized delta bar.

    delta_bar_length, delta_bar_height
Set delta bar length and height in pixels.

    delta_bar_display_range
Set maximum display range (gain or loss) in seconds for delta bar, accepts decimal place. Default is `2` seconds.

    delta_display_range
Set maximum display range (gain or loss) in seconds for delta reading, accepts decimal place. Default is `99.999` seconds.

    freeze_duration
Set freeze duration (seconds) for displaying previous lap time difference against best lap time source after crossing finish line. Value range in `0` to `30` seconds. Default is `3` seconds. Set to `0` to disable.

    enable_animated_deltabest
Deltabest display follows delta bar progress.

    show_invalid_lap_indicator
Modern design: outline deltabest in loss color while game invalidated current lap (track limits). This option only works for `LMU`.

[**`Back to Top`**](#)


## Deltabest extended
**This widget displays deltabest info against multiple lap time sources.**

No delta is shown (a dash) on an out lap, that is a lap started in pit lane or garage (back to garage starts a new lap, time spent there counts), while in pit lane before start line, or while the reference lap does not exist yet (stint best before first lap of stint, last lap after an out lap). See [Delta module](#delta-module).

    show_all_time_deltabest
Show deltabest against personal all time best lap time.

    show_session_deltabest
Show deltabest against current personal session best lap time. Session best lap is kept when Modern Tiny Pedals restarts or preset is reloaded during the same session, and reset when a new session starts. Until a first pit stop, session best and stint best are the same lap.

    show_stint_deltabest
Show deltabest against current personal stint best lap time. Note: stint deltabest will be reset if vehicle stops in pit lane (pit stop, or back to garage), or when a new session starts.

    show_deltalast
Show delta against personal last lap time (deltalast). Note: deltalast will be reset upon ESC.

    show_game_deltabest_if_available
Show delta to best lap computed by game (`LMU`) instead of delta computed by APP, when game provides it. Game delta (best lap as defined by game) replaces session deltabest reading. Delta computed by APP is used when game delta is unavailable (`RF2`). Default is disabled.

[**`Back to Top`**](#)


## Differential
**This widget displays wheel differential locking info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_inverted_locking
Invert minimum differential locking percent reading.

    show_power_locking_*, show_coast_locking_*
Show minimum differential locking percent between left and right wheels on the same axle under power (on throttle) or coasting (off throttle).

A `100%` reading indicates two wheels on the same axle are rotating at same speed; while `0%` indicates that one of the wheels is completely spinning or locked.

    off_throttle_threshold
Set percentage threshold which counts as off throttle if throttle position is lower, value range in `0.0` to `1.0`. Default is `0.01` (1%).

    on_throttle_threshold
Set percentage threshold which counts as on throttle if throttle position is higher, value range in `0.0` to `1.0`. Default is `0.01` (1%).

    power_locking_reset_cooldown, coast_locking_reset_cooldown
Set cooldown duration (seconds) before resetting minimum power or coast locking percent value if value hasn't changed during cooldown period. Default is `5` seconds.

[**`Back to Top`**](#)


## DRS
**This widget displays DRS(rear flap) usage info.**

    drs_text
Set custom DRS text.

    font_color_activated, background_color_activated
Set color when DRS is activated by player.

    font_color_allowed, background_color_allowed
Set color when DRS is allowed but not yet activated by player.

    font_color_available, background_color_available
Set color when DRS is available but current disallowed to use.

    font_color_not_available, background_color_not_available
Set color when DRS is unavailable for current track or car.

[**`Back to Top`**](#)


## Electric motor
**This widget displays electric motor usage info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_motor_temperature
Show electric motor temperature.

    show_water_temperature
Show electric motor cooler water temperature.

    overheat_threshold_motor, overheat_threshold_water
Set temperature threshold for electric motor and water overheat color indicator, unit in Celsius.

    show_rpm
Show electric motor RPM.

    show_torque
Show electric motor torque.

    show_power
Show electric motor power.

    show_regeneration_level
Show electric motor regeneration level.

[**`Back to Top`**](#)


## Elevation
**This widget displays elevation plot. Note: elevation plot data is recorded together with track map. At least one complete and valid lap is required to generate elevation plot.**

Modern design: elevation profile on a chart with a soft area under the line, part of lap already driven in accent color, car as a dot on the profile, faint start, sector and zero elevation lines, current elevation and chart scale above chart. Colors and text positions are set by design.

    display_detail_level
Sets detail level for track map. Default value is `1`, which auto adjusts map detail according to display size. Higher value reduces map detail and RAM usage, and may also help reduce rough edges from large map. Set to `0` for full detail.

    display_width
Set widget display width in pixels. Minimum width is limited to `20`.

    display_height
Set widget display height in pixels. Minimum height is limited to `10`.

    display_margin_*
Set widget display margin in pixels. Maximum margin is limited to half of `display_height` value.

    show_elevation_reading
Show elevation difference in game's coordinate system.

    show_elevation_scale
Show elevation plot scale reading, which is ratio between screen pixel and real world elevation. A `1:10.5` reading means 1 pixel equals 10.5 meters (or feet, depends on distance unit setting).

    show_background
Show widget background.

    show_elevation_background
Show background of elevation plot.

    show_elevation_progress
Show elevation progress bar according player's current position.

    show_elevation_progress_line
Show elevation progress line according player's current position.

    show_elevation_line
Show elevation reference line.

    show_zero_elevation_line
Show zero elevation reference line in game's coordinate system.

    show_start_line
Show start line mark.

    show_sector_line
Show sector line mark.

    show_position_mark
Show player's current position line mark.

[**`Back to Top`**](#)


## Engine
**This widget displays engine usage info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_oil_temperature
Show oil temperature.

    show_water_temperature
Show water temperature.

    overheat_threshold_oil, overheat_threshold_water
Set temperature threshold for oil and water overheat color indicator, unit in Celsius.

    show_turbo_pressure
Show turbo pressure.

    show_rpm
Show engine RPM.

    show_rpm_maximum
Show maximum engine RPM (rev limit).

    show_torque
Show engine torque.

    show_power
Show engine power.

    show_power_to_weight_ratio
Show estimated (maximum recorded) power to (current) weight ratio. Final reading is affected by power and weight units setting, and resets after returning to garage. The accuracy depends on game API data, and may not be available on certain vehicles.

    show_game_overheating_warning
Modern design: highlight oil and water temperature while game shows engine overheating warning, besides `overheat_threshold_oil` and `overheat_threshold_water`.

[**`Back to Top`**](#)


## Engine temperature
**This widget displays additional engine temperature info.**

    show_oil_temperature
Show oil temperature.

    show_water_temperature
Show water temperature.

    overheat_threshold_oil, overheat_threshold_water
Set temperature threshold for oil and water overheat color indicator, unit in Celsius.

    show_game_overheating_warning
Modern design: highlight oil and water temperature while game shows engine overheating warning, besides `overheat_threshold_oil` and `overheat_threshold_water`.

    show_rate_of_change
Show temperature rate of change for a specific time interval.

    rate_of_change_interval
Set time interval in seconds for rate of change calculation. Default interval is `10` seconds. Minimum interval is limited to `1` second, maximum interval is limited to `60` seconds.

    rate_of_change_smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

    show_net_change_per_lap
Show temperature net change per lap.

[**`Back to Top`**](#)


## Flag
**This widget displays flags, pit state, warnings, start lights info.**

Modern design: one chip per active item, in flag color (yellow, blue, green, red...), caption above value (pit time, fuel left, speed, distance to yellow flag, class & time of blue flag, traffic gap, pit window laps, repair time, sectors under yellow, full course yellow phase). Chips are packed in display order, inactive items take no room. Text options (`*_text`) replace design captions once changed from default value.

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_pit_timer
Show pit timer, and total amount time spent in pit after exit pit.

    pit_time_highlight_duration
Set highlight duration for total amount time spent in pit after exit pit.

    pit_in_text, pit_out_text, pit_closed_text
Set custom text for pit in, out, closed.

    font_color_pit_closed, background_color_pit_closed
Set color indicator on pit timer when pit lane is closed.

    show_low_fuel
Show low fuel (or low virtual energy if available) indicator when below certain amount value. Only one indicator will be displayed for low fuel (LF) or low virtual energy (LE), depends on which one would deplete sooner.

    show_low_fuel_for_race_only
Only show low fuel indicator during race session.

    low_fuel_volume_threshold
Set fuel volume threshold (in Liter) to show low fuel indicator when total amount of remaining fuel is equal or less than this value. This setting is used to limit low fuel warning when racing on lengthy tracks, where fuel tank may only hold for a lap or two. Default is `20` Liter.

    low_fuel_lap_threshold
Set amount lap threshold to show low fuel indicator when total completable laps of remaining fuel is equal or less than this value. Default is `2` laps before running out of fuel.

    low_fuel_text, low_energy_text
Set custom text for low fuel or energy.

    show_speed_limiter
Show speed limiter indicator.

    show_current_speed_while_limiter_on
Show current vehicle speed while speed limiter is on. This option is enabled by default.

    speed_limiter_text
Set custom pit speed limiter text which shows when speed limiter is engaged.

    show_yellow_flag
Show yellow flag indicator and distance display which shows nearest yellow flag vehicle distance. Note, positive distance reading indicates yellow flag that ahead of driver, negative indicates behind.

    show_yellow_flag_for_race_only
Only show yellow flag indicator during race session.

    yellow_flag_maximum_range_ahead, yellow_flag_maximum_range_behind
Set maximum range (meters) for displaying yellow flags that ahead of or behind driver. Default range ahead is `500` meters, range behind is `50` meters. To disable yellow flag that behind driver, set range behind to `0`.

Note, yellow flags that ahead of driver take priority over those from behind.

    yellow_flag_text
Set custom text for yellow flag.

    show_blue_flag
Show blue flag indicator with nearest leading vehicle class name displayed on the left, and total duration (seconds) under blue flag on the right. Note, the class name is limited and trimmed to 4 characters.

    show_blue_flag_for_race_only
Only show blue flag indicator during race session.

    show_start_lights
Show race start lights indicator with light frame number for standing-type start.

    red_lights_text, green_flag_text
Set custom text for red lights and green flag.

    green_flag_duration
Set display duration(seconds) for green flag text before it disappears. Default is `3`.

    show_traffic
Show nearest incoming on-track traffic indicator (time gap) while in pit lane or after pit-out.

    show_traffic_while_off_track
Show nearest incoming on-track traffic indicator while off-track. Note, only all four wheels that are on either grass, dirt, or gravel is considered off-track.

    traffic_maximum_time_gap
Set maximum time gap (seconds) of incoming on-track traffic.

    traffic_extended_duration
Set traffic indicator extended duration (seconds) after pitting out, or recently recovered from off-track or low speed.

    traffic_low_speed_threshold
Set low speed threshold for showing nearest incoming traffic indicator. Default is `8` m/s (roughly 28kph). Set to `0` to disable. This option can be useful to quickly determine nearby traffic situation after a spin or crash.

    traffic_text
Set custom text for traffic.

    show_pit_request
Show pit request indicator and `pit-in laps countdown` alongside `estimated remaining laps` reading that current fuel or energy can run. Note, `pit-in laps countdown` value is always calculated towards the finish line of current stint's final lap, and thus is always less than or equal to `estimated remaining laps` reading. If countdown drops below 1.0 (laps), it indicates the final lap of current stint, and driver should pit in before the end of current lap to refuel. If countdown reaches zero or negative, there may still be some fuel or energy left in tank, however it will not be enough to complete another full lap.

    show_finish_state
Show finish or disqualify state.

    finish_text, disqualify_text
Set custom text for finish and disqualify.

    show_scheduled_repairs
Show scheduled repairs notification and estimated repair time when damage repair is turned on. This option only works for `LMU`.

    scheduled_repairs_text
Set custom text for scheduled repairs.

    show_sector_yellow_flags
Show sectors under local yellow flag (sector numbers, `-` for clear sector). This option follows `show_yellow_flag_for_race_only`.

    sector_yellow_flags_text
Set custom text before sector numbers.

    show_full_course_yellow
Show full course yellow phase: pending or pits closed (`FCY`), pits open for lead lap cars (`LDR`), pits open (`PIT`), last lap (`END`), resuming (`GO`), race halted (`RED`).

    full_course_yellow_text
Set custom text for full course yellow, shown before phase.

[**`Back to Top`**](#)


## Force
**This widget displays g force and downforce info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_longitudinal_g_force
Show longitudinal g force with direction indicator.

    show_lateral_g_force
Show lateral g force with direction indicator.

    show_downforce_ratio
Show downforce ratio between front and rear. 50% indicates equal downforce; higher than 50% indicates front has more downforce.

    show_front_downforce, show_rear_downforce
Show front and rear downforce reading in Newtons.

    warning_color_liftforce
Set lift force indicator color.

    show_estimated_static_weight
Show estimated total vehicle weight measured while vehicle is stationary.

Note, it may take a lap or two to calibrate measurement for certain vehicles. The accuracy of static weight measurement depends on game API data, and may not be available on certain vehicles, see [Wheels Module](#wheels-module) for details.

    show_minimum_static_weight_without_fuel
Show estimated minimum static weight (in kilograms) excluding fuel.

    show_estimated_dynamic_weight
Show estimated total vehicle weight while vehicle is moving.

    show_acceleration_reduction
Show percentage acceleration reduction due to amount carried fuel weight.

[**`Back to Top`**](#)


## Friction circle
**This widget displays g force in circle diagram.**

    display_size
Set widget size in pixels.

    display_radius_g
Set viewable g force range by radius(g).

    show_inverted_orientation
Set `true` to invert display orientation for longitudinal and lateral g force axis. Default is `false`, which shows brake at top, acceleration at bottom, right-turn at left, left-turn at right.

    show_readings
Show values from g force reading. Value at top is current longitudinal g force, and value at bottom is maximum longitudinal g force. Value at left is maximum lateral g force, and value at right is current lateral g force.

    show_background
Show background color that covers entire widget.

    show_circle_background
Show circle background color.

    show_fade_out
Fade out circle background edge.

    fade_in_radius, fade_out_radius
Set fade in/out radius, value range in `0.0` to `1.0`.

    show_maximum_average_lateral_g_circle
Show maximum average lateral g force reference circle.

    maximum_average_lateral_g_circle_style
Set circle line style. `0` for dashed line, `1` for solid line.

    maximum_average_lateral_g_circle_width
Set circle line width in pixels.

    show_dot
Show g force dot.

    dot_size
Set g force dot size in pixels.

    show_trace
Show g force trace.

    trace_maximum_samples
Set maximum amount g force trace samples.

    trace_style
Set g force trace style. `0` for line style. `1` for point style.

    trace_width
Set g force trace width in pixels.

    show_trace_fade_out
Show trace fade out effect.

    trace_fade_out_step
Set trace fade out speed. Value range in `0.1` to `0.9`, higher value increases trace fade out speed. Default value is `0.2`.

    show_center_mark
Show center mark.

    center_mark_radius_g
Set center mark size by radius(g).

    center_mark_style
Set center mark line style. `0` for dashed line, `1` for solid line.

    center_mark_width
Set center mark line width in pixels.

    show_reference_circle
Show reference circle.

    reference_circle_*_radius_g
Set reference circle size by radius(g). Circle will not be displayed if radius is bigger than `display_radius_g`.

    reference_circle_*_style
Set reference circle line style. `0` for dashed line, `1` for solid line.

    reference_circle_*_width
Set reference circle line width in pixels.

[**`Back to Top`**](#)


## Fuel
**This widget displays fuel usage info.**

Note, for non-hybrid pure electric vehicle, this widget will show `battery charge` usage (in percentage) info instead. Since multiple different electric systems exist in `RF2`, there is no reliable way to distinguish pure electric vehicles from fuel or hybrid vehicles, it is important to make sure `fuel_unit` option in [Units](#units) setting is set to `Liter` in order to correctly display battery charge usage in `percentage` for pure electric vehicles.

---

Differences between `relative` and `absolute` refueling:

* Relative refueling value shows total amount `additional` fuel required to finish the remaining race length, which matches `relative refueling` mechanism (amount to add on top of remaining fuel in tank) in `RF2`.

* Absolute refueling value shows absolute total amount fuel required to finish the remaining race length, which matches `absolute refueling` mechanism (amount total fuel to fill tank up to) in `LMU`.

Also see `estimated laps` display option in [Session](#session) widget that can be used for `absolute refueling`.

---

    show_absolute_refueling
Show absolute refueling value instead of relative refueling when enabled. Note, `+` or `-` sign is not displayed with absolute refueling.

    show_estimated_pitstop_count
Show estimated number of pit stop counts column.

    show_delta_consumption_and_end_remaining
Show delta consumption and estimated end stint remaining fuel column.

    *remaining
Remaining fuel in tank.

    *refueling
Estimated refueling reading, which is the total amount additional fuel required to finish race.

Note, for `relative refueling` (`show_absolute_refueling` disabled), positive value indicates additional refueling and pit stop would be required, while negative value indicates total remaining fuel at the end of race, and no extra pit stop required. For example, a `-1.5` value indicates `1.5` remaining fuel after crossed finish line.

For `absolute refueling` (`show_absolute_refueling` enabled), total remaining fuel at the end of race can be found by subtracting `refuel` value from `remain` value. For example, `6` (remain column) - `4.5` (refuel column) = `1.5` remaining fuel after crossed finish line.

    *estimated_laps
Estimated laps reading that current fuel can last.

    *estimated_minutes
Estimated minutes reading that current fuel can last.

    *estimated_consumption
Estimated fuel consumption reading, which is calculated from last-valid-lap fuel consumption and delta fuel consumption. Note, when vehicle is in garage stall, this reading only shows last-valid-lap fuel consumption without delta calculation.

    *saving_target
Estimated fuel saving target consumption reading for making one less pit stop.

    *delta_consumption
Estimated delta fuel consumption reading. Positive value indicates an increase in consumption, while negative indicates a decrease in consumption.

    *end_remaining
Estimated remaining fuel reading at the end of current stint before next pit stop, which reflects fuel usage efficiency.

Note, this value does not count towards the end of race; instead, this value always counts towards the end of last completeable lap. To find out total remaining fuel at the end of race, see `refuel` column and explanation.

    *pitstop_count
Estimate number of pit stop counts when making a pit stop at end of current stint. Any non-zero decimal places would be considered for an additional pit stop.

    *early_pitstop_count
Estimate number of pit stop counts when making an early pit stop at end of current lap. This value can be used to determine whether an early pit stop is worth performing comparing to `pits` value.

Example 1: When this value is just below `1.0` (such as `0.97`), it indicates an early pit stop can be made right at the end of current lap with enough empty capacity to refuel according to `refuel` reading which would last to the end of race.

Example 2: When this value is just below `2.0` (such as `1.96`), and `pits` value is also in `1.x` range (such as `1.32`),  it indicates 2 required pit stops, and an early pit stop can be made right at the end of current lap with tank fully refueled according to `refuel` reading. After refueling, `pits` reading would show an approximately `0.96` value which indicates one more required pit stop.

Example 3: If this value is one or more integers higher than `pits` value, then additional pit stops would be required after making a pit stop at the end of current lap.

    bar_width
Set each column width, value in chars, such as 10 = 10 chars. Default is `5`. Minimum width is limited to `3`.

    low_fuel_lap_threshold
Set amount lap threshold to show low fuel indicator when total completable laps of remaining fuel is equal or less than this value. Default is `2` laps before running out of fuel.

    warning_color_low_fuel
Set low fuel color indicator, which changes widget background color when there is just 2 laps of fuel left.

    show_low_fuel_warning_flash
Show low fuel warning flash effect when below `low_fuel_lap_threshold`.

    number_of_warning_flashes
Set number of warning flashes that will be played for a limited number of times. Default is `10` flashes. Minimum value is limited to `3`.

    warning_flash_highlight_duration
Set color highlight duration for each warning flash. Default is `0.4` seconds. Minimum value is limited to `0.2`.

    warning_flash_interval
Set minimum time interval between each warning flash. Default is `0.4` seconds. Minimum value is limited to `0.2`.

    show_fuel_level_bar
Show visualized horizontal fuel level bar.

    fuel_level_bar_height
Set fuel level bar height in pixels.

    show_starting_fuel_level_mark
Show starting fuel level mark of current stint. Default mark color is red.

    show_refueling_level_mark
Show estimated fuel level mark after refueling. If the mark is not visible on fuel level bar, it indicates total refueling has exceeded fuel tank capacity. Default mark color is green.

    starting_fuel_level_mark_width, refueling_level_mark_width
Set fuel level mark width in pixels.

    caption_text
Set custom caption text.

    swap_upper_caption, swap_lower_caption
Swap caption row position.

[**`Back to Top`**](#)


## Fuel energy saver
**This widget displays fuel or virtual energy saving info.**

Show current stint estimated total completable laps and completed laps based on current consumption.

Show estimated target lap consumption to save (extend) one or more total stint laps.

Show delta consumption against target lap consumption, which allows fuel or energy saving to be visualized and easily controlled in real-time.

Show consumption type in `FUEL` or `NRG` (if virtual energy available).

Show last lap consumption.

    layout
Set target laps horizontal display order. Set `0` to show from left (less laps) to right (more laps). Set `1` to show from right to left instead.

    minimum_reserve
Set minimum amount fuel or virtual energy in tank that is excluded from saving calculation and reserved for the end of stint. Default is `0.2` Liter for fuel (or % for virtual energy).

    number_of_more_laps
Set number of target slots for more completable laps. Default is `3`. Range in `1` to `10`.

    number_of_less_laps
Set number of target slots for less completable laps. Default is `0`. Range in `0` to `5`.

    show_rate_of_consumption
Show fuel or energy consumption per second and current vehicle speed (meters per second) under `RATE` column.

This option shows how consumption rate changes with throttle, RPM, engine map, etc. It also helps to determine amount distance required to lift-and-coast to save corresponding amount fuel or energy.

For example, if energy consumption per second value is `0.05`, and current speed value is `75m`, it indicates it would take roughly 1 second and 75 meters of lift-and-coast time and distance to save 0.05 energy.

    enable_pit_entry_bias
Auto calibrate target fuel (or energy) saving bias towards either pit entry position or finish line, depending on number of estimated remaining pit stops.

This feature is made specially for tracks that have pit entry position located far away from finish line, which it is necessary to take pit entry position into fuel saving calculation for increased accuracy.

While enabled, a `BIAS` column will be displayed, which shows amount added fuel (or energy) bias towards pit entry position, as well as percentage pit entry bias from finish line, When bias is `0`, it means there is no pit entry bias added.

**Important notes:** Do not enable this feature if you are not sure what it does. You must enter pit at least once to record pit entry position of the track for this feature to work.

    remaining_pitstop_threshold
Set number of remaining pit stops threshold for auto calibrating target fuel (or energy) saving bias. Default value is `0.1`.

Fuel (or energy) saving calculation is biased towards pit entry position when number of estimated remaining pit stops is greater than the threshold, otherwise biased towards finish line.

[**`Back to Top`**](#)


## Gap trend
**This widget displays gap to car ahead and car behind, and how it changes lap after lap.**

For each car, widget shows current gap in seconds (or laps), gap change per lap, and gap at end of each of the last laps as a small chart. Gap change per lap is averaged over the laps run against the same car, negative value means gap is shrinking. It is shown in gain color when good for player (catching up car ahead, pulling away from car behind), and in loss color otherwise. Gap history starts again when car ahead or behind changes. `Vehicles module` must be enabled.

    number_of_laps
Set number of laps kept in gap chart and used for gap change per lap. Value range in `2` to `50`. Default is `8` laps.

    show_gaps_in_class
Show gaps to car ahead and car behind in same class. Set `false` to show gaps to car ahead and car behind in overall position instead.

    show_driver_name
Show driver name of car ahead and car behind.

    show_closing_rate
Show gap change per lap, in gain or loss color.

    show_trend_chart
Show gap at end of each lap as a small line chart.

[**`Back to Top`**](#)


## Gear
**This widget displays gear, RPM, speed, battery info.**

    inner_gap
Set inner gap between gear and speed readings. Negative value reduces gap, while positive value increases gap. Default is `0`.

    show_speed
Show speed reading.

    show_speed_below_gear
Show speed reading below gear.

    font_scale_speed
Set font scale for speed reading. This option only takes effect when `show_speed_below_gear` is enabled. Default is `0.5`.

    show_speed_limiter
Show pit speed limiter indicator.

    speed_limiter_text
Set custom pit speed limiter text which shows when speed limiter is engaged.

    show_speed_limiter_reminder
Modern design: show outlined speed limiter reminder while driving in pit lane with pit speed limiter off (vehicle with pit speed limiter only).

    show_battery_bar
Show battery bar, which is only visible if electric motor available.

    show_inverted_battery
Invert battery bar progression.

    battery_bar_height
Set battery bar height in pixels.

    high_battery_threshold, low_battery_threshold
Set percentage threshold for displaying low or high battery charge warning indicator. Default high threshold is `95` percent (default color purple), low threshold is `10` percent (default color red).

    show_battery_reading
Show battery charge (in percentage) reading text on battery bar.

    show_rpm_bar
Show a RPM bar at bottom of gear widget, which moves when RPM reaches range between safe and maximum RPM.

    show_inverted_rpm
Invert RPM bar progression.

    rpm_bar_height
RPM bar height, in pixel.

    show_rpm_reading
Show RPM reading text on RPM bar.

    rpm_multiplier_safe
This value multiplies maximum RPM value, which sets relative safe RPM range for RPM color indicator (changes gear widget background color upon reaching this RPM value).

    rpm_multiplier_redline
This value multiplies maximum RPM value, which sets relative redline RPM range for RPM color indicator.

    rpm_multiplier_critical
This value multiplies maximum RPM value, which sets critical RPM range for RPM color indicator.

    show_rpm_flickering_above_critical
Show flickering effects when RPM is above critical range and gear is lower than maximum gear.

    neutral_warning_speed_threshold, neutral_warning_time_threshold
Set speed/time threshold value for neutral gear color warning, which activates color warning when speed and time-in-neutral is higher than threshold. Speed unit in meters per second, Default is `28`. Time unit in seconds, Default is `0.3` seconds.

    show_consumption_bar
Show fuel or energy consumption per second in a visualized progression bar.

    show_virtual_energy_if_available
Show virtual energy consumption instead of fuel consumption if available.

    consumption_progression_exponential_scale
Apply exponential scale to consumption progression, value range in `1.0` to `10.0`. This option affects visual only. Increase this option to scale up high end consumption range. Set to `1.0` to disable exponential scale. This option is useful to enlarge changes at high end consumption range for certain vehicles.

    high_consumption_threshold
Set high consumption threshold in percentage. Default is `0.95` (95%).

    maximum_average_consumption_samples
Set amount samples for calculating maximum average consumption per second, which helps filtering out unusual fluctuation. Minimum value is limited to `1`.

    show_consumption_reading
Show fuel or energy consumption per second reading.

[**`Back to Top`**](#)


## Heading
**This widget displays vehicle yaw angle, slip angle, heading info.**

    display_size
Set widget size in pixels.

    show_yaw_angle_reading
Show yaw angle reading in degrees.

    show_slip_angle_reading
Show average front tyre slip angle reading in degrees.

    show_degree_sign
Set `true` to show degree sign for yaw angle reading.

    show_background
Show background color that covers entire widget.

    show_circle_background
Show circle background color.

    show_yaw_line
Show yaw line (vehicle heading).

    show_direction_line
Show vehicle's direction of travel line.

    show_slip_angle_line
Show slip angle (average of the front tyres) line.

    *_line_head_scale
Set line length scale from center to head, value range in `0.0` to `1.0`.

    *_line_tail_scale
Set line length scale from center to tail, value range in `0.0` to `1.0`.

    *_line_width
Set line width in pixels.

    show_dot
Show center dot.

    show_center_mark
Show center mark.

    center_mark_length_scale
Set center mark length scale, value range in `0.0` to `1.0`.

    center_mark_style
Set center mark line style. `0` for dashed line, `1` for solid line.

    center_mark_width
Set center mark line width in pixels.

[**`Back to Top`**](#)


## Instrument
**This widget displays vehicle instruments info.**

    icon_size
Set size of instrument icon in pixel. Minimum value is limited to `16`.

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_headlights
Show headlights state.

    show_ignition
Show engine ignition, starter, stalling state.

    stalling_rpm_threshold
Set RPM threshold for triggering engine stalling warning. Default is `100` RPM.

    show_clutch
Show auto-clutch and clutch state.

    show_wheel_lock
Show wheel lock state.

    show_wheel_slip
Show wheel slip state.

    wheel_lock_threshold
Set percentage threshold for triggering wheel lock warning under braking. `0.3` means 30% of tyre slip ratio.

    wheel_slip_threshold
Set percentage threshold for triggering wheel slip warning under acceleration. `0.1` means 10% of tyre slip ratio.

[**`Back to Top`**](#)


## Laps and position
**This widget displays lap number, driver overall position, position in class info.**

    show_laps
Show your current lap number (lap progression) and total race laps. If total race laps is not available, such as in time-based session, estimated total laps will be displayed instead, and a `~` sign will be displayed before estimated total laps reading, and up to two decimal places will be kept.

Note, estimated total laps reading is calculated based on local player's lap time pace, which can be different from in-game HUD reading.

This reading does not concern about race leader's lap time pace, which means there may be an extra final lap on top of it. See `show_predicted_extra_laps` option below for extra laps prediction.

    show_predicted_extra_laps
Show number of more (or less) laps prediction on top of total estimated laps in race, based on leader's lap time pace and player's estimated pit stop duration.

Predicted extra laps reading is not added to the estimated laps reading, and is not taken into fuel calculation. Positive reading indicates there may be extra final laps on top of total estimated laps; negative reading indicates there may be less final laps on top of total estimated laps.

For example, a `12.45(+1)` reading means there are `12.45` total estimated laps, plus `1` predicted final lap, which may result `12.45 + 1` = `13.45` final estimated laps.

Note, this option only works for time-based race type, and there is no guarantee that prediction will be 100% accurate, as anything can happen in the last hour of race.

    warning_color_maximum_laps
Set warning color that shows 1 lap before exceeding maximum laps in qualify (or indicates the last lap of a lap-type race).

    show_position_overall
Show your current overall position against all drivers in a session.

    show_position_in_class
Show your current position in class against all drivers from the same class.

    show_track_limits_points
Show current track cut points against total track limits points per penalty.

    show_position_change
Show overall driver position change relative to overall qualification position.

    show_position_change_in_class
Show driver position change in class instead of overall. This option is enabled by default.

    show_invalid_lap_indicator
Modern design: show lap progress in loss color while game invalidated current lap (track limits). This option only works for `LMU`.

[**`Back to Top`**](#)


## Lap time history
**This widget displays lap time history info.**

Note, history data are loaded and updated from corresponding [Consumption History](#consumption-history) file.

    layout
2 layouts are available: `0` = vertical layout, `1` = reversed vertical layout.

    lap_time_history_count
Set the number of lap time history display. Default is to show `10` most recent lap times.

    show_empty_history
Show empty lap time history. Default is `false`, which hides empty rows.

    show_laps
Show lap number.

    show_time
Show lap time.

    show_delta
Show lap time delta between two consecutive laps.

    show_fuel
Show fuel consumption per lap.

    show_virtual_energy_if_available
Show virtual energy consumption instead of fuel consumption if available. This option is enabled by default.

    show_fuel_sign
Show fuel (or virtual energy) unit sign. `L` for liter, `G` for Gallon, `E` for virtual energy.

    show_fuel_ratio
Show fuel ratio between fuel and energy consumption.

    show_wear
Show average tyre wear (percent) per lap.

    show_wear_sign
Show tyre wear percentage sign.

[**`Back to Top`**](#)


## Lift and coast LED
**This widget displays lift and coast, TC & ABS activation, wheel slip & lock LED info.**

Note, currently this widget only works for `LMU`.

    display_orientation
Set LED display orientation: `0` = left to right (horizontal), `1` = bottom to top (vertical), `2` = right to left (horizontal), `3` = top to bottom (vertical).

    enable_double_side_led
Show a second set of LEDs on the opposite side.

    double_side_led_gap
Set horizontal gap (in pixels) between double side LEDs.

    number_of_led
Set number of LED to display. Minimum LED is limited to `3`.

    led_width, led_height, led_radius
Set LED width, height, radius in pixels. To achieve circle LED, set a higher radius value.

    lift_and_coast_multiplier_critical
This value multiplies maximum lift and coast range, which sets critical range of lift and coast LED.

    show_tc_activation
Show TC activation state.

    show_abs_activation
Show ABS activation state.

    show_wheel_lock
Show wheel lock state.

    show_wheel_slip
Show wheel slip state.

    wheel_lock_threshold
Set percentage threshold for triggering wheel lock warning under braking. `0.3` means 30% of tyre slip ratio.

    wheel_slip_threshold
Set percentage threshold for triggering wheel slip warning under acceleration. `0.1` means 10% of tyre slip ratio.

[**`Back to Top`**](#)


## Navigation
**This widget displays a zoomed navigation map that centered on player's vehicle. Note: at least one complete and valid lap is required to generate map.**

    display_size
Set widget size in pixels.

    view_radius
Set viewable area by radius(unit meter). Default is `500` meters. Minimum value is limited to `5`.

    show_background
Show background color that covers entire widget.

    show_circle_background
Show circle background color.

    circle_outline_width
Set circle background outline width. Set value to `0` to hide outline.

    show_fade_out
Fade out view edge.

    fade_in_radius, fade_out_radius
Set fade in/out radius, value range in `0.0` to `1.0`.

    map_width
Set navigation map line width.

    map_outline_width
Set navigation map outline width.

    show_start_line
Show start line mark.

    show_sector_line
Show sector line mark.

    show_vehicle_standings
Show vehicle standings info on navigation map.

    show_circle_vehicle_shape
Set `True` to show vehicle in circle shape, set `False` for arrow shape.

    vehicle_size
Set vehicle size in pixels.

    vehicle_offset
Set vehicle vertical position offset (percentage) relative to display size, value range in `0.0` to `1.0`.

    vehicle_outline_width
Set vehicle outline width.

[**`Back to Top`**](#)


## Push to pass
**This widget displays push to pass (P2P) usage info.**

    show_battery_charge
Show percentage available battery charge.

    show_activation_timer
Show electric boost motor activation timer.

    activation_threshold_gear
Set minimum gear threshold for P2P ready indicator.

    activation_threshold_speed
Set minimum speed threshold for P2P ready indicator, unit in KPH.

    activation_threshold_throttle
Set minimum throttle input percentage threshold for P2P ready indicator, value range in `0.0` to `1.0`. Default is `0.6` (60%).

    minimum_activation_time_delay
Set minimum time delay between each P2P activation, unit in seconds.

    maximum_activation_time_per_lap
Set maximum P2P activation time per lap, unit in seconds.

[**`Back to Top`**](#)


## Onboard setting
**This widget displays onboard setting info.**

Note, currently this widget only works for `LMU`.

    show_abs
Show current ABS level.

    show_tc
Show current TC level.

    show_tc_cut
Show current TC power cut level.

    show_tc_slip
Show current TC slip angle level.

    show_brake_migration
Show current brake migration level.

    show_motor_map
Show current motor (or engine) map level.

    show_front_arb
Show current front anti-roll bar level.

    show_rear_arb
Show current rear anti-roll bar level.

[**`Back to Top`**](#)


## Pace notes
**This widget displays pace notes, comments, debugging info.**

    show_background
Show background color. Turn off to show text only.

    show_pit_notes_while_in_pit
Show custom notes while in pit lane.

    pit_notes_text, pit_comments_text
Set custom notes and comments to be displayed while in pit lane.

    show_pace_notes
Show nearest pace notes info behind current vehicle position.

    show_comments
Show nearest pace notes comments info behind current vehicle position.

    enable_comments_line_break
Enable line break for displaying multi-line comments. To break a line into multiple lines, add `\n` to any part of the comment.

    show_debugging
Show nearest pace notes index number behind current vehicle position, and distance value (meters) behind current position to next index position.

    pace_notes_width, comments_width, debugging_width
Set maximum display width, value in chars, such as 10 = 10 chars.

    enable_auto_hide_if_not_available
Auto hide this widget if pace notes data is not available for current track.

    maximum_display_duration
Set maximum display duration (seconds) of each note. Set to `-1` to always display notes. Default is `-1`.

[**`Back to Top`**](#)


## Pedal
**This widget displays pedal input and force feedback info.**

    show_readings
Show pedal input and force feedback readings. Note, while `show_*_filtered` option is enabled, only the highest reading between filtered and raw input is displayed.

    readings_offset
Set reading text offset position (percentage), value range in `0.0` to `1.0`.

    enable_horizontal_style
Show pedal bar in horizontal style.

    bar_length, bar_width_unfiltered, bar_width_filtered
Set pedal bar length and width in pixels.

    inner_gap
Set gap between pedal and maximum indicator.

    maximum_indicator_height
This is the indicator height when pedal reaches maximum travel (100%), value in pixel.

    show_brake_pressure
Show brake pressure changes applied on all wheels, which auto scales with maximum brake pressure and indicates amount brake released by ABS on all wheels. This option is enabled by default, which replaces game's filtered brake input that cannot show ABS.

    show_throttle
Show throttle bar.

    show_brake
Show brake bar.

    show_clutch
Show clutch bar.

    show_ffb_meter
Show Force Feedback meter.

    show_*_filtered
Show filtered pedal input if available. Note, some vehicles may not provide filtered pedal input value, which the value will be zero. Disable this option to show raw input only.

[**`Back to Top`**](#)


## Pit lane helper
**This widget displays pit lane info while approaching pit lane and in pit lane.**

Widget is shown while car is in pit lane, and while approaching pit lane entry with pit stop requested (or speed limiter on). Nothing is shown otherwise, unless `show_always` is enabled. While overlay is unlocked, widget is always shown for positioning.

Pit speed limit is learned by `Mapping module` while driving through pit lane with speed limiter on, and saved per track. Speed is shown in loss color above pit speed limit, and in gain color below. Speed limiter state is shown in warning color while approaching pit lane without speed limiter, and in loss color while driving in pit lane without speed limiter. Pit box distance requires pit box position from game (LMU), its bar fills up while car approaches pit box. Planned services (pit stop time, refuel, repair) are read from game pit menu through Rest API (LMU), `enable_vehicle_info` must be enabled in LMU API setting.

    show_always
Always show widget, also out of pit lane.

    approach_distance
Set distance in meters before pit lane entry from which widget is shown while pit stop is requested. Pit entry position is read from game (LMU), or learned by `Mapping module`. If pit entry position is unknown, distance to start/finish line is used instead. Default is `400` meters.

    show_speed
Show vehicle speed and pit speed limit, in [Speed Units](#units).

    show_limiter_state
Show speed limiter state.

    show_pit_box_distance
Show distance to pit box, with a bar filling up while approaching pit box.

    show_planned_services
Show estimated pit stop time, fuel (or virtual energy) added, and repair time, as planned in game pit menu.

[**`Back to Top`**](#)


## Pit stop estimate
**This widget displays estimated pit stop duration and refilling info.**

Note, this widget is designed for `LMU`. Most readings are not available for `RF2` due to lack of API data.

    lengthy_stop_duration_threshold
Set warning threshold for lengthy pit stop duration in seconds. Default is `60` seconds. This option can be useful to check for unusually long pit stop duration, such as repairing.

    pass_duration
Show estimated pit-lane pass through (drive-through) time, calculated from pit-entry to pit-exit line. Average accuracy is within `0.5` seconds. Note, for any new tracks, at least one pit-lane pass through is required to record data for pass through time calculation.

    pit_timer
Show pit timer, useful for comparing against other pit time readings.

    stop_duration
Show estimated pit stop time while making a service stop or serving a penalty, calculated according to each setting from MFD `Pitstop` page and underlying service timing and concurrency differences. Average accuracy is within `1` seconds.

Note, for unscheduled pit stop (without requesting pit), game sometimes will add random amount extra delay (as part of pit crew preparation time) on top of pit stop time. To avoid this, always requests pit before entering pit.

    minimum_total_duration
Show estimated minimum total pit time, which is the sum of `pass_duration`, `stop_duration`, and `additional_pitstop_time`. Note, this reading is recalculated only while not in pit lane.

    additional_pitstop_time
Set additional pit stop time that is not part of `pass_duration` or `stop_duration`. Default value is `2` seconds, which is the average time it takes to decelerate and accelerate towards and away from pit spot.

    show_relative_refilling
Show `actual_relative_refill` and `total_relative_refill` columns.

    actual_relative_refill
Show actual relative refilling, as the total additional fuel or virtual energy that will be added in next pit stop according to remaining fuel or virtual energy and user refill setting from MFD `Pitstop` page.

    total_relative_refill
Show total relative refilling, as the total additional fuel or virtual energy that is required to finish the race. This is the same value as seen from `refill` column of Fuel Widget or Virtual energy Widget.

With both `actual` and `total` relative refilling readings, users can determine precisely how much fuel or virtual energy that will be added in next pit stop, and whether the refilling will be enough or more pit stops are required.

    show_estimated_laps_and_minutes
Show estimated total runnable laps and minutes after next pit stop according to refill setting from MFD `Pitstop` page. The estimation is calculated based on player's current consumption per lap and lap time pace. Useful for checking whether there will be enough fuel or energy added for the next stint and remaining time.

    show_pit_occupancy
Show `pit_occupancy` and `pit_requests` columns.

    pit_occupancy
Show number of vehicles that stopped in pit lane, and number of vehicles currently in pit lane (whether passing or stopped). This does not include vehicles that are parked in garage.

    pit_requests
Show number of vehicles that requested for pit stop, and number of vehicles currently outside pit lane.

[**`Back to Top`**](#)


## Race notifications
**This widget displays short race messages that fade out after a few seconds.**

Messages: position gained or lost (overall and in class, once new position is held for 1 second), new penalty, new fastest lap in player class (driver name and lap time), blue flag, full course yellow start and end, lap invalidated by game (LMU, track limits). Position, fastest lap and full course yellow messages are shown in race only. Same message is not repeated while it is shown. Nothing is shown while there is no message, unless overlay is unlocked.

Modern design: each message is a card with an icon in message color (arrow for positions, flag, stopwatch for fastest lap, penalty mark, cross for lap invalidated), title above detail, and a thin bar shrinking with the time left.

    layout
2 layouts are available: `0` = newest message at top, `1` = newest message at bottom.

    display_duration
Set how long each message is shown in seconds, fading out at the end. Value range in `1` to `60`. Default is `5` seconds.

    number_of_notifications
Set maximum number of messages shown at the same time, oldest message is removed first. Value range in `1` to `8`. Default is `3`.

    show_position_change, show_position_change_in_class
Show message when overall position, or position in class, is gained or lost.

    show_penalty
Show message when a new penalty is given.

    show_class_fastest_lap
Show message when a new fastest lap is set in player class.

    show_blue_flag
Show message when blue flag is shown to player, with class name of faster car.

    show_full_course_yellow
Show message when full course yellow starts and ends.

    show_lap_invalidated
Show message when game invalidates current lap.

[**`Back to Top`**](#)


## Race plan
**This widget displays the next pit stop of the [Race Calculator](#race-calculator) plan: lap, fuel & energy to add, tyres to change and stops left.** The race calculator keeps the input of its plan (tyre plan & compounds included) whenever it changes, so the widget shows the same plan with race calculator closed. Laps count from race start, formation laps of race calculator left out. The stop of the lap just completed stays shown while the car is in the pits (finish line before the pit box; after it, the stop is still ahead).

    enable_live_replan
Plan the rest of the race again at each lap & stop during a race, from the car: laps & time done, fuel, energy & tyres of now, stops done. Disabled: plan made before the race is followed.

    pit_window_laps
Set number of laps before next stop from which next stop is highlighted with `warning_color_pit_window`.

    show_next_stop
Show lap of next stop, and laps to go in brackets. `END` is shown after last stop, `---` when race calculator has no plan.

    show_refuel
Show fuel to add at next stop.

    show_energy
Show virtual energy to add at next stop.

    show_tyres
Show number of tyres to change at next stop, highlighted with `highlight_color_tyre_change` when tyres are changed. Tyres of race calculator tyre plan, or 4 tyres at stops proposed from minimum tread when tyre plan has no tyre.

    show_stops_left
Show stops left, and total stops of plan.

    show_pit_menu
Show pit menu check: refill set in game pit menu (fuel, or virtual energy for a car using it) against amount after next stop of the plan. `OK` when close (1 unit), `menu>plan` in `warning_color_pit_menu` otherwise, `--` when game gives no refill.

    show_target
Show consumption per lap to hold to reach next stop (or the finish) with fuel of now (energy for a car using energy only), safety margin kept, in `warning_color_target` when last lap used more.

    show_pit_entry
Show distance to pit lane entry (LMU, Rest API `enable_race_info` option), in `warning_color_pit_entry` on the lap ending with the next stop. `--` in the pits or when unknown. Distance unit follows `Distance Unit` setting from [Units](#units) config dialog.

    show_stint_limit
Modern design: show what ends stints of the plan: fuel, energy, driver stint time, mandatory stops, or tyre life (highlighted). Default is disabled.

    show_consumption_estimate
Modern design: show consumption estimate used by fuel (or energy) module: from game, from last lap, or median of recent laps (with number of laps). Default is disabled.

[**`Back to Top`**](#)


## Radar
**This widget displays vehicle radar info.**

    global_scale
Sets global scale of radar display. Default is `6`, which is 6 times of original size.

    radar_radius
Set the radar display area by radius(unit meter). Default is `30` meters. Minimum value is limited to `5`.

    show_vehicle_orientation
Show opponent vehicle orientation (heading) relative to player. Disable this option to show player and opponent vehicle headings in parallel.

    vehicle_length, vehicle_width
Set vehicle overall size (length and width), value in meters.

    vehicle_border_radius
Set vehicle round border radius.

    vehicle_outline_width
Set vehicle outline width.

    enable_radar_fade
Enable radar gradually fade in/out effect.

    radar_fade_out_radius
Set radar fade out radius relative to radar radius. Value range in `0.5` to `1.0`. Default value is `0.98`.

    radar_fade_in_radius
Set radar fade in radius relative to radar radius. Minimum value is limited to `0.1`, maximum value cannot exceed `radar_fade_out_radius`. Default value is `0.8`.

    show_background
Show background color that covers entire widget.

    show_circle_background
Show circle background color.

    show_edge_fade_out
Fade out radar edge.

    edge_fade_in_radius, edge_fade_out_radius
Set fade in/out radius relative to radar radius, value range in `0.0` to `1.0`.

    show_overlap_indicator
Show overlap indicator when there are nearby side by side vehicles. This option shows `boundary style` indicator if `show_overlap_indicator_in_cone_style` option is disabled.

    show_overlap_indicator_in_cone_style
Show overlap indicator in `cone style` instead of `boundary style`.

    overlap_cone_angle
Set cone display angle in degrees. This option does not affect overlap detection range. Default is `120` degrees.

    overlap_nearby_range_multiplier
Set nearby vehicle overlap detection range multiplier that scales with vehicle width. A value of `5` would result a 5-vehicle-wide detection range. Default is `5` vehicle-wide.

    overlap_critical_range_multiplier
Set nearby vehicle critical overlap detection range multiplier that scales with vehicle width. Default is `1` vehicle-wide.

    indicator_size_multiplier
Set indicator size multiplier that scales with vehicle width.

    show_collision_course
Show highlighted collision course from high speed approaching vehicle, or vehicle that caused yellow flag. Useful to quickly spot vehicle closing in at dangerous speed.

    collision_course_minimum_speed_difference
Set minimum speed difference (m/s) between you and opponent for displaying collision course. Default is `4` m/s.

    collision_course_speed_increment_per_meter
Set speed difference increment per meter for scaling speed difference threshold with the distance gap between you and opponent. Default is `0.5` m/s.

For example, a value of `0.5` (m/s) increment with a `15` meters distance gap would require at least `0.5 x 15 = 7.5 m/s` speed difference between you and opponent to show collision course. Minimum speed difference is limited by `collision_course_minimum_speed_difference` option.

    collision_course_nearby_range_multiplier
Set nearby collision course detection range multiplier that scales with vehicle width. A value of `4` would result a 4-vehicle-wide detection range. Default is `4` vehicle-wide.

    collision_course_critical_range_multiplier
Set critical collision course detection range multiplier that scales with vehicle width. Default is `1.5` vehicle-wide.

    show_center_mark
Show center mark on radar.

    center_mark_style
Set center mark line style. `0` for dashed line, `1` for solid line.

    center_mark_radius
Set center mark size by radius(unit meter).

    center_mark_width
Set center mark line width in pixels.

    show_angle_mark
Show angle mark (fixed 45 degrees) on radar.

    show_distance_circle
Show distance circle line on radar for distance reference.

    distance_circle_*_style
Set distance circle line style. `0` for dashed line, `1` for solid line.

    distance_circle_*_radius
Set distance circle size by radius(unit meter). Circle will not be displayed if radius is bigger than `radar_radius`.

    distance_circle_*_width
Set distance circle line width in pixels.

    enable_auto_hide
Auto hides radar display when no nearby vehicles.

    enable_auto_hide_in_private_qualifying
Auto hides radar in private qualifying session, requires both `enable_auto_hide` and `enable_restapi_access` enabled.

    auto_hide_time_threshold
Set amount time(unit second) before triggering auto hide. Default is `1` second. Note, this option has no effect while `enable_radar_fade` is enabled.

    auto_hide_minimum_distance_ahead, behind, side
The three values define an invisible rectangle area(unit meter) that auto hides radar if no vehicle is within the rectangle area. Default value is `-1`, which auto scales with `radar_radius` value. Set to any positive value to customize radar auto-hide range. Note, each value is measured from center of player's vehicle position.

    vehicle_maximum_visible_distance_ahead, behind, side
The three values define an invisible rectangle area(unit meter) that hides any vehicle outside the rectangle area. Default value is `-1`, which auto scales with `radar_radius` value. Set to any positive value to customize vehicle visible range. Note, each value is measured from center of player's vehicle position.

[**`Back to Top`**](#)


## Rake angle
**This widget displays vehicle rake angle info.**

    wheelbase
Set wheelbase in millimeters. Default is `2800` millimeters. This option affects `rake angle` calculation accuracy.

    rake_angle_smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

    show_degree_sign
Set `true` to show degree sign for rake angle value.

    show_ride_height_difference
Show average front and rear ride height difference in millimeters.

[**`Back to Top`**](#)


## Relative
**This widget displays relative standings info.**

    column_position, column_class, column_position_change, column_driver_name, column_vehicle_name, column_tyre_compound, column_pit_status, column_pitstop_count, column_laptime, column_best_laptime, column_energy_remaining, column_vehicle_integrity, column_incidents, column_stint_laps, column_time_gap
Modern design columns, shown in this order: overall position, class pill with position in class (class color also on row edge), places gained, driver name, vehicle name, tyre compounds, pit status (pit, garage, slow, finished), pit stops (green on pit request, `PEN` with penalty), last lap time (purple if class fastest), best lap time, virtual energy left, vehicle integrity, incident points, stint laps, relative time gap (highlighted when near).

    column_brand_logo, column_average_laptime, column_speed_trap, column_lift_and_coast_time
Modern design columns: brand logo after vehicle name (on by default: own logo of brand logo folder, else logo taken from the game, brand initials until found; width follows `brand_logo_width`), then, off by default, average lap time of recent laps after best lap time, speed trap (fastest speed at speed trap line, in speed unit) and lift and coast time (highlighted above `lift_and_coast_highlight_threshold`) after stint laps. Overlay Options page lists columns in one Columns list, from left to right: each column switched on or off there, and moved by drag or arrows. With `show_compound_for_each_wheel`, tyre compounds of each wheel are shown in a 2x2 grid when left and right compounds of an axle differ. With `show_class_style_for_position_in_class`, position in class part of class pill is in class color.

    show_player_highlighted
Highlight player row with customizable specific color.

    show_lap_difference
Show different font color based on lap difference between player and opponents. Note, this option will override `font_color` setting from `position`, `driver name`, `vehicle name`.

    font_color_same_lap, font_color_laps_ahead, font_color_laps_behind
Set font color for lap difference. Note, `font_color_laps_ahead` and `font_color_laps_behind` applies to race session only.

    show_position
Show overall position standings.

    show_position_change
Show overall driver position change relative to overall qualification position.

    show_position_change_in_class
Show driver position change in class instead of overall. This option is enabled by default.

    show_driver_name
Show driver name.

    driver_name_shorten
Shorten driver's first name to a single letter with a period separating driver's last name, and any middle names will not be displayed. Note, if a driver is using nickname that consists only a single word, the name will not be shortened.

    driver_name_uppercase
Set driver name to uppercase.

    driver_name_width
Set drive name display width, value in chars, such as 10 = 10 chars.

    driver_name_align_center
Align driver name in the center when enabled. Default is left alignment when disabled.

    show_vehicle_name
Show vehicle name. Note, game API outputs `skin livery name` as `vehicle name`, which means actual displayed name depends on what skin livery name is called. For example, some vehicles may add `team name` and/or `class name` in `skin livery name`, some may not.

    show_vehicle_brand_as_name
Show vehicle brand name instead of vehicle name. If brand name does not exist, vehicle name will be displayed instead.

    vehicle_name_uppercase
Set vehicle name to uppercase.

    vehicle_name_width
Set vehicle name display width, value in chars, such as 10 = 10 chars.

    vehicle_name_align_center
Align vehicle name in the center when enabled. Default is left alignment when disabled.

    show_brand_logo
Show user-defined brand logo if available.

    brand_logo_width
Set maximum brand logo display width in pixels. Note, maximum brand logo display height is automatically adapted to `font_size`. Modern design: logo column width follows `font_size` too, 20 being the default width.

    show_time_gap
Show relative time gap between player and opponents.

    show_time_gap_sign
Show plus or minus sign for time gap. `-` sign indicates opponent's relative position is in front of player, `+` sign indicates the opposite.

    time_gap_width
Set time gap display width, value is in chars, 5 = 5 chars wide.

    time_gap_align_center
Align time gap in the center when enabled. Default is right alignment when disabled.

    show_highlighted_nearest_time_gap
Show highlighted color on opponents within nearest time gap threshold.

    nearest_time_gap_threshold_front, nearest_time_gap_threshold_behind
Set nearest time gap threshold (in seconds) for opponent who is in front of or behind player. Default is `1` second for front, and `2` seconds for behind.

    show_laptime
Show driver's last lap time or pit stop duration if available. Invalid lap time is preceded by asterisk mark, such as *1:23.54.

    show_pitstop_duration_while_requested_pitstop
Show driver's last recorded pit stop duration (in lap time column) while you have requested pit stop.

    show_highlighted_fastest_last_laptime
Highlight the fastest last lap time within the same class if available.

    show_position_in_class
Show driver's position standing in class.

    show_class_style_for_position_in_class
Show class style background color for position in class.

    show_class
Show vehicle class categories. Class alias name and color are fully customizable in `classes.json` preset, see [Vehicle Class Editor](#vehicle-class-editor) section for details.

Note, random color will be displayed for unknown class name that is not defined in `classes.json` preset.

    class_width
Set class name display width, value is in chars, `4` = 4 chars wide. Set to `0` to hide class name while showing only class color.

    show_pit_status
Show indicator whether driver is currently in pit or garage, or causes yellow flag.

    pit_status_text
Set custom pit status text which shows when driver is in pit.

    garage_status_text
Set custom garage status text which shows when driver is in garage.

    yellow_flag_status_text
Set custom yellow flag status text which shows when driver causes (or likely to) yellow flag. Note, unlike in-game yellow flag, the indicator is always displayed when driver's speed is below 28kph (outside pit lane), regardless whether driver has caused yellow flag on track.

    finish_status_text
Set custom finish (checkered flag) status text which shows when driver finished race.

    show_tyre_compound
Show tyre compound symbol for tyre that matches specific tyre compounds defined in `compounds.json` preset.

    show_compound_for_each_wheel
Show tyre compound symbol for each wheel. Compound symbol display order is arranged as `front left, front right, rear left, rear right`. This option is enabled by default.

Disable this option to show a single symbol for all tyres, which allows a more compact view. If mixed tyres are used, a `X` symbol will be displayed instead, which can be customized by `mixed_compound_symbol` option.

    show_compound_color_by_type
Show different compound color by compound type, which can be customized in [Tyre Compound Editor](#tyre-compound-editor).

Note, player's compound color is not affected by this setting while `show_player_highlighted` option is enabled.

    tyre_compound_spacing
Set display spacing (in pixels) between each compound symbol. Default is `1` pixel.

    show_pitstop_count
Show each driver's pit stop count and penalty count if available. Note, when a driver accumulates one or more penalties, this column will show the number of penalties in negative value with purple (default) background to distinguish from number of pit stops.

    show_pit_request
Show pit request color indicator on pit stop count column.

    show_vehicle_in_garage
Show vehicles parked in garage stall. Default is `false`. Note, local player is always displayed.

    additional_players_front, additional_players_behind
Set additional players shown on relative list. Each value is limited to a maximum of 60 additional players (for a total of 120 additional players). Default is `0`.

[**`Back to Top`**](#)


## Relative finish order
**This widget displays estimated relative finish order between leader and local player with corresponding refilling estimate in a table view.**

**Overview**

This widget predicts `relative final lap progress` (percent into lap) at the moment when session timer ended in time-type race, or leader crossed finish line in laps-type race, which can be used to determine whether extra laps are required to finish race.

Simple example: in time-type race, at the moment when session timer ended, assume race leader's vehicle is in `Sector 1` (or 20% into lap), and local player is in `Sector 3` (or 80% into lap) which is ahead of leader in terms of `relative lap progress` (0% from start line to 100% at finish line). When local player finishes his current lap, the race does not end for him because leader is behind local player and has not yet crossed finish line. This means local player has to complete another lap in order to finish the race, and needs an extra lap of fuel.

---

The table consists of 5 fixed rows, 1 optional row, 3 fixed columns, and 10 optional prediction columns that can be customized. Example:

| TIME |   0s  |  30s  |  40s  |  50s  |  60s  |  54s  |
|:----:|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
|  LDR |  0.49 |  0.20 |  0.11 |  0.02 |  0.92 |  0.98 |
| 0.04 |  0.91 |  0.64 |  0.55 |  0.46 |  0.37 |  0.51 |
| DIFF |   0s  |  30s  |  40s  |  50s  |  60s  |  43s  |
|  NRG | +18.1 | +18.1 | +18.1 | +18.1 | +18.1 | +18.1 |
| EX+1 | +20.3 | +20.3 | +20.3 | +20.3 | +20.3 | +20.3 |

First and fourth rows, starting from second cell, show estimated `leader's pit time` and `local player's pit time`, where first row first cell shows current session type in `TIME` or `LAPS`. Last cell shows last recorded total time that leader and local player had spent in pit. Note, last recorded total pit time counts from pit entry to pit exit point, it doesn't include the extra few seconds that spent while approaching or exiting from pit.

Second and third rows, starting from second cell, show estimated `leader's final lap progress` (fraction of lap) and `local player's final lap progress` that depend on current session type:
* For `TIME` type race, it shows final lap progress at the moment when session timer ended.
* For `LAPS` type race, it shows relative final total lap difference between leader and local player.
Leader's value from second row second cell always shows `integer value`, because laps-type race has no timer, and the end of race is determined at the moment when leader crossed finish line, which can only be full laps.
Local player's value from third row second cell always shows final lap progress relative to leader's value from second row second cell.
Both leader's and local player's `final lap progress` values starting from third cell are offset from second cell of same row.

Third row, first cell shows `relative lap difference` between leader and local player that is calculated from lap time pace difference of both players, which can be used to determine whether leader has the chance to overtake local player on final lap. For example:
* If relative lap difference value shows 0.25, that means for every full lap, leader is faster than local player by 0.25 lap. If leader is at start line and player is just within 0.25 lap distance from leader, that means leader can catch up and overtake player before the end of lap.
* If relative lap difference value shows 0.25 and leader is at middle of current lap (0.5 lap), that means leader now only has roughly half of the lap distance (0.12 lap) to make successful overtake before the end of lap. If player is not within this 0.12 lap distance, then leader may not be able to overtake.

Fifth row, first cell shows refilling type in `FUEL` or `NRG` (if virtual energy available). Starting from second cell, shows estimated `local player's refilling` that depends on current session type:
* For `TIME` type race, refilling value from each column is calculated based on local player's current `laptime pace`, `consumption`, and `local player's final lap progress` from third row of same column. Note, each refilling value has no relation to `leader's final lap progress` value from same column. Refilling value from `0s` column gives same reading as seen from `Fuel` or `Virtual Energy` Widget in time-type race.
* For `LAPS` type race, only refilling value from `0s` column is calculated and displayed according to leader's `leader's final lap progress` value.
Other column values are not displayed, this is done to avoid confusion. Because unlike `TIME` type race where all `final lap progress` values are within `0.0` to `1.0` range, in `LAPS` type race values can exceed `1.0` or below `0.0` (negative), which the number of possible lap differences would increase exponentially and not possible to list all of them in the widget.

Sixth row (optional), first cell shows `number of extra laps` for extra refilling display. Starting from second cell, shows estimated `extra refilling` value that depends on `local player's refilling` value and `number of extra laps` setting. Each extra refilling value equals `extra laps of consumption` plus `local player's refilling` value of same column. Those values save the trouble from manual calculation in case there will be extra laps.

See `TIME` or `LAPS` type race example usages below for details.

---

**Important notes**

* Prediction accuracy depends on many variables and is meant for final stint estimate. Such as laptime pace, pit time, penalties, weather condition, safety car, yellow flag, can all affect prediction accuracy. It requires at least 2-3 laps to get sensible readings, and more laps to have better accuracy.

* `Final lap progress` values will not be displayed if no corresponding valid lap time pace data found, which requires at least 1 or 2 laps to record. If local player is the leader, then all values from leader's row will not be displayed. Refilling values will not be displayed during formation lap for the reasons mentioned in first note.

* Refilling estimate calculation is different between `TIME` and `LAPS` type races, make sure to look at the correct value, check out `example usage` below for details.

* `LMU` currently uses `absolute refueling` mechanism (amount `total` fuel to fill tank up to), as opposite to relative fuel (amount to `add` on top of remaining fuel in tank). User can enabled `show_absolute_refilling` option to display total amount fuel/energy required (including fuel/energy in tank) to finish race.

---

**Time-type race example usage**

| TIME | 0s   | 30s  | 40s  | 50s  | 60s  | 0s   |
|:----:|:----:|:----:|:----:|:----:|:----:|:----:|
| LDR  | 0.38 | 0.10 | 0.01 | 0.91 | 0.82 | 0.38 |
| 0.11 | 0.72 | 0.47 | 0.39 | 0.31 | 0.22 | 0.37 |
| DIFF | 0s   | 30s  | 40s  | 50s  | 60s  | 43s  |
| FUEL | +7.4 | +7.4 | +7.4 | +7.4 | +7.4 | +7.4 |
| EX+1 | +11.2 | +11.2 | +11.2 | +11.2 | +11.2 | +11.2 |

1. Determine leader's next pit time and select `leader's final lap progress` (second row) value from corresponding pit time (first row) column. `0s` column means no pit stop.

2. Determine local player's next pit time and select `local player's final lap progress` (third row) value from corresponding pit time (fourth row) column.

3. Compare the two `final lap progress` values from leader and local player, assume fuel per lap is `3.8`:

    * If leader's `final lap progress` value is greater than local player, such as leader's 0.91 (50s column) vs player's 0.47 (30s column), it indicates that leader will be ahead of local player when timer ended, and there will be no extra final lap. So `local player's refilling` value from corresponding `30s` column can be used, in this case, it's `+7.4` fuel to add.
    However, if leader is closer to finish line (as show in orange color indicator), there is a chance that leader may be fast enough to cross finish line before the end of timer, which would result an extra final lap for local player, and requires adding an extra lap of fuel (`3.8`) on top of `+7.4` fuel. In this case it would be `+11.2` refuel, or you can simply look at the refuel value from `extra refilling row` of same column.

    * If local player's `final lap progress` value is greater than leader, such as leader's 0.10 (30s column) vs player's 0.39 (40s column), it indicates that local player will be ahead of leader when timer ended, and there will be an extra final lap for local player, and here again requires adding an extra lap of fuel (`3.8`) on top of `+7.4` fuel from `40s` column, which is `+11.2` refuel.
    However, if the difference between the two `final lap progress` values is smaller than `relative lap difference` (from third row first cell) value, it may indicate that leader could overtake local player on final lap, which would result no extra final lap.

4. To sum up, if comparison shows no extra final lap, then just refill according to `local player's refilling` (fifth row) value from the same column of `local player's final lap progress` (third row). If comparison shows an extra final lap, then just add an extra lap of fuel on top of `local player's refilling` value; or, just look at the refuel value from `extra refilling row` of same column.


**Laps-type race example usage**

Note, there is generally no reason to use this widget in `LAPS` type race unless you are doing multi-class laps-type race which is very rarely seen.

| LAPS | 0s    | 30s  | 40s   | 50s   | 60s   | 0s   |
|:----:|:-----:|:----:|:-----:|:-----:|:-----:|:----:|
| LDR  | 2.00  | 1.57 | 1.43  | 1.28  | 1.14  | 2.00 |
| 0.11 | 0.40  | 0.02 | -0.11 | -0.24 | -0.37 | 0.40 |
| DIFF | 0s    | 30s  | 40s   | 50s   | 60s   | 43s  |
| FUEL | +12.8 | -    | -     | -     | -     | -    |
| EX+1 | +15.0 | -    | -     | -     | -     | -    |

1. Determine leader's next pit time and select `leader's final lap progress` (second row) value from corresponding pit time (first row) column. `0s` means no pit stop.

2. Determine local player's next pit time and select `local player's final lap progress` (third row) value from corresponding pit time (fourth row) column.

3. Subtract `local player's final lap progress` value from `leader's final lap progress`, then round down value:

    * If leader's `final lap progress` value is 2.00 (0s column), and local player's `final lap progress` value is 0.40 (0s column), then after subtracting (2 - 0.4 = 1.6) and rounding down, the final value is `1` lap difference, which means local player will do `one less lap` than leader.
    As mentioned earlier, for laps-type race, refilling value from `0s column` is calculated according to leader's `leader's final lap progress` value, which any lap difference is already included in the result from `local player's refilling` value (fifth row second cell), in this case, it's `+12.8` fuel to add.

    * If leader's `final lap progress` value is 1.43 (40s column), and local player's `final lap progress` value is -0.24 (50s column), then after subtracting (1.43 - -0.24 = 1.67) and rounding down, the final value is also `1` lap difference, which means local player will do the same `one less lap` than leader. So in this case, it's still `+12.8` fuel to add.

    * If leader's `final lap progress` value is 2.00 (0s column), and local player's `final lap progress` value is -0.11 (40s column), then after subtracting (2 - -0.11 = 2.11) and rounding down, the final value is `2` lap difference, which means local player will do `two less laps` than leader. So an extra lap of fuel may be removed from `local player's refilling` value from fifth row second cell, in this case, it's `12.8` minus one lap of fuel `2.2`, equals `+10.6` fuel to add. Alternatively, it can be calculated from full lap refuel (as show in Fuel Widget), which will be `15.0` minus two lap of fuel `4.4`, and equals `+10.6` fuel to add.
    Be aware that carrying less fuel is risky in laps-type race due to reasons below.

4. Last note, since the end of laps-type race is determined by the moment that leader completed all race laps, leader can greatly affect final prediction outcome. To give an extreme example, if leader is ahead of everyone by a few laps, and decides to wait a few minutes on his final lap before finish line, then everyone else will be catching up and do a few `extra laps` which would require more fuel. Thus it is always risky to carry less fuel in laps-type race.

---

    layout
2 layouts are available: `0` = show columns from left to right, `1` = show columns from right to left.

    near_start_range
Set detection range (in seconds) near (after) start/finish line to show color indicator when vehicle is within the range (or less). Default is `20` seconds. Default color is green.

    near_finish_range
Set detection range (in seconds) near (before) start/finish line to show color indicator when vehicle is within the range (or less). Default is `20` seconds. Default color is orange.

    show_absolute_refilling
Show absolute refilling value instead of relative refilling when enabled. Note, `+` or `-` sign is not displayed with absolute refilling.

    show_extra_refilling
Show readings of extra refilling row below `local player's refilling` row. Each extra refilling value equals `extra laps of consumption` plus `local player's refilling` value of same column. Those values save the trouble from manual calculation in case there will be extra laps.

The first column of extra refilling row shows number of extra laps depends on `number of extra laps` setting, such as `EX+1` for 1 extra lap, or `EX+3` for 3 extra laps.

    number_of_extra_laps
Set number of extra laps for extra refilling calculation. Default is `1` extra lap.

    number_of_prediction
Set number of optional prediction columns with customizable pit time. Value range in `0` to `10`. Default is `4` extra customizable columns.

    prediction_*_leader_pit_time, prediction_*_player_pit_time
Set prediction pit time for leader or local player.

[**`Back to Top`**](#)


## Ride height
**This widget displays visualized ride height info.**

    ride_height_maximum_range
Set visualized maximum ride height display range (millimeter).

    bottoming_height_*
Set bottoming ride height (in millimeters). This option is used for vehicle that hits ground before ride height reading reaches zero.

    show_axle_ride_height
Modern design: show front and rear ride height from game (aerodynamic reference, in millimeters) between left and right tiles.

[**`Back to Top`**](#)


## Rivals
**This widget displays standings info from opponent ahead and behind local player from same vehicle class.**

Note, most options are inherited from [Relative](#relative) and [Standings](#standings) widgets, with some additions noted below.

    column_delta_laptime, column_time_interval
Modern design columns besides those of [Relative](#relative): lap time difference to player over recent laps, and interval to player (car ahead in green, car behind in orange).

    column_brand_logo, column_average_laptime, column_speed_trap, column_lift_and_coast_time
Modern design columns: brand logo after vehicle name (on by default: own logo of brand logo folder, else logo taken from the game, brand initials until found; width follows `brand_logo_width`), then, off by default, average lap time of recent laps after best lap time, speed trap (fastest speed at speed trap line, in speed unit) and lift and coast time (highlighted above `lift_and_coast_highlight_threshold`) after stint laps. Overlay Options page lists columns in one Columns list, from left to right: each column switched on or off there, and moved by drag or arrows. With `show_compound_for_each_wheel`, tyre compounds of each wheel are shown in a 2x2 grid when left and right compounds of an axle differ. With `show_class_style_for_position_in_class`, position in class part of class pill is in class color.

    show_player_highlighted
Highlight player row with customizable specific color.

    show_lap_difference
Show different font color based on lap difference between player and opponents. Note, this option will override `font_color` setting from `position`, `driver name`, `vehicle name`.

    show_highlighted_fastest_last_laptime
Highlight the fastest last lap time within the same class if available.

    time_interval_align_center
Align time interval in the center when enabled. Default is right alignment when disabled.

    *_color_time_interval_ahead, *_color_time_interval_behind
Set custom time interval color of opponent ahead and behind.

[**`Back to Top`**](#)


## Roll angle
**This widget displays vehicle front and rear roll angles info.**

    show_degree_and_percentage_sign
Set `true` to show degree and percentage sign.

    wheel_track_front, wheel_track_rear
Set front and rear wheel track in millimeters. Default is `1800` millimeters. This option affects `roll angle` calculation accuracy.

    roll_angle_smoothing_samples, roll_angle_ratio_smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

    show_roll_angle_difference
Show roll angle difference between front and rear roll angles.

    show_roll_angle_ratio
Show roll angle ratio between front and rear. 50% indicates equal roll angle; less than 50% indicates rear rolls more than front.

[**`Back to Top`**](#)


## RPM LED
**This widget displays RPM LED info.**

Modern design: capsule LEDs with a soft glow when lit; unlit LEDs keep a faint tint of their color zone (green, yellow, red), so zones can be read before they light up.

    number_of_led
Set number of LED to display. Minimum LED is limited to `3`.

    enable_double_side_led
Enable `Outside to Center` LED layout (as opposite to `Left to Right` layout). While this option is enabled, total number of LED is doubled.

    led_width, led_height, led_radius
Set LED width, height, radius in pixels. To achieve circle LED, set a higher radius value.

    rpm_multiplier_low
This value multiplies maximum RPM value, which sets starting range of RPM LED.

    rpm_multiplier_safe
This value multiplies maximum RPM value, which sets safe range of RPM LED.

    rpm_multiplier_redline
This value multiplies maximum RPM value, which sets redline range of RPM LED.

    rpm_multiplier_critical
This value multiplies maximum RPM value, which sets critical range of RPM LED.

    rpm_multiplier_over_rev
This value multiplies maximum RPM value, which sets over rev range of RPM LED.

    show_rpm_flickering_above_critical
Show flickering effects when RPM is above critical range and gear is lower than maximum gear.

    show_speed_limiter_flash
Show RPM LED flash effect when speed limiter is activated.

    speed_limiter_flash_interval
Set minimum time interval between each LED flash. Default is `0.25` seconds. Minimum value is limited to `0.2`.

[**`Back to Top`**](#)


## Sectors
**This widget displays sectors timing info.**

    enable_all_time_best_sectors
Show sectors timing based on all time best sectors instead of current session. This option is enabled by default. Set `false` to show sectors timing from current session only.

    target_laptime
Set target laptime for display target reference lap and sector time. Set `Theoretical` to show theoretical best sector time. Set `Personal` to show sector time from personal best lap time. Note, if `enable_all_time_best_sectors` option is enabled in `Sectors Module`, all time best sectors data will be displayed instead, otherwise only current session best sectors data will be displayed.

    freeze_duration
Set freeze duration (seconds) for displaying previous sector time. Default is `5` seconds.

    show_formatted_sector_time
Show sector time in `minutes:seconds` format. Disable this option to show sector time in `seconds` only.

    extra_digits
Set extra digits for sector time display.

[**`Back to Top`**](#)


## Session
**This widget displays system clock, session name, timing, lap number, overall position info.**

    show_session_name
Show current session name that includes testday, practice, qualify, warmup, race.

    session_text_*
Set custom session name text.

    show_system_clock
Show current system clock time.

    system_clock_format
Set clock format string. To show seconds, add `%S`, such as `%H:%M:%S %p`. See [link](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) for full list of format codes.

    show_session_time
Show total remaining session time.

    show_estimated_laps
Show estimated total remaining laps (from current lap position towards finish line) based on total remaining session time and local player's lap time pace.

Note, this is the same value that used for calculating estimated refueling value in Fuel Module.

This reading does not concern about race leader's lap time pace, which means there may be an extra final lap on top of it. See `show_predicted_extra_laps` option below for extra laps prediction.

    show_predicted_extra_laps
Show number of more (or less) laps prediction on top of total estimated laps in race, based on leader's lap time pace and player's estimated pit stop duration.

Predicted extra laps reading is not added to the estimated laps reading, and is not taken into fuel calculation. Positive reading indicates there may be extra final laps on top of total estimated laps; negative reading indicates there may be less final laps on top of total estimated laps.

For example, a `12.45(+1)` reading means there are `12.45` total estimated laps, plus `1` predicted final lap, which may result `12.45 + 1` = `13.45` final estimated laps.

Note, this option only works for time-based race type, and there is no guarantee that prediction will be 100% accurate, as anything can happen in the last hour of race.

[**`Back to Top`**](#)


## Slip angle
**This widget displays visualized slip angle info.**

    slip_angle_maximum_range
Set visualized maximum slip angle display range (degrees). Default is `15` degrees.

    minimum_oversteer_slip_angle_difference, minimum_understeer_slip_angle_difference
Set minimum slip angle difference threshold (in degrees) for neutral steer, oversteer and understeer color indication.

Note, value should be set as negative angle for oversteer, and positive angle for understeer.

[**`Back to Top`**](#)


## Slip ratio
**This widget displays visualized slip ratio info.**

    slip_ratio_optimal_range
Set optimal slip ratio range (percentage) for optimal and critical slip ratio color indication, value range in `0` to `100`. Default is `30` percent.

    slip_ratio_maximum_range
Set visualized maximum slip ratio display range (percentage), value range in `10` to `100`. Default is `50` percent.

[**`Back to Top`**](#)


## Speedometer
**This widget displays conditional speed info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_speed
Show current vehicle speed.

    show_speed_minimum
Show minimum speed that is updated while off throttle.

    show_speed_maximum
Show maximum speed that is updated while on throttle.

    show_speed_fastest
Show fastest recorded speed. To reset current record, shift gear into reverse, or reload preset.

    off_throttle_threshold
Set throttle threshold which counts as off throttle if throttle position is lower, value range in `0.0` to `1.0`. Default is `0.5`.

    on_throttle_threshold
Set throttle threshold which counts as on throttle if throttle position is higher, value range in `0.0` to `1.0`. Default is `0.01`.

    speed_minimum_reset_cooldown, speed_maximum_reset_cooldown
Set cooldown duration (seconds) before resetting minimum or maximum speed value.

[**`Back to Top`**](#)


## Spotter
**This widget displays two slim side bars, lit while a car is alongside.**

Place widget so that its bars sit at left and right screen edges (see `horizontal_gap`). Lit part of a bar is the part of player car overlapped by the car alongside: top of bar is front of car, bottom of bar is rear of car. Bar is shown in critical color while car alongside is close sideways. Once a side is free again, its bar flashes in clear color (green), like a spotter calling "clear". A car coming up behind on a side, not alongside yet, lights the bottom of the bar, brighter as it gets closer. Car positions come from `Vehicles module`, same as Radar widget. Nothing is shown while no car is alongside, unless overlay is unlocked, or `show_bar_background` is enabled.

Modern design: bars with rounded ends glowing toward screen center, lit part going from warning to loss color as the car alongside gets closer sideways.

    bar_width, bar_height
Set side bar width and height in pixels.

    horizontal_gap
Set gap between left and right side bars in pixels.

    vehicle_length, vehicle_width
Set vehicle overall size (length and width), value in meters.

    nearby_side_distance
Set maximum side distance in meters (between car centers) for a car to be alongside. Default is `5` meters.

    critical_side_distance
Set side distance in meters (between car centers) under which car alongside is shown in critical color. Default is `2.6` meters.

    show_clear_signal, clear_signal_duration
Flash side bar in clear color once the car alongside is gone, fading out over `clear_signal_duration` seconds. Default is enabled, `1` second.

    show_approaching_cars, approaching_distance
Light bottom of side bar while a car comes up behind on that side (not in player lane), brighter as it gets closer: from `approaching_distance` meters between its front and player car rear, up to overlapping. Default is enabled, `10` meters.

    bar_color_clear
Set side bar color of clear signal (classic layout).

    show_bar_background
Always show side bar background, also while no car is alongside.

[**`Back to Top`**](#)


## Standings
**This widget displays standings info.**

Note, most options are inherited from [Relative](#relative) widget, with some additions noted below.

    column_delta_laptime, column_time_interval
Modern design columns besides those of [Relative](#relative): lap time difference to player over recent laps (green if player was faster), and interval to car ahead. `column_time_gap` shows gap to leader (or to leader best lap outside race). Space separates class groups in multi-class split mode.

    column_brand_logo, column_average_laptime, column_speed_trap, column_lift_and_coast_time
Modern design columns: brand logo after vehicle name (on by default: own logo of brand logo folder, else logo taken from the game, brand initials until found; width follows `brand_logo_width`), then, off by default, average lap time of recent laps after best lap time, speed trap (fastest speed at speed trap line, in speed unit) and lift and coast time (highlighted above `lift_and_coast_highlight_threshold`) after stint laps. Overlay Options page lists columns in one Columns list, from left to right: each column switched on or off there, and moved by drag or arrows. With `show_compound_for_each_wheel`, tyre compounds of each wheel are shown in a 2x2 grid when left and right compounds of an axle differ. With `show_class_style_for_position_in_class`, position in class part of class pill is in class color.

    show_player_highlighted
Highlight player row with customizable specific color.

    show_lap_difference
Show different font color based on lap difference between player and opponents. Note, this option will override `font_color` setting from `position`, `driver name`, `vehicle name`.

    show_highlighted_fastest_last_laptime
Highlight the fastest last lap time within the same class if available.

    enable_single_class_exclusive_mode
Enable single-class exclusive mode, which displays vehicles from player's class only. This mode takes priority over all other display mode.

    enable_multi_class_split_mode
Enable multi-class split mode, which splits and displays each vehicle class in separated groups. This mode will only take effect when there is more than one vehicle class present in a session, otherwise it will automatically fall back to normal single class mode.

    minimum_top_vehicles
Set minimum amount top place vehicles to display. This value has higher priority over other `maximum_vehicles` settings. Default is `3`, which always shows top 3 vehicles if present.

    maximum_vehicles_exclusive_mode
Set maximum amount vehicles to display in exclusive mode, which takes effect when `enable_single_class_exclusive_mode` is enabled.

    maximum_vehicles_combined_mode
Set maximum amount vehicles to display in combined mode, which takes effect when `enable_multi_class_split_mode` is not enabled. When total vehicle number is lower than this value, extra rows will auto-hide. When total vehicle number is above this value, the top 3 vehicles will always show, and rest of the vehicles will be selected from the nearest front and behind places related to player.

    maximum_vehicles_split_mode
Set maximum amount vehicles to display in split mode, which takes effect when in multi-class session and `enable_multi_class_split_mode` is enabled. If total vehicle number is above this value, any extra vehicles will not be shown. Default is `50`, which is sufficient in most case.

    maximum_vehicles_per_split_player
Set maximum amount vehicles to display for class where player is in. Default is `7`. Note that, if player is not in first place, then at least one opponent ahead of player will always be displayed, even if this value sets lower.

    maximum_vehicles_per_split_others
Set maximum amount vehicles to display for classes where player is not in. Default is `3`.

    split_gap
Set split gap between each class.

    show_time_gap
Show each driver's time gap behind overall leader in race session. In none race sessions, time gap is calculated from overall leader's session best lap time.

    show_time_gap_from_same_class
Show time gap from same class leader instead of overall leader. This option only takes effect while `enable_multi_class_split_mode` is enabled.

    time_gap_leader_text
Set text indicator for race leader in time gap column. Modern design shows its own label (Leader) while this text is left at default.

    show_time_interval
Show time interval between each closest driver in order.

    show_time_interval_from_same_class
Show time interval from same class. This option only takes effect while `enable_multi_class_split_mode` is enabled.

    time_interval_leader_text
Set text indicator for race leader in time interval column. Modern design shows a dash while this text is left at default.

    show_laptime
Show driver's last lap time or pit stop duration if available. Invalid lap time is preceded by asterisk mark, such as *1:23.54.

Note, if `show_best_laptime` is not enabled, this option will show driver's session best lap time in none-race sessions.

    show_best_laptime
Show driver's session best lap time.

    show_best_laptime_from_recent_laps_in_race
Show driver's best lap time from (five) most recent laps in race session. This option provides a better view of driver's recent performance during longer race.

    show_average_laptime
Show driver's average lap time calculated from (five) most recent laps.

    show_delta_laptime
Show lap time difference (delta) between player and opponents from most recent laps (up to 5 recent lap time records). The default layout order shows delta lap time records from right side column (most recent lap) to left.

A green color (default) delta indicates that player's recent lap time is faster than opponent, while orange color delta indicates the opposite.

    show_inverted_delta_laptime_layout
Enable this option to invert layout order for delta lap time records.

    number_of_delta_laptime
Set number of delta lap time records to display. Minimum number is limited to `2`, maximum is limited to `5`.

    show_stint_laps
Show number of completed laps from current stint and estimated total stint laps. Note, it may require a few laps to get accurate estimate.

    show_energy_remaining
Show remaining virtual energy reading in percentage from each driver, with 4 different states:
- Unavailable: virtual energy reading is not available currently, default color grey.
- High: above 30% remaining, default color green.
- low: from 30% to 10% remaining, default color orange.
- critical: 10% or lower remaining, default color red.

Note, for vehicle without virtual energy, remaining fuel (only if available) will be displayed instead. If fuel data is not available from game API, then nothing will be displayed.

    energy_remaining_decimal_places
Set additional decimals to be displayed.

**Important notes on decimal place accuracy:**

Currently due to known limitation from game API (as explained in User Guide), energy remaining readings from game API does not grant decimal place accuracy. The margin of error from this option can be as high as 1.0% per lap, which may not provide more accuracy than without decimals.

    show_vehicle_integrity
Show opponent vehicle integrity reading.

The integrity reading is calculated from hull damage, detachable wheels and parts, and displayed as:
- Full integrity (no damage), as `-` (default color grey).
- High integrity (lightly damaged hull), from `9` to `5` (default color blue).
- Low integrity (severely damaged hull, and most likely has detached wheels or parts), from `4` to `0` (default color red).

    show_incidents
Show total number of incidents for each driver from current session. This option helps tracking opponent's safeness and cleanness during long race. This option only works for `LMU`.

Note, incidents are counted from vehicle contacts and track cuts only for each individual driver. Incidents are not counted towards team. Incidents are only counted while this APP is running, and reset if changed session or restarted this APP.

    incidents_high_threshold, incidents_extreme_threshold
Set threshold for showing color indication when number of incidents are equal or above.

    show_speed_trap
Show fastest recorded speed of each driver per lap at user-defined speed trap position on track. This option can be useful to keep track of each driver's straight line performance from most recent lap.

Note, speed trap position is defined in `tracks.json` preset, which can be customized via [Track Info Editor](#track-info-editor). Default speed trap position is set at start/finish line.

    show_lift_and_coast_time
Show most recent recorded lift and coast time (in seconds) from each driver.

    lift_and_coast_reset_threshold
Set time threshold (in seconds) for resetting recent recorded lift and coast time. Default is `60` seconds.

    lift_and_coast_highlight_threshold
Set minimum time threshold (in seconds) for highlighting lift and coast time. Default is `1` seconds.

[**`Back to Top`**](#)


## Steering angle
**This widget displays steering and wheel angle info.**

    wheel_track_front
Set front wheel track in millimeters. Default is `1800` millimeters. This option affects `Ackermann percentage` calculation accuracy.

    wheelbase
Set wheelbase in millimeters. Default is `2800` millimeters. This option affects `Ackermann percentage` and `turning radius` calculation accuracy.

    show_steering_angle
Show steering angle in degrees.

    manual_steering_range
Manually set steering display range in degrees. Set to `0` to read physical steering range from API. This option may be useful when steering range value is not provided by some vehicles.

    show_front_wheel_angle
Show average front wheel angle in degrees.

    show_steering_ratio
Show steering ratio between steering wheel angle and average front wheel angle.

    show_ackermann_percentage
Show Ackermann percentage of inner and outer wheel angle during cornering. `0` percent indicates parallel steering. `100` percent indicates true Ackermann steering. Negative percent indicates Anti-Ackermann steering.

    show_slip_angle_difference
Show slip angle difference (in degrees) between average front and rear slip angle, with neutral steer, oversteer and understeer color indication.

Positive reading indicates understeer tendency (default orange color). Negative reading indicates oversteer tendency (default blue color). Reading close to zero indicates neutral steer (default white color).

    minimum_oversteer_slip_angle_difference, minimum_understeer_slip_angle_difference
Set minimum slip angle difference threshold (in degrees) for neutral steer, oversteer and understeer color indication.

Note, value should be set as negative angle for oversteer, and positive angle for understeer.

    show_yaw_rate
Show yaw rate (angular velocity) in degrees per second.

    show_inverted_yaw_rate_sign
Show inverted plus and minus signs for yaw rate. This option is disabled by default.

    show_turning_radius
Show turning radius based on front wheel angle (average of left and right front wheel).

Note, this value does not take account of slip angle effect, which can be different from, or in extreme case, opposite of actual turning radius that affected by slip angle, such as during counter steering.

    show_turning_radius_under_slip_angle
Show turning radius affected by slip angle.

[**`Back to Top`**](#)


## Steering meter
**This widget displays steering input info.**

Modern design: track with a center mark, bar growing from center toward steering side with a bright thumb at wheel position, faint scale marks, steering angle written on the other half of the track.

    bar_width, bar_height
Set steering meter bar width and height in pixels.

    bar_edge_width
Set left and right edge boundary width.

    manual_steering_range
Manually set steering display range in degrees. Set to `0` to read physical steering range from API. This option may be useful when steering range value is not provided by some vehicles.

    show_steering_angle
Show steering angle in degrees.

    show_scale_mark
This enables scale marks on steering meter bar.

    scale_mark_degree
Set gap between each scale mark in degrees. Default is `90` degrees. Minimum value is limited to `10` degrees.

[**`Back to Top`**](#)


## Steering wheel
**This widget displays virtual steering wheel.**

    show_custom_steering_wheel
Show user-defined custom steering wheel image instead of default image.

    custom_steering_wheel_image_file
Set custom steering wheel image file path. Double-click this option in widget's `Config` dialog to select an image file.

Note, image file must be in `PNG` format with same width and height. Maximum supported `PNG` file size is limited to `10MB`. Default image will be used if selected image is not valid.

    display_size
Set widget display size in pixels.

    display_margin
Set widget display margin in pixels.

    show_steering_angle
Show steering angle in degrees.

    manual_steering_range
Manually set steering display range in degrees. Set to `0` to read physical steering range from API. This option may be useful when steering range value is not provided by some vehicles.

    show_rotation_line
Show steering rotation reference line, which can be useful to see if physical steering wheel is misaligned.

    show_rotation_line_while_stationary_only
Show rotation line only while vehicle is stationary (less than 1m/s).

[**`Back to Top`**](#)


## Stint history
**This widget displays stint history info.**

Note, stint history is not recorded while in garage or during formation lap.

    layout
2 layouts are available: `0` = vertical layout, `1` = reversed vertical layout.

    stint_history_count
Set the number of stint history display. Default is to show `2` most recent stints.

    show_empty_history
Show empty stint history. Default is `false`, which hides empty rows.

    show_laps
Show number of completed laps in the stint.

    show_time
Show total driving time in the stint.

    show_fuel
Show total fuel (or virtual energy) consumption in the stint.

    show_virtual_energy_if_available
Show virtual energy consumption instead of fuel consumption if available. This option is enabled by default.

    show_fuel_sign
Show fuel (or virtual energy) unit sign. `L` for liter, `G` for Gallon, `E` for virtual energy.

    show_tyre
Show tyre compound used in the stint.

    show_wear
Show total average tyre wear (percent) in the stint.

    show_wear_sign
Show tyre wear percentage sign.

    show_delta
Show lap time delta between stint best and stint average non-best lap time. Note, pit-in and pit-out laps are excluded from calculation.

    show_consistency
Show lap time consistency (percent) between stint best and stint average non-best lap time. Note, pit-in and pit-out laps are excluded from calculation.

    show_consistency_sign
Show consistency percentage sign.

[**`Back to Top`**](#)


## Stint timer
**This widget displays stint time and driving time of each driver, for endurance races.**

Stint time and laps come from `Stint module`. Driving time of each driver is counted from driver name of player car (teammates included while they drive the car), from the moment widget is running: it is kept while widget reloads, and reset when a new session starts. Fair share is race length divided by number of drivers (timed race only).

    maximum_stint_minutes
Set maximum stint length in minutes for stint countdown. Countdown is shown in warning color near the end, and as negative time in loss color once exceeded. Set `0` to disable. Default is `0`.

    stint_warning_minutes
Set remaining stint minutes under which countdown is shown in warning color. Default is `5` minutes.

    show_stint_laps
Show laps of current stint.

    show_stint_countdown
Show countdown to maximum stint length.

    show_driver_times
Show fair share, and driving time of each driver with time left to target. Target is minimum driving time if set, otherwise fair share.

    number_of_drivers
Set number of drivers of the car, for fair share and number of driver rows. Set `0` to use number of drivers seen in session. Value range in `0` to `6`. Default is `0`.

    minimum_driving_minutes
Set minimum driving time per driver in minutes, used as target. Set `0` to use fair share as target instead. Default is `0`.

[**`Back to Top`**](#)


## Suspension force
**This widget displays visualized suspension force and ratio info.**

    show_force_ratio
Show percentage force ratio between each and total suspension force. Set `false` to show individual suspension force in Newtons.

[**`Back to Top`**](#)


## Suspension position
**This widget displays visualized suspension position info.**

    position_maximum_range
Set visualized maximum display range of suspension position (millimeter).

    show_third_spring_position_mark
Show front and rear third spring position mark relative to each suspension position.

    show_maximum_position_range
Show a visualized line indicating maximum suspension position range under compression, which can be useful to check suspension travel limits. While this option enabled, the suspension position line will also change its color to match `maximum_position_range_color` when reaching maximum position. The visualized line will not be displayed if maximum position range is negative (such as with too much packers).

Note, maximum suspension position calculation is handled by [Wheels Module](#wheels-module), and resets after exited garage. A minimum of two laps are required to get sensible readings.

[**`Back to Top`**](#)


## Suspension travel
**This widget displays suspension travel info.**

Note, suspension travel data calculation is handled by [Wheels Module](#wheels-module), and resets after exited garage.

Static suspension position is measured only while car is stationary on track or in garage stall (neutral gear and no throttle). Measurement is disabled in pit lane, as car can be lifted by pit crew which would result incorrect readings.

A minimum of two laps are required to get sensible readings.

    show_total_travel
Show total travel (millimeter) between minimum and maximum recorded suspension position.

    show_bump_travel
Show bump travel (millimeter) between static and maximum recorded suspension position. Note, bump travel may not be available if static suspension position was not recorded.

    show_rebound_travel
Show rebound travel (millimeter) between static and minimum recorded suspension position. Note, rebound travel may not be available if static suspension position was not recorded.

    show_travel_ratio
Show travel ratio (percentage) between bump travel and total travel. For example, a `70%` reading indicates 70% of travel is spent in bump, and 30% of travel in rebound. A `50%` reading indicates equal travel in bump and rebound travel.

    show_motion_ratio
Show estimated motion ratio between suspension and wheel travel. Note, the accuracy depends on game API data, and may not be available on certain vehicles.

    show_minimum_position
Show minimum recorded suspension position (millimeter) where suspension is reaching its maximum extension.

    show_maximum_position
Show maximum recorded suspension position (millimeter) where suspension is reaching its maximum compression.

    show_live_position
Show current suspension position (millimeter).

    show_live_position_relative_to_static_position
Show current suspension position (millimeter) relative to static position instead.

[**`Back to Top`**](#)


## System performance
**This widget displays system performance info.**

    show_system_performance
Show system's overall CPU utilization (percent) and memory usage (GB). Note, sampling interval is determined by `update_interval` setting.

    show_tinypedal_performance
Show Modern Tiny Pedals's CPU utilization (percent) and memory usage (MB).

    average_samples
Set number of samples for average CPU utilization calculation. Lower value may result more fluctuated reading. Set `1` to disable averaging.

[**`Back to Top`**](#)


## Telemetry comparison
**This widget compares live telemetry with reference lap of Lap Telemetry Viewer, along a distance window around car.**

Charts show speed, throttle & brake, steering and gear. Reference lap is drawn over whole window, so next braking point of reference lap shows ahead of car; current lap is drawn behind car, up to position mark. With modern design, reference lap is a soft area & faint line, current lap a bright line. Reference lap comes from laps recorded by [Recorder module](#recorder-module) for current track & class, `Recorder module` must be enabled. `Delta module` keeps charts moving smoothly between game position updates.

    display_width, display_height
Set chart width and speed chart height in pixels. Pedal, steering and gear charts are smaller, in proportion to `display_height`.

    bar_gap
Set gap between charts in pixels (classic layout).

    distance_behind, distance_ahead
Set distance in meters shown behind and ahead of car. Default is `250` meters behind and `150` meters ahead.

    reference_lap_source
Set reference lap. Available values are: `Viewer` = lap set as reference in Lap Telemetry Viewer (last lap selection of track), `Best` = fastest valid recorded lap, `Last` = last recorded lap. Without lap set in viewer, fastest valid lap is used. Reference lap is checked again every few seconds, so a new best lap or a reference changed in viewer is used while driving.

    decimal_places
Set amount of decimal places of delta reading.

    show_reference_lap_time
Show reference lap time, or `No reference lap` while track has no recorded lap.

    show_delta
Show time delta against reference lap at car position: current lap time minus reference lap time at same distance.

    show_speed_difference
Show speed difference against reference lap at car position: positive when faster than reference lap.

    show_speed, show_throttle, show_brake, show_steering, show_gear
Show chart of each channel. Throttle and brake share pedal chart.

    reference_line_opacity
Set opacity of reference lap lines (classic layout), from `0` to `1`. Reference lap lines are drawn with color of channel, thicker and faded.

[**`Back to Top`**](#)


## Timing
**This widget displays lap time info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_session_best
Show current session best lap time from all vehicle classes.

    show_session_best_from_same_class_only
Show current session best lap time from same vehicle class only.

    show_best
Show personal all time best lap time.

    show_last
Show personal last lap time.

    show_current
Show personal current lap time.

    show_estimated
Show personal current estimated lap time.

    show_session_personal_best
Show personal current session best lap time.

    show_stint_best
Show personal current stint best lap time.

    show_average_pace
Show personal current average lap time pace, this reading is also used in real-time fuel calculation. Note, additional `average lap time pace` calculation setting can be found in [Delta Module](#delta-module) config. After ESC or session ended, lap time pace reading will be reset, and aligned to `all time personal best lap time` if available.

    show_invalid_lap_indicator
Modern design: highlight current lap time in loss color while game invalidated current lap (track limits). This option only works for `LMU`.

[**`Back to Top`**](#)


## Track clock
**This widget displays track clock, time scale, sunlight phase info.**

    show_track_clock
Show current in-game clock time of the circuit.

    enable_track_clock_synchronization
Enable auto track clock and time scale synchronization. `enable_restapi_access` must be enabled to synchronize track clock from Rest API.

Note, synchronization may not work in multiplayer.

    track_clock_time_scale
Manually set time multiplier for time-scaled session. Default is `1`, which matches `Time Scale: Normal` setting in-game. Note, this option will only be used if `enable_track_clock_synchronization` option is disabled.

    track_clock_format
Set track clock format string. To show seconds, add `%S`, such as `%H:%M:%S %p`. See [link](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) for full list of format codes.

    show_time_scale
Show current session track clock time scale multiplier.

    show_sunlight_phase_countdown
Show sunlight phase countdown timer and indicator. The timer counts down towards each of four primary sunlight phases: sunrise, midday, sunset, midnight. An arrow indicator is displayed alongside with day/night color.

This countdown timer can be used to check how long until sunrise or sunset for planning strategy.

Note, game does not provide `sunrise` and `sunset` data. Sunrise and sunset hours must be manually defined in [Track Info Editor](#track-info-editor) to get correct readings.

See Wiki Appendix page for sunrise and sunset reference table for some common tracks.

    enable_time_scaled_countdown
Enable time scaled countdown, which scales with session track clock time scale multiplier. This option is disabled by default.

[**`Back to Top`**](#)


## Track map
**This widget displays track map and standings. Note: at least one complete and valid lap is required to generate track map.**

    display_orientation
Set track map display orientation in degrees. For example, a `270` value will rotate map by `270` degrees clockwise. Default value is `0`, which always displays track map `North Up` in game's coordinate system.

    display_detail_level
Sets detail level for track map. Default value is `1`, which auto adjusts map detail according to display size. Higher value reduces map detail and RAM usage, and may also help reduce rough edges from large map. Set to `0` for full detail.

    vehicle_scale, vehicle_scale_player, vehicle_scale_safety_car
Set vehicle scale that multiplies base vehicle size. Note, base vehicle size is determined by `font size` and `bar padding`. Minimum scale is limited to `1.0`.

    area_size
Set area display size.

    area_margin
Set area margin size.

    show_background
Show widget background.

    show_map_background
Show background of the inner map area. This option only works for circular type tracks.

    map_color_sector_*
Set map sector color.

    map_width
Set track map line width.

    map_outline_width
Set track map outline width.

    show_start_line
Show start line mark.

    show_sector_line
Show sector line mark.

    show_proximity_circle
Show proximity circle around player's position, which helps to quickly spot player and nearby opponents on map.

    proximity_circle_radius
Set proximity circle radius in meters. Default radius is `150` meters.

    show_vehicle_standings
Show vehicle standings info on track map. Note, if `enable_multi_class_styling` is enabled, position in class will be displayed for each vehicle class instead.

    enable_multi_class_styling
Show vehicles in multi-class color styles on map instead. Multi-class color can be customized from [Vehicle Class Editor](#vehicle-class-editor).

Note, while multi-class styling is enabled, following color styles will not be displayed:
`vehicle_color_player`, `vehicle_color_leader`, `vehicle_color_same_lap`, `vehicle_color_laps_ahead`, `vehicle_color_laps_behind`.

    show_custom_player_color_in_multi_class
Show custom player vehicle color (defined in `vehicle_color_player` option) while `enable_multi_class_styling` option is enabled.

    show_position_in_class
Show position in class while `enable_multi_class_styling` option is also enabled, otherwise this option has no effect.

    show_lap_difference_outline
Show outline color based on lap difference (ahead or behind) between player and opponents. This option is disabled by default.

    show_safety_car
Show safety car position on map if available. This option currently only works in RF2.

Note, safety car position data from RF2 API is fairly limited, and has a very low update rate, in order to workaround API limitation, safety car position data is interpolated to display smoothly, but may still desync occasionally.

    safety_car_text
Set custom text for safety car. Default is `SC`.

    show_pitout_prediction
Show estimated pit-out on-track position indication for each pit stop duration. Default indication shows `circle` with `pit stop duration` displayed above.

Note, pit-out position prediction is based on `delta best` data which scaled with player's latest `lap time pace` for accurate real-time position prediction under various track conditions. Pit-out prediction requires both valid `track map` and `delta best` data to display. At least `one valid lap` for any car and track combo is required to display pit-out prediction.

For accurate prediction, the location of `pit-out line` must be found first. And since each track has different pit-out line location, it is required to `pit-out` at least `once per session` to mark the correct pit-out line location. This can be easily done by driving out of pit lane.

    show_pitout_prediction_while_requested_pitstop
Show estimated pit-out on-track position indication while player has requested pit stop and not in pit lane.

    number_of_prediction
Set number of pit-out prediction to display. Value range is limited in `1` to `20`.

    pitout_time_offset
Set amount time offset (in seconds) for catching up with vehicle speed after pit-out. Default is `3` seconds.

Note, this value is important for accurate prediction, as initial vehicle speed is much slower after pit-out, so extra time is needed for driver to catch up, and also affected by pit-out line location. For most tracks, this extra time after pit-out is roughly within `1` to `5` seconds.

    pitout_duration_minimum
Set pit stop duration (in seconds) of first prediction. This option has no effect if `enable_fixed_pitout_prediction` is enabled.

    pitout_duration_increment
Set each pit stop duration (in seconds) increment after previous prediction. Default increment is `10` seconds. This option has no effect if `enable_fixed_pitout_prediction` is enabled.

Note, each time when pit stop duration of the nearest prediction exceeded current pit stop timer, the prediction circle will be removed, and a new prediction circle will be appended with pit stop duration increment after the last prediction.

    enable_auto_pitout_prediction
Show auto-estimated pit-out duration prediction. Default indication shows as a green circle. This option does not count towards `number_of_prediction` limit.

Auto estimated pit-out duration is calculated in the same way as [Pit Stop Estimate](#pit-stop-estimate) Widget.

Note, this option only works for `LMU`, and `enable_restapi_access` must be enabled in [LMU API](#le-mans-ultimate-api) setting.

    auto_prediction_additional_pitstop_time
Set additional pit stop time it takes to decelerate and accelerate towards and away from pit spot. This option corresponds to `additional_pitstop_time` option from `Pit stop estimate` Widget, and both should be set to same amount. Default value is `2` seconds.

    enable_fixed_pitout_prediction
Show pit-out prediction based on user-defined fixed pitstop duration instead. This option overrides `pitout_duration_minimum` and `pitout_duration_increment` options.

While this option is enabled, total pit-out duration is calculated from the sum of `pit-out time offset`, `fixed pit stop duration` and `estimated pit lane pass-through duration`. It's required to enter and exit pit lane at least once to get correct total pit-out duration.

    fixed_pitstop_duration
Set fixed amount pit stop duration (in seconds). Note, only `stopped` time should be considered for this option. Set to `0` if only passing through pit lane (such as `Drive Through`). Set to `-1` to disable this option.

    show_pitstop_duration
Show pit stop duration reading on top of each prediction circle.

[**`Back to Top`**](#)


## Track notes
**This widget displays track notes, comments, debugging info.**

    show_background
Show background color. Turn off to show text only.

    show_pit_notes_while_in_pit
Show custom notes while in pit lane.

    pit_notes_text, pit_comments_text
Set custom notes and comments to be displayed while in pit lane.

    show_track_notes
Show nearest track notes info behind current vehicle position.

    track_notes_uppercase
Set track notes text to uppercase.

    show_comments
Show nearest track notes comments info behind current vehicle position.

    enable_comments_line_break
Enable line break for displaying multi-line comments. To break a line into multiple lines, add `\n` to any part of the comment.

    show_debugging
Show nearest track notes index number behind current vehicle position, and distance value (meters) behind current position to next index position.

    track_notes_width, comments_width, debugging_width
Set maximum display width, value in chars, such as 10 = 10 chars.

    enable_auto_hide_if_not_available
Auto hide this widget if track notes data is not available for current track.

    maximum_display_duration
Set maximum display duration (seconds) of each note. Set to `-1` to always display notes. Default is `-1`.

[**`Back to Top`**](#)


## Traffic
**This widget displays traffic vehicle info.**

This widget is designed to show the nearest traffic vehicles that are closing in, either the `slower` vehicle that you are catching up ahead, or the `faster` vehicle that is catching up from behind.

Note, vehicles are not counted as traffic if they cannot close the gap, or while in pit lane. For example, a driver that falls constantly 3 seconds behind you is not considered as traffic since he cannot close the gap and overtake you.

    bar_width
Set each column width, value in chars, such as 10 = 10 chars. Default is `6`. Minimum width is limited to `3`.

    show_race_leader
Show column for race leader relatively from behind.

    show_slower_ahead
Show column for nearest reachable slower vehicle relatively ahead.

    show_faster_behind
Show column for nearest reachable faster vehicle relatively from behind.

    show_class
Show traffic vehicle class name.

    show_driver_name_instead_of_class
Show driver name instead of class name.

    driver_name_shorten
Shorten driver's first name.

    driver_name_uppercase
Set driver name to uppercase.

    show_estimated_laps
Show estimated laps towards nearest reachable traffic vehicles. Note, it may take 1 or more laps to get accurate estimates.

For example, a `2.34L` value from `faster` column indicates the amount laps it would take for the faster vehicle that behind you to catch up with you; while same value from `slower` column indicates the amount laps it would take for you to catch up with the slower vehicle ahead.

    enable_traffic_highlight_from_current_lap
Highlight traffic vehicles that can potentially overtake or be overtaken from current lap, which is useful to determine fuel saving strategy.

    show_time_interval
Show time interval between you and traffic vehicles.

[**`Back to Top`**](#)


## Trailing
**This widget displays pedal, steering input and force feedback plots.**

    display_width
Set pedal plot display width in pixels.

    display_height
Set pedal plot display height in pixels.

    display_margin
Set pedal plot display margin (vertical relative to pedal) in pixels.

    display_scale
Set plot display scale. Default scale is `2`. Minimum scale is limited to `1`.

Note, when `high DPI scaling` mode is enabled on high resolution (2k or 4k) screen, the widget base size will also be scaled up according to system's DPI setting, which may result larger plot even when `display_scale` is set to `1`. If smaller plot size is preferred, manually disable `high DPI scaling` mode via `Scale` button on main window status bar.

    time_scale
Set plot time scale. When time scale is `1` (default), plot will be synchronized with `update_interval`.

Note, value less than `1` draws plot slower; higher than `1` draws plot faster. Setting this value too high or too low may result plot stuttering.

    maximum_paused_frames
Set maximum number of paused frames to keep plotting. This option is disabled by default.

Set value to `1` or higher will keep plotting for maximum number of frames while game data desynced or stopped updating. Set to `0` to disable this option, which plots only when data synced. Note, it's generally not required to enable this option.

    show_inverted_pedal
Invert pedal range display.

    show_inverted_trailing
Invert trailing direction.

    show_tc_activation
Show TC activation plot, which overlaps throttle plot when active.

    show_abs_activation
Show ABS activation plot, which overlaps brake plot when active.

    show_throttle
Show filtered throttle plot. Note, some vehicles may not provide filtered pedal input value, which the value will be zero.

    show_raw_throttle
Show unfiltered throttle instead.

    show_absolute_ffb
Convert force feedback value to absolute value before plotting. Set to `false` to show force feedback plot in both positive and negative range.

    show_steering
Show steering plot.

    show_inverted_steering
Invert steering plot direction.

    show_speed
Show speed plot relative to player's top reference speed from current stint.

Note, at least one lap is required to calibrate top reference speed. Top reference speed resets when vehicle stopped on track.

    *_line_width
Set trailing line width in pixels.

    *_line_style
Set trailing line style. `0` for solid line, `1` for dashed line.

    show_wheel_lock
Show wheel lock (slip ratio) plot under braking when slip ratio has exceeded `wheel_lock_threshold` value.

    wheel_lock_threshold
Set percentage threshold for triggering wheel lock warning under braking. `0.3` means 30% of tyre slip ratio.

    show_wheel_slip
Show wheel slip (slip ratio) plot under acceleration when slip ratio has exceeded `wheel_slip_threshold` value.

    wheel_slip_threshold
Set percentage threshold for triggering wheel slip warning under acceleration. `0.1` means 10% of tyre slip ratio.

    show_slip_angle_difference
Show slip angle difference plot (difference between average front and rear slip angle). Plot line that draws above the center reference line indicates understeer tendency; while below the center reference line indicates oversteer tendency.

    maximum_slip_angle_difference
Set maximum display range (in degrees) for slip angle difference plot. Default is `5` degrees.

    show_reference_line
Show reference line.

    reference_line_*_offset
Set reference line vertical offset position (percentage) relative to pedal, value range in `0.0` to `1.0`.

    reference_line_*_style
Set reference line style. `0` for solid line, `1` for dashed line.

    reference_line_*_width
Set reference line width in pixels. Set value to `0` to hide line.

    display_order_*
Set display order of plot lines.

[**`Back to Top`**](#)


## Tyre carcass temperature
**This widget displays tyre carcass temperature info.**

Note, if temperature drops below `-100` degrees Celsius, temperature readings will be replaced by unavailable sign as `-`.

    enable_heatmap_auto_matching
Enable automatically heatmap style matching for specific tyre compounds defined in `compounds.json` preset. This option applies matching heatmap style to front and rear tyre compounds separately.

Note, separate compounds info for tyres on the same axle is not available from game API, which currently it is not possible to show left and right compounds separately.

    heatmap_name
Set heatmap preset name that is defined in `heatmap.json` preset. Note, this option has no effect while `enable_heatmap_auto_matching` is enabled.

    enable_heatmap_from_optimal_temperature
Modern design: color tyre temperature around optimal tyre temperature given by game (`LMU`): blue below, green around optimal, yellow to red above, in 10 degree Celsius steps (same colors as `tyre_optimal_*` heatmaps). Applies instead of `enable_heatmap_auto_matching` and `heatmap_name` while game gives optimal temperature, otherwise (`RF2`) they apply. Default is disabled.

    show_degree_sign
Set `true` to show degree sign for each temperature value.

    leading_zero
Set amount leading zeros for each temperature value. Default is `2`. Minimum value is limited to `1`.

    show_rate_of_change
Show carcass temperature rate of change for a specific time interval.

    rate_of_change_interval
Set time interval in seconds for rate of change calculation. Default interval is `5` seconds. Minimum interval is limited to `1` second, maximum interval is limited to `60` seconds.

    rate_of_change_smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

    show_tyre_compound
Show tyre compound symbols (front and rear) that matches specific tyre compounds defined in `compounds.json` preset.

    show_compound_color_by_type
Show different compound color by compound type, which can be customized in [Tyre Compound Editor](#tyre-compound-editor).

[**`Back to Top`**](#)


## Tyre deflection
**This widget displays visualized tyre vertical deflection info.**

    deflection_maximum_range
Set visualized maximum tyre deflection display range (millimeter).

    lift_off_threshold
Set millimeter threshold of tyre deflection for detecting lifted wheels. Default threshold is `1` millimeter.

[**`Back to Top`**](#)


## Tyre inner layer
**This widget displays tyre inner layer temperature info.**

Note, if temperature drops below `-100` degrees Celsius, temperature readings will be replaced by unavailable sign as `-`.

    enable_heatmap_auto_matching
Enable automatically heatmap style matching for specific tyre compounds defined in `compounds.json` preset. This option applies matching heatmap style to front and rear tyre compounds separately.

Note, separate compounds info for tyres on the same axle is not available from game API, which currently it is not possible to show left and right compounds separately.

    heatmap_name
Set heatmap preset name that is defined in `heatmap.json` preset. Note, this option has no effect while `enable_heatmap_auto_matching` is enabled.

    enable_heatmap_from_optimal_temperature
Modern design: color tyre temperature around optimal tyre temperature given by game (`LMU`): blue below, green around optimal, yellow to red above, in 10 degree Celsius steps (same colors as `tyre_optimal_*` heatmaps). Applies instead of `enable_heatmap_auto_matching` and `heatmap_name` while game gives optimal temperature, otherwise (`RF2`) they apply. Default is disabled.

    swap_style
Swap heatmap color between font and background color.

    show_inner_center_outer
Set inner, center, outer temperature display mode. Set `false` to show average temperature instead.

    show_degree_sign
Set `true` to show degree sign for each temperature value.

    leading_zero
Set amount leading zeros for each temperature value. Default is `2`. Minimum value is limited to `1`.

    show_tyre_compound
Show tyre compound symbols (front and rear) that matches specific tyre compounds defined in `compounds.json` preset.

    show_compound_color_by_type
Show different compound color by compound type, which can be customized in [Tyre Compound Editor](#tyre-compound-editor).

[**`Back to Top`**](#)


## Tyre load
**This widget displays visualized tyre load and ratio info.**

    show_tyre_load_ratio
Show percentage load ratio between each and total tyre load. Set `false` to show individual tyre load in Newtons.

    low_load_threshold
Show warning indication when load (in Newtons) is below the threshold.

[**`Back to Top`**](#)


## Tyre pressure
**This widget displays tyre pressure info.**

    hot_pressure_temperature_threshold
Set minimum temperature threshold (measured from tyre carcass in Celsius) for hot pressure indication. Default is `65` degrees Celsius. Default color for cold pressure is blue, and orange for hot pressure.

    show_pressure_deviation
Show average tyre pressure deviation between each tyre and the tyre with highest pressure.

    average_sampling_duration
Set duration (seconds) for calculating average tyre pressure. Default is `10` seconds. Maximum duration is limited to `600` seconds.

    swap_style
Swap cold and hot pressure color.

    show_tyre_compound
Show tyre compound symbols (front and rear) that matches specific tyre compounds defined in `compounds.json` preset.

    show_compound_color_by_type
Show different compound color by compound type, which can be customized in [Tyre Compound Editor](#tyre-compound-editor).

[**`Back to Top`**](#)


## Tyre temp trend
**This widget displays surface temperature trend of each tyre.**

Each tyre has a small line chart of surface temperature over the last seconds (or average temperature of each of the last laps), colored by tyre heatmap, with current temperature. All tyres share the same temperature scale. A dashed line shows tyre optimal temperature when game provides it (LMU).

    display_width, display_height
Set chart width and height of each tyre in pixels.

    trend_duration
Set time span of chart in seconds, with one sample every 1/60 of time span. Minimum value is limited to `10`. Default is `120` seconds.

    show_trend_by_lap
Show average temperature of each completed lap instead of last seconds.

    number_of_laps
Set number of laps shown while `show_trend_by_lap` is enabled. Value range in `2` to `100`. Default is `10` laps.

    show_optimal_temperature
Show tyre optimal temperature as a dashed line (LMU).

    show_degree_sign
Set `true` to show degree sign for each temperature value.

    enable_heatmap_auto_matching
Enable automatically heatmap style matching for specific tyre compounds defined in `compounds.json` preset. This option applies matching heatmap style to front and rear tyre compounds separately.

Note, separate compounds info for tyres on the same axle is not available from game API, which currently it is not possible to show left and right compounds separately.

    heatmap_name
Set heatmap preset name that is defined in `heatmap.json` preset. Note, this option has no effect while `enable_heatmap_auto_matching` is enabled.

[**`Back to Top`**](#)


## Tyre temperature
**This widget displays tyre surface temperature info.**

Note, if temperature drops below `-100` degrees Celsius, temperature readings will be replaced by unavailable sign as `-`.

    enable_heatmap_auto_matching
Enable automatically heatmap style matching for specific tyre compounds defined in `compounds.json` preset. This option applies matching heatmap style to front and rear tyre compounds separately.

Note, separate compounds info for tyres on the same axle is not available from game API, which currently it is not possible to show left and right compounds separately.

    heatmap_name
Set heatmap preset name that is defined in `heatmap.json` preset. Note, this option has no effect while `enable_heatmap_auto_matching` is enabled.

    enable_heatmap_from_optimal_temperature
Modern design: color tyre temperature around optimal tyre temperature given by game (`LMU`): blue below, green around optimal, yellow to red above, in 10 degree Celsius steps (same colors as `tyre_optimal_*` heatmaps). Applies instead of `enable_heatmap_auto_matching` and `heatmap_name` while game gives optimal temperature, otherwise (`RF2`) they apply. Default is disabled.

    swap_style
Swap heatmap color between font and background color.

    show_inner_center_outer
Set inner, center, outer temperature display mode. Set `false` to show average temperature instead.

    show_degree_sign
Set `true` to show degree sign for each temperature value.

    leading_zero
Set amount leading zeros for each temperature value. Default is `2`. Minimum value is limited to `1`.

    show_tyre_compound
Show tyre compound symbols (front and rear) that matches specific tyre compounds defined in `compounds.json` preset.

    show_compound_color_by_type
Show different compound color by compound type, which can be customized in [Tyre Compound Editor](#tyre-compound-editor).

[**`Back to Top`**](#)


## Tyre wear
**This widget displays tyre wear info.**

    layout
2 layouts are available: `0` = vertical layout, `1` = horizontal layout.

    show_remaining
Show total remaining tyre tread in percentage that changes color according to wear.

    show_wear_difference
Show estimated tyre wear difference per lap (at least one valid lap is required).

    show_live_wear_difference
Show current lap tyre wear difference.

    show_flat_spot
Show amount wear from flat spot due to wheel lock.

    show_lifespan_laps
Show estimated tyre lifespan in laps.

    show_lifespan_minutes
Show estimated tyre lifespan in minutes.

    show_end_stint_remaining
Show estimated total remaining tyre tread at the end of current stint, which helps to determine whether there is enough tread for current or more stints. Negative reading indicates that there will not be enough tyre tread remaining at the end of current stint.

For example, if minimum safe tyre tread is around 10%, then for triple-stint tyre saving, aim for 70% remaining tread for first stint, 40% for second stint, and 10% for third stint.

    warning_threshold_remaining
Set warning threshold for total remaining tyre in percentage. Default is `30` percent.

    warning_threshold_wear
Set warning threshold for total amount tyre wear of last lap in percentage. Default is `3` percent.

    warning_threshold_laps
Set warning threshold for estimated tyre lifespan in laps. Default is `5` laps.

    warning_threshold_minutes
Set warning threshold for estimated tyre lifespan in minutes. Default is `5` laps.

[**`Back to Top`**](#)


## Virtual energy
**This widget displays virtual energy usage info.**

Note, most options are inherited from [Fuel](#fuel) widget, with some additions noted below. For battery charge usage info, see [Battery](#battery) widget.

    show_absolute_refilling
Show absolute refilling value instead of relative refilling when enabled. Note, `+` or `-` sign is not displayed with absolute refilling.

    show_fuel_ratio_and_bias
Show fuel ratio and fuel bias column.

    *fuel_ratio
Show fuel ratio between estimated fuel and energy consumption, which can help balance fuel and energy usage, as well as providing refueling reference for adjusting pit stop `Fuel ratio` during race.

    *fuel_bias
Show fuel bias (unit in laps) that calculated from estimated laps difference between fuel and virtual energy.

Positive value indicates more laps can be run on fuel than virtual energy; in other words, virtual energy will deplete sooner than fuel. For example, a value of `+1.5` indicates that there will be `1.5 laps` of extra fuel remaining after virtual energy depleted.

Note, depleting virtual energy could result a `Stop-Go` penalty in `LMU`; while running out of fuel means no power for vehicle and would result retirement from race. So it is a good idea to keep fuel bias close to `0.0`, and slightly towards positive side to avoid depleting fuel before virtual energy.

[**`Back to Top`**](#)


## Weather
**This widget displays weather info.**

    show_temperature
Show track and ambient temperature.

    decimal_places_temperature
Set amount decimal places to keep. Default is `1` decimal place, set to `0` to hide decimals. Note, when number of digits is less than expected, extra leading zero or decimal place will be added to fill the gap.

    show_rain
Show rain precipitation in percentage.

    show_wetness
Show average surface wetness in percentage.

    show_wind
Modern design: show wind speed in speed unit, with arrow of where wind blows relative to vehicle (up: tailwind, down: headwind, no arrow while calm).

    show_rubber_coverage_while_dry
Show rough estimate of rubber coverage (percent) based on total number of laps done by all drivers while road surface is dry.

Note, rubber coverage reading may not be accurate during `practice session` in multiplayer, as some API data will be lost or reset while people joining or leaving server. This does not affect `qualifying` and `race` session.

| Rubber Coverage | Equivalent Grip | Equivalent Laps (LMU) | Equivalent Laps (RF2) |
|:-:|:-:|:-:|:-:|
| 0.0 (0%) | Green | 0+ | 0+ |
| 0.25 (25%) | Light | 600+ | 300+ |
| 0.5 (50%) | Medium |  1200+ | 600+ |
| 0.75 (75%) | Heavy (High) | 2000+ (Median) | 1000+ (Median) |
| 1.0 (100%) | Saturated | 4000+ | 2000+ |

**Note, all data from above table are rough estimate based on testing.*

    rubber_median_laps
Set median laps at the point when grip becomes `Heavy (High)` for calculating accurate rubber coverage. Default median laps is `2000`. This value may vary from different games, see above table for reference.

    rubber_time_scale_*
Set time scale multiplier for calculating rubber coverage in corresponding sessions (practice, qualifying, race). This value should match `Realroad Time Scale` session setting from game. For `static` rubber, set time scale to `0`.

Note, since Realroad Time Scale data is not available from game API, it is required to manually set the value.

Most online servers use default `1.0` Realroad Time Scale setting during `qualifying` and `race` session, while some servers may use `static` setting during `practice` session only.

    starting_rubber_*
Set starting rubber coverage (percent) in corresponding sessions (practice, qualifying, race).

Note, since session starting rubber coverage data is not available from game API, it is required to manually set the value.

    show_trend
Show weather change trend for temperature, raininess, surface wetness readings.

    temperature_trend_interval, raininess_trend_interval, wetness_trend_interval
Set weather change trend interval in seconds. Default interval is `60` seconds.

If weather readings increased within the interval, `▲` uparrow sign will be shown; if readings decreased within the interval, `▼` downarrow sign will be shown; If readings has not changed during the interval, `●` sign will be shown after.

[**`Back to Top`**](#)


## Weather forecast
**This widget displays weather forecast info.**

    layout
2 layouts are available: `0` = show columns from left to right, `1` = show columns from right to left. Note, the `now` column always shows current weather condition.

    show_estimated_time
Show estimated time reading for upcoming weather. Note, estimated time reading only works in time-based race. Other race type such as lap-based race shows `n/a` instead.

    show_ambient_temperature
Show estimated ambient temperature reading for upcoming weather. Note, the `now` column always shows current ambient temperature instead.

    show_rain_chance_bar
Show visualized rain chance bar reading for upcoming weather. Note, the `now` column always shows current raininess instead.

    show_rain_chance_reading
Show rain chance reading in percentage.

    number_of_forecasts
Set number of forecasts to display. Value range in `1` to `4`. Default is `4` forecasts.

    show_unavailable_data
Show columns with unavailable weather data. Set `False` to auto hide columns with unavailable data. Note, auto hide only works for time-based race.

[**`Back to Top`**](#)


## Weight distribution
**This widget displays weight distribution info.**

Note, to get accurate static weight distribution readings, test setup on level ground.

Weight distribution is calculated from tyre load data, and may not be available from certain vehicles in game API (such as LMGT3).

To workaround this limitation, suspension load data, while not entirely the same, will be used for calculation instead.

    show_front_to_rear_distribution
Show front to rear weight distribution in percentage.

    show_left_to_right_distribution
Show left to right weight distribution in percentage.

    show_cross_weight
Show cross weight (known as `wedge`) in percentage.

    smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

[**`Back to Top`**](#)


## Wheel camber
**This widget displays wheel camber angle info.**

Note, all camber readings are in degrees.

    positive_camber_threshold
Set positive camber threshold for highlighting positive camber angle.

    show_camber_difference
Show camber difference between left and right wheel on the same axle, useful for quickly checking misalignment while driving.

    camber_smoothing_samples, camber_difference_smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

[**`Back to Top`**](#)


## Black box
**This widget displays an all-in-one view of the four wheels: tyre temperature, brake temperature, wheel lock & spin, ABS & TC activation, brake bias and pedals.**

Modern design: same layout and options as classic, drawn with design font (labels in capitals), theme colors (colors left at default value follow `overlay_theme` and `enable_colorblind_colors`, customized colors are kept), cards with soft shading and a hairline border, and capsule RPM LEDs keeping a faint tint of their color zone while unlit. Enable `enable_classic_layout` to use classic look.

Tyres are drawn at each corner (seen from above), with a thin brake bar next to each tyre and brake temperature written beside it, colored with heatmap (auto matched with tyre compound & brake type if enabled). A locked wheel gets a red outline, a spinning wheel gets a yellow outline. `Wheels module` must be enabled for lock & spin warning.

    layout
Set layout: `0` = info column between tyres (default), `1` = vertical (info column below tyres), `2` = compact (tyres & brakes only).

    display_scale
Scale whole widget, including text. Value range in `0.5` to `4`. Default is `1.0`.

    show_background
Show widget background color, set by `background_color`.

    show_caption, caption_text, font_color_caption, background_color_caption
Show short caption text on top of widget.

    show_degree_sign
Show degree sign (`°`) next to temperature values. Disabled by default, as it may not render correctly with some fonts.

    warning_outline_width
Outline width (pixel) for wheel lock (`wheel_lock_color`) and wheel spin (`wheel_spin_color`) warning. Default is `3`.

    show_rpm_leds, number_of_rpm_leds, rpm_led_start_ratio
Show a row of RPM LEDs on top of widget, lit from `rpm_led_start_ratio` (fraction of maximum RPM) up to `rpm_redline_ratio`, green, yellow then red. Over `rpm_redline_ratio` all LEDs flash with `rpm_led_shift_color` (shift point).

    enable_gear_rpm_color, gear_color_low, gear_color_mid, gear_color_shift, gear_mid_rpm_ratio
Color gear number by RPM: low color, mid color from `gear_mid_rpm_ratio`, shift color from `rpm_redline_ratio`.

    enable_shift_flash, shift_flash_interval
Flash gear number (and LEDs) over shift point, interval in seconds. Default is `0.12`.

    show_tyre_temperature_bands
Show tyre surface temperatures across the tread as 3 colored bands in each tyre, seen from above: game reports left, center and right of the car, so the outer side of a left tyre and the inner side of a right tyre are on the left. Useful for camber setup.

    show_tyre_camber_spread
Show inner minus outer tread surface temperature on each tyre (`Δ+8`, Celsius): the reading camber is set with. Positive means inner side hotter, the usual result of negative camber. Disabled by default.

    show_tyre_surface_overheat
Draw a hot strip across the top of a tyre (pulsing, `font_color_tyre_temperature_warning`) while its surface is above the hot threshold but the rubber below is not: the tyre is sliding and wearing, even though its working temperature is fine. Needs a hot threshold (`tyre_temperature_warning_threshold` or compound target). Enabled by default.

    enable_tyre_pressure_target, tyre_pressure_target_minimum, tyre_pressure_target_maximum
Highlight tyre pressure below minimum (`tyre_pressure_low_color`) or above maximum (`tyre_pressure_high_color`). Values in kPa, psi or bar, the unit is found from the value (under `10` is bar, `10` to `60` is psi, above is kPa), so `23-27` works as psi and `1.6-1.9` as bar whatever pressure unit is displayed. Defaults are `160` and `190` (kPa).

    tyre_pressure_target_rear_minimum, tyre_pressure_target_rear_maximum
Own pressure window (kPa, psi or bar) for rear tyres, front and rear usually differ. `0` (default) uses the front window. In `tyre_target_by_compound`, an entry named `symbol:R` (for example `S:R=165-195`) sets the rear window of that compound.

    show_tyre_pressure_range
Show lowest and highest hot pressure of the current stint on each tyre (`171-184`), reset when leaving the pits: what the cold pressure is set from at the next stop. Disabled by default.

Pressure and temperature options are always entered in kPa and Celsius, whichever units the overlay displays, so that changing a display unit cannot reinterpret a saved threshold. When your display unit differs, the config dialog shows the same value in your unit inside the field while you type (for example `23.21 psi` for `160`).

    show_tyre_wear_end_stint
Show estimated remaining tyre tread at end of current stint (`→61%`), from `Wheels module` and `Fuel module`.

    tyre_wear_forecast_laps
Laps the end of stint tread estimate is made for. `0` (default) uses the laps left in the tank (`Fuel module`); another value, for example the laps to the next planned stop, needs only `Wheels module`.

    show_tyre_status, flat_spot_threshold
Show detached wheel (dashed outline, `OFF`), puncture (`PUNCT`) and flat spot (`FLAT`, tyre wear while locked above `flat_spot_threshold` percent).

    show_tyre_carcass_temperature, show_tyre_load, show_tyre_slip_angle, show_wheel_camber, show_ride_height, show_tyre_wear_per_lap
Additional per-wheel readings, all off by default. Each is prefixed so it can be told apart from the others at a glance: carcass temperature `K85`, tyre load `L26%` (see `tyre_load_display`), slip angle `S+4.1` (degrees), camber `C-3.2` (degrees), ride height `H32` (millimeters), and estimated tread lost over a full lap `▼0.82` (percent, from `Wheels module`).

    tyre_load_display
Tyre load reading: `Percent` share of the car's total tyre load (default), or absolute load in `Kilogram` or `Newton`. Absolute load shows aero downforce: the same share at 80 and 250 km/h is a very different load.

    show_suspension, suspension_scale
Show each suspension (coilover seen from the side) right beside the brake bar. It is anchored to its wheel: it turns with the tyre and brake disc when steering, and a link joins its wheel mount to the disc bar (hub). Damper body and top mount, coil spring and shaft down to the wheel mount. The wheel mount moves 1:1 with the wheel in game, together with tyre and disc: its distance from the static position tick is the real wheel offset in millimeters, at the same scale as the tyre drawing (tyre height stands for the real tyre diameter, learned from wheel rolling radius by `Wheels module`, 680 mm until known). Tyre and disc move by the real wheel travel, which is the spring travel divided by the motion ratio learned by `Wheels module` (on a pushrod or rocker suspension the wheel moves more than the spring). Static position from `Wheels module`; while it is unknown (joined while driving, or module off) a slow average of positions is used and the static tick is drawn hollow, as the offset is then approximate. `suspension_scale` sets its width (default `1.0`, range `0.5` to `3`).

    enable_wheel_suspension_motion
Move tyre and brake disc with the suspension wheel mount (enabled by default). Disable to keep them fixed, suspension travel then only shows on the coilover.

    suspension_motion_scale
Magnify suspension motion, `1.0` (default) is real scale. Real suspension travel is small next to a tyre, `3` to `5` makes small movements easier to see.

    suspension_spring_color, suspension_compression_color, suspension_rebound_color, suspension_low_speed_threshold, suspension_velocity_scale
Spring color at rest, tinted toward compression color while compressing and rebound color while extending, by damper speed (smoothed over 60 ms) in two zones like a real damper: low speed, up to `suspension_low_speed_threshold` mm/s (default `50`, body roll & pitch), gives a light tint; high speed (kerbs & bumps) goes on to the full color at `suspension_velocity_scale` mm/s (default `150`).

    suspension_bump_color, suspension_bump_force_margin
Spring turns bump stop color, pulsing with `alert_pulse_frequency`, while the bump rubber is loaded. A spring alone gives a force growing linearly with deflection: that line is learned from suspension force at low damper speed in the lower part of the travel, and contact is shown once force in the upper part of the travel is above it by more than `suspension_bump_force_margin` (fraction, default `0.3`). Judged at low to medium damper speed only, where damper force does not hide the spring force.

    show_coilover_damage
Show suspension damage on each coilover, with the damage panel thresholds and colors (`damage_panel_suspension_*`): damper body, mounts and link take the color of the damage level (light, medium, heavy), the spring is drawn broken (dashed) from heavy damage, and pulses in totaled color once totaled. Enabled by default.

    suspension_airborne_color
Spring color, pulsing, while the wheel is in the air (tyre load near zero with the car moving): kerb strike, crest, or two wheels lifting in a corner.

    show_suspension_lap_stats
Show on each tyre the bump stop contacts (`B3`) and the travel range used (`T12-88`, percent of the travel range) over the current lap, reset on each new lap. Disabled by default.

    show_ride_height_minimum, ride_height_bottoming_threshold
Show on each tyre the lowest ride height of the current lap and how many times it went below `ride_height_bottoming_threshold` (millimeters, default `5`): `⊥18/2`, in warning color once it bottomed. The key reading for ride height setup. Disabled by default.

    show_third_spring
Show third (heave) spring deflection of the axle on each tyre (`Z12`, millimeters), on cars that have one (prototypes). Disabled by default.

    show_damper_histogram
Add a bottom row with, for each wheel, the time share of the current lap spent in each damper speed zone: fast rebound, slow rebound, slow bump, fast bump (split at `suspension_low_speed_threshold`). The base tool of damper setup. Disabled by default.

    show_brake_pressure, brake_pressure_color
Show brake pressure (percent of maximum) per wheel, below brake temperature and remaining thickness.

    enable_brake_bias_migration_merge
Show brake bias and brake migration in one chip (`BB/BMIG 56.0/2.5`) when both are shown. Enabled by default, disable for two separate chips.

    deltabest_source
Lap the delta is against: `Best` (default, best lap), `Session` (session best), `Stint` (stint best) or `Last` (last lap), from `Delta module`. Other than `Best`, its initial follows the label (`DELTA S`).

    pedal_input_source, show_clutch_bar, clutch_color
Pedal bars (and incident recorder pedal traces): `Filtered` (default) shows pedals as the car receives them, after game filtering and driving aids (auto blip, traction control throttle cut, ABS), `Raw` as pressed by the driver. Comparing both shows how much the aids step in. `show_clutch_bar` adds a third bar for the clutch.

    show_wheel_locking
Show percentage of lap distance spent locking a front and a rear wheel (`LOCK 12/4`), from `Wheels module`. Shown as a center column item.

Tyre readings share the space inside each tyre. When too many are enabled to stay readable, the least important ones are dropped, in this order: ride height, camber, slip angle, load, carcass temperature, wear per lap, compound, end of stint wear, pressure, wear, temperature. Puncture and flat spot are always shown. Enabling many readings at once therefore shows only a few of them unless `display_scale` is raised.

    show_battery_bar, battery_bar_position
Show hybrid battery charge as a full-height bar outside the tyre/brake columns. `battery_bar_position` sets `Left` or `Right`. Requires a car with a hybrid system (LMU); shows a dash instead of a percentage on cars without one.

    battery_bar_scale
Width of the battery bar, relative to `font_size`. Value range in `0.3` to `4`. Default is `1.1`. Widget width adapts to this value.

    show_battery_percentage, font_scale_battery
Show charge percentage on a readout at the top of the battery bar. `font_scale_battery` sets its text size relative to `font_size`, value range in `0.3` to `4`, default `0.9`.

    enable_battery_bar_animation, battery_bar_animation_speed
Show a moving highlight inside the battery bar: flows upward while the battery is charging (regen), downward while it is draining. Disabled automatically while the motor is off or the car has no hybrid system (charge is then shown as a static fill). `battery_bar_animation_speed` scales the flow speed, default `1.0`.

    battery_idle_color, battery_charge_color, battery_discharge_color
Battery bar fill color: motor off or not available, charging (regen), draining.

    battery_low_threshold, battery_high_threshold
Charge percentage at or below which the battery bar shows `warning_color_low_battery`, and at or above which it shows `warning_color_high_battery`. Defaults are `10` and `95`. A car without hybrid system never warns.

    show_battery_warning_flash, number_of_battery_warning_flashes, battery_warning_flash_duration, battery_warning_flash_interval
Flash the battery bar when it enters a low or high charge warning, then keep the warning color steady. `number_of_battery_warning_flashes` sets how many flashes, `battery_warning_flash_duration` how long each flash lasts and `battery_warning_flash_interval` the gap between them, both in seconds. Set `show_battery_warning_flash` to false to show the warning color without flashing.

    show_pit_limiter_indicator
Show pit lane (`PIT`) and speed limiter (`LIM`) indicators, only while active.

    show_fuel_gauge, show_energy_gauge
Show fuel gauge and virtual energy gauge at the bottom, one full-width bar each, like the level bar of `Fuel` and `Virtual Energy` widgets: filled to current level (percent of capacity), with a mark at stint start level and a mark at the level after refuel/refill (current level plus amount needed to finish). Label on the left, remaining amount & estimated laps, then amount to add (`+12.4 L`, in refill mark color when fuel must be added) on the right, from `Fuel module` and `Energy module`. The energy row stays empty on cars without virtual energy, so the widget never resizes.

    fuel_gauge_color, energy_gauge_color, gauge_low_color, gauge_low_lap_threshold
Gauge fill colors. Below `gauge_low_lap_threshold` estimated laps (default `2`), the gauge and its reading turn `gauge_low_color` and pulse with `alert_pulse_frequency`.

    show_gauge_start_mark, gauge_start_mark_color, show_gauge_refill_mark, gauge_refill_mark_color
Stint start level mark and level after refuel/refill mark.

    display_order_*
Set order of center column items (locking, delta, lap time, pit & limiter, gear, speed, RPM, pedals, brake heat). Can be changed in the `Display Order` section of Overlay Options page. ABS, TC, brake bias and motor map are not in the center column: they are stacked between the right wheels.

    show_wheel_angle
Turn tyres left or right with real wheel angle, 1:1 with the car in game (read from the game, each wheel its own angle, so Ackermann and toe show as they are). How the game signs wheel angles (same sign on both sides, or toe-in per wheel, positive left or right) is learned from steering input within the first corners of each car, then both front wheels turn the way the steering wheel does. The brake disc bar and the suspension turn with their wheel, keeping the corner assembly together, while brake readings stay upright.

    maximum_wheel_angle
Maximum displayed wheel angle in degrees, value range in `0` to `45`. Default is `30`. It also sets the room kept around tyres, a real angle above it is shown at this maximum.

    show_tyre_temperature, show_tyre_pressure, show_brake_temperature
Show tyre temperature, tyre pressure and brake temperature.

    tyre_temperature_source
Tyre temperature that colors the tyre, is written in it and drives its cold & hot warnings: `Inner layer` (default), `Carcass` or `Surface`. Surface temperature jumps within milliseconds in a slide and cools on every straight, so a surface colored tyre flickers with each corner; the inner layer and the carcass follow the temperature the rubber actually works at, which tells whether the tyre is in its window. Temperature bands (`show_tyre_temperature_bands`) always show surface temperatures.

    tyre_temperature_warning_threshold, font_color_tyre_temperature_warning
Highlight tyre temperature (Celsius) at or above this threshold. Set `0` to disable. Default is `110`.

    tyre_pressure_warning_background_color
Background color of tyre pressure text when out of target range (see `enable_tyre_pressure_target`).

    show_tyre_compound
Show tyre compound symbol (from `Tyre compound editor`) on each tyre.

    show_tyre_wear
Show remaining tyre tread (percent) in each tyre.

    tyre_wear_warning_threshold
Remaining tread (percent) below which tyre wear is highlighted with `tyre_wear_warning_color`. Default is `30`.

    show_brake_wear, brake_wear_warning_threshold, font_color_brake_wear_warning
Show remaining brake thickness (percent of usable thickness) beside brake temperature, from `Wheels module`. Highlighted with `font_color_brake_wear_warning` below `brake_wear_warning_threshold` percent. Default threshold is `30`.

    brake_wear_display
Remaining brake thickness as `Percent` (default) or `Laps` left before failure thickness (`12L`), from brake wear per lap measured by `Wheels module`.

    enable_heatmap_auto_matching, heatmap_name_tyre, heatmap_name_brake
Heatmap used for tyre and brake colors. Auto matching selects heatmap from tyre compound and brake type while in pit.

    show_slip_warning
Show wheel lock (while braking) and wheel spin warning outline.

    wheel_lock_threshold, wheel_spin_threshold
Slip ratio threshold for wheel lock (negative slip while braking) and wheel spin (positive slip). Default is `0.2` and `0.15`. Peak grip is around `0.08` to `0.12`, so the default lock threshold means past peak grip, not a stopped wheel. Slip ratio is measured against each wheel's own ground speed (from `Wheels module`), so the outer wheels of a corner, which travel faster than the car center, show no false slip.

    wheel_locked_threshold
Slip ratio of a locked (stopped) wheel, shown with a twice as thick lock outline. Default is `0.8`, `1.0` being a fully stopped wheel.

    slip_warning_minimum_speed
Minimum speed (km/h) for lock & spin warning. Default is `10`.

    show_abs_indicator, show_tc_indicator
Show ABS and TC indicators with current level, lit while ABS or TC is active. TC indicator shows `TC level/cut/slip` when TC cut and TC slip levels are available (for example `TC 5/3/2`). Indicators are only shown if the car has ABS or TC (level reported by game, or ABS/TC seen active with current car).

Right wheels stack: ABS, TC, brake bias and motor map are drawn as chips of the same width between the front and rear right wheels, in this order from top to bottom. If `status_icons_side` is `Right`, headlights & engine icons sit above them. The gap between axles grows to fit the stack.

    show_brake_bias, show_pedal_bars
Show front brake bias (percentage) as a chip between the right wheels, and throttle & brake bars.

    brake_bias_color
Brake bias & brake migration chip color. Default is orange.

    show_brake_migration
Show brake migration (percent) as a chip between the right wheels, below brake bias (inside the brake bias chip while `enable_brake_bias_migration_merge` is enabled).

    show_motor_map, motor_map_color
Show current engine (motor) map level as a chip (`MAP 3`) between the right wheels, below brake bias. Level is read from the game (Le Mans Ultimate); the chip is hidden on a car without engine map, its room kept. Disabled by default.

    show_delta_best, delta_gain_color, delta_loss_color
Show delta to best lap in the center column, colored by gain or loss, from `Delta module`.

    show_laptime
Show current lap time in the center column, from `Delta module`.

    center_column_alignment
`Centered` (default) draws speed and RPM as large centered text. `Justified` draws them as label & value rows, the same as delta and lap time, so every value in the column lines up on the right edge.

    display_order_locking, display_order_delta, display_order_laptime
Position of the new rows in the center column. Adding them shifted the default order of the rows below (pit & limiter, gear, speed, RPM, pedals); presets saved before these options existed keep their own order values.

    show_gear, show_speed, show_rpm
Show engaged gear (`N` neutral, `R` reverse), vehicle speed (unit from `Units` setting) and engine RPM with RPM bar.

    show_gear_speed_cluster
Draw gear and speed together in one block of the center column: thin RPM accent along the top in gear color (turns shift color over redline), large gear, large speed and its unit below (`KM/H`). In normal layout the block grows to fill free room of the center column, so no empty space is left between items. Enabled by default, speed display order is then ignored.

    font_scale_gear, font_scale_speed, font_scale_rpm
Set text size of gear, speed and RPM, relative to `font_size`. Defaults are `3.0`, `1.6` and `0.75`. Widget height adapts to these sizes.

All texts of this widget are automatically reduced if they do not fit in their box (for example large font, long values, `TC 10/10/10`), and follow `font_name`, `font_weight`, `Global Font Override` and modern overlay font.

    rpm_redline_ratio
RPM bar turns `rpm_redline_color` above this fraction of maximum RPM. Default is `0.95`.

    display_profile
Preset group of show options: `Custom` (default) uses your own values, `Minimal` keeps only the essentials (tyre temperature & wear, brakes, center column basics), `Sprint` favours lap time & delta without fuel rows, `Endurance` turns on pressure, wear estimates, compound, brake wear, fuel & energy rows, stint comparison and trends. A profile overrides the matching options while it is selected, without changing your saved values.

    auto_compact_display_scale
Hide secondary elements (diagnostic readings, end of stint wear, compound, brake wear & pressure, caption, stint comparison, trends) when `display_scale` is below this value. `0` disables (default).

    slow_data_update_interval
Update interval (milliseconds) of slow changing data: temperatures, pressure, wear, damage, fuel & energy. Fast data (slip warning, steering, center column, battery) still follows `update_interval`. `0` updates everything every time. Default is `200`. The widget is also only repainted when something visible changed.

    enable_auto_resize, resize_delay
Resize widget to what the current car and data actually have: energy gauge dropped on cars without virtual energy, battery gauge on cars without hybrid system, ABS & TC rows on cars without them, gauges when `Fuel module` is off. Stint comparison row appears once there is stint data. The widget starts compact (fuel gauge only, no energy, battery, ABS, TC or stint row), so nothing empty is shown in menus, and each block appears once its data exists. A change is applied only once it stayed the same for `resize_delay` seconds (default `2`), so data arriving in steps never makes it jump several times. When disabled, room is kept for every enabled block and the widget never resizes.

    resize_anchor
Corner that stays in place on screen when the widget resizes: `Top Left` (default), `Top Center`, `Top Right`, `Bottom Left`, `Bottom Center` or `Bottom Right`. For example `Bottom Right` for a widget placed in the bottom right corner of the screen.

    fixed_width, fixed_height
Force widget width and/or height in pixels, `0` (default) follows content. Content is scaled uniformly to fit inside (never distorted) and centered, background fills the whole widget. With only one set, the other follows the content proportions.

    tyre_scale, center_column_scale, gauge_row_scale, event_log_line_scale
Size of each block relative to its default, on top of `display_scale`: tyres & brakes, center column width (normal layout), fuel / energy gauge & stint rows height, event log lines height. Value range `0.5` to `3`. Battery gauge, damage panel and incident trace have their own `battery_bar_scale`, `damage_panel_scale` and `trace_height_scale`.

    show_module_warning, font_color_module_warning
Several readings come from data modules: `Wheels module` (slip warning, wheel angle, camber, slip angle, wear per lap, end of stint wear, brake wear, locking, flat spot, stint wear), `Fuel module` (fuel & energy gauges, end of stint wear), `Delta module` (delta, lap time) and `Hybrid module` (battery gauge). When a module needed by an enabled option is turned off, its readings are no longer read (they would stay frozen), values show `-` or are hidden, and a notice at the bottom of the car view says which module is off (`Wheels, Fuel modules off`). Module state is checked about once per second, so turning a module back on is picked up without reloading the widget.

    enable_required_modules
Turn on and start any data module needed by enabled options when the widget starts, the same as turning it on in the module list (saved). Disabled by default.

    override_unit_temperature, override_unit_tyre_pressure, override_unit_speed, override_unit_fuel
Unit used by this widget only. `Global` follows the `Units` setting. Default is `Global`, except fuel which defaults to `Liter`, so fuel gauge always reads in liters unless changed here.

    tyre_temperature_cold_threshold, font_color_tyre_temperature_cold, font_color_tyre_temperature_warming
Tyre temperature text turns cold color below this temperature (Celsius), or warming color while still below it but rising (see trends). `0` disables. Default is `70`. Above `tyre_temperature_warning_threshold` it turns `font_color_tyre_temperature_warning`.

    show_tyre_temperature_trend, show_tyre_pressure_trend, tyre_trend_duration, tyre_heat_trend_threshold, tyre_pressure_trend_threshold
Append an arrow to tyre temperature or pressure: `↑` rising, `↓` falling, compared with the value `tyre_trend_duration` seconds ago (default `10`). A change smaller than the threshold (`2` Celsius degrees, `1` kPa by default) shows no arrow.

    tyre_target_by_compound
Pressure target (kPa, psi or bar, as `tyre_pressure_target_minimum`) and optional temperature window (Celsius) per tyre compound, replacing `tyre_pressure_target_minimum`, `tyre_pressure_target_maximum`, `tyre_temperature_cold_threshold` and `tyre_temperature_warning_threshold` for that compound. Format: `symbol=min-max/cold-hot`, entries separated by `;`, for example `S=160-190/75-105; W=150-175/40-70`. The symbol is the compound symbol (see `Tyre Compound Editor`) or the full compound name. Invalid entries are ignored. Empty by default.

    brake_temperature_cold_threshold, brake_temperature_hot_threshold, font_color_brake_temperature_cold, font_color_brake_temperature_hot
Brake temperature text turns cold color below the cold threshold, hot color above the hot threshold (Celsius), instead of heatmap color. `0` disables (default). Used for car classes not found in `brake_target_by_class`.

    brake_target_by_class
Brake disc temperature window (Celsius) per car class, replacing `brake_temperature_cold_threshold` and `brake_temperature_hot_threshold` for that class: carbon discs (prototypes, GTE) work far hotter than iron discs (GT3, LMP3). Format: `class=cold-hot`, entries separated by `;`, matched when the name is found in the car class name (longest name wins, case ignored). Default is `Hypercar=400-950; LMP2=400-950; GTE=400-950; LMP3=250-650; GT3=250-650`.

    show_brake_peak_temperature
Show highest disc temperature of the last braking zone below the live temperature (`▲812`), in hot color above the hot threshold. The live reading drops as soon as braking ends; the peak tells whether the brakes stay in their window. Disabled by default.

    brake_imbalance_threshold
Draw a dashed warning outline on both discs of an axle when their temperatures differ by more than this (Celsius, default `150`, `0` disables) while one of them is warm: sticking caliper, blocked brake duct, or damage.

    show_brake_heat_balance, text_brake_heat
Show average front minus rear disc temperature (`BHEAT +120`) as a center column item: which way to move brake bias. Disabled by default.

    show_brake_temperature_trend, brake_trend_duration, brake_heat_trend_threshold
Append an arrow to brake temperature: `↑` heating (braking zone), `↓` cooling, compared with the value `brake_trend_duration` seconds ago (default `2`). A change smaller than `brake_heat_trend_threshold` (default `20` Celsius degrees) shows no arrow.

    show_stint_comparison
Show an extra bottom row with average tread wear per lap (percent) and average tyre pressure of the current stint, followed by the difference with the previous stint once a stint has been completed (a stint ends when entering the pits). Needs `Wheels module` for wear.

    text_puncture, text_flat_spot, text_detached, text_abs, text_tc, text_brake_bias, text_brake_migration, text_locking, text_delta, text_laptime, text_pit, text_limiter, text_speed, text_rpm, text_fuel, text_energy, text_stint_wear, text_stint_pressure, text_motor_map
Custom label texts, for translation or shorter abbreviations. Defaults are `PUNCT`, `FLAT`, `OFF`, `ABS`, `TC`, `BB`, `BMIG`, `MAP`, `LOCK`, `DELTA`, `TIME`, `PIT`, `LIM`, `SPD`, `RPM`, `Fuel`, `Energy`, `Wear/lap` and `Pres`.

The order of the center column items can be changed with the arrows of the `Center Column Order` section of Overlay Options page.

    enable_depth_effects
Soft drop shadow and rounded rubber shading on tyres, thin highlight edge on info rows.

    smooth_transition_duration
Fade tyre and brake heatmap colors from one grade to the next over `smooth_transition_duration` seconds (default `0.4`), instead of stepping. `0` turns fading off.

    alert_pulse_frequency
Pulse wheel lock & spin outline, detached wheel, puncture and flat spot warnings at `alert_pulse_frequency` (Hz, default `1.5`), `0` keeps them steady.

    show_damage_panel, damage_panel_position, damage_panel_scale
Show the same data as `Damage` widget in its own column outside the main area, flush with a corner of the widget: `Bottom Right` (default), `Bottom Left`, `Top Right` or `Top Left`. It sits on its own card with the same background as the widget, placed right against it without being merged into it, room above or below it stays transparent. `Center Horizontally` and `Center Vertically` (widget right click menu) center the black box card only, the damage panel card is left out. It shows the car seen from above: rounded body cut in 8 segments (front, sides, rear), intact ones in body color, damaged ones light up, detached ones pulse; wheels on both sides colored by suspension damage (outlined on puncture, dashed when detached); a fading cone toward the last impact; integrity in the middle, colored by level (green, yellow, red) with its source (`BODY` or `AERO`) and a gauge. `damage_panel_scale` sets its height in lines (default `4.5`).

    damage_panel_body_color, damage_panel_body_color_light, damage_panel_body_color_heavy, damage_panel_body_color_detached
Body part color: intact, light damage, heavy damage, detached.

    damage_panel_suspension_color, damage_panel_suspension_color_light, damage_panel_suspension_color_medium, damage_panel_suspension_color_heavy, damage_panel_suspension_color_totaled, damage_panel_wheel_color_detached, damage_panel_puncture_color
Wheel color by suspension damage, detached wheel color, and puncture outline color.

    damage_panel_suspension_light_threshold, damage_panel_suspension_medium_threshold, damage_panel_suspension_heavy_threshold, damage_panel_suspension_totaled_threshold
Suspension damage fraction from which each color is used. Defaults are `0.02`, `0.15`, `0.4` and `0.8`, same as `Damage` widget.

    show_damage_panel_impact_cone, damage_panel_impact_cone_angle, damage_panel_impact_cone_duration, damage_panel_impact_cone_color
Show a cone toward the last impact for `damage_panel_impact_cone_duration` seconds (default `15`), `damage_panel_impact_cone_angle` degrees wide (default `15`).

    show_damage_panel_integrity, show_damage_panel_aero_integrity, text_integrity_body, text_integrity_aero
Show remaining body integrity in the middle, or aero integrity if the car reports it, with its source label (defaults `BODY` and `AERO`).

    show_incident_recorder, recorder_duration, incident_deceleration_threshold, incident_display_duration
Incident recorder: a trace panel shows the last `recorder_duration` seconds (default `15`) of speed (line), throttle & brake (filled areas), ABS & TC activity (ticks on top) and wheel lock & spin (marks at bottom). An incident is detected on an impact reported by the game (contact with a car or a wall, even without much speed loss), on a deceleration above `incident_deceleration_threshold` measured over 150 ms (g, default `4`, `0` disables; a single telemetry step is too noisy, and a prototype already brakes at 3 to 3.5 g), or on new body or suspension damage. The recording continues 2 seconds after the incident, then the trace freezes on it for `incident_display_duration` seconds (default `20`), with the incident moment marked and a caption (`IMPACT L12 6.3g ↗`, with an arrow toward the impact reported by the game), before going back to live. Steering input is drawn around the middle line (up is right). Use the `black_box_next_incident` hotkey to look at older incidents. The dot at top right counts incidents of the session. A new session clears the live recording; an incident still recording its last 2 seconds is kept. The recording stops while the game is paused, so a pause leaves no gap in it. Incidents and event log are kept when the widget is reloaded after an option change.

    enable_incident_replay
Replay a frozen incident: a cursor sweeps the recording in real time, then starts again, with the time from the incident, speed, throttle, brake and gear under it at the bottom of the trace (`-1.2s 184km/h T0 B87 3`). Enabled by default.

    show_previous_incident_trace
Draw the speed of the previous incident behind the shown one (dashed and faded), aligned on the incident moment, to compare both. Enabled by default.

    damage_event_threshold
Smallest damage increase (sum of body severity and suspension damage fraction) logged as damage and recorded as an incident. Default is `0.02`, so damage creeping up by tiny steps on kerbs does not fill the event log.

    trace_steering_color
Color of the steering input line in the incident trace.

    enable_incident_file_export, incident_export_format
Save each incident (written in the background, never slowing the widget; a second incident within the same second gets a numbered name) (times relative to incident, speed in m/s, pedals, steering, gear, ABS, TC, slip, slip ratio and tyre load per wheel) in the `blackbox` folder of the configuration folder, to look at afterwards. `incident_export_format`: `JSON` (default, with incident summary), `CSV` (opens in a spreadsheet or telemetry tool) or `Both`. Enabled by default, only used with the incident recorder.

    trace_height_scale, trace_speed_color, trace_background_color, incident_color
Height of trace panel relative to font line height (default `2.5`), speed line color, panel background, incident mark & critical event color.

    show_event_log, number_of_event_log_lines, font_color_event_log
Event log below the trace: puncture, flat spot, detached wheel, damage and incidents, newest on top, with lap and session time (`L12 04:31 PUNCT FR`). Critical events use `incident_color`. Tyre events need `show_tyre_status`.

    show_flag_events, text_yellow_flag, text_blue_flag
Log a yellow flag in any sector and a blue flag for you, each once when it comes out. Defaults are `YELLOW` and `BLUE`. Enabled by default.

    show_pit_events, text_pit_in, text_pit_out
Log pit lane entry and exit. Defaults are `PIT IN` and `PIT OUT`. Enabled by default.

    show_penalty_events, text_penalty, text_track_limits
Log each new penalty (critical, with the number of penalties) and each new track limits point (`LIMITS 2/4`, points per penalty when the game reports it, LMU only; critical once a penalty is reached). Defaults are `PENALTY` and `LIMITS`. Enabled by default.

    show_engine_overheat_events, text_overheat
Log oil or water temperature reaching `engine_oil_warning_temperature` or `engine_water_warning_temperature` (critical, `OIL HOT 126°`), once each time it gets hot. Default label is `HOT`. Enabled by default.

    show_contact_events, text_contact, text_wall
Log each contact of the player with another car (`CONTACT` and its driver name) or a wall (`WALL`), from the contact list of the game (LMU, Rest API `enable_race_info` option), at the time of the contact. Contacts with the same car within 2 seconds are logged once, contacts from before the widget started are not logged. Defaults are `CONTACT` and `WALL`. Enabled by default.

    text_damage, text_impact
Custom labels of damage and incident events. Defaults are `DAMAGE` and `IMPACT`.

Options of this widget in Overlay Options page are in sections, one per part of the widget: General, Profile & Data, Size & Layout, Visual Style, Units, Steering & Wheel Slip, Tyre Temperature, Tyre Pressure, Tyre Wear & Status, Tyre Readings, Brakes, Suspension, RPM LEDs, Gear & Speed, Center Column, Fuel & Energy Gauges, Battery, Damage Panel, Incident Recorder & Event Log, Labels and Center Column Order. The live preview shows changes before saving. The page shows this widget in simple mode, showing on/off and choice options plus the few common ones; tick `Advanced Options` to show every option (colors, thresholds, labels). Click a section title to collapse or expand it, `Reset` beside it resets that section only; a search looks through every option, collapsed or advanced ones included. Options that only matter while another option is on are dimmed while it is off, and options set by the selected `display_profile` are locked in italic, naming the profile. `Color Theme...` sets every color at once (Default, Colorblind Safe), saved only with Apply. The table button of `tyre_target_by_compound` edits it as a table. Each label text sits in the section of the part it names. Default colors follow one palette: red for warnings and hot, cyan for cold and low, green for good, orange and yellow for intermediate states.

[**`Back to Top`**](#)


## Wheel toe
**This widget displays wheel toe angle info.**

Note, all toe readings are in degrees.

    enable_symmetric_toe_angle
Enable this option to show symmetric toe angle, where positive reading indicates toe-in (inward), negative indicates toe-out (outward). Disable this option to show each wheel's toe angle with reference to vehicle's heading (positive to right side of vehicle, negative to left side). This option is enabled by default.

    show_total_toe_angle
Show total toe angle between left and right wheel on the same axle, useful for quickly checking amount total toe angle while driving.

    toe_in_smoothing_samples, total_toe_angle_smoothing_samples
Set number of samples for reducing data fluctuation. Lower value may result more fluctuated reading. Set `1` to disable smoothing.

[**`Back to Top`**](#)


# Widget plugins
**Custom widgets can be added without changing Modern Tiny Pedals code.**

Each plugin is a folder in `plugins` folder (next to Modern Tiny Pedals), named with lowercase letters, digits or `_`:

    plugins/<name>/setting.json   default options of the widget
    plugins/<name>/widget.py      Realtime class, inherits tinypedal.widget._base.Overlay

Plugin appears as `plugin_<name>` widget in `Overlays` tab, with the same common options as other widgets (position, font, opacity...). A plugin that fails to load shows a red `PLUGIN ERROR` widget instead of stopping Modern Tiny Pedals; error details are shown in [Plugin manager](#plugin-manager) and log.

Minimal example, a speed widget (`plugins/speed/setting.json` holds `{"enable": false, "font_color": "#FFFFFF", "background_color": "#222222"}`):

    from tinypedal.api_control import api
    from tinypedal.widget._base import Overlay


    class Realtime(Overlay):
        def __init__(self, config, widget_name):
            super().__init__(config, widget_name)  # options of setting.json & preset in self.wcfg
            layout = self.set_grid_layout()
            self.set_primary_layout(layout=layout)
            font = self.config_font(self.wcfg["font_name"], self.wcfg["font_size"], self.wcfg["font_weight"])
            self.setFont(font)
            font_m = self.get_font_metrics(font)
            self.bar_speed = self.set_rawtext(
                text="---", width=font_m.width * 7, fixed_height=font_m.height, offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color"], bg_color=self.wcfg["background_color"], last=-1)
            layout.addWidget(self.bar_speed, 0, 0)

        def timerEvent(self, event):  # every update_interval ms while on track
            speed = round(api.read.vehicle.speed() * 3.6)  # m/s to km/h
            if self.bar_speed.last != speed:  # repaint only on change
                self.bar_speed.last = speed
                self.bar_speed.text = f"{speed:3d} kph"
                self.bar_speed.update()

Important: plugins run as normal Python code with full access to your computer, only install plugins from trusted sources.

[**`Back to Top`**](#)


# Language packs

A new UI language can be added without changing code, with a JSON language pack:

1. Create a template (from repository root): `python tools/make_language_template.py de Deutsch`. This writes `de.json` with every UI text, dialog message, option label and option description to translate, plus French text in `_reference` as a guide.
2. Fill the empty values. Empty values stay in English, so a partial translation works. `messages` entries are regular expressions: keep the pattern (first item) as is, translate the replacement (second item), `\1`, `\2`... insert the matched parts.
3. Copy the file to the `languages` folder of the global config folder (`Config` > `Open Folder` > `Config`), restart, then select the language in `Config` > `Application` > `Language`.

Language pack format:

    {
        "format": "modern-tiny-pedals-language",
        "code": "de",
        "name": "Deutsch",
        "ui": {"Config": "Konfiguration", ...},
        "messages": [["^Preset imported: ", "Preset importiert: "], ...],
        "options": {"font_size": "Schriftgröße", ...},
        "option_help": {"English description": "Übersetzung", ...},
        "overlay": {"Fuel": "Kraftstoff", ...}
    }

`overlay` holds the short labels of modern design widgets (kept apart from `ui`, as overlays need shorter words).

Invalid files are skipped and reported in the log. A language pack cannot replace English or French.
