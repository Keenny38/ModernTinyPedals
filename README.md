# Modern Tiny Pedals

**Overlay de télémétrie pour Le Mans Ultimate et rFactor 2**, libre et gratuit. 78 widgets configurables (pneus, freins, carburant, delta, classement, radar, météo…), des outils d'analyse et une interface en français.

Modern Tiny Pedals est une version modernisée de [TinyPedal](https://github.com/TinyPedal/TinyPedal) : même base solide, avec une nouvelle interface, de nouveaux outils et beaucoup de travail sur la fiabilité.

[Télécharger](https://github.com/Keenny38/ModernTinyPedals/releases/latest) ·
[Démarrage rapide](#démarrage-rapide) ·
[Nouveautés](#ce-que-cette-version-apporte) ·
[Guide des réglages](docs/customization.md) ·
[Changelog](CHANGELOG.md) ·
[Feuille de route](docs/ROADMAP.md)

![Aperçu des 78 overlays (style modern) sur une course simulée à Road Atlanta](images/readme_preview.png)

---

## Démarrage rapide

1. **Télécharge** `ModernTinyPedals-<version>-windows-setup.exe` sur la page [Releases](https://github.com/Keenny38/ModernTinyPedals/releases/latest) et lance-le. Pas besoin de droits administrateur : l'app s'installe dans ton profil (`%LOCALAPPDATA%\Programs\Modern Tiny Pedals`).
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

> **Nouveau dans la 0.18.0** : **visionneuse de télémétrie** bien plus complète (repères A/B et statistiques de plage, tour idéal, canaux calculés comme le glissement des roues, panneaux 4 roues, lecture animée du tour, mode Direct, ouverture du replay au curseur, export en image) et **carte de trajectoire** enrichie (points de freinage, de corde et de sortie de chaque tour, coloration trajectoire, rapport ou altitude, temps des secteurs, blocages de roues, suivi des voitures pendant la lecture, grande carte). Les pages Qt Quick sont enfin **en français**. Détails dans le [changelog](CHANGELOG.md).

**Interface**
- Interface Qt 6 modernisée, en français ou en anglais (changement à chaud), avec noms et bulles d'aide des options traduits.
- Assistant de premier lancement, recherche globale d'option (`Ctrl+F`), aperçu en direct des widgets, annuler/rétablir dans les éditeurs.
- Tout s'ouvre dans la fenêtre de l'app : outils, éditeurs et réglages s'affichent comme des pages, avec un bouton `Fermer` pour revenir ; les outils de la barre de navigation sont des pages comme Widget ou Module (entrée surlignée, aucun bouton `Fermer`). Les pages d'outils laissées ouvertes se rouvrent au démarrage suivant, et l'app revient sur la dernière page affichée, même après un plantage.
- Barre de navigation personnalisable (clic droit > `Personnaliser la barre de navigation...`) : pages et outils au choix, dans l'ordre voulu ; les icônes gardent leur taille et la barre défile si la fenêtre est petite. `Alt+←` ou le bouton souris arrière revient à la page précédente.
- Liste des widgets avec filtre et pastille de couleur par catégorie, statut des plugins en badges.
- Style d'overlay moderne : thèmes (sombre, contraste élevé, adapté au daltonisme, classique), éditeur de thèmes, thème par widget, export et import de thèmes en fichier.
- Éditeur de disposition avec guides d'alignement et magnétisme, échelle globale de l'overlay, positions mémorisées par configuration d'écran.
- Affichage des widgets selon la session (essais, qualif, course) et le passage aux stands, avec fondu.
- Code de partage de preset : copier un preset en texte, l'importer avec un aperçu.

**Widgets et données**
- Widget **Black box** : pneus, freins, suspensions, dégâts, jauges carburant et énergie, enregistreur d'incidents, et pastilles ABS, TC, répartition de freinage et cartographie moteur entre les roues droites. Plages de pression cible saisies en kPa, psi ou bar. Aucun chevauchement : roues, disques et suspensions qui braquent et bougent gardent leur place.
- Enregistreur de tours et visionneuse de télémétrie en Qt Quick, dessinée par la carte graphique (zoom fluide et animé, tours regroupés par session, superposer plusieurs tours avec couleurs stables, écart à la référence au curseur, repères A/B et statistiques de plage, canaux calculés (glissement des roues, vitesse de braquage, carburant consommé, écart de température des pneus), panneaux 4 roues, bande min/max des tours, lissage, presets de voies, lecture animée du tour, mode Direct qui compare chaque nouveau tour au meilleur, replay ouvert au curseur, export en image, vrais numéros de virages des circuits LMU), carte de trajectoire (points de freinage, de corde et de sortie de chaque tour, coloration par tour, gain/perte, vitesse, pédales, trajectoire intérieur/extérieur, rapport ou altitude, temps des secteurs, blocages et patinage des roues, suivi des voitures pendant la lecture, carte qui suit le zoom, grande carte, orientation auto), cercle G avec enveloppe d'adhérence, export **MoTeC `.ld`**, import d'un journal MoTeC (celui de LMU par exemple) pour se comparer au tour d'un autre pilote (bibliothèque des tours importés : importer, rechercher, afficher, renommer, supprimer ; un `.ld` déposé sur l'app est importé directement), comparaison virage par virage (temps, vitesse mini, vitesses d'entrée et de sortie, rapport, pression de freinage, points de freinage et de plein gaz, freinage dégressif, roue libre, chevauchement des pédales, tour idéal, tri par temps perdu), trajectoire colorée selon le temps gagné ou perdu, courbe de gain/perte de temps, axe en temps, virages numérotés, export CSV pour Excel, tours gardés et notes par tour.
- **Visionneuse de carte de piste** refaite en Qt Quick : carte par secteurs dessinée par la carte graphique, vrais numéros de virages, courbe et pente à la position (rayon, cercle osculateur, angle, longueur), profil d'altitude, suivi de la position et parcours animé du circuit.
- **Calculateur de course** : carburant, énergie et pneus dans une seule page. Plan d'arrêts tour par tour (plein ou juste ce qu'il faut, pneus, pilote, durée de l'arrêt), course au temps calculée avec le temps passé aux stands (débit de ravitaillement, pneus, changement de pilote), marge de sécurité, arrêts obligatoires et relais max, effet du carburant, objectif d'économie, plan pneus relié aux relais avec propositions dans la limite des pneus autorisés, historique de consommation triable et effaçable, fichier plan de course à partager.
- Widget **Plan de course** : le prochain arrêt en jeu (tour, carburant et énergie à remettre, pneus, arrêts restants).
- **Statistiques pilote** : chiffres clés par circuit et comparaison de tes records aux temps de la communauté LMU (feuille d'[ohne_speed](https://www.youtube.com/@ohne_speed)), avec un niveau d'Alien à Hors rythme et l'écart au temps de référence.
- **Rejeu de télémétrie** : enregistre une session LMU ou rFactor 2 et rejoue-la dans tous les widgets, sans lancer le jeu.

**Connexions**
- Contrôle à distance pour Stream Deck, Companion ou SimHub, et flux de télémétrie en direct par WebSocket.
- Tableau de bord web pour téléphone ou tablette, avec code d'accès et HTTPS en option.
- Overlay SteamVR expérimental, et fenêtre miroir VR pour les jeux OpenXR (à afficher dans le casque avec OpenKneeboard, OVR Toolkit, XSOverlay ou Desktop+).

**Fiabilité**
- Installeur Windows et mises à jour vérifiées (SHA-256) depuis l'app.
- Sauvegardes automatiques des presets, écriture de fichiers atomique, redémarrage automatique des threads plantés.
- Plugins de widgets avec gestionnaire, rapport de bug en un clic, moniteur de performance.
- Plus de 1300 tests automatisés (85 % du code couvert), vérification de types et lint en intégration continue.

Tout est détaillé dans le [guide des réglages](docs/customization.md), et les nouveautés de chaque version dans le [changelog](CHANGELOG.md).

## Lancer depuis le code source

Nécessite [Python](https://www.python.org/) 3.10 ou plus récent.

```bash
git clone https://github.com/Keenny38/ModernTinyPedals.git
```

```bash
cd ModernTinyPedals
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

Le benchmark des widgets se lance à part avec `pytest -m benchmark`. La CI échoue si la couverture totale des tests passe sous le seuil `fail_under` de `pyproject.toml` (81 %).

L'intégration continue installe toujours les dernières versions de `ruff` et `mypy`. Si un contrôle échoue en CI alors qu'il passe chez toi, mets-les à jour :

```bash
pip install -U ruff mypy
```

Après avoir ajouté des options ou modifié la documentation, régénère les libellés et les bulles d'aide :

```bash
python tools/gen_fr_options.py
```

```bash
python tools/gen_option_help.py
```

Le second script signale les bulles d'aide qui n'ont pas encore de traduction française (`tinypedal/i18n/data/fr_option_help.json`).

Les pages Qt Quick (visionneuse de télémétrie, Track Map Viewer) sont en QML dans `tinypedal/ui/qml`, avec leur état dans `tinypedal/ui/quick` (Python pur, testable sans affichage). Courbes et cartes sont envoyées une seule fois à la carte graphique (`GpuShape`), le zoom ne fait que changer une matrice. Un nouveau module QML importé par une page doit être ajouté à `tinypedal/ui/quick/qml_modules.py` : l'exe n'embarque que ceux-là (un test charge les pages avec ces seuls modules). Les textes QML passent par `i18n.tr("...")` et `i18n.trm("...")` (traduits comme le reste de l'app, un test vérifie la page en français). Les numéros officiels des virages sont dans `tinypedal/userfile/track_corners.py`.

### Releases, mises à jour et changelog

Tout passe par les [Releases GitHub](https://github.com/Keenny38/ModernTinyPedals/releases), sans rien faire à la main : chaque push sur `master` publie une nouvelle version dès que les contrôles (`Checks`) passent.

- **Version** (`MAJEUR.MINEUR.CORRECTIF`, à partir de `0.10.0`) : calculée depuis les commits depuis la dernière release. Un titre qui commence par `Add` (nouveauté) monte la version mineure (`0.10.3` → `0.11.0`), tout le reste monte le correctif (`0.10.0` → `0.10.1`). Une version majeure se choisit à la main : lance `Build and Release` depuis l'onglet Actions avec `bump: major`.
- **Contenu** : le code source en ZIP, l'app compilée en ZIP, l'installeur Windows et son `.sha256`.
- **Changelog** : [`CHANGELOG.md`](CHANGELOG.md) décrit en français les nouveautés de chaque version (section `## X.Y.Z (date)`). Les notes de la release commencent par la section de sa version, puis listent ses commits en **Added**, **Fixed** et **Changed** : écris donc des titres de commit clairs, et ajoute la section de la prochaine version dans le changelog avant de pousser.
- **Visuels** : quand un commit change l'apparence d'un overlay, ajoute-lui une image avant/après dans `docs/changes`. Les notes de la release l'affichent dans une section **Visuals** (pas dans l'app, qui n'affiche pas les images).
- **Captures du changelog** : les captures d'une nouveauté (pages de l'app) vont dans `docs/changelog` et sont insérées dans `CHANGELOG.md` par leur adresse `raw.githubusercontent.com` (visibles sur GitHub et dans les notes de release ; la page `Nouveautés` de l'app ignore ces lignes).
- **Dans l'app** : la version installée voit la nouvelle release au démarrage, affiche ses notes dans la page `Nouveautés` (une carte par thème, commits et SHA256 repliés) et propose `Télécharger et installer` (dans le navigateur quand l'app ne peut pas s'installer seule, depuis le code source par exemple).

Pour prévisualiser en local la prochaine version et ses notes :

```bash
python tools/next_version.py
```

```bash
python tools/gen_release_notes.py v0.10.0
```

La version de l'app est indépendante de celle du format des réglages (`SETTING_VERSION` dans `tinypedal/version.py`, restée sur la numérotation TinyPedal 2.x), pour que les presets existants continuent de se charger sans migration inutile.

L'image d'aperçu de ce README est générée à partir des vrais widgets : `python tools/make_readme_preview.py`.

Pour l'image avant/après d'un overlay modifié (dernier commit à gauche, code en cours à droite), avant de commiter :

```bash
python tools/make_change_visual.py black_box --title "Black box : cartographie moteur"
```

`--set black_box.show_motor_map=true` montre une option désactivée par défaut, `--base` choisit la révision « avant ».

### Compiler pour Windows

```bash
pip install pyinstaller
```

```bash
python build_pyinstaller.py
```

L'exécutable est créé dans `dist\TinyPedal`. Le hook `tools/pyinstaller_hooks/hook-PySide6.QtQml.py` n'embarque que les modules QML utilisés (environ 2 Mo au lieu de 300 Mo avec WebEngine et 3D). Pour l'installeur, installe [Inno Setup 6](https://jrsoftware.org/isinfo.php) puis (en remplaçant la version) :

```bash
iscc /DAppVersion=0.10.0 installer\tinypedal.iss
```

Le workflow `Build and Release` signe l'exécutable et l'installeur si un certificat `.pfx` ou un compte Azure Artifact Signing est configuré dans les secrets et variables du dépôt (détail dans `.github/workflows/build-release.yml`), sinon il les publie sans signature.

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

Signale un problème ou propose une idée dans les [issues](https://github.com/Keenny38/ModernTinyPedals/issues). Les règles de contribution sont dans [CONTRIBUTING.md](CONTRIBUTING.md), et ce qui reste à faire dans la [feuille de route](docs/ROADMAP.md).

## Licence et crédits

Modern Tiny Pedals est dérivé de [TinyPedal](https://github.com/TinyPedal/TinyPedal), Copyright (C) 2022-2026 TinyPedal developers. Voir [docs/contributors.md](docs/contributors.md) pour la liste des développeurs et contributeurs.

Logiciel libre sous licence [GNU GPL v3](LICENSE.txt) ou toute version ultérieure, distribué SANS AUCUNE GARANTIE. L'icône et les images du dossier `images` sont sous licence [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Les licences des logiciels tiers sont dans [docs/licenses](docs/licenses/THIRDPARTYNOTICES.txt).
