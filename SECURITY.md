# Security policy

## Supported versions

Only the latest version published on the [Releases](https://github.com/Keenny38/NeoPedal/releases/latest) page receives fixes. Check that the problem still exists in that version before reporting it.

## Reporting a vulnerability

**Do not open a public issue** for a security vulnerability: everyone would see it before it is fixed.

Use GitHub private reporting: `Security` tab of the repository, then [`Report a vulnerability`](https://github.com/Keenny38/NeoPedal/security/advisories/new). Only you and the maintainer can see the report.

Include:

- the app version (`Help > About`), your system and the game;
- what the vulnerability allows, and to whom (another program on the PC, a device on the local network, a website, an imported file…);
- the steps to reproduce it, with a sample file or script if possible.

The project is made in spare time: expect an answer within 7 days in general. A confirmed vulnerability is fixed in a new version, then described in a security advisory (`Security > Advisories`), with your name if you wish.

In scope: the app and its overlays, the web dashboard and the command server, the automatic update, file imports (presets, laps, MoTeC), plugins, the Windows installer and the release build chain.

## Verifying a download

Every release is built and published by GitHub Actions from the code of this repository, with no file added by hand. A release has the Windows installer `NeoPedal-<version>-windows-setup.exe` (with its `.sha256` file, and zipped as `NeoPedal-<version>-setup.zip`) and `NeoPedal-<version>-source.zip`.

- **SHA-256**: the hash of each file is listed in the release notes, and shown by GitHub next to each file.
- **Signed manifest** (since 0.28.0): `NeoPedal-<version>-manifest.json` lists the SHA-256 and size of each release file, with repository, tag and version; `NeoPedal-<version>-manifest.json.sig` is its Ed25519 signature, made by the release workflow with a key kept in the protected `release` environment. The app updater installs an official release only if this signature is valid, the manifest matches the release and is newer than the running app, and the downloaded files match it; it also checks the installer's Authenticode signature when present. Check it yourself with `python tools/sign_release.py <version> --dist <folder> --verify` (source folder of the app), or with OpenSSL 3 and the release public key `MCowBQYDK2VwAyEAIXQf44dlh0E9y51KulqUIhaLV93FqR3KzQc2gQNNSR8=` (PEM body):

  ```bash
  base64 -d NeoPedal-<version>-manifest.json.sig > manifest.sig
  openssl pkeyutl -verify -pubin -inkey release-key.pem -rawin -in NeoPedal-<version>-manifest.json -sigfile manifest.sig
  ```

- **Build provenance attestation** (since 0.20.0): signed proof that the file was built by the `Build and Release` workflow from a commit of this repository. The installer and both ZIP files are attested. With [GitHub CLI](https://cli.github.com/):

  ```bash
  gh attestation verify NeoPedal-0.20.1-windows-setup.exe --repo Keenny38/NeoPedal
  ```

  ```bash
  gh attestation verify NeoPedal-0.20.0-windows-setup.exe --repo Keenny38/NeoPedal
  ```

- **Immutable releases**: once published, a release can no longer be changed (files and tag).

More in the [Updates and security](https://github.com/Keenny38/NeoPedal/wiki/Updates-and-Security) wiki page.

## Français

Signale une faille en privé avec le [signalement privé de GitHub](https://github.com/Keenny38/NeoPedal/security/advisories/new), jamais dans une issue publique. Seule la dernière version reçoit des correctifs. Les fichiers d'une release se vérifient avec `gh attestation verify <fichier> --repo Keenny38/NeoPedal`. Depuis la 0.28.0, l'app n'installe une mise à jour officielle que si son manifeste signé (`NeoPedal-<version>-manifest.json` et sa signature `.sig`) est valide.
