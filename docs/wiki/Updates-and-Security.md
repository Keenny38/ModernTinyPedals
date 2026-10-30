# Updates and Security

## In-app updates

The app checks GitHub for a new release at startup (`check_for_updates_on_startup` in `Settings` > `Application`, on by default), then again every 12 hours while it runs (`number_of_hours_between_update_checks`, `0` = startup only; never while driving). Check by hand any time with `Help` > `Check for Updates`, or the update button of the `Home` page.

### When an update is available

- A notice appears in the main window. Click it for its menu: `Download And Install`, `What's New`, `View Updates On GitHub`, `Skip This Version` and `Dismiss` (`Cancel Download` while downloading).
- With the Windows installed version, the **What's New** page of the new version opens once, with `Install Now` and `Later`.
- If the app is hidden in the tray (or minimized), it never pops up over your game: a tray message tells you about the update, and the What's New page waits inside the app.
- A version found by the check every 12 hours opens What's New only if the main window is the active window; otherwise the notice waits in the window (or a tray message tells you). A notice you dismissed does not come back for the same version.

### What's New page

- Shows the version, its release date and the release notes as they are written: groups (`New`, `Improvements`, `Fixes`...), one card per topic, bullets with their sub-bullets, and the screenshots of the changelog in their card (space kept while they load, decoded at the shown size; click one for the viewer: arrows browse the others, `Esc` closes). Before / after visuals and technical details (commits, SHA-256 checksums) are folded at the end.
- Skipped versions: when you skipped updates, the notes of every version since the installed one follow (newest first, up to 12), each with its header; the chips at the top jump to a version (or to a group when one version is shown).
- `Search the notes` (`Ctrl+F`) keeps only the cards with every word typed, accents and case ignored, technical details included.
- The version menu (top right) shows the notes of any older version, from the changelog shipped with the app (offline).
- Option names written in the notes (`show_apex_speed`) are links: a click opens that option (the overlay of the card first, `Find Option` when several overlays have it). A topic naming an overlay offers `Try <overlay>` (turns it on in the loaded preset, `Undo` in the message shown after), then `Options: <overlay>`.
- The notes are in the app language: French notes come from `CHANGELOG.fr.md` at the release tag, English notes from the GitHub release. When a translation is missing, the English notes are shown.
- Buttons: `View On GitHub`, `Skip This Version` (both in a `⋯` menu when the window is narrow), `Later` (or `Close`) and `Install Now` (or `Download And Install`), which always keep their text.
- The notes of the version you have installed are always available offline: `What's New` button on the `Home` page.
- After an update, the page opens once at the first start of the new version, with the notes of every version since the one you ran before (`show_release_notes_after_update`, also the `Show after each update` switch under the page title). Not at the very first start, nor when an older copy is started.

### Download and install

`Download And Install` (or `Install Now`) shows the progress (percent and size) in the notice and on the What's New page. `Cancel Download` stops it and removes the partial file. Then the updater:

1. downloads `NeoPedal-<version>-setup.zip` from GitHub, into a new private temporary folder. Every request and every redirect goes to a GitHub address over HTTPS (`github.com`, `api.github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`, `raw.githubusercontent.com`): a redirect anywhere else, or to plain HTTP, is refused;
2. checks its **SHA-256** and size, and refuses a file that does not match. For the official repository, the expected values come from the **signed release manifest** (see below), never from GitHub alone. For a custom update repository: the digest GitHub gives for the file, else the `### SHA256` list at the end of the release notes (nothing else of the notes is read);
3. extracts the installer from the ZIP, read through the same open file as a second SHA-256 check (the installer itself is checked against the manifest too);
4. checks the installer's **Authenticode signature** when it is signed, and refuses an invalid signature. An unsigned installer is accepted (and logged) only from the official repository, because its manifest was verified. With a custom update repository, the installer must be signed by a certificate that is not revoked (checked online, see below), and you are always asked first, with the repository and the signer name shown. The repository checked is the one the update was found in, even if the setting changed since;
5. runs the installer silently: it closes the app, updates it and starts it again. Your presets and data are kept. From its last checks until it is started, the installer file is held open so that no other program can change, replace or delete it: its SHA-256 and signature are checked again through that open file, then it is started from it.

The downloaded installer and its folder are deleted when you decline the install or when it fails to start.

### Signed releases

Since 0.28, every official release has a **signed manifest**: `NeoPedal-<version>-manifest.json` lists the SHA-256 and size of each release file, with the repository, tag and version, and `NeoPedal-<version>-manifest.json.sig` is its Ed25519 signature. The signing key is a secret of the release workflow; the app holds the public key. The app offers and installs an official update only when:

- the manifest is signed by the release key;
- it is for this repository, this tag and this version, and that version is newer than the one you run;
- the downloaded files match its SHA-256 and sizes.

