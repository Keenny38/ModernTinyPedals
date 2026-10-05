# Security policy

## Supported versions

Only the latest version published on the [Releases](https://github.com/Keenny38/ModernTinyPedals/releases/latest) page receives fixes. Check that the problem still exists in that version before reporting it.

## Reporting a vulnerability

**Do not open a public issue** for a security vulnerability: everyone would see it before it is fixed.

Use GitHub private reporting: `Security` tab of the repository, then [`Report a vulnerability`](https://github.com/Keenny38/ModernTinyPedals/security/advisories/new). Only you and the maintainer can see the report.

Include:

- the app version (`Help > About`), your system and the game;
- what the vulnerability allows, and to whom (another program on the PC, a device on the local network, a website, an imported file…);
- the steps to reproduce it, with a sample file or script if possible.

The project is made in spare time: expect an answer within 7 days in general. A confirmed vulnerability is fixed in a new version, then described in a security advisory (`Security > Advisories`), with your name if you wish.

In scope: the app and its overlays, the web dashboard and the command server, the automatic update, file imports (presets, laps, MoTeC), plugins, the Windows installer and the release build chain. A vulnerability that also exists in the original [TinyPedal](https://github.com/TinyPedal/TinyPedal) can be reported to both projects.

## Verifying a download

Every release is built and published by GitHub Actions from the code of this repository, with no file added by hand. A release has two files: `ModernTinyPedals-<version>-setup.zip` (the Windows installer) and `ModernTinyPedals-<version>-source.zip`.

- **SHA-256**: the hash of each file is listed in the release notes, and shown by GitHub next to each file. The app updater checks it before running the installer, and checks the installer signature when it is signed.
- **Build provenance attestation** (since 0.20.0): signed proof that the file was built by the `Build and Release` workflow from a commit of this repository. The installer inside `setup.zip` is attested too. With [GitHub CLI](https://cli.github.com/):

  ```bash
  gh attestation verify ModernTinyPedals-0.20.0-setup.zip --repo Keenny38/ModernTinyPedals
  ```

  ```bash
  gh attestation verify ModernTinyPedals-0.20.0-windows-setup.exe --repo Keenny38/ModernTinyPedals
  ```

- **Immutable releases**: once published, a release can no longer be changed (files and tag).

More in the [Updates and security](https://github.com/Keenny38/ModernTinyPedals/wiki/Updates-and-Security) wiki page.

## Français

Signale une faille en privé avec le [signalement privé de GitHub](https://github.com/Keenny38/ModernTinyPedals/security/advisories/new), jamais dans une issue publique. Seule la dernière version reçoit des correctifs. Les fichiers d'une release se vérifient avec `gh attestation verify <fichier> --repo Keenny38/ModernTinyPedals`.
