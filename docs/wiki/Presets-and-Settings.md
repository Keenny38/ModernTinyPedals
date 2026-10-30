# Presets and Settings

NeoPedal keeps two kinds of settings:

- **Presets**: the layout and options of all overlays and modules, one JSON file per preset in the `settings` folder. You can have as many as you want.
- **Global config**: app-wide options (window, language, units, overlay style, remote control, web dashboard...), in `config.json` of the global config folder.

Every option is described in the [settings reference (customization.md)](https://github.com/Keenny38/NeoPedal/blob/master/docs/customization.md).

## Presets

Open the `Presets` page. The loaded preset is shown on top, with the `Auto Load Primary Preset` switch. Each preset shows when it was last changed, how many overlays and modules it turns on, its car class and track tags, its preset hotkeys and a lock mark. Search by preset, class or track name (`Ctrl+F`, `/`, or just type), and sort by last change or by name. On a wide window, the selected preset's details are shown on the right: its overlays and modules, the game it remembers, its tags (add a car class or track, or remove one with its `×`) and every action.

| Action | How |
|---|---|
| Load a preset | Double-click it, `Load` on its row (or `Enter`) |
| Create a default preset | `New` (`Ctrl+N`): the name is checked as you type |
| Copy settings from the loaded preset to another one | `Transfer` (choose settings and option types: positions, colors, fonts...), see [Transfer](#transfer) |
| Restore a backup | `Restore`, see [Backups](#backups) |
| Restore a deleted preset | `Trash`, see [Recently deleted presets](#recently-deleted-presets) |
| Import a preset package | `Import`, choose the `.zip` file, see [Preset packages](#preset-packages) |
| Load a preset automatically | `Auto Load Primary Preset`, see [Auto load](#auto-load-per-class-session-or-track) |

Right-click a preset (or its `...` button) for more actions: `Duplicate…`, `Rename…` (`F2`), `Lock Preset` / `Unlock Preset`, `Backup Preset`, `Export Package…`, `Compare with Loaded Preset`, `Set Primary for Class`, `Set Primary for Track`, `Clear Primary Tag` and `Delete` (`Del`). A renamed preset keeps its backups, layout profiles, primary tags and preset hotkeys. Locked and loaded presets cannot be deleted, a locked preset cannot be renamed. Names reserved by Windows (`CON`, `NUL`, `AUX`, `PRN`, `COM1`...`LPT9`) are refused.

Overlay positions, overlays turned on or off and the lock state are saved automatically; options are saved with `Apply` or `Save` on their page. Hotkeys can load a given preset, or the next and previous preset: see [Getting Started](Getting-Started.md#hotkeys).

### Locked presets

A locked preset is never saved by the app: changes made while it is loaded are not written to its file. Useful for a reference layout. Locking does not stop you from editing or deleting the file by other means.

### Preset packages

To share a preset, use a preset package: `Export Package…` saves a preset with its style presets and, if you want, its track and pace notes, in one `.zip` file. `Import` imports one. Imported presets never overwrite yours: they are renamed if needed. Options that belong to your computer keep your values: file and folder paths (custom steering wheel image, pace notes file and sound folder) and the game API address (`url_host`, `url_port`); the import message tells how many were kept. A package with more than 1000 files, more than 200 presets or more than 100 MB once uncompressed is refused. Files on a network path (`\\server\share`) are never loaded from a preset, and a pace note naming a folder (`/`, `\`, `:`, `..`) plays no sound.

You can also drag a preset file, a preset package, an overlay settings file or a plugin `.zip` onto the main window to import it.

### Share overlay settings

To share the look of one overlay or of a few, without a whole preset, save their settings as a file:

- **Export**: on the `Overlays` page, `Share` > `Export Overlay Settings…` (or right-click an overlay > `Export Options…`), or `Share` in `Overlay Options`. Tick the overlays to include (`All`, `None`, `Active`, `With changes`), then choose where to save the `.zip` file (`NeoPedal-overlay-<name>.zip` or `NeoPedal-overlays-<count>.zip`). Only options changed from default are written, with each overlay's position. From `Overlay Options`, unsaved values are exported as shown.
- **Import**: `Share` > `Import Overlay Settings…` on the same pages, or drop the file on the main window. The file shows its overlays, how many options each changes and the NeoPedal version that made it. Untick overlays you don't want, and keep `Keep my positions` ticked to leave your overlays where they are (unticked, they move to the positions of the file, adapted to your screen size).

Imported values become unsaved changes of `Overlay Options` in the loaded preset: check them on the live preview, undo them, then `Apply` to save. Options you never changed on these overlays go back to default, so they look the same as the sender's. Overlay state (on/off) and options pointing to your own files and folders are never changed. Overlays or options unknown to your version are skipped, and a locked preset refuses the import.

### Recently deleted presets

`Delete` moves a preset (and its layout profiles) to the trash. `Undo` in the message at the bottom of the page, `Undo Delete` at the bottom of the page, or `Ctrl+Z` on the page puts it back.

`Trash` opens `Recently Deleted Presets` over the page (the same panel as the recently deleted laps of the telemetry viewer), newest first, with the deletion date and the days left:

- `Restore` (or `Enter`) puts a preset back, with its primary tags and preset hotkeys unless they were reassigned meanwhile. A preset whose name was reused is renamed (`name (2)`).
- `Delete Permanently` (or `Del`) and `Empty Trash` delete for good, after confirmation.

Deleted presets are kept `number_of_days_to_keep_deleted_presets` days (default `30`, `Settings` > `Application`). The loaded preset cannot be deleted: load another one first.

### Backups

- **Automatic backups**: before saving a preset, the app keeps a copy, at most once every 10 minutes. `number_of_automatic_backups` (default `10` per preset, `0` to turn off) is in `Settings` > `Application`.
- **Manual backup**: right-click a preset > `Backup Preset`.
- **Load failure**: if a preset file cannot be loaded, a backup copy is made and the preset is reset to default.

To restore, click `Restore Backup` on the `Presets` page: backups are listed newest first and checked in the background (an unreadable one is marked `Unreadable file` and cannot be restored). `Restore` on a preset backup asks the name of the new preset; a style preset backup replaces the existing style preset after confirmation. `Delete Permanently` removes a backup after confirmation.

### Auto load per class, session or track

1. Right-click a preset > `Set Primary for Class` (classes from `Tools` > `Vehicle Class Editor`) or `Set Primary for Track` (tracks from `Tools` > `Track Info Editor`). `Set Primary for Class` asks for the session: `Every session`, or only `Practice`, `Qualify` or `Race`. The `Car Class` button of the preset details opens the same menu.
2. Turn on `Auto Load Primary Preset` on the `Presets` page.

This way you can combine car class and session, for example `Hypercar` practice, `GT3` qualifying and `GT3` race, each with its own preset. A class preset of one session is tagged with its session (`GT3 · Race`).

When you get on track, and again when the session changes while you drive, NeoPedal loads the first preset found:

1. the preset of your car class for this session (test day counts as practice, warmup as race),
2. the primary preset of the track,
3. the preset of your car class for every session.

A preset already loaded is not loaded again.

### Compare presets

Right-click a preset > `Compare with Loaded Preset` (or the same action in its details) opens the comparison over the `Presets` page: the options that differ between preset A (the loaded one) and preset B, both can be changed. Overlay positions are left out unless `Ignore overlay positions` is turned off; `Filter` narrows the list. Click rows (or `Space`, `Ctrl+A` for every shown row), `Copy B → A` or `Copy A → B`, then `Save`: only the copied values are written, so changes made meanwhile (an overlay moved) are kept. Closing with copied values not saved asks first. `Preset Comparison` in the command palette (`Ctrl+K`) opens the `Presets` page with this comparison.

### Transfer

`Transfer` copies settings of the loaded preset into another preset: choose the destination (loaded and locked presets are left out), the settings (overlays, modules, units...) and the option types (positions, colors, fonts...), with `All` and `None` for each list, then `Transfer` and confirm: the other preset's options are overwritten.

### Style presets

Some settings are shared by all presets and edited with their own tools (`Tools` menu): brands (`Vehicle Brand Editor`), classes and class colors (`Vehicle Class Editor`), brakes (`Brake Editor`), tyre compounds (`Tyre Compound Editor`), heatmaps (`Heatmap Editor`) and track info (`Track Info Editor`). They are stored as `brands.json`, `classes.json`, `brakes.json`, `compounds.json`, `heatmap.json` and `tracks.json` in the `settings` folder. These editors share one table page: filter field, click a header to sort, `Enter` or `F2` (or double-click) edits a cell and `Esc` puts it back, `Delete` removes the selected rows (with `Undo`), `Ctrl+Z` / `Ctrl+Y` undo and redo, and one `Save` (`Ctrl+S`) checks, saves and applies the table. Columns are as wide as their header (French included), track distances and pit speed follow `Units` (stored in meters and m/s), heatmap temperatures follow the temperature unit with a live preview of the colors, and the track primary preset is chosen among existing presets, the same setting as `Set Primary for Track`. Tyre compounds are colored by default soft white, medium yellow, hard red, wet blue, the same as in the race calculator and the broadcast director.

## Global config

Global options are in `config.json`, in the global config folder: `%APPDATA%\NeoPedal` on Windows, `~/.config/NeoPedal/` on Linux. They are all edited in the `Settings` page: its entry in the navigation bar, the gear button at the bottom of the bar, `Settings` > `All Settings` (`Ctrl+,`), the Home page quick access, the `Tools` page or the command palette. Like the other navigation bar tools, it stays as you left it (category, pending changes) while you browse other pages.

- One category per section of `config.json`, options in groups with their description, and an editor matching each option: switch, choice list, number with its limits, color with a picker, folder with `Choose Folder…` and `Open Folder`.
- `Search settings` (`Ctrl+F` on the page) looks through every category; the count of matches shows next to each category.
- `Apply` restarts only what reads the changed settings, never the whole app: application and notification settings apply at once, `Overlay Style` restarts the overlays, `Remote Control`, `Web Dashboard`, `Stream Overlay` and `VR Overlay` restart only their own server or layer. On / off switches of global hotkeys, preset auto load, overlay previews and these servers apply as soon as you switch them.
- Changes stay pending until `Apply` (`Ctrl+S`): the bar at the bottom counts them, with `Undo`, `Redo` (`Ctrl+Z`, `Ctrl+Y`) and `Discard`. Undo also goes back past `Apply`: the change undone is pending again, to apply. Invalid values are shown in red with the reason and block `Apply`. The circular arrow next to an option puts it back to default, `Reset Section` the whole category.
- The `Web Dashboard` category shows the addresses to open and the access code (with copy buttons), `Remote Control` the command and stream addresses, `Notification` a preview of each notice. The `Stream Overlay` category holds the server settings of the `Stream Overlays` page, which lists the browser source addresses (see [Connections](Connections.md#stream-overlays-obs-streamlabs-xsplit-vmix)).
- `In the loaded preset` lists the categories saved in the loaded preset (its name shows under the title, with `Locked` if changes are not saved): `Units`, `Global Font Override`, `Pace Notes Playback` and `API Options` (options of the selected game API). They are edited like the others (pending until `Apply`) and saved in the preset; applying restarts only what reads them (overlays for units and fonts, the API for its options). If another preset was loaded meanwhile, `Apply` asks before saving into it.
- `Global Font Override` changes the font of every overlay at once: font name, font size added (from -20 to +20), weight, auto vertical offset and vertical offset added. A preview shows the smallest and largest font size now and after `Apply`, in the chosen font. It is applied once, then its fields go back to `no change` (applying again never adds twice); the toast offers `Undo`.
- `Pace Notes Playback`: volume, playback in the pit lane, longest sound and queue, global offset, sound folder and format, pace notes file chosen by hand. Its switch turns playback on or off at once, `Test Sound` plays a sound of the sound folder at the volume shown. The `Pacenotes` page shows this category alone.
- Module options: the gear of a module card (`Module` page), a module option found by `Find Option` or the command palette open the Settings page at that module, listed under `In the loaded preset` until the page closes. Its switch turns the module on or off at once; saving its options restarts the module.

The menus open the matching category:

| Menu | Settings |
|---|---|
| `Settings` > `Application` | Startup, tray, updates (`number_of_hours_between_update_checks`), language, window theme, setup wizard, auto load, backups, trash |
| `Settings` > `Compatibility` | Linux window manager bypass, translucent background, window position correction, X11 override |
| `Settings` > `Notification` | Notices shown in the main window |
| `Settings` > `Units` | Distance, fuel, speed, temperature, pressures, power, weight (saved in the preset) |
| `Settings` > `Global Font Override` | Font name, size, weight and offset for every overlay, applied once (saved in the preset) |
| `Settings` > `Overlay Style` | Modern design, theme, fonts, corners, depth effects, overlay scale, fade, overlay editing (edit mode, snapping, grid, layout guides, layout per screen setup) |
| `Settings` > `Remote Control`, `Web Dashboard`, `VR Overlay (Experimental)` | See [Connections](Connections.md) |
| `Settings` > `User Path` | Folders for presets, data and recorded laps |
| `API` > `Options` | Game connection (saved in the preset), see [Game Setup](Game-Setup.md) |
| `Window` | `Show at Startup`, `Minimize to Tray`, `Remember Position`, `Remember Size`, `Reopen Pages at Startup`, `Reset Window Size and Position`, `Restart NeoPedal` |

`Settings` > `Import Settings…` copies the global settings of another copy of the app, see [Import settings](Installation.md#import-settings). `Settings` > `Open Folder` opens any user folder in your file manager. Data folders set inside the app folder are stored as relative paths (each copy keeps its own data); set them outside the app folder to share data between copies.

### Reset data

`Overlay` > `Reset Data` deletes recorded data of the track and car class you are driving (after confirmation): `Delta Best`, `Energy Delta`, `Fuel Delta`, `Consumption History`, `Sector Best`, or the `Track Map` of the track. Driver stats are reset from the [Driver Stats](Driver-Stats.md#edit-and-backups) page. See also [Troubleshooting](Troubleshooting.md#reset-the-app).

## Language

The interface is available in **English** and **French**. Change it in `Settings` > `Application` > `language`: the window is rebuilt at once, no restart needed. Option names and their tooltips are translated too, and overlay labels follow the app language. The web dashboard and the What's New page also use the app language.

### Language packs

Another language can be added without changing code, with a JSON language pack:

1. From the repository root, create a template, for example for German:

   ```bash
   python tools/make_language_template.py de Deutsch
   ```

   This writes `de.json` with every text to translate (interface, messages, option labels and descriptions, overlay labels), plus the French text as a guide.
2. Fill in the empty values. Empty values stay in English, so a partial translation works. In `messages`, keep the pattern (first item) and translate the replacement (second item).
3. Copy the file to the `languages` folder of the global config folder (`Settings` > `Open Folder` > `Config`), restart, then select the language in `Settings` > `Application` > `language`.

Overlay labels (the `overlay` table) must stay short. Invalid packs are skipped and reported in the log. A pack cannot replace English or French. Format details: [Language packs](https://github.com/Keenny38/NeoPedal/blob/master/docs/customization.md#language-packs).