Otherwise the update is refused: the notice says `Update Refused: v<version> Has No Valid Signature` and the log says why. Someone who could publish a release on GitHub (stolen access token, altered workflow run) still cannot get an installer onto your computer without the signing key. Apps before 0.28 do not read the manifest: they update to the first signed release as before, and from then on require it.

With a custom update repository (`update_repository`, a fork for example), no manifest is required, but the installer must be Authenticode-signed. Revocation of its certificate chain is checked online: if the revocation servers cannot be reached, the update is refused (`Revocation of the installer signing certificate could not be checked`); try again later. The installer is never trusted without that check, as a custom repository has no other proof of who published it.

Running from source on Windows, the update installs the Windows app the same way: it updates your installed copy (folder found from the installer registry entry, else from the `NeoPedal` Start menu shortcut), or installs it if there is none, then the installed app starts. The source folder itself is not changed: update it with `git pull`.

Apps up to 0.19 download `NeoPedal-<version>-windows-setup.exe` instead and check it against its `.sha256` file. Release 0.20.0 has neither: these apps update from the app again from 0.20.1 on.

The SHA-256 check detects a corrupt or altered download. For the official repository, the signed manifest also proves that the file comes from the release workflow holding the signing key; the build provenance attestation (see below) proves the commit it was built from.

### Skip a version

`Skip This Version` hides the notice of that version: it is not shown again at startup, but a newer version is. `Help` > `Check for Updates` still shows the skipped version.

### When the app cannot install the update

