# Updates and Security

## In-app updates

The app checks GitHub for a new release at startup (once per start, `check_for_updates_on_startup` in `Config` > `Application`, on by default). Check by hand any time with `Help` > `Check for Updates`, or the update button of the `Home` page.

### When an update is available

- A notice appears in the main window. Click it for its menu: `Download And Install`, `What's New`, `View Updates On GitHub`, `Skip This Version` and `Dismiss` (`Cancel Download` while downloading).
- With the Windows installed version, the **What's New** page of the new version opens once, with `Install Now` and `Later`.
- If the app is hidden in the tray (or minimized), it never pops up over your game: a tray message tells you about the update, and the What's New page waits inside the app.

### What's New page

- Shows the version, its release date and one card per topic of the release notes. Technical details (commits, SHA-256 checksums) are folded: `Show Technical Details`.
- The notes are in the app language: French notes come from `CHANGELOG.fr.md` at the release tag, English notes from the GitHub release. When a translation is missing, the English notes are shown.
- Buttons: `View On GitHub`, `Skip This Version`, `Later` (or `Close`) and `Install Now` (or `Download And Install`).
- The notes of the version you have installed are always available offline: `Release Notes` button on the `Home` page.

### Download and install

`Download And Install` (or `Install Now`) shows the progress (percent and size) in the notice and on the What's New page. `Cancel Download` stops it and removes the partial file. Then the updater:

1. downloads `ModernTinyPedals-<version>-setup.zip` from GitHub;
2. checks its **SHA-256**, against the digest GitHub gives for the file, or else the SHA256 list of the release notes, and refuses a file that does not match;
3. extracts the installer from the ZIP;
4. checks the installer's **Authenticode signature** when it is signed, and refuses an invalid signature (an unsigned installer is accepted and logged);
5. runs the installer silently: it closes the app, updates it and starts it again. Your presets and data are kept.

Apps up to 0.19 download `ModernTinyPedals-<version>-windows-setup.exe` instead and check it against its `.sha256` file. Release 0.20.0 has neither: these apps update from the app again from 0.20.1 on.

The SHA-256 check detects a corrupt or altered download. As the checksum comes from the same release page, it does not prove who published the file: the build provenance attestation does (see below).

### Skip a version

`Skip This Version` hides the notice of that version: it is not shown again at startup, but a newer version is. `Help` > `Check for Updates` still shows the skipped version.

### When the app cannot install the update

- **Running from source** (Windows or Linux): `Download And Install` opens the download in your browser. Update your source folder instead (`git pull`, or a new `-source.zip`).
- **Portable copy** (ZIP from releases up to 0.19): the app opens the releases page. Turn it into an installed copy once: see [Moving from a portable copy](Installation.md#moving-from-a-portable-copy).

To turn update checks off, uncheck `check_for_updates_on_startup`. `update_repository` (default `Keenny38/ModernTinyPedals`) sets the GitHub repository checked; an empty value disables checks.

## Release files

Every release on the [Releases page](https://github.com/Keenny38/ModernTinyPedals/releases) has these files (0.20.0 only has the two ZIP files):

| File | Content |
|---|---|
| `ModernTinyPedals-<version>-windows-setup.exe` | The Windows installer |
| `ModernTinyPedals-<version>-windows-setup.exe.sha256` | Its SHA-256 (`sha256sum` format), checked by the updater of apps up to 0.19 |
| `ModernTinyPedals-<version>-setup.zip` | The same installer, zipped: downloaded by the app updater since 0.20 |
| `ModernTinyPedals-<version>-source.zip` | The source code with its version number set, for Linux or running from source |

GitHub also adds its own automatic `Source code` archives to every release. They are not built by the release workflow and are not covered by the checksums and attestations: prefer `-source.zip`.

Releases are built and published by GitHub Actions from the code of the repository, with nothing added by hand. The Windows executable is started in a self-test mode before publishing: if a module, data file, QML page or worker process fails, nothing is published. Release notes start with the changelog of the version, then list its commits (**Added**, **Fixed**, **Changed**) and the SHA-256 of every file.

## Verifying a download

### SHA-256 checksum

Compare the checksum of your file with the SHA256 list at the end of the release notes. GitHub also shows a `sha256:` digest next to each file of the release.

Windows (PowerShell):

```powershell
Get-FileHash .\ModernTinyPedals-<version>-windows-setup.exe -Algorithm SHA256
```

Linux:

```bash
sha256sum ModernTinyPedals-<version>-source.zip
```

### Build provenance attestation

Every release file has a signed **build provenance attestation**: proof that the file was built by the `Build and Release` workflow of this repository, from a commit of this repository. Verify it with the [GitHub CLI](https://cli.github.com/):

```bash
gh attestation verify ModernTinyPedals-<version>-windows-setup.exe --repo Keenny38/ModernTinyPedals
```

```bash
gh attestation verify ModernTinyPedals-<version>-source.zip --repo Keenny38/ModernTinyPedals
```

Attestations exist from version 0.20.0.

### Signature

When a release is code-signed, right-click the installer > `Properties` > `Digital Signatures` to check it. Unsigned installers can trigger a SmartScreen warning: see [Installation](Installation.md#smartscreen-warning).

### Immutable releases

Once published, a release cannot be modified: its files and tag stay as they were built.

## How the project protects releases

- Workflow actions are pinned by commit SHA and updated by Dependabot, with a 7-day cooldown before a new version is proposed.
- Release builds use pinned dependency versions (`requirements-build.txt`). Pull requests that add a dependency with a known vulnerability fail the dependency review.
- `master` refuses force pushes and deletion; pull requests must pass the `Checks` workflow. Release tags `v*` cannot be moved or deleted.
- Signing secrets are only available to the `release` environment, open to `master` only.

## Security of app features

- **Game access**: the app reads game data. Commands are sent to the game only on an explicit action of yours (opening a replay), never automatically.
- **Remote control** listens on `127.0.0.1` only and requires an `X-TinyPedal` header, so web pages cannot send commands. See [Connections](Connections.md#remote-control).
- **Web dashboard** is off by default, requires an access code, is limited to this computer unless you allow LAN access, and can use HTTPS. See [Connections](Connections.md#web-dashboard).
- **Plugins** run as normal Python code with full access to your computer: only install plugins you trust. Plugin ZIP files are checked before install (paths, code run).
- **Bug reports** (`Help` > `Create Bug Report...`) remove your user folder name, access codes and repository names from the files they collect.

## Reporting a vulnerability

**Do not open a public issue** for a security problem: it would be visible to everyone before it is fixed.

Use GitHub private vulnerability reporting: [Report a vulnerability](https://github.com/Keenny38/ModernTinyPedals/security/advisories/new) (repository `Security` tab). Only you and the maintainer see the report. Include:

- the app version (`Help` > `About`), your system and game;
- what the vulnerability allows, and to whom (another program on the PC, a device on the local network, a website, an imported file...);
- steps to reproduce it, with an example file or script if possible.

Only the latest release receives fixes: check that the problem still exists in it. The project is maintained on free time; expect an answer within about 7 days. A confirmed vulnerability is fixed in a new release, then described in a security advisory, with your name if you wish.

In scope: the app and its overlays, the web dashboard and command server, the updater, file imports (presets, laps, MoTeC), plugins, the Windows installer and the release build chain. A problem that also exists in the original [TinyPedal](https://github.com/TinyPedal/TinyPedal) can be reported to both projects. Full policy: [SECURITY.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/SECURITY.md).
