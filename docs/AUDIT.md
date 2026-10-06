# Audit — TinyPedal 2.50.0 (fork modernisé)

> Ce fichier garde l'historique des audits et de ce qui a été fait. Ce qui reste à faire est dans [ROADMAP.md](ROADMAP.md).

Date : 27/09/2026 · Périmètre : tout le code `tinypedal/` (~60 000 lignes), `run.py`, build, CI.

Méthode :
- **ruff**, règles « bugs » (pyflakes, bugbear, pylint-erreurs, exceptions…) : 148 remarques, surtout du style.
- **mypy** (`--check-untyped-defs`) : 2 453 messages, triés à la main. La grande majorité est du bruit de typage (voir P3).
- **Revue manuelle ciblée** : threads, sauvegardes, calculs, chargement des fichiers, boucles bloquantes dans l'interface.
- **Rendu réel des 76 widgets** en classique et moderne, lancement de l'app, 120 tests automatisés.

Légende : ✅ corrigé dans ce fork · 🔴 grave · 🟠 moyen · 🟡 mineur · 💡 idée

---

## 1. Bugs corrigés

| # | Gravité | Problème | Correction |
|---|---|---|---|
| 1 | 🔴 ✅ | **L'app se fige quand on clique sur « Save ».** Si le thread de sauvegarde plante (ex. `RuntimeError: dictionary changed size during iteration`), `cfg.is_saving` reste bloqué à `True`. Huit dialogues attendent `while cfg.is_saving: sleep()` dans le thread de l'interface, et plus aucun réglage n'est sauvegardé jusqu'au redémarrage. | [setting.py](../tinypedal/setting.py) : verrou, `try/except`, erreur journalisée, état toujours remis à zéro. |
| 2 | 🔴 ✅ | **Blocage au rechargement ou à la fermeture si un module plante.** `closed` n'était jamais remis à `True`, et `module_control` attend `while not module.closed` sans fin. | [module/_base.py](../tinypedal/module/_base.py) : `try/finally` + journalisation du crash. |
| 3 | 🔴 ✅ | Même blocage possible avec les threads `overlay_control` et `hotkey_control` (`disable()` attend `_stopped`). | Petite fonction d'enveloppe `try/finally` dans les deux fichiers. |
| 4 | 🟠 ✅ | **Race condition : une demande de sauvegarde pouvait être perdue** (fenêtre entre « file vide » et `is_saving = False`). | Le contrôle et le changement d'état se font maintenant sous le même verrou. |
| 5 | 🟠 ✅ | **Fichiers de données corrompus ou perdus** : delta best, secteurs, carburant, consommation et carte étaient écrits directement dans le fichier final. Un crash, un disque plein ou un fichier verrouillé (OneDrive, antivirus) → fichier à moitié écrit, **meilleur tour réinitialisé**. L'exception tuait aussi le thread du module (delta figé). | Nouvelle fonction `atomic_write()` dans [userfile/\_\_init\_\_.py](../tinypedal/userfile/__init__.py) : fichier temporaire puis `os.replace`, erreur journalisée. |
| 6 | 🟠 ✅ | **Marqueur de safety car mal placé** sur `track_map` : l'interpolation partait de la fin du segment au lieu du début (décalage d'un segment). Division par zéro, donc crash du dessin, si deux points de la carte ont la même distance. | `distance_interp_coordinate` dans [calculation.py](../tinypedal/calculation.py). |
| 7 | 🟠 ✅ | `tri_coords_angle` : `acos()` recevait parfois une valeur à peine supérieure à 1 (erreur d'arrondi) → `ValueError: math domain error` dans l'éditeur de carte. | Valeur bornée à [-1, 1]. |
| 8 | 🟡 ✅ | `scale_elevation` / `scale_map` : division par zéro sur un tracé plat ou un seul point. | Garde `or 1`. |
| 9 | 🟡 ✅ | `DeltaLapTimeHistory.__init__` appelait `array.__init__(typecode, …)` sans `self` : l'appel ne faisait rien. | Ligne supprimée. |
| 10 | 🟡 ✅ | `rf2_connector.py:71` : l'annotation citait `rF2data.LMUVehicleScoring`, qui n'existe pas (copié-collé depuis LMU). | `rF2VehicleScoring`. |
| 11 | 🟡 ✅ | Appel Qt 6 obsolète : `QApplication.fontMetrics()`. | `QFontMetrics(QApplication.font())`. |
| 12 | 🟠 ✅ | `PySide6-Essentials` ne contient pas `QtMultimedia` : les pace notes plantaient à l'import. | Dépendance `PySide6` complète. |

Tous ces cas sont couverts par [tests/test_fixes.py](../tests/test_fixes.py) ou les tests de rendu.

---

## 2. Bugs et risques restants (non corrigés)

### 🔴 / 🟠 À traiter en priorité
1. 🟠 **Crash silencieux des connecteurs API** (`lmu_connector`, `rf2_connector`, `restapi_connector`, méthode `__update`). Une exception dans le thread fige la télémétrie (valeurs gelées) sans rien écrire dans le journal. → Envelopper dans `try/except` + `logger.exception`, avec redémarrage automatique si possible.
2. 🟠 **Sauvegarde JSON pendant une modification.** Le thread de sauvegarde sérialise le dict pendant que l'interface peut le modifier. C'est maintenant journalisé au lieu de tout bloquer (#1), mais la sauvegarde concernée est perdue. → Copier le dict (`copy.deepcopy`) au moment de l'ajout dans la file, ou sérialiser dans le thread de l'interface.
3. 🟠 **Attente active dans le thread de l'interface** : 8 dialogues (`ui/config.py`, `brake_editor.py`, `heatmap_editor.py`, `track_info_editor.py`, `tyre_compound_editor.py`, `vehicle_brand_editor.py`, `vehicle_class_editor.py`) font `while cfg.is_saving: time.sleep(0.01)`. Ça ne bloque plus indéfiniment, mais l'interface gèle pendant l'écriture. → Utiliser un signal « sauvegarde terminée » (`app_signal`).
4. 🟠 **Fichiers verrouillés au chargement** : les chargeurs CSV (`delta_best`, `sector_best`, `fuel_delta`, `consumption_history`) n'interceptent que `FileNotFoundError` + erreurs de format. Un `PermissionError` ou autre `OSError` (OneDrive, antivirus) fait planter le module. → Ajouter `OSError` aux exceptions interceptées.
5. 🟠 **`restapi_connector.py:225` et `async_request.py:167`** : `except BaseException: pass` avale aussi `KeyboardInterrupt`/`SystemExit` et masque les vraies erreurs réseau. → `except (asyncio.CancelledError, Exception)` + journalisation au niveau debug.

### 🟡 Mineurs
6. `process/garage.py:278` : `_shared_data: dict = {}` en argument par défaut, utilisé comme cache global caché. Ça marche, mais c'est fragile (état partagé entre API, jamais vidé au changement de session). → Attribut explicite de module ou de classe.
7. `update.py` : les dates et versions sont extraites du JSON de GitHub à coups de `bytes.find()`, ce qui est fragile. → `json.loads`.
8. `update.py` / `const_app.py` : `REPO_NAME = "TinyPedal/TinyPedal"`. Ton fork vérifie les mises à jour du projet officiel et propose des versions qui écraseraient la modernisation. → Pointer vers ton dépôt ou désactiver.
9. `ui/menu.py:340` : `subprocess.run(["xdg-open", …])` sans `check`, et l'échec n'est pas signalé à l'utilisateur.
10. `ui/tyre_strategy_planner.py` (3×) : la variable `file_filter` est dépaquetée mais jamais utilisée. De même dans `setting.py` (ancienne boucle), `preset_view.py:184`, `tyre_strategy.py:100`, `track_clock.py:148` (variables de boucle inutilisées).
11. `widget/steering_wheel.py:139`, `relative_finish_order.py:280` : chaînes `a and b or c` sans parenthèses. Le comportement est correct, mais la lecture est piégeuse.
12. `adapter/lmu_reader.py:948` : `incidents()` est annotée `int` mais renvoie un `float`.
13. `widget/track_map.py:577` : la fonction est annotée `-> str` mais renvoie un `QBrush`.
14. Le script de test intégré `lmu_connector.py:548+` (`print`) est laissé dans le module de production. → Le déplacer dans `tests/`.

### ⚙️ Dette technique
15. **208 enums Qt « courts »** (`Qt.AlignLeft`, `Qt.WA_DeleteOnClose`, `QFont.Bold`…) dans 22+ fichiers. PySide6 les accepte encore via un mode de compatibilité, mais c'est déprécié. → Migrer vers les formes complètes (`Qt.AlignmentFlag.AlignLeft`), faisable largement par script.
16. **682 accès `api.read.xxx` typés « peut être None »** (mypy `union-attr`). → Typer `api.read` comme non optionnel après `connect()` ; ça ferait passer mypy de ~2 450 à quelques centaines de messages utiles.
17. **Couverture de tests faible** : 120 tests (fumée + corrections + style). Rien ne teste les modules de calcul (fuel, delta, secteurs) avec de vraies données. → Enregistrer quelques tours de télémétrie et rejouer.
18. 148 remarques ruff de style (`zip()` sans `strict=`, `if` imbriqués…) à nettoyer en passant.

---

## 3. Déjà modernisé dans ce fork
- **Qt 6 / PySide6 natif** (PySide2 supprimé), Python 3.10 → 3.14 testé.
- **Build PyInstaller** à la place de py2exe, `pyproject.toml`, CI GitHub (ruff + pytest, Windows/Linux, 3.10 et 3.13).
- **Interface refaite** : palettes Dark/Light modernes, boutons arrondis, onglets soulignés, menus aérés, barres de défilement fines.
- **Overlay Style** (Config → Overlay Style) pour les **76 widgets** :
  - police **JetBrains Mono** intégrée, 8 graisses, sans ligatures, adaptée à tous les widgets ;
  - palette ardoise et couleurs d'accent adoucies ;
  - coins arrondis partout, y compris radar, carte, boussole, jauges et LED ;
  - espacement minimal entre les cases ;
  - tes personnalisations sont conservées et rien n'est écrit dans les presets ; désactivable.

---

## 4. Améliorations proposées

### Interface & confort
1. 💡 **Traduction française** (et multilingue) de l'interface : `QTranslator` + fichiers `.ts`. Tout est en anglais aujourd'hui.
2. 💡 **Recherche dans les dialogues de config.** Certains widgets ont plus de 100 options (`relative`, `standings`).
3. 💡 **Aperçu en direct** dans la config d'un widget (mini-rendu avec des valeurs factices, comme mes captures de test).
4. 💡 **Préréglages de thème d'overlay** (« Moderne sombre », « Classique », « Contraste élevé », « Daltonien ») applicables en un clic.
5. 💡 **Mode édition de la disposition** : grille visible, guides d'alignement et aimantation entre widgets pendant le déplacement.
6. 💡 **Annuler / rétablir** dans les éditeurs (freins, marques, classes, notes de piste).
7. 💡 Remplacer les attentes actives de sauvegarde par un indicateur non bloquant (« Saving… » dans la barre d'état).

### Performance
8. 💡 Mettre en cache les `QPainterPath` arrondis par taille de case (aujourd'hui recréés à chaque dessin ; coût faible, mais cumulé sur 76 widgets à 50 Hz).
9. 💡 Mesurer le temps de dessin par widget (option debug) pour repérer les widgets coûteux.

### Robustesse
10. 💡 **Superviseur de threads** : redémarrage automatique d'un module ou connecteur planté, avec une notification dans la barre de l'interface.
11. 💡 **Sauvegarde automatique des presets** avant chaque modification (versions horodatées). Le mécanisme de restauration de backups existe déjà.
12. 💡 Journal tournant (`RotatingFileHandler`) au lieu d'un fichier unique.

### Nouvelles fonctionnalités
13. 💡 **Sortie OBS / streaming** : petit serveur HTTP local qui expose les widgets en page web (source navigateur OBS), sans capture de fenêtre.
14. 💡 **Enregistrement de télémétrie** et export CSV / MoTeC `.ld` pour l'analyse après la session.
15. 💡 **Profils automatiques par piste** (en plus du chargement existant par classe de voiture).
16. 💡 **Import / export de presets en un fichier** (`.zip` avec presets + styles + notes), pour partager un setup d'overlay.
17. 💡 **Support d'autres simulateurs** via l'architecture d'adaptateurs existante : Automobilista 2 / Project CARS (mémoire partagée), Assetto Corsa / ACC, iRacing.
18. 💡 **Overlay VR natif** (OpenVR/OpenXR) au lieu du mode de compatibilité fenêtre.
19. 💡 **Intégration Stream Deck / boutons de volant** via les raccourcis existants (commandes exposées en local).
20. 💡 **Widgets personnalisés par plugin** : dossier `plugins/` chargé au démarrage, basé sur `Overlay`.

### Qualité du code & outillage
21. 💡 Activer progressivement plus de règles ruff (`B`, `SIM`, `UP`, `I`) et `mypy` en CI.
22. 💡 Script de capture automatique des 76 widgets (celui utilisé pour cet audit) comme **test de régression visuelle** en CI.
23. 💡 Tests des modules avec des enregistrements de télémétrie rejoués.
24. 💡 Signature du `.exe` et publication automatique des releases sur ton fork.

---

# Vérification n°2 — après les ajouts (27/09/2026)

Point de départ : 236 tests OK, ruff OK, mypy OK (206 fichiers), 0 texte `tr()` sans traduction.
Méthode : relecture complète des modules ajoutés (serveur de commandes, VR, enregistreur, plugins,
paquets de presets, aperçu, perf, i18n), des zones à risque (sauvegarde, écriture de fichiers,
redémarrage, gestion des presets), et des 505 erreurs mypy masquées (catégories désactivées).
« Confirmé » = reproduit par un script ou certain à la lecture du code.

## A. Bugs et risques

### 🔴 / 🟠 Prioritaires
1. 🔴 **Contrôle à distance : attaque « DNS rebinding » possible** (confirmé par le code). Le serveur
   ne vérifie pas l'en-tête `Host`. Une page web malveillante qui fait pointer son domaine vers
   127.0.0.1 devient « même origine » et peut alors envoyer l'en-tête `X-TinyPedal`, donc déclencher
   des commandes. Correctif : refuser toute requête dont `Host` n'est pas `127.0.0.1:<port>` ou
   `localhost:<port>`. Ne concerne que ceux qui ont activé le contrôle à distance.
2. 🟠 **Renommer un preset casse le « preset principal » des pistes et des classes** (confirmé).
   Seuls les raccourcis clavier sont mis à jour : le chargement automatique s'arrête sans message.
3. 🟠 **Renommer / dupliquer / restaurer un preset sans protection** (`os.rename`, `shutil.copy`) :
   fichier verrouillé (OneDrive, antivirus) ou nom déjà pris en différence de casse, donc exception
   non gérée et fenêtre bloquée dans un état incohérent.
4. 🟠 **Redémarrage de l'app cassé si le chemin contient un espace** (ex. `C:\Program Files\...`).
   `os.execl` ne met pas les arguments entre guillemets sous Windows (limite connue de Python).
   Correctif : relancer avec `subprocess.Popen` puis quitter.

### 🟡 Mineurs
5. 🟡 **`atomic_write` laisse un fichier `.tmp`** si une erreur autre qu'une erreur de fichier arrive
   pendant l'écriture (confirmé par un script).
6. 🟡 **Overlay VR : la dernière image reste affichée** quand tous les widgets sont masqués
   (hors session, masquage auto). Il faut cacher l'overlay VR dans ce cas.
7. 🟡 **Overlay VR : coût élevé**. Tous les widgets sont recapturés à chaque tick dans le fil de
   l'interface, les pixels copiés deux fois, et l'image envoyée même si rien n'a changé.
8. 🟡 **Enregistreur : « saved » écrit dans le journal même si l'écriture a échoué**, sans aucun
   message dans l'interface. Les tours invalides (limites de piste) sont enregistrés sans marque.
9. 🟡 **Enregistreur : la limite de tours conservés est globale**. 20 tours à Spa peuvent effacer
   tous les tours d'une autre piste ; une limite par piste serait plus logique.
10. 🟡 **~10 textes non traduits** construits par f-string : « Loaded: », « From: », « Select … »,
    « Key Binding - … », « … Keybinding », « API: … », « Version … », « About … »,
    « Total recorded time », « Preview not available ».
11. 🟡 **Renommer un preset ne renomme pas ses sauvegardes automatiques**. La restauration ne les
    voit plus sous le nouveau nom.

### ⚙️ Dette technique
12. ⚙️ **505 erreurs mypy masquées** : 135 assignment, 117 arg-type, 107 attr-defined, 88 union-attr…
    Vérifiées : aucun bug réel caché dans return-value / operator / index / call-overload
    (faux positifs Qt ou valeurs protégées par try/except). Il faut les réactiver catégorie par
    catégorie.
13. ⚙️ **Le projet n'est pas sous Git**. Pas d'historique, pas de retour arrière : la seule copie de
    sécurité est une sauvegarde manuelle. La CI GitHub ne peut donc pas tourner.
14. ⚙️ **CI : Python 3.14 absent de la matrice** (c'est pourtant ta version). Les dépendances ne sont
    pas figées (pas de fichier de verrouillage) et il n'y a pas de mesure de couverture de tests.
15. ⚙️ **Documentation `docs/customization.md` en retard** : langue, dépôt de mise à jour, sauvegardes
    auto, guides d'alignement, contrôle à distance, VR, enregistreur, preset principal par piste,
    plugins.

## B. Ajouts et améliorations proposés

### Interface
1. 💡 **Traduire aussi les libellés des options** des fenêtres de réglage (~1 500 options), avec une
   bulle d'aide qui explique chaque option (texte repris de la doc).
2. 💡 **Changer de langue sans redémarrer**.
3. 💡 **Assistant de premier lancement** : choix du jeu, du thème, de la langue et d'un preset de départ.
4. 💡 **Éditeur de thème** : créer sa propre palette de couleurs d'overlay avec aperçu en direct.
5. 💡 **Thème par widget** : forcer « Classique » ou une autre palette sur un seul widget.
6. 💡 **Recherche globale d'option** : trouver une option dans tous les widgets à la fois.
7. 💡 **Comparateur de presets** : voir les différences entre deux presets et copier des réglages.

### Télémétrie & données
8. 💡 **Visionneuse de tours enregistrés** : superposer 2 tours (vitesse, gaz, frein, rapport en
   fonction de la distance) et afficher le delta. C'est le complément naturel de l'enregistreur.
9. 💡 **Enregistreur** : export MoTeC `.ld`, marquage des tours invalides, fréquence réglable,
   limite par piste.
10. 💡 **Tableau de bord web** : afficher des widgets sur une tablette ou un téléphone via le réseau
    local, avec activation manuelle et un code d'accès.
11. 💡 **Flux de données en direct** (WebSocket) pour SimHub, Companion et les outils maison, en
    plus des commandes.

### Robustesse & diagnostic
12. 💡 **Bouton « Créer un rapport de bug »** : zip des journaux, de la config et des versions, en un
    clic.
13. 💡 **Moniteur de performance étendu** : ajouter les modules (fils de calcul), le CPU et la mémoire
    de l'app.
14. 💡 **Gestionnaire de plugins** : liste, activer/désactiver, erreurs visibles, rechargement à
    chaud.

### Outillage & distribution
15. 💡 **Mettre le projet sous Git** et le publier sur ton fork GitHub, pour avoir l'historique et
    faire tourner la CI.
16. 💡 **CI** : ajouter Python 3.14, mesurer la couverture de tests, ajouter des hooks pre-commit
    (ruff avant chaque commit).
17. 💡 **Tests d'interface** : fenêtres de réglages, gestion des presets, éditeurs (ouverture,
    modification, sauvegarde).
18. 💡 **Installeur Windows** (Inno Setup) avec raccourcis et désinstallation, et mise à jour
    automatique depuis les releases de ton fork.
19. 💡 **Traductions communautaires** : fichiers de langue JSON dans un dossier `i18n/`, pour
    ajouter une langue sans toucher au code.

## C. Réalisé (27/09/2026, suite de la vérification n°2)

Bugs et risques : **A1 à A12, A14, A15 corrigés** (A13 Git non demandé).
- A1 : en-tête `Host` vérifié (anti DNS rebinding), 2 tests.
- A2, A3, A11 : renommage de preset sûr (erreurs affichées), preset principal piste/classe et sauvegardes renommés.
- A4 : redémarrage par `subprocess` sous Windows (chemins avec espaces).
- A5 : fichier temporaire toujours supprimé.
- A6, A7 : overlay VR masqué si aucun widget, image envoyée seulement si elle change (somme de contrôle), une seule copie des pixels.
- A8, A9 : enregistreur : validation du tour (comme le delta best), tours « invalid », message d'erreur visible, limite par piste.
- A10 : textes restants traduits (règles de messages).
- A12 : mypy : `call-overload`, `index`, `operator`, `override`, `return-value` réactivés (erreurs corrigées). Découverte au passage : lignes de secteur de la visionneuse de carte (secteur 2 fusionné dans le secteur 1), corrigé.
- A14 : CI Python 3.10 / 3.13 / 3.14, couverture (résumé dans la CI), `requirements-lock.txt`, `requirements-dev.txt`, `.pre-commit-config.yaml`.
- A15 : `docs/customization.md` à jour (toutes les nouvelles options, outils, module, widget, plugins).

Améliorations : **B1 à B8, B10, B12, B13, B14, B16, B17 réalisées**, plus le widget demandé.
- B1 : 2 643 noms d'options traduits (générateur `tools/gen_fr_options.py`), bulles d'aide tirées de la doc (`tools/gen_option_help.py`, 1 079 descriptions, en anglais).
- B2 : langue changée à chaud (menus, onglets, barre d'état, menu de la zone de notification).
- B3 : assistant de premier lancement (menu Aide pour le relancer).
- B4, B5 : éditeur de thèmes (aperçu, annuler/rétablir) et option `widget_theme` sur chaque widget.
- B6 : recherche globale d'option (`Ctrl+F`), en français ou en anglais.
- B7 : comparateur de presets avec copie d'options.
- B8 : visionneuse de télémétrie (delta, vitesse, pédales, rapport, direction ; zoom).
- B10 : tableau de bord web (code d'accès, blocage après 10 erreurs, réseau local optionnel).
- B12 : rapport de bug (zip, données personnelles retirées).
- B13 : moniteur étendu : CPU par fil (modules, connexion au jeu), CPU et mémoire de l'app.
- B14 : gestionnaire de plugins (erreurs, activation, rechargement à chaud, installation depuis zip sécurisée).
- B16, B17 : CI (voir A14) et tests d'interface ; couverture 41 % → 49 %.
- Nouveau widget `Black box` (anciennement « Wheel status » / « Black box »).

Bilan : 295 tests, ruff et mypy propres (222 fichiers).

## D. Idées suivantes (27/09/2026)

### Widget « Black box »
1. 💡 Couleur du rapport engagé selon le régime (vert → orange → rouge) et clignotement au régime de passage.
2. 💡 Rangée de LED de régime en haut du widget (shift lights).
3. 💡 Delta best et temps au tour courant sous la vitesse.
4. 💡 Carburant restant et nombre de tours possibles, à côté de Refuel.
5. 💡 Températures intérieur / milieu / extérieur du pneu en 3 bandes dans le rectangle (réglage du carrossage).
6. 💡 Pression colorée selon une plage cible (trop basse / bonne / trop haute).
7. 💡 Usure estimée en fin de relais, en plus de l'usure actuelle.
8. 💡 Signalement crevaison / roue détachée / pneu à plat (flat spot) sur le pneu.
9. 💡 Voyants limiteur de vitesse et voie des stands.
10. 💡 Dégâts carrosserie / suspension affichés autour des roues.
11. 💡 Mode compact (sans colonne centrale) et disposition verticale.
12. 💡 Choix de l'ordre des éléments de la colonne centrale (glisser-déposer dans les réglages).

### Application
13. 💡 Rejouer une télémétrie enregistrée dans les widgets (tester l'overlay sans lancer le jeu).
14. 💡 Éditeur visuel de disposition : placer / aligner les widgets sur une capture d'écran du jeu.
15. 💡 Bulles d'aide des options traduites en français.
16. 💡 Export MoTeC `.ld` des tours enregistrés.
17. 💡 Installeur Windows et mise à jour automatique.
18. 💡 Mettre le projet sous Git et le publier sur GitHub.

Réalisé (27/09/2026) : D1, D2, D4 à D12 dans le widget « Black box » (D3 non demandé).

## E. Audit du widget « Black box » (28/09/2026)

Audit dédié du fichier `tinypedal/widget/black_box.py` (640 lignes exécutables, 114 options, 98 % de couverture de tests après corrections ; 2ᵉ widget le plus lourd sur 77 au benchmark).

### 🔴 Bugs corrigés
1. ✅ La dernière LED de régime ne s'allumait jamais (son seuil était égal à `redline`, où la branche « surrégime » prend le dessus). Formule corrigée : `start + led / count * (redline - start)`.
2. ✅ L'usure estimée en fin de relais affichait « →0 % » au lieu de rien quand le module Wheels/Fuel n'avait pas encore de données (sentinelle `-1.0` qui satisfaisait la condition d'affichage `>= -100`). Remplacé par un indicateur explicite `tread_end_known`.
3. ✅ Seuil de masquage incohérent, résolu par le même correctif (n°2).

### 🟠 Corrigé
4. ✅ La pastille d'alerte de pression réutilisait `tyre_wear_warning_color` (option de l'usure) au lieu d'une couleur dédiée ; nouvelle option `tyre_pressure_warning_background_color`.
5. ✅ `display_scale` n'avait pas de borne haute (une faute de frappe pouvait produire un overlay de 2000 px) ; borné à `4`, comme les autres options d'échelle du widget.
6. ✅ Trois options sans bulle d'aide (`show_background`, `show_degree_sign`, `warning_outline_width`) ; documentées dans `docs/customization.md` et régénérées.

### ⚙️ Performance (corrigé)
7. ✅ Données lues même quand non affichées (pression, température de frein, niveaux ABS/TC, biais de frein, vitesse, régime, pédales, ravitaillement) : lecture conditionnée à l'affichage réel, la disposition compacte ne lit plus du tout la colonne centrale.
8. ✅ `QPainterPath` du pneu reconstruit à chaque roue à chaque frame ; construit une fois à l'initialisation (les 4 pneus ont la même géométrie). `is_right` calculé depuis l'index de roue au lieu d'une comparaison de coordonnées.
9. ✅ `in_pits()` lu deux fois par tick ; lu une fois et réutilisé.

Résultat mesuré (benchmark `pytest -m benchmark`) : **0,785 ms → 0,585 ms par frame** (−25 %), pic de mise à jour 0,283 → 0,097 ms.

### 💡 Ajouté
10. ✅ Usure de frein (`show_brake_wear`), épaisseur restante en pourcentage, avec seuil et couleur d'alerte dédiés — donnée déjà calculée par le module Wheels mais absente du widget.
11. ✅ Symbole de composé de gomme sur chaque pneu (`show_tyre_compound`).
12. Delta best / temps au tour sous la vitesse (D3 de la section D) — toujours pas fait, hors périmètre de cet audit.
13. ✅ Seuil d'alerte de température pneu (`tyre_temperature_warning_threshold`).
14. ✅ Titre optionnel (`show_caption`), comme la plupart des autres widgets.
15. ✅ Étiquette « lap » ajoutée aux lignes carburant/énergie restants (affichaient un nombre nu).

### 🟡 Corrigé
16. ✅ Colonne centrale en disposition verticale : l'espace des éléments masqués (ABS/TC/PIT-LIM inactifs) est maintenant partagé au-dessus et en dessous au lieu de laisser un vide en bas.
17. ✅ Seuils de pression cible en psi (03/10/2026) : les plages (avant, arrière, par gomme) se saisissent en kPa, psi ou bar, l'unité étant reconnue à la valeur (moins de 10 : bar, de 10 à 60 : psi, au-delà : kPa), sans dépendre de l'unité affichée, donc sans réinterpréter les presets existants.

### 🧪 Tests
- Couverture 94 % → **98 %**. 13 nouveaux tests couvrant chaque bug corrigé (régression) et chaque ajout.
- Effet de bord découvert en testant : le faux lecteur API des tests (`tests/conftest.py`) recréait un nouvel objet à chaque accès (impossible à monkeypatcher) et renvoyait un entier nu pour les lecteurs par roue. Corrigé (mise en cache du groupe, formes par roue correctes) ; ce correctif a aussi éliminé un crash latent (`Fatal Python error: Aborted`) dans le rendu de prévisualisation du widget `elevation` lors de l'exécution de la suite complète.

Réalisé (28/09/2026) : E1 à E11, E13 à E16. Non traités : E12 (D3, non demandé), E17 (mineur).

## F. Audit du style / interface de l'application (28/09/2026)

Contexte : l'app a deux couches de style bien distinctes. Les **widgets overlay** (ce qui s'affiche en jeu) ont déjà un vrai système de design moderne — thème « Modern Dark » par défaut, police JetBrains Mono, coins arrondis configurables, palettes Daltonien/Contraste élevé (`tinypedal/widget/_style.py`). Cet audit porte sur l'autre couche : **l'interface de configuration** (fenêtre principale, dialogues, menus — `tinypedal/ui/`), moins homogène. Vérifié par lecture de code (grep systématique des sélecteurs Qt) et par rendu réel de captures d'écran (fenêtre principale, dialogue de config, gestionnaire de plugins, menu, boîte de message), en thèmes clair et sombre.

### 🔴 Corrigé
1. ✅ **Le style ne s'appliquait qu'à la fenêtre principale, pas à l'application.** `AppWindow.setStyleSheet(...)` au lieu de `QApplication.setStyleSheet(...)` : en Qt, une feuille de style posée sur un widget ne descend qu'à ses enfants *visuels* directs, pas aux fenêtres de haut niveau construites séparément (`QMessageBox`, `QColorDialog`…) même si elles sont « parentées » à la fenêtre stylée pour leur cycle de vie. Vérifié par capture d'écran : tous les `QMessageBox.warning/question/critical` (**108 appels dans 25 fichiers**) s'affichaient avec des boutons « Oui/Non » à coins carrés et chrome natif de l'OS, détonnant avec le reste de l'app (boutons arrondis partout ailleurs). Déplacé au niveau `QApplication`, vérifié en clair et en sombre après correctif — cohérent partout, y compris pour toute boîte de dialogue future.
2. ✅ **Cases à cocher, boutons radio, listes déroulantes et curseurs non stylés.** Aucun sélecteur `QCheckBox`, `QComboBox`, `QRadioButton` ou `QSlider` dans la feuille de style (`tinypedal/ui/__init__.py`), seuls `QLineEdit`/`QPushButton`/`QTabBar` etc. l'étaient. Ces contrôles apparaissaient donc avec le rendu Fusion générique (petites cases natives) au milieu d'un habillage par ailleurs entièrement personnalisé. Ajout de règles cohérentes avec la palette existante : case à cocher/radio en carré/rond plein (couleur d'accent) au lieu de coche, liste déroulante avec bordure et arrondi assortis (la flèche Fusion native est conservée — une tentative de flèche personnalisée en CSS pur rendait mal, testé et écarté), curseur avec piste et poignée aux couleurs du thème.

### 🟡 Mineur (non corrigé, signalé)
3. Couleurs codées en dur hors du système de palette : `#638` (bouton de notification de mise à jour), `#2A6EC2` et `#777` (étiquettes de preset dans `preset_view.py`). Contraste correct dans les deux thèmes actuellement (texte blanc dessus), donc pas de bug visuel constaté, mais ces couleurs n'évolueraient pas si la palette change plus tard.
4. Icône native du système dans les `QMessageBox` (triangle d'avertissement, point d'interrogation) — cohérente dans les deux thèmes mais dessinée par l'OS, pas par l'app ; remplacer demanderait une icône custom par sévérité.

### 💡 Pistes de modernisation (non implémentées, proposées)
5. **Aucune icône nulle part dans le chrome de l'app** (vérifié par grep : zéro `QIcon`/`.svg`/`.png` en dehors de l'icône d'app/barre des tâches et de 4 images décoratives *à l'intérieur* de widgets overlay spécifiques — compas, instrument, volant, météo). Menus, onglets, 78 lignes de la liste de widgets, boutons de dialogues : tout est en texte seul. C'est la différence la plus visible avec une app « moderne » typique (Fluent/Material). Ajouter des icônes demande de vraies ressources SVG — travail de conception à part, proposé mais pas fait ici.
6. **Pas de recherche/filtre sur la liste principale des 78 widgets**, alors que chaque dialogue de configuration individuel en a une (`edit_search`). Avec 78 lignes identiques à faire défiler, c'est l'incohérence UX la plus concrète entre les deux niveaux de l'interface.
7. Liste de widgets sans regroupement par catégorie ni icône distinctive par ligne — toutes les lignes sont visuellement identiques hormis l'état ON/OFF, ce qui rend le survol difficile avec autant d'entrées.
8. Le statut du gestionnaire de plugins (« Loaded », « Error », « Not trusted ») est en texte de couleur sans badge/pastille — repérage moins rapide qu'un badge plein comme utilisé pour ON/OFF dans la liste des widgets.

Réalisé (28/09/2026) : F1, F2. Non traités : F3, F4 (mineurs), F5 à F8 (nécessitent des ressources ou une refonte plus large, proposés comme prochaine étape).

Suite (03/10/2026) : F3 (étiquettes de preset et bouton de mise à jour suivent la palette ou les couleurs de notification), F6 (recherche et filtres de la liste, en place), F7 (pastille de couleur par catégorie sur chaque ligne, légende dans le filtre de catégorie), F8 (statut et activation des plugins en badges pleins). F5 en partie : icônes de la barre de navigation et de l'onglet Outils (police Segoe Fluent Icons, lettres sans cette police). Non traité : F4.

## E (suite, 28/09/2026) — Modernisation visuelle du widget « Black box »

Suite à la demande explicite de pousser plus loin le style de `black_box`, sans toucher au reste de la suite de widgets (dont le rendu reste volontairement plus sobre, cf. section F sur le style applicatif général).

### 💡 Ajouté
- Badges (ABS/TC/PIT/LIM), LED de régime, barre de régime, barres de pédales, barre de dégâts de suspension et pastilles d'alerte (pression, crevaison, pneu à plat) rendus en **capsule pleinement arrondie** au lieu du très léger arrondi hérité du réglage global (`corner_radius_scale`, 0,05 par défaut, quasi invisible sur des éléments aussi fins). Le rendu reste carré si l'utilisateur désactive explicitement les coins arrondis (`corner_radius_scale = 0`) — le choix de l'utilisateur reste respecté, seule l'intensité par défaut est renforcée sur ces petits éléments.
- **Dégradé subtil** sur le remplissage de la barre de régime et des barres de pédales (plus sombre à la base, plus clair vers le bord), au lieu d'un aplat uni — lecture plus « jauge premium », cohérent avec l'esthétique « Modern Dark » déjà en place pour la couleur.
- **Halo lumineux** autour de chaque LED de régime allumée (glow semi-transparent), effet « shift light » habituel sur les tableaux de bord modernes, désactivé pendant la phase « éteinte » du clignotement en surrégime.

Toutes les formes représentant une pièce physique (pneu vu de dessus, disque de frein) gardent leur arrondi propre, indépendant du réglage utilisateur — seuls les éléments de chrome (jauges, badges, LED) suivent la nouvelle règle.

Coût mesuré (`pytest -m benchmark`) : 0,585 → 0,64 ms/frame (+0,05 ms), toujours très en dessous du budget de 15 ms et de l'ancien 0,785 ms pré-audit. Couverture maintenue à 98 % (5 nouveaux tests dédiés : rayon des capsules selon le réglage utilisateur, rendu carré vs arrondi vérifié pixel par pixel, dégradé sans exception sur largeur nulle, halo affiché seulement sur LED allumée).

## G. Audit bugs / optimisation / robustesse (28/09/2026)

### A. Données non finies (nan, inf) — ✅ fait
Un `nan` ou un `inf` atteignant un appel Qt qui convertit vers un `int` C++ ne lève pas d'exception : il **abandonne le processus entier**, emportant tous les widgets. Les lecteurs assainissent les données du jeu, mais une division par une consommation quasi nulle ou un angle de direction dégénéré peut en produire un en aval.

Trois chemins corrigés : `end_stint_laps`, `turning_radius` et `ackermann_percentage` renvoient 0 plutôt qu'une valeur non finie ; `friction_circle` borne son point et sa trace au widget avant `drawPixmap` ; `force` assainit les valeurs d'appui et de masse avant arrondi.

`tests/test_widget_robustness.py` peint les 78 widgets contre cinq jeux de données dégénérés. **Sans ces garde-fous, il abandonne pytest exactement comme l'overlay.** Effet de bord : le faux lecteur de `conftest.py` déduit désormais la forme de retour de chaque lecteur des annotations du vrai lecteur au lieu d'une liste maintenue à la main — c'est ainsi que le tuple manquant d'`impact_position` était passé inaperçu.

### B. Banc d'essai aveugle sur les widgets de liste — ✅ fait
Les modules de données ne tournent pas dans le banc d'essai, donc `minfo` ne contenait **aucun véhicule** : `standings`, `relative`, `radar` et les autres widgets de liste dessinaient une liste vide et se mesuraient parmi les moins coûteux du projet. Avec une grille de 20 voitures, ils sont en réalité les plus coûteux : **standings à 3,7 ms/frame** contre 0,4 ms pour le suivant. Plusieurs ne repeignent que si `dataSetVersion` change, donc le pilote de trame l'incrémente désormais comme le fait le module véhicules. Chaque mesure vérifie d'abord la présence de la grille, pour que ce point aveugle ne puisse plus revenir en silence.

### C. Erreurs de type `arg-type` — ✅ fait (92 → 0, contrôle activé)
`arg-type` est désormais bloquant dans `pyproject.toml`. Deux corrections dépassaient l'annotation :
- `widget_preview` gardait sa zone de défilement dans `self.scroll`, masquant `QWidget.scroll()`, la méthode héritée du même nom.
- Le calculateur de carburant construisait ses lignes de tableau *à l'intérieur* de l'`enumerate()` qui les consommait, où les lignes avec et sans couleur de surbrillance étaient fusionnées en un type inutilisable.
- L'historique des couleurs était initialisé avec des chaînes puis alimenté en `QColor` — il contenait donc les deux.
- La lecture d'une carte SVG passait `nodeValue` directement à un analyseur de chaîne, sans la vérification que les autres champs de la même fonction ont déjà.

### D. Modules de données non testés — ✅ fait
| Module | Avant | Après |
|---|---|---|
| `module_wheels.py` | 6 % | 40 % |
| `module_relative.py` | 14 % | 51 % |
| `module_vehicles.py` | 7 % | 37 % |

Chaque lot a été vérifié **par mutation du code source**, pas seulement au vert : inverser les compteurs avant/arrière de la fenêtre de classement, supprimer le marquage du meilleur tour de classe, prendre le plus long de carburant/énergie au lieu du plus court, ou retirer la correction de tour de formation — chacun fait échouer un test.

Deux de mes attentes initiales étaient fausses et c'est le code qui avait raison : le rayon de roue n'est pas établi aux premières trames, et une remise à zéro de tour est suivie de l'accumulation de la trame courante.

Réalisé (28/09/2026) : A, B, C, D — intégralement.

---

## F. Réalisé (30/09/2026)

- Sous-modules `pyLMUSharedMemory` et `pyRfactor2SharedMemory` intégrés au dépôt (leurs corrections de typage ne pouvaient pas être poussées vers les dépôts officiels).
- Projet publié sur GitHub : [Keenny38/ModernTinyPedals](https://github.com/Keenny38/ModernTinyPedals). Les mises à jour sont vérifiées sur ce dépôt par défaut.
- Sauvegarde : plus d'attente active au redémarrage ni au rechargement (événement avec délai maximal).
- Rejeu de télémétrie LMU (`Outils > Rejeu de télémétrie`) : enregistre la mémoire partagée et la rejoue dans tous les widgets, sans le jeu.
- Export MoTeC `.ld` depuis la visionneuse de télémétrie.
- Éditeur de disposition (`Outils > Éditeur de disposition`) : placer les widgets sur une capture du jeu, avec magnétisme.
- Flux de télémétrie en direct par WebSocket (`ws://127.0.0.1:8337/stream`) sur le serveur de contrôle à distance.
- Installeur Windows (Inno Setup, par utilisateur) et installation des mises à jour depuis l'app, avec vérification SHA-256.
- Bulles d'aide des options traduites en français (996 textes).
- mypy : `misc`, `has-type`, `var-annotated`, `type-arg`, `no-redef` et `assignment` réactivés. Seul `attr-defined` reste masqué.
- Tests des modules Sectors, Stint, Hybrid et Force (couverture de 10-14 % à 71-84 %).
- Moniteur de performance : le temps de mise à jour du Black box n'était jamais mesuré (méthode venant d'un mixin), corrigé.
- Tableau de bord web en HTTPS (certificat auto-signé, empreinte affichée).


---

## H. Télémétrie : enregistreur, visionneuse, rejeu, flux (01/10/2026)

Corrections :
- L'enregistreur de tours ne tourne plus pendant un rejeu (option `enable_lap_recording_during_replay` pour le permettre ; les tours portent alors l'heure où ils ont été roulés et le nom du rejeu). Avant, rejouer créait des doublons datés du rejeu et la rotation supprimait de vrais tours.
- Un tour est abandonné quand le temps de jeu recule (rejeu en boucle ou rembobiné), au lieu d'être enregistré avec une durée fausse.
- La rotation garde les `number_of_best_laps_kept_per_track` meilleurs tours valides (3 par défaut), même s'ils sont les plus anciens.
- Rejeu : les images sont lues dans le fichier à la demande (seules leurs positions restent en mémoire), au lieu de charger tout le fichier (~430 Mo pour une heure).

Enregistreur de tours :
- 26 canaux de plus : altitude, accélérations latérale et longitudinale (G), secteur, TC et ABS actifs, batterie, et par roue : température des freins, usure des pneus, vitesse de roue, hauteur de caisse, débattement.
- Première ligne d'infos du tour (JSON) : circuit, véhicule, catégorie, session, températures, humidité, carburant, temps intermédiaires officiels, type de tour, version.
- Échantillons ignorés quand les données du jeu n'ont pas changé.
- Options : tours de sortie et de rentrée, fichiers compressés `.csv.gz`, désactivation de l'enregistrement des tours.

Visionneuse :
- Plusieurs tours à la fois (une couleur par tour), meilleur tour valide en référence par défaut, ajout de fichiers d'autres dossiers.
- Choix des canaux (menu `Canaux`, mémorisé), secteurs sur les courbes, temps par secteur, meilleur tour théorique, alerte si les véhicules diffèrent.
- Courbes dessinées une fois dans une image en cache (le curseur ne redessine plus tout), réduction min/max par pixel (les pics de freinage restent visibles).
- Glisser pour déplacer, Maj+glisser pour zoomer sur une zone, raccourcis clavier.
- Onglet `Cercle G`. Export MoTeC de tous les canaux, du tour de référence, des tours affichés ou de tout le circuit, avec véhicule et session.

Rejeu :
- Enregistrement automatique en option (`enable_auto_replay_recording`), avec limite du nombre de fichiers automatiques.
- Images hors conduite ignorées (option), trous de plus d'une seconde retirés du temps du rejeu.
- En-tête avec circuit, véhicule et session ; résumé en fin de fichier pour lister durée et taille sans tout lire.
- Liste des rejeux, repères des tours et des incidents de la Black box sur la barre de progression, aller au tour N, incident précédent/suivant, image par image, raccourcis clavier, enregistrement d'une section.
- Données de l'API REST écrites seulement quand elles changent.

Flux WebSocket `/stream` : `?fields=` pour choisir les champs, `?changes=1` pour n'envoyer que ce qui a changé, modifiables par message du client.

### Audit de la télémétrie (01/10/2026)

Corrigé :
- 🔴 « Revenir au jeu » fermait le fichier de rejeu alors que le fil de l'API lisait encore des images : `ValueError: seek of closed file`, fil de mise à jour arrêté. Le fichier se ferme maintenant quand le lecteur n'est plus utilisé.
- 🟠 Distance du tour remise à zéro en retard par le jeu : les premiers échantillons gardaient la distance du tour précédent. La visionneuse n'affichait qu'un point, et un faux tour de 6,8 s passait le contrôle des 90 % de distance. Échantillons écartés à la lecture et pour le contrôle.
- 🟠 Distance mise à jour 5 fois par seconde : courbes en escalier (412 distances pour 4 000 échantillons). Distance interpolée dans le temps entre deux mises à jour.
- 🟠 Enregistrement du tour dans le fil d'échantillonnage : trou de données au début du tour suivant. Enregistrement en arrière-plan.
- 🟡 Tour confirmé par le jeu mais marqué `invalid` si on rentre au garage moins d'une seconde après la ligne. Le temps du jeu est vérifié avant d'abandonner.
- 🟡 Visionneuse : meilleur tour théorique et meilleurs secteurs mélangeaient les fichiers ajoutés d'autres circuits ; cache de tours sans limite (plusieurs Mo par tour, export de tout un circuit) ; plan du circuit et cercle G entièrement redessinés à chaque mouvement de souris.
- 🟡 Accélérateur et frein enregistrés après l'électronique de la voiture (coups de gaz et coupures aux passages de rapports). Valeurs non filtrées des pédales.

Restant (mineur) : un tour aberrant élargit l'échelle du delta pour tous ; la vitesse de roue vaut 0 si le module Wheels est désactivé ; l'indice de secteur n'est mis à jour qu'à 5 Hz (limites de secteur à ±10 m).

Suite (01/10/2026) :
- Unités vérifiées en rejouant un enregistrement LMU réel : usure des pneus en fraction restante, rotation des roues négative en marche avant (valeur absolue utilisée), hauteur de caisse et débattement en mm, freins en °C. La distance du tour est négative dans la voie des stands avant la ligne, sans effet sur le découpage des tours.
- MoTeC : un vrai fichier `.ld` place l'unité dans le champ documenté comme « nom court ». L'unité est maintenant écrite dans les deux champs.
- Visionneuse : échelle du delta robuste aux tours aberrants, légende des tours sur les courbes. Rendu avec les vraies polices : boutons tronqués, libellés coupés à gauche, colonne Temps tronquée et rapport affiché « 2.00 » corrigés.

---

## I. Audit complet (05/10/2026)

Méthode : ruff (règles du projet et règles étendues), mypy, suite de tests (1 573 tests, 83 % de couverture au départ), lancement de l'app sur un profil vierge, relecture de chaque zone par un agent (données du jeu, calculs et réglages, overlays, interface, visionneuses Qt Quick, build et documentation), puis rendu des 79 overlays dans les deux designs avec des données extrêmes (0 à 128 voitures, NaN, unités impériales, combinaisons d'options au hasard). Chaque correction a son test de non-régression ; après corrections : 1 957 tests, 90 % de couverture.

### Bugs corrigés (prioritaires)
- 🔴 Stratégie en course : la clé de session contenait le temps écoulé, le compteur d'arrêts et le suivi des rivaux repartaient à zéro chaque seconde (`race_live.py`). Règle « même session » centralisée (`validator.session_token` / `is_same_session`).
- 🔴 L'app ne démarrait plus si la mémoire partagée du jeu existait déjà avec une taille plus petite (ancien plugin rF2, autre outil) : erreur interceptée, état « non connecté » et message.
- 🔴 Plugins : installation depuis un ZIP pouvant écrire hors du dossier (nom `D:xxx.py`), et `.pyc` livré exécuté à la place du code relu. Chemins vérifiés, code exécuté depuis les octets vérifiés.
- 🔴 Fermer la fenêtre puis « Annuler » détruisait quand même la fenêtre (app sans interface) ; modifications d'une page de config perdues au changement de preset.
- 🔴 Race plan moderne : arrêt suivant affiché au lieu de l'arrêt en cours au stand.
- 🔴 Visionneuse : delta et tour idéal faussés (jusqu'à 0,19 s / 0,4 s) par les extrémités du tour coupées ; fichier `.csv.gz` corrompu rechargé en boucle.
- 🔴 `install.sh` exigeait un `.gitmodules` disparu ; mise à jour automatique lancée depuis la version ZIP portable.

### Autres corrections
- Rejeux : pause masquant les overlays, structure de données vérifiée (format 2 avec CRC par image, fichiers endommagés lus jusqu'à la partie saine), rotation qui supprimait les extraits sauvegardés, export en arrière-plan, tour en attente sauvegardé à la fermeture.
- Données LMU : tâches REST relancées après une réponse vide, entier JSON accepté pour un décimal, connexions réutilisées, adresse du jeu en cache, état des connecteurs dans le moniteur de performance (onglet « Données du jeu »).
- Calculs : « +664 tours » au tour 1, relais compté depuis l'arrêt prévu, notes de pilotage près de la ligne, bilan batterie après un arrêt, carburant négatif, format 599,6 s → « 00:09:00 ».
- Fichiers : presets et `config.json` écrits de façon atomique avec `fsync`, CSV abîmés, sauvegardes horodatées, données des modules enregistrées à leur arrêt.
- Interface : redémarrage sans demande, fenêtre ouverte par-dessus le jeu pour une mise à jour, journal corrompu après « Enregistrer », éditeurs (doublons, couleurs invalides, erreurs d'écriture), unité dans les codes de partage, contraste du thème clair, navigation au clavier, signature de l'installeur vérifiée.
- Overlays : deltabest_extended qui plantait, heatmaps modernes jamais rafraîchies, tailles à l'échelle ×2, textes tronqués (test qui échoue si un texte dépasse), maxima du moteur et des pédales, °F, libellés traduits, performances (LRU, caches, historique des tours).
- Sécurité : tableau de bord web (longueur négative, expiration des sessions), flux WebSocket refusant l'origine `null`, caches de la visionneuse sans `pickle`, JSON non fini refusé.
- Build et CI : test de démarrage de l'exe avant publication (`--self-test`), versions figées, droits et secrets limités, actions épinglées, délais maximum, comparaison visuelle sur tout le push, hash du setup.exe, version réelle quand l'app tourne depuis les sources, licences tierces complétées, `NOTICE.md`, `CONTRIBUTING.md` du fork.

### Ajouts et améliorations (suite de l'audit)
- 7 nouveaux overlays : graphique de delta, tendance des écarts, aide en voie des stands, minuteur de relais, spotter, alertes de course, tendance des températures pneus.
- Design moderne au niveau de l'ancien : race plan (recalcul en direct, menu des stands, conso cible), colonnes des classements, gommes par roue, textes personnalisés, ordre des lignes, couleurs des overlays redessinés.
- Nouvelles données LMU dans l'API de lecture et les overlays : delta officiel, tour invalidé, écarts, crevaison, température idéale des pneus, limiteur, état de charge, position du box, drapeaux jaunes par secteur, vent, hauteurs de caisse, surchauffe, événements de session.
- Stratégie : conso médiane hors neutralisation (option), tour du leader dans les tours restants, pilote de chaque relais, relais limités par les pneus, badge d'unité et copie de l'image du plan.
- Visionneuse : valeurs ajustées à la partie visible par panneau, canaux calculés (formule vérifiée, jamais `eval`), alignement sur un freinage, CSV sur base de temps, zoom clavier, régularité par mini-secteur, tours d'un coéquipier, meilleur tour en conditions proches, différences de setup, rapport HTML / PDF. Statistiques : dégradation par gomme, régularité, export, comparaison avec un ami.
- Interface : marqueur de modifications et `Ctrl+S`, validation pendant la saisie, corbeille des presets, `Ignorer cette version` et progression du téléchargement, démarrage sans échec (`--safe-mode`).
- Tableau de bord web traduit, unités de l'utilisateur, énergie virtuelle. Python 3.10 abandonné (fin de vie), 3.11 minimum. Couverture minimale relevée à 88 %.

Après l'ensemble : 2 188 tests, 91 % de couverture. Ce qui reste à vérifier en jeu est listé dans la [feuille de route](ROADMAP.md).

---

## J. Audit du Lap Telemetry Viewer (06/10/2026)

Périmètre : la visionneuse de télémétrie (~14 000 lignes Python + QML) : état et chargement des tours, calculs (delta, mini-secteurs, tour idéal, relais), carte et virages, interface QML, import / export / bibliothèque. Méthode : 5 revues en parallèle avec reproduction sur une copie des vrais tours (Le Mans, Road Atlanta, Laguna Seca, imports MoTeC), mesures de temps, puis contre-vérification des points majeurs. Les numéros de ligne datent du 06/10/2026, avant les corrections.

Légende : 🔴 données fausses ou blocage · 🟠 moyen · 🟡 mineur · ⚙️ performance · 💡 amélioration

### ✅ Résultat (06/10/2026) : tout est corrigé, J53 en partie
Correction en 6 lots parallèles, puis J56 et les restes. 6 nouveaux fichiers de tests (`tests/test_lap_viewer_fix_*.py`, 82 tests). Suite complète : aucun échec dans la visionneuse (2 607 tests au vert ; les 14 échecs restants viennent de pages en cours de refonte dans une autre session). ruff et mypy (Windows et Linux) sont propres sur les 22 fichiers touchés.

**Données** :
- Road Atlanta : bords de piste à 12,5 m de large en médiane au lieu de 5,5 m, et 4 sorties de limites au lieu de 28 (fichier `.track_limits` versionné, donc recalculé une fois).
- Tour Genesis importé : delta à la ligne de −0,304 s et tour idéal de 68,843 s.
- La session du 03/10 est découpée en 5 relais.
- Les canaux calculés suivent la référence.
- Le Mans : Forest Esses et Indianapolis replacés.

**Robustesse** :
- Aucun import relancé dans l'app si le processus de travail meurt ; un log d'une heure prend 149 Mo au lieu de 879 Mo, et un fichier piégé 0,02 s au lieu de 20 s.
- Bibliothèque : suppression vers la corbeille avec annulation, fichiers verrouillés signalés.
- Imports écrits via un fichier temporaire.

**Clavier** :
- Les touches vont aux graphiques à l'ouverture ; `Ctrl+Z` ne marche que sur la page affichée.
- `Échap` ne ferme jamais la visionneuse.
- La grande carte reçoit ses touches ; la rangée de chiffres AZERTY marche sans `Maj`.

**Performance** :
- Courbes de 6 tours du Mans : 6,6 Mo au lieu de 100 Mo.
- Liste de 360 tours : 30 éléments au lieu de 201, recherche en 20 à 80 ms.
- Ouverture d'un circuit de 360 tours neufs : 0,35 s au lieu de 1,5 s (index des en-têtes).
- Traînées de la carte 2 à 3 fois moins chères ; recherche sur la carte dézoomée en 3,5 ms au lieu de 40 ms.
- J56 : signaux séparés pour les panneaux, les virages et la carte.
- J53 : seul le cercle G est construit à la demande (revenir au Mans : ~0,55 s au lieu de ~0,64 s) ; la carte et les courbes restent nécessaires aux graphiques.

**En plus** :
- L'enregistreur note l'heure exacte de fin de tour (lien vers le rejeu).
- La liste déroulante de l'onglet Session ne garde plus le clavier.
- Plus d'avertissements QML à la fermeture de la visionneuse.

### ✅ Corrigé
- **J0** : des tours de circuits différents étaient comparés : un tour ajouté restait coché au changement de circuit, et les tours d'un autre circuit étaient tracés et comparés, seulement exclus du tour idéal. Désormais, un tour d'un autre circuit que le tour de référence est décoché, avec un message (`lap_backend.drop_other_circuits`).

### 🔴 Prioritaires
- **J1** : les bords de piste venant du jeu sont beaucoup trop étroits. Le signe de `path_lateral` est choisi au hasard pour chaque tour, et le bord opposé est complété à partir de quelques points (`lap_geometry.py:251-289`).
  - Sur tes limites de Road Atlanta enregistrées, la largeur est de 5,5 m en médiane et descend à 1,2 m, au lieu d'environ 12,6 m. C'est vérifié.
  - Les 26 tours sans bords enregistrés reçoivent ainsi 28 faux « hors limites ».
  - « Room to edge » et la « Track Position » sont faux aussi.
  - Après correction, il faudra versionner `.track_limits` (voir J52), sinon les mauvais bords déjà enregistrés resteront.
- **J2** : « Distance to Center » et « Track Position » sont remplacées par la mesure faite sur la carte, même quand le jeu les a enregistrées (`lap_map_view.py:542-569`, `trace_data.py:547`). Exemple : 0,62 m / +55 % affiché, alors que le jeu donne −5,74 m / −90 %, du côté opposé.
  - Sans bords de piste, c'est la distance au tracé « type 0 » de l'API qui s'affiche. Ce tracé est une trajectoire de course, pas le centre de la piste : vérifié, ton meilleur tour passe à 0,2–0,7 m de ce tracé en médiane.
- **J3** : les tours importés ne sont pas recalés sur la longueur du circuit quand l'écart est inférieur à 1 %. L'échelle est calculée sur le dernier échantillon et non sur la longueur du tour (`telemetry_lap.distance_scale`, même logique dans `lap_geometry.py:568`).
  - Tour Genesis à Road Atlanta : delta à la ligne de +0,056 s au lieu de −0,304 s, et tour idéal trop optimiste de 0,55 s.
- **J4** : après un changement de tour de référence, les courbes des autres tours gardent l'ancienne échelle de distance. La clé des vertices ne contient pas l'échelle (`trace_data.set_laps` / `signature`). Les courbes, le curseur, la carte et les virages peuvent alors être décalés de jusqu'à ~200 m.
- **J5** : un canal calculé qui utilise `delta`, `delta_rate`, `path_lateral` ou `track_position` n'est jamais recalculé (`trace_data.py`). Le changement de référence, le mode idéal, la fenêtre de delta ou le recalage sur la carte n'y changent rien. Exemple : `delta * 2` reste à 1,017 alors que le delta vaut 0,395.
- **J6** : l'import d'un `.ld` convertit les 184 canaux en listes Python (`motec_ld.py:209`).
  - Un log d'une heure prend environ 45 s et 1 Go.
  - Un `.ld` piégé de 400 Ko prend 18 s et 472 Mo.
  - Si le processus de travail meurt, le travail est relancé dans l'app elle-même (`lap_backend.py:713`), avec un risque de gel ou de manque de mémoire. Ensuite, un export de tous les tours lance un fil par tour.
- **J7** : supprimer dans la bibliothèque des tours importés échoue au milieu si un fichier est verrouillé (`PermissionError`, `lap_library.py:194`). La bibliothèque et la visionneuse restent alors désynchronisées. La suppression est de plus définitive, sans corbeille ni annulation.

### 🟠 Moyens
**Clavier et interface**
- **J8** : à l'ouverture, le clavier va dans la liste des circuits et non dans les graphiques (`LapViewer.qml:130-201`). `↓` change de circuit et recharge les tours, `Espace` ne lance pas la lecture. C'est pareil après avoir choisi un circuit et avec les listes de l'onglet XY.
- **J9** : `Ctrl+Z` reste actif quand la page est cachée (`LapViewer.qml:29`). Depuis l'accueil, il restaure les tours supprimés. Dans Driver Stats, il bloque le `Ctrl+Z` de la page.
- **J10** : la recherche dans la liste des tours supprime l'espace final après 250 ms (`LapList.qml:142` + `strip()`). « porsche 963 » devient « porsche963 ».
- **J11** : la largeur de la liste n'est jamais restaurée : `layoutState.length` est indéfini sur un `ArrayBuffer`, il faut `byteLength` (`LapViewer.qml:465`). Vérifié.
- **J12** : la grande carte (mode focus) n'a jamais le focus clavier (`LapViewer.qml:550`). `Échap`, `R`, `F` et `1-9` agissent sur le graphique caché.
- **J13** : `Échap` sur la carte latérale ferme la visionneuse quand elle est ouverte en fenêtre séparée (`TrackMap.qml:255`).
- **J14** : la lecture continue quand la page est cachée, à environ 62 appels Python par seconde (`TraceChart.qml:427`).
- **J15** : le menu des canaux remonte en haut à chaque case cochée (94 canaux, `LapViewer.qml:327`).
- **J16** : la liste des tours remonte en haut à chaque nouveau tour enregistré, à chaque « Garder », note, suppression ou annulation : le modèle est remis à zéro (`fill_list` → `reset`).

**Sélection et chargement**
- **J17** : un tour du circuit courant ajouté par `Add File...` apparaît deux fois, dans la liste et dans la légende : les chemins mélangent `/` et `\` (`add_external`).
- **J18** : quand la référence est un tour ajouté, la sélection est perdue au rafraîchissement, au changement de circuit ou à la réouverture. Elle est remplacée par meilleur + dernier tour (`load_track` / `save_selection`).
- **J19** : `check_jobs` évalue `is_alive()` deux fois (`lap_backend.py:709`). Un travail qui se termine entre les deux n'est jamais traité : indicateur d'occupation bloqué, onglet Session ou mini-secteurs jamais mis à jour.
- **J20** : `Maj` + clic sur une plage coche aussi les tours des sessions repliées, qui restent invisibles (`selectRange`).
- **J21** : l'alignement sur un virage, le virage sélectionné, les repères A/B et le tour comparé sont gardés au changement de circuit.
- **J22** : supprimer pendant un chargement : si un fichier est verrouillé, les graphiques ne sont jamais redessinés, et `Annuler` ne restaure qu'une partie de la suppression.
- **J23** : choisir à nouveau un tour déjà listé dans la bibliothèque ou réimporter le même `.ld` ne fait rien de visible (`add_external`).

**Calculs**
- **J24** : dans l'onglet Session, les relais ne sont séparés que par les tours de sortie et de rentrée, qui ne sont pas enregistrés par défaut (`stint_analysis.split_stints`).
  - Exemple : session du 03/10 à Road Atlanta, avec 3 ravitaillements, comptée comme 1 relais.
  - La tendance est calculée sur la position du tour dans la liste et non sur son numéro : −0,129 s/tour au lieu de −0,060 s/tour.
- **J25** : la fin du tour est perdue pour la moitié des tours MoTeC importés : `track_length` est arrondi vers le bas (`motec_import.py:295`). Les mini-secteurs et le delta à la ligne sont faux de 0,04 s.

**Carte et virages**
- **J26** : des écarts par virage manquent sur la carte (`official_points`, `lap_map_view.py:409`).
  - Au Mans, les Esses et le virage à 12 240 m n'apparaissent pas.
  - « Maison Blanche » affiche la valeur d'un autre virage.
- **J27** : si le tour de référence n'a pas de positions (ton `.ld` McLaren), les modes gain et ligne n'affichent rien. Les repères de virages, la zone A–B et le clic sur la carte utilisent alors le tour comparé.
- **J28** : au Mans, « Forest Esses » est placé au pli de 1 105 m au lieu de l'apex vers 1 450–1 590 m. « Indianapolis » est aussi mal placé (`track_corners.py:111`).

**Import, export et bibliothèque**
- **J29** : `Import Folder...` prend n'importe quel `.csv` pour un tour : `notes.csv`, exports CSV de la visionneuse, vieux tours sans en-tête.
- **J30** : la protection contre l'import de son propre dossier fonctionne mal (`startswith`, `lap_library.py:153`). Choisir un dossier parent importe tes propres tours comme tours étrangers, et un dossier voisin `telemetry_mate` est refusé.
- **J31** : la limite de 2 000 fichiers est comptée avant le filtre circuit/catégorie. Chez un coéquipier qui a beaucoup de circuits, on obtient « aucun tour de ce circuit ».
- **J32** : réimporter le même dossier crée un groupe « (2) » et recopie tout. Il y a déjà un doublon de lap015 dans ton dossier `.imported`.
- **J33** : un log MoTeC sans « Lap Number » est importé comme un seul tour (`motec_import.py:246`). Exemple : 3,5 tours deviennent un tour de 210 s nommé `0m29.950s`, qui devient la référence.
- **J34** : un log MoTeC dont la distance est cumulée (compteur kilométrique) donne des tours décalés, écartés comme « autre circuit ».
- **J35** : « Reference Lap as Delta Best... » ne fait rien, sans message, quand la référence est un tour importé. C'est le cas juste après un import MoTeC ou un ajout depuis la bibliothèque.
- **J36** : la copie `.bak` du delta best est écrasée à chaque utilisation : le delta best d'origine est perdu dès la deuxième fois.

### 🟡 Mineurs
- **J37** : `format_laptime(119.9996)` donne « 1:60.000 », ce qui touche le meilleur théorique et le tour idéal. Vérifié.
- **J38** : un échec de lecture passager (antivirus) n'est jamais retenté par Rafraîchir.
- **J39** : si le tour de référence est illisible, l'étoile reste dessus alors que les graphiques utilisent un autre tour.
- **J40** : `Annuler` après la suppression de la référence ne restaure pas la référence.
- **J41** : le circuit officiel reçu du jeu est jeté si on a changé de circuit pendant la requête, et il n'est pas redemandé.
- **J42** : `LapData.lap_time` donne le dernier échantillon et non le temps officiel. Écarts de setup et écart « Ideal Lap » faux de 17 ms (73 ms pour un tour importé). Un « +0,01 » rouge s'affiche alors que la référence est la plus rapide partout.
- **J43** : le gain/perte de temps est sous-estimé jusqu'à 50 % dans les 75 premiers et derniers mètres du tour (`delta_rate`).
- **J44** : l'usure devient négative dans l'onglet Session quand les pneus sont changés pendant un tour enregistré.
- **J45** : les lignes « Straights » et « Total » sont absurdes avec un tour partiel (−75,66 s).
- **J46** : le mode carte « corners » garde les couleurs du tour comparé précédent (`lap_corners.py:83`).
- **J47** : l'export MoTeC interpole le rapport, le secteur et le TC, ce qui donne des valeurs comme 2,33, 1,5 ou 0,5.
- **J48** : lien vers le rejeu.
  - Tous les tours MoTeC importés pointent vers la fin du log.
  - Un rejeu interrompu est supposé durer 24 h.
  - La position arrive jusqu'à 1 s trop tôt.
- **J49** : les tours importés sont écrits sans fichier temporaire, et ceux de la bibliothèque ne sont pas attendus à la fermeture. Un tour peut donc rester tronqué.
- **J50** : le curseur de détection des virages ne réagit pas aux flèches du clavier (`CornerList.qml:39`).
- **J51** : en zoom fort, les libellés d'axe sont dupliqués (« 1501 m » deux fois) et « 1:60 » peut s'afficher.
- **J52** : les caches `.track_maps` et `.track_limits` ne sont jamais invalidés : ni version d'algorithme, ni version du circuit dans le jeu.

### ⚙️ Performance
- **J53** : revenir sur un circuit avec 5 tours du Mans bloque l'interface environ 1 s. Répartition : carte 0,3 s, courbes 0,14 s, et 0,2 s pour le cercle G et les virages, calculés même quand leur onglet est caché.
- **J54** : les traînées de la carte sont reconstruites à chaque mouvement de souris : 8,7 ms par mouvement avec 31 tours, soit 97 % du coût du curseur.
- **J55** : la liste crée des éléments pour les tours des sessions repliées : avec 360 tours, 199 éléments sont créés pour 31 visibles, et la recherche prend 148 ms.
- **J56** : `chartChanged` sert à tout. Redimensionner un panneau recrée 164 éléments QML et relit une vingtaine de propriétés calculées.
- **J57** : 6 tours du Mans × 58 canaux prennent environ 100 Mo en séries, contre 12 Mo pour les tours eux-mêmes : listes de distances recopiées pour chaque canal, valeurs en `float` Python.
- **J58** : quand la page est cachée, chaque nouveau tour recharge et redessine tout pendant que tu roules, ce qui annule la libération de la mémoire.
- **J59** : la recherche du point le plus proche sur la carte dézoomée prend 28 ms par geste au Mans (`LineGrid.nearest`).
- **J60** : avec 600 tours dans un circuit, la première ouverture prend 2,4 s, à cause de la lecture des en-têtes dans l'interface.

### 💡 Améliorations
- **J61** : mode live. Un nouveau meilleur tour n'est comparé à rien : il faudrait le comparer à l'ancien meilleur. La référence choisie est remplacée à chaque tour. Seul le circuit ouvert est surveillé.
- **J62** : import MoTeC. Des canaux du log LMU sont ignorés : températures eau et huile, températures pneus intérieur/centre/extérieur, répartition de freinage, charge des pneus. La date, le numéro et le temps exact du tour sont perdus : la date est celle de la copie du fichier.
- **J63** : bibliothèque. Ajouter une corbeille avec annulation, comme dans la visionneuse, et nettoyer les caches orphelins.
- **J64** : un tour écarté parce qu'il vient d'un autre circuit n'est signalé que 8 s. Il faudrait une ligne grisée avec une infobulle.
- **J65** : afficher des états vides quand la recherche ne trouve aucun tour ou aucun canal.
- **J66** : clavier AZERTY. Les touches 1-9 de la carte demandent `Maj`, et 6 et 8 dézooment (non reproduit hors écran).
- **J67** : autoriser le delta best depuis un tour importé d'un coéquipier sur le même circuit.

### Vérifié et correct
- Les canaux calculés sont sûrs : arbre syntaxique avec liste blanche, jamais d'`eval`.
- Le cache des tours est sans `pickle`, avec des tailles vérifiées et une version à jour.
- Le format écrit par l'enregistreur et celui lu par la visionneuse concordent.
- Sur les tours enregistrés, le delta et les mini-secteurs sont exacts.
- Les conversions d'unités sont justes.
- Pas d'avertissement QML, traductions complètes.
- Les travaux de la carte et des limites qui finissent après un changement de circuit sont ignorés.
- Le survol des courbes est rapide (0,2 ms).