- **Running from source on Linux**: `Download And Install` opens the download in your browser. Update your source folder instead (`git pull`, or a new `-source.zip`).
- **Portable copy** (ZIP from releases up to 0.19): the app opens the releases page. Turn it into an installed copy once: see [Moving from a portable copy](Installation.md#moving-from-a-portable-copy).

To turn update checks off, uncheck `check_for_updates_on_startup`. `number_of_hours_between_update_checks` set to `0` keeps the check at startup only. `update_repository` (default `Keenny38/ModernTinyPedals`) sets the GitHub repository checked; an empty value disables checks. Since 0.23.0 the check also follows GitHub redirects, so updates keep working if the repository is renamed later.

## Release files

Every release on the [Releases page](https://github.com/Keenny38/ModernTinyPedals/releases) has these files (0.20.0 only has the two ZIP files):

| File | Content |
|---|---|
| `NeoPedal-<version>-windows-setup.exe` | The Windows installer |
| `NeoPedal-<version>-windows-setup.exe.sha256` | Its SHA-256 (`sha256sum` format), checked by the updater of apps up to 0.19 |
| `NeoPedal-<version>-setup.zip` | The same installer, zipped: downloaded by the app updater since 0.20 |
| `NeoPedal-<version>-source.zip` | The source code with its version number set, for Linux or running from source |
| `NeoPedal-<version>-manifest.json` | SHA-256 and size of the four files above, with repository, tag and version (since 0.28) |
| `NeoPedal-<version>-manifest.json.sig` | Ed25519 signature of the manifest (base64), checked by the app updater since 0.28 |

Releases up to 0.22.4 named these files `ModernTinyPedals-<version>-…`. Older apps find the installer by the end of its name (`-setup.zip`, `-windows-setup.exe`), so they still update to the renamed files.

GitHub also adds its own automatic `Source code` archives to every release. They are not built by the release workflow and are not covered by the checksums and attestations: prefer `-source.zip`.

Releases are built and published by GitHub Actions from the code of the repository, with nothing added by hand. The Windows executable is started in a self-test mode before publishing: if a module, data file, QML page or worker process fails, nothing is published. Release notes start with the changelog of the version, then list its commits (**Added**, **Fixed**, **Changed**) and the SHA-256 of every file.

## Verifying a download

### SHA-256 checksum

Compare the checksum of your file with the SHA256 list at the end of the release notes. GitHub also shows a `sha256:` digest next to each file of the release.

Windows (PowerShell):

```powershell
Get-FileHash .\NeoPedal-<version>-windows-setup.exe -Algorithm SHA256
```

Linux:

```bash
sha256sum NeoPedal-<version>-source.zip
```

### Build provenance attestation

Every release file has a signed **build provenance attestation**: proof that the file was built by the `Build and Release` workflow of this repository, from a commit of this repository. Verify it with the [GitHub CLI](https://cli.github.com/):

```bash
gh attestation verify NeoPedal-<version>-windows-setup.exe --repo Keenny38/ModernTinyPedals
```

```bash
gh attestation verify NeoPedal-<version>-source.zip --repo Keenny38/ModernTinyPedals
```

Attestations exist from version 0.20.0.

### Signed manifest

Since 0.28, check the release files against the signed manifest, as the app updater does. Put the downloaded files and both manifest files in one folder, then, from a source folder of the app (with `cryptography` installed):

```bash
python tools/sign_release.py <version> --dist <folder> --verify
```

It checks the signature with the public key of the app and the SHA-256 and size of each file present. Or with OpenSSL 3, using the release public key:

```text
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAIXQf44dlh0E9y51KulqUIhaLV93FqR3KzQc2gQNNSR8=
-----END PUBLIC KEY-----
```

```bash
base64 -d NeoPedal-<version>-manifest.json.sig > manifest.sig
openssl pkeyutl -verify -pubin -inkey release-key.pem -rawin -in NeoPedal-<version>-manifest.json -sigfile manifest.sig
```

Then compare the `sha256` values of the manifest with the checksums of your files.

### Signature

When a release is code-signed, right-click the installer > `Properties` > `Digital Signatures` to check it. Unsigned installers can trigger a SmartScreen warning: see [Installation](Installation.md#smartscreen-warning).

### Immutable releases

Once published, a release cannot be modified: its files and tag stay as they were built.

## How the project protects releases

- Workflow actions are pinned by commit SHA and updated by Dependabot, with a 7-day cooldown before a new version is proposed.
- Release builds install every package and dependency (also those of PyInstaller and openvr) from hash-pinned lock files (`requirements-build-lock.txt`, `requirements-sign-lock.txt`), wheels only, with `pip install --require-hashes --no-deps`: a package file changed on PyPI is refused. Inno Setup is installed at a pinned version when the runner does not have it. Pull requests that add a dependency with a known vulnerability fail the dependency review.
- The pre-commit hooks are pinned to commit SHAs.
- `master` refuses force pushes and deletion; pull requests must pass the `Checks` workflow. Release tags `v*` cannot be moved or deleted.
- Signing secrets are only available to the `release` environment, open to `master` only. The release manifest is signed in the publishing job, which installs nothing but its hash-pinned signing package: the build job never sees the manifest signing key.

## Security of app features

- **Game access**: the app reads game data. Commands are sent to the game only on an explicit action of yours (opening a replay, moving the camera, or the camera cuts of the [Broadcast Director](Broadcast-Director.md) once you put it in `Automatic` mode).
- **Remote control** listens on `127.0.0.1` only and requires an `X-NeoPedal` header, so web pages cannot send commands. Turn on `enable_access_token` so that other programs and other Windows accounts of this computer cannot use it either. See [Connections](Connections.md#remote-control).
- **Web dashboard** is off by default, requires an access code (8 characters at least), is limited to this computer unless you allow LAN access, refuses code guesses from other web sites and DNS rebinding, and can use HTTPS. See [Connections](Connections.md#web-dashboard).
- **Online ranks** (`enable_online_driver_ranks`, on by default): the Steam session ticket of the running game, and the names of the drivers of an online session, are sent to raceos.gg (RaceControl, the online service of Le Mans Ultimate, a third party) to read Driver and Safety Ranks, the way the game menu does. Nothing is saved, and nothing is sent when the option is off (`Settings` > `Application` > `Online`). See [Overlays](Overlays.md).
- **Plugins** run as normal Python code with full access to your computer: only install plugins you trust. Plugin ZIP files are checked before install (paths, code run). Trust covers every file of the plugin folder, and a plugin holding native code files (`.pyd`, `.dll`, `.so`, `.pth`) is never installed nor loaded.
- **Language packs** shared by others cannot freeze the app (message rules that could take very long are left out) nor add links or pictures to dialogs (texts with formatting tags their English text does not have are left out).
- **Bug reports** (`Help` > `Create Bug Report…`) remove your user folder name (short `C:\Users\NAME~1` form too), access codes, repository names, local network & IPv6 addresses and team driver names from the files they collect.

## Reporting a vulnerability

**Do not open a public issue** for a security problem: it would be visible to everyone before it is fixed.

Use GitHub private vulnerability reporting: [Report a vulnerability](https://github.com/Keenny38/ModernTinyPedals/security/advisories/new) (repository `Security` tab). Only you and the maintainer see the report. Include:

- the app version (`Help` > `About`), your system and game;
- what the vulnerability allows, and to whom (another program on the PC, a device on the local network, a website, an imported file...);
- steps to reproduce it, with an example file or script if possible.

Only the latest release receives fixes: check that the problem still exists in it. The project is maintained on free time; expect an answer within about 7 days. A confirmed vulnerability is fixed in a new release, then described in a security advisory, with your name if you wish.

In scope: the app and its overlays, the web dashboard and command server, the updater, file imports (presets, laps, MoTeC), plugins, the Windows installer and the release build chain. Full policy: [SECURITY.md](https://github.com/Keenny38/ModernTinyPedals/blob/master/SECURITY.md).
