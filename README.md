# Modern Tiny Pedals

**Overlay de télémétrie pour Le Mans Ultimate et rFactor 2**, libre et gratuit. Une centaine de widgets configurables (pneus, freins, carburant, delta, classement, radar, météo…), des outils d'analyse et une interface en français.

Modern Tiny Pedals est une version modernisée de [TinyPedal](https://github.com/TinyPedal/TinyPedal) : même base solide, avec une nouvelle interface, de nouveaux outils et beaucoup de travail sur la fiabilité.

[Télécharger](https://github.com/Keenny38/overlays/releases/latest) ·
[Démarrage rapide](#démarrage-rapide) ·
[Nouveautés](#ce-que-cette-version-apporte) ·
[Guide des réglages](docs/customization.md) ·
[Changelog](CHANGELOG.md) ·
[Feuille de route](docs/ROADMAP.md)

![Aperçu](https://user-images.githubusercontent.com/21177177/282278970-b806bf02-a83d-4baa-8b45-0ca10f28f775.png)

---

## Démarrage rapide

1. **Télécharge** `ModernTinyPedals-<version>-windows-setup.exe` sur la page [Releases](https://github.com/Keenny38/overlays/releases/latest) et lance-le. Pas besoin de droits administrateur : l'app s'installe dans ton profil (`%LOCALAPPDATA%\Programs\Modern Tiny Pedals`).
2. **Prépare le jeu** : mode d'affichage `Sans bordure` ou `Fenêtré` (le plein écran exclusif cache l'overlay), puis le réglage de ton jeu ci-dessous.
3. **Au premier lancement**, l'assistant te demande la langue, le jeu, le thème et les widgets de départ.
4. **Lance une session** : l'overlay apparaît dès que la voiture est en piste et se cache sinon.

Ensuite :

- **Déplacer les widgets** : déverrouille l'overlay (menu de l'icône dans la zone de notification > `Verrouiller l'overlay`) puis fais-les glisser, ou utilise `Outils > Éditeur de disposition` sur une capture du jeu.
- **Régler un widget** : onglet `Widgets` de la fenêtre principale, ou `Ctrl+F` pour chercher une option par son nom.
- **Mises à jour** : l'app te prévient d'une nouvelle version et peut la télécharger et l'installer (`Télécharger et installer`).

Une version ZIP portable existe aussi. Ne l'extrais pas dans `Program Files` ni dans le dossier du jeu : l'app enregistre ses réglages à côté de l'exécutable.

### Réglage du jeu

| Jeu | Windows | Linux |
|---|---|---|
| **Le Mans Ultimate** | Rien à installer. Active `Paramètres > Gameplay > Activer les plugins`. | Nécessite un plugin tiers, voir [cette discussion](https://github.com/TinyPedal/TinyPedal/issues/9). |
| **rFactor 2** | Plugin [rF2SharedMemoryMapPlugin](https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin#download). | [Version Wine du plugin](https://github.com/schlegp/rF2SharedMemoryMapPlugin_Wine/blob/master/build). |

Pour rFactor 2 : copie `rFactor2SharedMemoryMapPlugin64.dll` dans `rFactor 2\Bin64\Plugins` (crée le dossier s'il manque), active-le dans `Paramètres > Gameplay > Plugins`, puis redémarre le jeu. Si le plugin n'apparaît pas, installe le runtime `Visual C++ 2013` fourni dans `Support\Runtimes` du jeu.

## Ce que cette version apporte

**Interface**
- Interface Qt 6 modernisée, en français ou en anglais (changement à chaud), avec noms et bulles d'aide des options traduits.
- Assistant de premier lancement, recherche globale d'option (`Ctrl+F`), aperçu en direct des widgets, annuler/rétablir dans les éditeurs.
- Style d'overlay moderne : thèmes (sombre, contraste élevé, adapté au daltonisme, classique), éditeur de thèmes, thème par widget.
- Éditeur de disposition avec guides d'alignement et magnétisme.

**Widgets et données**
- Widget **Black box** : pneus, freins, suspensions, dégâts, jauges carburant et énergie, enregistreur d'incidents.
- Enregistreur de tours et visionneuse de télémétrie (superposer deux tours), export **MoTeC `.ld`**.
- **Rejeu de télémétrie** : enregistre une session LMU et rejoue-la dans tous les widgets, sans lancer le jeu.

**Connexions**
- Contrôle à distance pour Stream Deck, Companion ou SimHub, et flux de télémétrie en direct par WebSocket.
- Tableau de bord web pour téléphone ou tablette, avec code d'accès et HTTPS en option.
- Overlay SteamVR expérimental.

**Fiabilité**
- Installeur Windows et mises à jour vérifiées (SHA-256) depuis l'app.
- Sauvegardes automatiques des presets, écriture de fichiers atomique, redémarrage automatique des threads plantés.
- Plugins de widgets avec gestionnaire, rapport de bug en un clic, moniteur de performance.
- Plus de 800 tests automatisés, vérification de types et lint en intégration continue.

Tout est détaillé dans le [guide des réglages](docs/customization.md), et chaque changement dans le [changelog](CHANGELOG.md).

## Lancer depuis le code source

Nécessite [Python](https://www.python.org/) 3.10 ou plus récent.

```bash
git clone https://github.com/Keenny38/overlays.git
```

```bash
cd overlays
```

Crée un environnement virtuel, active-le, puis installe les dépendances (PySide6, psutil, cryptography) :

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

Les bibliothèques de mémoire partagée (`pyLMUSharedMemory`, `pyRfactor2SharedMemory`) sont incluses dans le dépôt : pas de sous-module à récupérer. Pour des versions exactes testées, utilise `requirements-lock.txt`.

### Développement

```bash
pip install -r requirements-dev.txt
```

Contrôles lancés en intégration continue (et avant chaque commit avec `pre-commit install`) :

```bash
ruff check .
```

```bash
mypy tinypedal
```

```bash
pytest --cov=tinypedal
```

Le benchmark des widgets se lance à part avec `pytest -m benchmark`.

Après avoir ajouté des options ou modifié la documentation, régénère les libellés et les bulles d'aide :

```bash
python tools/gen_fr_options.py
```

```bash
python tools/gen_option_help.py
```

Le second script signale les bulles d'aide qui n'ont pas encore de traduction française (`tinypedal/i18n/data/fr_option_help.json`).

### Changelog automatique

`CHANGELOG.md` est régénéré depuis l'historique Git à chaque push sur `master` (workflow `Changelog`), et chaque release reprend les commits depuis la précédente comme notes de version. Il suffit d'écrire des titres de commit clairs : ceux qui commencent par `Add` vont dans **Added**, `Fix` dans **Fixed**, le reste dans **Changed**. Pour voir le résultat en local :

```bash
python tools/gen_changelog.py
```

### Compiler pour Windows

```bash
pip install pyinstaller
```

```bash
python build_pyinstaller.py
```

L'exécutable est créé dans `dist\TinyPedal`. Pour l'installeur, installe [Inno Setup 6](https://jrsoftware.org/isinfo.php) puis (en remplaçant la version) :

```bash
iscc /DAppVersion=2.50.0 installer\tinypedal.iss
```

Pour publier une version, augmente `__version__` dans `tinypedal/version.py`, pousse, puis lance le workflow `Build and Release` depuis l'onglet Actions de GitHub. Il crée la release avec le ZIP, l'installeur, son fichier `.sha256` et les notes de version.

> Le nom affiché est « Modern Tiny Pedals », mais le nom interne reste `TinyPedal` (dossier de configuration `%APPDATA%\TinyPedal`, `tinypedal.exe`, en-tête `X-TinyPedal` du contrôle à distance), pour garder les réglages existants et la compatibilité des outils.

## Linux

Lance l'app depuis le code source comme ci-dessus (pas d'exécutable). Paquets nécessaires : `PySide6`, `psutil`, `cryptography` et `pyxdg`, par exemple `python3-pyside6`, `python3-psutil`, `python3-cryptography`, `python3-pyxdg` selon ta distribution. Certaines distributions découpent PySide6 : installe alors `python3-pyside6.qtgui`, `python3-pyside6.qtwidgets` et `python3-pyside6.qtmultimedia`.

```bash
./run.py
```

Les réglages sont dans `$HOME/.config/TinyPedal/` et les données dans `$HOME/.local/share/TinyPedal/`.

Pour installer un lanceur et la commande `TinyPedal` dans `/usr/local/` :

```bash
sudo ./install.sh
```

Des arguments de lancement permanents se mettent dans `~/.config/TinyPedal/launcher.conf`, par exemple `TINYPEDAL_RUN_ARGS="--log-level 2"`.

Problèmes connus :
- Sous KDE, les widgets n'apparaissent pas au-dessus du jeu : active `Activer contourner le gestionnaire de fenêtres` dans `Config > Compatibilité`.
- La transparence ne marche pas sans compositing : active la composition de fenêtres de ton environnement de bureau.

## Contribuer

Signale un problème ou propose une idée dans les [issues](https://github.com/Keenny38/overlays/issues). Les règles de contribution sont dans [CONTRIBUTING.md](CONTRIBUTING.md), et ce qui reste à faire dans la [feuille de route](docs/ROADMAP.md).

## Licence et crédits

Modern Tiny Pedals est dérivé de [TinyPedal](https://github.com/TinyPedal/TinyPedal), Copyright (C) 2022-2026 TinyPedal developers. Voir [docs/contributors.md](docs/contributors.md) pour la liste des développeurs et contributeurs.

Logiciel libre sous licence [GNU GPL v3](LICENSE.txt) ou toute version ultérieure, distribué SANS AUCUNE GARANTIE. L'icône et les images du dossier `images` sont sous licence [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Les licences des logiciels tiers sont dans [docs/licenses](docs/licenses/THIRDPARTYNOTICES.txt).
