# Audit & feuille de route — TinyPedal 2.50.0 (fork modernisé)

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
- Nouveau widget `Wheel status` (Roues et freins).

Bilan : 295 tests, ruff et mypy propres (222 fichiers).

## D. Idées suivantes (27/09/2026)

### Widget « Roues et freins »
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

Réalisé (27/09/2026) : D1, D2, D4 à D12 dans le widget « Roues et freins » (D3 non demandé).

## E. Audit du widget « Roues et freins » (28/09/2026)

Audit dédié du fichier `tinypedal/widget/wheel_status.py` (640 lignes exécutables, 114 options, 98 % de couverture de tests après corrections ; 2ᵉ widget le plus lourd sur 77 au benchmark).

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
17. Conversion des seuils de pression cible selon l'unité choisie (psi) — pas fait, mineur, les seuils restent en kPa comme documenté.

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
