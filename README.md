# TinyPedal - racing simulation overlay

TinyPedal is a Free and Open Source telemetry overlay application for racing simulation.

Focuses on minimalist design, light-weight and efficiency, extensive customization and data analysis. Features a large collection of highly configurable overlay widgets and data modules, advanced fuel calculator and editing tools.

Currently supports `rFactor 2` and `Le Mans Ultimate`, and runs on `Windows` and `Linux`.

[Download](https://github.com/TinyPedal/TinyPedal/releases) -
[Quick Start](#quick-start) -
[FAQ](https://github.com/TinyPedal/TinyPedal/wiki/Frequently-Asked-Questions) -
[User Guide](https://github.com/TinyPedal/TinyPedal/wiki/User-Guide) -
[Run on Linux](#running-on-linux) -
[License](#license)
---

![preview](https://user-images.githubusercontent.com/21177177/282278970-b806bf02-a83d-4baa-8b45-0ca10f28f775.png)

### What's new in this modernized fork

* Qt 6 (PySide6), modern overlay style (themes, rounded corners, bundled JetBrains Mono font), custom themes editor and per widget theme.
* French interface (`Config` > `Application` > `Language`), switched live, including all option names; option descriptions from the documentation shown as tooltips.
* First launch setup wizard, global option search (`Ctrl+F`), live widget preview, undo & redo in editors, layout guides.
* New `Black box` widget: tyres, brake discs, wheel rotation, lock & spin, ABS & TC activation.
* Telemetry recorder (CSV per lap) and lap telemetry viewer, preset comparison, preset packages (zip).
* Remote control for Stream Deck & co, web dashboard for phone or tablet, experimental SteamVR overlay.
* Widget plugins with plugin manager, bug report generator, widget & thread performance monitor.
* Robustness: thread supervisor, automatic preset backups, atomic file writing, safer networking; 295 automated tests.

See [customization guide](docs/customization.md) for details.

## Requirements

### Supported Sims

| API | Windows | Linux |
|:-:|:-:|:-:|
| Le Mans Ultimate | No plugin required | Requires third-party plugin |
| rFactor 2 | rF2SharedMemoryMapPlugin | rF2SharedMemoryMapPlugin(Wine) |

### Display Mode

Game display mode must be set to `Borderless` or `Windowed` to show overlay. `Fullscreen` mode is not supported.

### Setup for Le Mans Ultimate

#### Windows

* There is no plugin required for accessing LMU's built-in API on Windows. However, make sure `Enable Plugins` option is turned `ON` from in game `Settings` -> `Gameplay` page.

#### Linux

* LMU's built-in API can be selected on Linux, but may require third-party plugin to access, see [discussion #9](https://github.com/TinyPedal/TinyPedal/issues/9) for info.

### Setup for rFactor 2

TheIronWolf's [rF2 Shared Memory Map Plugin](https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin) is required for accessing `rFactor 2` API.

#### Windows

* Download the plugin from:\
https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin#download

#### Linux

* Download the forked plugin for Wine from:\
https://github.com/schlegp/rF2SharedMemoryMapPlugin_Wine/blob/master/build

#### Install plugin

The plugin file is named `rFactor2SharedMemoryMapPlugin64.dll` and should be placed in `rFactor 2\Bin64\Plugins` folder.

Note, manually create this `Plugins` folder if it is missing.

#### Enable plugin in game

In game `Settings` -> `Gameplay` page, find `Plugins` section and toggle on `rFactor2SharedMemoryMapPlugin64.dll`.

After plugin enabled, must `restart game` to take effect.

Note, if game cannot generate `rFactor2SharedMemoryMapPlugin64.dll` entry in `CustomPluginVariables.JSON` file, make sure `VC12 (Visual C++ 2013) runtime` is installed, which can be found in game's `Support\Runtimes` folder.

## Quick Start

> [!IMPORTANT]
> Make sure required plugins for specific game are installed according to [Requirements](#requirements).
>
> DO NOT extract TinyPedal into `system` or `game` folder, such as `Program Files` or `rFactor 2` folder, otherwise it may fail to run.
>
> See [Frequently Asked Questions](https://github.com/TinyPedal/TinyPedal/wiki/Frequently-Asked-Questions) for common issues, and [User Guide](https://github.com/TinyPedal/TinyPedal/wiki/User-Guide) for usage info.
>
> For Linux user, please follow [Running on Linux](#running-on-linux) section for instruction.

1. Download latest TinyPedal version from [Releases](https://github.com/TinyPedal/TinyPedal/releases) page, extract it into a clean folder, and run `tinypedal.exe`.

2. A tray icon will appear at system tray. If not shown, check hidden tray icon. `Right Click` on tray icon will bring up context menu.

3. Launch game, overlay will appear once vehicle is on track, and auto-hide otherwise. Auto-hide can be toggled On and Off by clicking `Auto Hide` from tray menu.

4. Overlay can be Locked or Unlocked by clicking `Lock Overlay` from tray menu. While Unlocked, click on overlay to drag around.

5. Widgets can be Enabled or Disabled from `Widget` panel in main window. `Right Click` on tray icon and select `Config` to show main window if it is hidden.

6. To quit APP, `Right Click` on tray icon and select `Quit`; or, click `Overlay` menu from main window and select `Quit`.

## Run from Source

### Dependencies:
* [Python](https://www.python.org/) 3.10 or higher
* PySide6 (Qt 6)
* pyLMUSharedMemory
* pyRfactor2SharedMemory
* psutil

### Download source code

#### Method 1

Download TinyPedal source code from [Releases](https://github.com/TinyPedal/TinyPedal/releases) page; or click `Code` button at the top of repository and select `Download ZIP`.

Download submodule source code from following links:
- pyLMUSharedMemory: https://github.com/TinyPedal/pyLMUSharedMemory
- pyRfactor2SharedMemory: https://github.com/TinyPedal/pyRfactor2SharedMemory

Extract TinyPedal source code ZIP file. Then extract submodule ZIP files and put them in corresponding folder in the root folder of TinyPedal.

#### Method 2

Use [Git](https://git-scm.com/) tool and run following command to clone TinyPedal source code alongside required submodules:
```
git clone --recursive https://github.com/TinyPedal/TinyPedal.git
```

To update submodules, run command:
```
git submodule update --init
```

Since `master` branch is the development branch, it may not be stable for normal use. You may switch to specific released version instead, such as `v2.45.0`, run command:
```
git checkout tags/v2.45.0
```

And to switch back to development branch, run:
```
git checkout master
```

### Setup development environment

It is recommended to setup an isolated development environment for running and testing code, especially useful if multiple different versions of Python are installed.

To start, make sure required Python version was installed. Python `3.12` is used in this example.

First, we need to create a [Python virtual environment](https://docs.python.org/3/library/venv.html). On windows, run following command in `Powershell` from project root folder:

```
py -3.12 -m venv .venv
```

Then run following command to activate this virtual environment:

```
.venv\Scripts\activate.ps1
```

Once activated, you can continue with [Install dependencies](#install-dependencies) section to install required package for this virtual environment, and running or building TinyPedal inside this virtual environment.

Finally, remember to activate this virtual environment (if haven't already) before installing packages or running the code.

### Install dependencies

Install additional dependencies by using command:
```
pip install -r requirements.txt
```

To start TinyPedal, type command from project root folder:
```
python run.py
```

To install development tools (linter, type checker, tests with coverage), and run checks:
```
pip install -r requirements-dev.txt
ruff check .
mypy tinypedal
pytest --cov=tinypedal
```

Optional: run checks automatically before each commit with `pre-commit install`.
For reproducible builds, `requirements-lock.txt` pins the tested versions.

After adding options or editing documentation, regenerate French option names and tooltips:
```
python tools/gen_fr_options.py  # writes tinypedal/i18n/data/fr_options.json
python tools/gen_option_help.py  # writes tinypedal/i18n/data/option_help.json
```

## Build Executable for Windows

Executable file can be built with [PyInstaller](https://pyinstaller.org).

To install PyInstaller, run command:
```
pip install pyinstaller
```

To build executable file, run command:
```
python build_pyinstaller.py
```

After building completed, executable file can be found in `dist\TinyPedal` folder.

To build Windows installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then run command (replace version):
```
iscc /DAppVersion=2.50.0 installer\tinypedal.iss
```

Installer is saved in `dist` folder. It installs for current user in `%LOCALAPPDATA%\Programs\TinyPedal` (no admin rights needed), keeps presets and user data when updating, and can be uninstalled from Windows settings. Installed version can download and install new releases from notification bar (`Download And Install`), after verifying installer SHA256 hash.

## Running on Linux

The procedure described in the [Run from Source](#run-from-source) section is mostly valid,
except some differences in the dependencies, and that no executable can be
built. The differences are explained here.

Configuration and data files will be stored in the defined user-specific
directories, default to:
```
$HOME/.config/TinyPedal/
$HOME/.local/share/TinyPedal/
```

The required Python packages are `PySide6`, `psutil` and `pyxdg`. Most distros
name the package with a prefix, like `python3-pyside6`, `python3-psutil` and
`python3-pyxdg`.

Some distros split `PySide6` in subpackages. If you don't find
`python3-pyside6` then you should install `python3-pyside6.qtgui`,
`python3-pyside6.qtwidgets` and `python3-pyside6.qtmultimedia`.

Alternatively, you can install them using `pip` but this will bypass your
system package manager and it isn't the recommended option. The command to
install the dependencies with this method is:
```
pip install -r requirements.txt pyxdg
```

To start TinyPedal type the following command:
```
./run.py
```

### Installation

Once you have a working instance of TinyPedal, created using the git command or
by unpacking the Linux release file, you can run the install script to install
or update TinyPedal on your system.

The install script will create a desktop launcher and will make `TinyPedal`
available as a command from the terminal.

The files will be installed at the `/usr/local/` prefix. You'll need
appropriate permissions to write there, for example, by using `sudo`.

You can run the script as (it doesn't support any arguments or options):
```sh
sudo ./install.sh
```

If you need persistent launch arguments (for example, to write log to file), create
`~/.config/TinyPedal/launcher.conf` with:

```sh
TINYPEDAL_RUN_ARGS="--log-level 2"
```

The installed launcher and desktop entry will read this file automatically.

### Known issues

- Some features may not be available on Linux currently.
- Widgets don't appear over the game window in KDE. Workaround: enable `Bypass Window Manager` option in `Compatibility` dialog from `Config` menu in main window.
- Transparency of widgets doesn't work when desktop compositing is disabled. Workaround: enable `window manager compositing` in your Desktop Environment.

## Contributing

Please follow [Contributing Guidelines](CONTRIBUTING.md) for how to report issue, request feature, or contribute code.

## License

Copyright (C) 2022-2026 TinyPedal developers

TinyPedal is free software and licensed under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. TinyPedal is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY. See [LICENSE.txt](./LICENSE.txt) for more info.

TinyPedal icon, as well as image files located in `images` folder, are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

Licenses and notices file for third-party software are located in `docs\licenses` folder, see [THIRDPARTYNOTICES.txt](./docs/licenses/THIRDPARTYNOTICES.txt) file for details.

## Credits

See [docs\contributors.md](./docs/contributors.md) file for full list of developers and contributors.
