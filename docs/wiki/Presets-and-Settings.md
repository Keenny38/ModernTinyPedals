# Presets and Settings

Modern Tiny Pedals keeps two kinds of settings:

- **Presets**: the layout and options of all overlays and modules, one JSON file per preset in the `settings` folder. You can have as many as you want.
- **Global config**: app-wide options (window, language, units, overlay style, remote control, web dashboard...), in `config.json` of the global config folder.

Every option is described in the [settings reference (customization.md)](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md).

## Presets

Open the `Preset` page. The loaded preset is shown on top, with the `Auto Load Primary Preset` switch. Each preset shows when it was last changed, how many overlays and modules it turns on, its car class and track tags, its preset hotkeys and a lock mark. Search by preset, class or track name, and sort by last change or by name. On a wide window, the selected preset's details are shown on the right: its overlays and modules, the game it remembers, its tags (add a car class or track, or remove one with its `×`) and every action.

| Action | How |
|---|---|
| Load a preset | Double-click it, `Load` on its row (or `Enter`) |
| Create a default preset | `New` (`Ctrl+N`): the name is checked as you type |
| Copy settings from the loaded preset to another one | `Transfer` (choose settings and option types: positions, colors, fonts...) |
| Restore a backup | `Restore`, see [Backups](#backups) |
| Restore a deleted preset | `Trash`, see [Trash](#trash) |
| Import a preset package or a share code | `Import` > `Preset Package (.zip)...` or `Share Code...` |
| Load a preset automatically | `Auto Load Primary Preset`, see [Auto load](#auto-load-per-class-or-track) |

Right-click a preset (or its `...` button) for more actions: `Duplicate...`, `Rename...` (`F2`), `Lock Preset` / `Unlock Preset`, `Backup Preset`, `Export Package...`, `Copy Share Code`, `Compare with Loaded Preset`, `Set Primary for Class`, `Set Primary for Track`, `Clear Primary Tag` and `Delete` (`Del`). A renamed preset keeps its backups, layout profiles, primary tags and preset hotkeys. Locked and loaded presets cannot be deleted, a locked preset cannot be renamed.

Overlay positions, overlays turned on or off and the lock state are saved automatically; options are saved with `Apply` or `Save` on their page. Hotkeys can load a given preset, or the next and previous preset: see [Getting Started](Getting-Started.md#hotkeys).

### Locked presets

A locked preset is never saved by the app: changes made while it is loaded are not written to its file. Useful for a reference layout. Locking does not stop you from editing or deleting the file by other means.

### Share codes

A share code is a whole preset as one line of text, to paste in a chat or a forum:

1. Right-click a preset > `Copy Share Code`.
2. To import one, `Import` > `Share Code...`, paste the code: the app shows the overlays and modules it contains, then asks for a name.

### Preset packages

`Export Package...` saves a preset with its style presets and, if you want, its track and pace notes, in one `.zip` file. `Import` > `Preset Package (.zip)...` imports one. Imported presets never overwrite yours: they are renamed if needed.

You can also drag a preset file, a preset package or a plugin `.zip` onto the main window to import it.

### Trash

`Delete` moves a preset (and its layout profiles) to the trash. `Undo` in the message at the bottom of the window, `Undo Delete` at the bottom of the page, or `Ctrl+Z` on the page puts it back.

The `Trash` page lists deleted presets:

- `Restore` (or double-click) puts a preset back, with its primary tags and preset hotkeys unless they were reassigned meanwhile. A preset whose name was reused is renamed (`name (2)`).
- `Delete Permanently` and `Empty Trash` delete for good, after confirmation.

Deleted presets are kept `number_of_days_to_keep_deleted_presets` days (default `30`, `Config` > `Application`). The loaded preset cannot be deleted: load another one first.

### Backups

- **Automatic backups**: before saving a preset, the app keeps a copy, at most once every 10 minutes. `number_of_automatic_backups` (default `10` per preset, `0` to turn off) is in `Config` > `Application`.
- **Manual backup**: right-click a preset > `Backup Preset`.
- **Load failure**: if a preset file cannot be loaded, a backup copy is made and the preset is reset to default.

To restore, click `Restore` on the `Preset` page, select a backup and enter a name. Invalid backups are shown in red; style preset backups (blue) replace the existing style preset after confirmation.

### Auto load per class or track

1. Right-click a preset > `Set Primary for Class` (classes from `Tools` > `Vehicle Class Editor`) or `Set Primary for Track` (tracks from `Tools` > `Track Info Editor`).
2. Turn on `Auto Load Primary Preset` on the `Preset` page.

When you get on track, the primary preset of the track is loaded first, else the primary preset of your car class.

### Compare presets

`Tools` > `Preset Comparison` (or right-click > `Compare with Loaded Preset`) lists the options that differ between two presets. Select rows, copy values from one preset to the other, then `Save`.

### Style presets

Some settings are shared by all presets and edited with their own tools (`Tools` menu): brands (`Vehicle Brand Editor`), classes and class colors (`Vehicle Class Editor`), brakes (`Brake Editor`), tyre compounds (`Tyre Compound Editor`), heatmaps (`Heatmap Editor`) and track info (`Track Info Editor`). They are stored as `brands.json`, `classes.json`, `brakes.json`, `compounds.json`, `heatmap.json` and `tracks.json` in the `settings` folder.

## Global config

Global options are in `config.json`, in the global config folder: `%APPDATA%\TinyPedal` on Windows, `~/.config/TinyPedal/` on Linux. They are all edited in the `Config` page: its entry in the navigation bar, the gear button at the bottom of the bar, `Config` > `All Settings` (`Ctrl+,`), the Home page quick access, the `Tools` page or the command palette. Like the other navigation bar tools, it stays as you left it (category, pending changes) while you browse other pages.

- One category per section of `config.json`, options in groups with their description, and an editor matching each option: switch, choice list, number with its limits, color with a picker, folder with `Choose Folder...` and `Open Folder`.
- `Search settings` (`Ctrl+F` on the page) looks through every category; the count of matches shows next to each category.
- Changes stay pending until `Apply` (`Ctrl+S`): the bar at the bottom counts them, with `Undo`, `Redo` (`Ctrl+Z`, `Ctrl+Y`) and `Discard`. Invalid values are shown in red with the reason and block `Apply`. The circular arrow next to an option puts it back to default, `Reset Section` the whole category.
- The `Web Dashboard` category shows the addresses to open and the access code (with copy buttons), `Remote Control` the command and stream addresses, `Notification` a preview of each notice. The `Stream Overlay` category holds the server settings of the `Stream Overlays` page, which lists the browser source addresses (see [Connections](Connections.md#stream-overlays-obs-streamlabs-xsplit-vmix)).
- Units, global font override and API options belong to the loaded preset: they open their own page from `In the loaded preset`.

The menus open the matching category:

| Menu | Settings |
|---|---|
| `Config` > `Application` | Startup, tray, updates, language, window theme, setup wizard, auto load, backups, trash, snapping, layout guides |
| `Config` > `Compatibility` | Linux window manager bypass, translucent background, window position correction, X11 override |
| `Config` > `Notification` | Notices shown in the main window |
| `Config` > `Units` | Distance, fuel, speed, temperature, pressures, power, weight |
| `Config` > `Global Font Override` | Font name, size, weight and offset for every overlay |
| `Config` > `Overlay Style` | Modern design, theme, fonts, corners, depth effects, overlay scale, fade |
| `Config` > `Remote Control`, `Web Dashboard`, `VR Overlay (Experimental)` | See [Connections](Connections.md) |
| `Config` > `User Path` | Folders for presets, data and recorded laps |
| `API` > `Options` | Game connection, see [Game Setup](Game-Setup.md) |
| `Window` | `Show at Startup`, `Minimize to Tray`, `Remember Position`, `Remember Size`, `Reopen Pages at Startup`, `Reset Window Size and Position`, `Restart Modern Tiny Pedals` |

`Config` > `Open Folder` opens any user folder in your file manager. Data folders set inside the app folder are stored as relative paths (each copy keeps its own data); set them outside the app folder to share data between copies.

### Reset data

`Overlay` > `Reset Data` deletes recorded data of the track and car class you are driving (after confirmation): `Delta Best`, `Energy Delta`, `Fuel Delta`, `Consumption History`, `Sector Best`, or the `Track Map` of the track. Driver stats are reset from the [Driver Stats](Driver-Stats.md#edit-and-backups) page. See also [Troubleshooting](Troubleshooting.md#reset-the-app).

## Language

The interface is available in **English** and **French**. Change it in `Config` > `Application` > `language`: the window is rebuilt at once, no restart needed. Option names and their tooltips are translated too, and overlay labels follow the app language. The web dashboard and the What's New page also use the app language.

### Language packs

Another language can be added without changing code, with a JSON language pack:

1. From the repository root, create a template, for example for German:

   ```bash
   python tools/make_language_template.py de Deutsch
   ```

   This writes `de.json` with every text to translate (interface, messages, option labels and descriptions, overlay labels), plus the French text as a guide.
2. Fill in the empty values. Empty values stay in English, so a partial translation works. In `messages`, keep the pattern (first item) and translate the replacement (second item).
3. Copy the file to the `languages` folder of the global config folder (`Config` > `Open Folder` > `Config`), restart, then select the language in `Config` > `Application` > `language`.

Overlay labels (the `overlay` table) must stay short. Invalid packs are skipped and reported in the log. A pack cannot replace English or French. Format details: [Language packs](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#language-packs).
