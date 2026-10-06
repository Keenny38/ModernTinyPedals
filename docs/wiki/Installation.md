# Installation

Modern Tiny Pedals runs on **64-bit Windows** (installer) and on **Linux** (from source). After installing, set up your game: see [Game Setup](Game-Setup.md).

## Windows

### Install

1. Open the [latest release](https://github.com/Keenny38/ModernTinyPedals/releases/latest) and download the installer `ModernTinyPedals-<version>-windows-setup.exe` (`ModernTinyPedals-<version>-setup.zip` holds the same installer, zipped).
2. Run the installer. It is available in English and French, asks you to accept the license (GPL v3) and can create a desktop shortcut.
3. Start Modern Tiny Pedals from the Start menu (or let the installer start it). The [setup wizard](Getting-Started.md#first-launch) opens on first launch.

The installer:

- installs **per user**, in `%LOCALAPPDATA%\Programs\Modern Tiny Pedals`, so **no administrator rights** are needed;
- creates a Start menu shortcut whose icon matches the Windows light or dark mode;
- closes a running Modern Tiny Pedals before updating it;
- on update, replaces only the program files and keeps your presets and data.

### SmartScreen warning

If a release is not code-signed, Windows SmartScreen may show "Windows protected your PC" when you run the installer. Click `More info`, then `Run anyway`. Before doing so, you can check that the file is the one GitHub built: see [Verifying a download](Updates-and-Security.md#verifying-a-download).

### Verify the download

Every release lists the SHA-256 of its files in the release notes, and each file has a signed build provenance attestation. Quick check in PowerShell:

```powershell
Get-FileHash .\ModernTinyPedals-<version>-windows-setup.exe -Algorithm SHA256
```

Compare the result with the release notes. Full details: [Updates and Security](Updates-and-Security.md#verifying-a-download).

### Where your files are

| What | Location |
|---|---|
| Program | `%LOCALAPPDATA%\Programs\Modern Tiny Pedals` (`tinypedal.exe`) |
| Presets and user data: `settings`, `deltabest`, `trackmap`, `telemetry`, `pacenotes`, `tracknotes`, `brandlogo`, `carsetups` | Next to `tinypedal.exe`, in the program folder |
| Global config: `config.json`, `shortcuts.json`, driver stats, logs, language packs, Black box incidents | `%APPDATA%\TinyPedal` |

The internal name stays `TinyPedal` (config folder, `tinypedal.exe`) so that existing TinyPedal settings keep working. Data folders can be moved with `Config` > `User Path`, and opened with `Config` > `Open Folder`.

### Updates

The app checks for a new version at startup and can download and install it for you. See [Updates and Security](Updates-and-Security.md#in-app-updates). You can also run a newer setup over your installation at any time: your presets and data are kept.

## Moving from a portable copy

Releases up to 0.19 also offered a portable ZIP. Portable copies cannot update themselves, and new releases no longer publish a portable ZIP. To turn a portable copy into an installed one, install the setup **into the folder of your portable copy**:

1. Quit the portable copy (tray icon menu > `Quit`).
2. Run the installer. On the destination page, select the folder of your portable copy (the folder that contains `tinypedal.exe`).
3. Finish the installation.

Your presets and data are kept: they live next to the executable, and the installer only replaces program files. The global config in `%APPDATA%\TinyPedal` is shared by every copy and is not touched. From then on, the copy is an installed copy and updates itself.

> [!NOTE]
> If Modern Tiny Pedals is already installed, the installer reuses that installation folder instead of asking for a destination. In that case, quit the app and copy the data folders of your portable copy (`settings`, `deltabest`, `trackmap`, `telemetry`, `pacenotes`, `tracknotes`, `brandlogo`, `carsetups`) into the installed folder instead.

Never put a copy in `Program Files` or in the game folder: the app writes its presets next to the executable.

## Linux

There is no Linux executable: run the app from source. You need Python 3.11 or newer and these packages: `PySide6`, `psutil`, `cryptography` and `pyxdg`. Package names depend on your distribution, for example `python3-pyside6`, `python3-psutil`, `python3-cryptography`, `python3-pyxdg`. Some distributions split PySide6 into several packages: then install `python3-pyside6.qtgui`, `python3-pyside6.qtwidgets` and `python3-pyside6.qtmultimedia` (plus the Qt QML and Qt Quick modules, used by the telemetry viewer, track map viewer and driver stats pages).

You can also install the Python packages in a virtual environment with `pip install -r requirements.txt` instead.

### Get the source and run

Download `ModernTinyPedals-<version>-source.zip` from the [latest release](https://github.com/Keenny38/ModernTinyPedals/releases/latest), or clone the repository:

```bash
git clone https://github.com/Keenny38/ModernTinyPedals.git
```

```bash
cd ModernTinyPedals
```

```bash
./run.py
```

Prefer the release `-source.zip` over the "Source code" archives that GitHub adds automatically to every release: the release ZIP has its version number set and is covered by the checksums and attestations. The shared memory libraries (`pyLMUSharedMemory`, `pyRfactor2SharedMemory`) are included in the repository: there is no submodule to fetch.

### Install a launcher

To install the app in `/usr/local/share/TinyPedal`, a `TinyPedal` command in `/usr/local/bin` and a desktop entry:

```bash
sudo ./install.sh
```

Pass another prefix as argument (for example `sudo ./install.sh /opt`, you are asked to confirm). Run it again from a newer source folder to update: the previous copy is removed first.

Permanent command line arguments for the `TinyPedal` launcher go in `~/.config/TinyPedal/launcher.conf`, for example:

```bash
TINYPEDAL_RUN_ARGS="--log-level 2"
```

### Linux folders

| What | Location |
|---|---|
| Global config, presets (`settings`), `brandlogo`, `pacenotes`, `tracknotes` | `~/.config/TinyPedal/` |
| Data: `deltabest`, `trackmap`, `carsetups`, `telemetry` | `~/.local/share/TinyPedal/` |

Known Linux issues (KDE, compositing) are listed in [Troubleshooting](Troubleshooting.md#overlay-not-visible).

## Running from source on Windows

Useful to test the latest code or to contribute. You need [Python](https://www.python.org/) 3.11 or newer.

```bash
git clone https://github.com/Keenny38/ModernTinyPedals.git
```

```bash
cd ModernTinyPedals
```

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

`requirements.txt` holds compatible version ranges; `requirements-lock.txt` pins the exact versions tested for release builds. The SteamVR overlay also needs the optional `openvr` package (`pip install openvr`), included in release builds. When run from a git checkout, the app shows the last release followed by the number of commits since (for example `0.19.1+3.g8a0f9f3`). See [Development](Development.md) for the developer tools.

## Uninstalling

### Windows

Uninstall from Windows `Settings` > `Apps` > `Installed apps`, or with the `Uninstall Modern Tiny Pedals` shortcut of the Start menu. The uninstaller removes the installed program files only. To remove everything, also delete:

- the data folders left in `%LOCALAPPDATA%\Programs\Modern Tiny Pedals` (presets, telemetry, track maps...);
- the global config folder `%APPDATA%\TinyPedal` (shared with any other copy you still use).

### Linux

Remove the files written by `install.sh` (default prefix shown):

```bash
sudo rm -r /usr/local/share/TinyPedal /usr/local/bin/TinyPedal /usr/local/share/applications/TinyPedal-overlay.desktop
```

Your config and data stay in `~/.config/TinyPedal/` and `~/.local/share/TinyPedal/`: delete them too for a full removal.
