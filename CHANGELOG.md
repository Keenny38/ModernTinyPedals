# Changelog

Toutes les nouveautés de **Modern Tiny Pedals**, la version la plus récente en premier.
La liste détaillée des commits de chaque version est aussi sur la page [Releases](https://github.com/Keenny38/ModernTinyPedals/releases).

## 0.13.0 (2026-10-04)

### Tout dans la fenêtre de l'app

- **Outils, éditeurs et réglages s'ouvrent comme des pages** dans la fenêtre principale, plus dans des fenêtres séparées. Les petites saisies (nom de preset, raccourci clavier, code de partage, nom de thème) aussi.
- **Barre de navigation personnalisable** (clic droit > `Personnaliser la barre de navigation...`) : pages et outils au choix, dans l'ordre voulu, avec `Ctrl+1` à `Ctrl+9` pour les 9 premières entrées. Par défaut : Pace Notes retiré, Telemetry, Driver Stats Viewer, Fuel Calculator et Tyre Strategy Planner ajoutés.
- **Les outils de la barre sont des pages comme Widget ou Module** : entrée surlignée quand on y est, pas de bouton Fermer, on les retrouve tels qu'on les a laissés. Échap ne les ferme plus.
- **Bouton « Pages ouvertes »** en bas de la barre (visible seulement s'il y en a) pour retrouver ou fermer les autres pages (réglages, outils hors barre).
- **Les icônes de la barre gardent leur taille** : si la fenêtre est petite, la barre défile (molette ou fine barre de défilement), avec un dégradé et une flèche quand des entrées sont cachées.
- **Retour à la page précédente** avec `Alt+←` ou le bouton souris arrière. Fermer une page ramène à celle d'avant.
- **Pages rouvertes au démarrage** : les outils laissés ouverts reviennent au lancement suivant, après un redémarrage ou un changement de langue (option `Fenêtre > Rouvrir les pages au démarrage`). Elles se rouvrent une fois la fenêtre affichée, sans ralentir le démarrage.
- **La fenêtre s'agrandit pour une page large** (dans la limite de l'écran), garde cette taille pendant la navigation et la reprend quand la page est fermée.
- **Les réglages ne se perdent plus** : fermer une page de réglages modifiée demande d'enregistrer, d'abandonner ou d'annuler, et un enregistrement n'est accepté que si toutes les valeurs sont valides. Les options internes de l'application (position et taille de fenêtre, barre...) ne sont plus affichées.
- **Changement de langue sans perte** : les pages de réglages et les pages avec des modifications non enregistrées sont gardées telles quelles.
- **Pastilles de couleur par catégorie** dans la liste des widgets, et statuts dans le gestionnaire de plugins.

### Telemetry (visionneuse de tours)

- **Tours regroupés par session** : une ligne repliable par session (type, date et heure de début, meilleur tour, nombre de tours, voiture), la plus récente en haut. Tours dans l'ordre (« Tour 1, Tour 2... »), tours invalides, de sortie et de rentrée grisés. Les tours enregistrés à partir de cette version gardent l'heure de début de session.
- **Comparaison virage par virage** (onglet Virages) : temps perdu ou gagné, vitesse mini, point de freinage et point de plein gaz pour chaque virage, plus une ligne pour les lignes droites et le total. Clic sur un virage pour zoomer dessus, sensibilité de détection réglable.
- **Trajectoire colorée selon le temps gagné ou perdu** face au tour de référence (rouge où l'on perd, vert où l'on gagne), avec légende.
- **Import de logs MoTeC `.ld`** (celui de LMU par exemple) pour se comparer au tour d'un autre pilote : temps au tour calculé au passage de la ligne, canaux principaux importés.
- **Bibliothèque des tours importés** : importer, rechercher (circuit, voiture, pilote, date, temps), afficher, renommer, supprimer. Un `.ld` déposé sur l'app est importé directement et affiché.
- **Limites de secteurs** placées aux temps de secteur officiels du jeu.
- **Moins de mémoire** : après 3 minutes en arrière-plan, les tours chargés sont libérés, puis rechargés avec le même zoom au retour.

### Overlay

- **Black box** : ABS, TC, répartition de freinage et carte moteur en pastilles entre les roues droites, et pressions cibles des pneus en psi ou bar.
- **Standings et Relative plus rapides à dessiner** (mise en cache du texte et des fonds de cellules).
- **Cellules transparentes** : plus d'effet de relief sur les cellules au fond entièrement transparent.

### Corrections

- La lecture des pace notes ne s'arrête plus quand la page est cachée.
- La migration des anciens presets ne plante plus quand une option manque.
- Une carte SVG qui n'a pas été créée par l'app est signalée comme invalide au lieu de provoquer une erreur.
- L'éditeur ne revient plus à d'anciennes données après une réinitialisation.
- Le pilote suivant en mode spectateur revient bien au leader après le dernier.
- Une fenêtre d'aperçu de widget déjà supprimée ne provoque plus d'erreur.
- Textes traduits qui manquaient : verrouillage de preset, raccourcis activés/désactivés, choix de preset, historique du Fuel Calculator.
- Les pages cachées mettent leurs rafraîchissements en pause.

### Qualité

- **1200 tests automatisés**, 85 % du code couvert (seuil minimum relevé à 81 %, identique sous Linux et Windows).
- Nouveaux tests pour la migration des réglages, les modules Relative et Wheels, le widget Track Map, les pages Presets et Raccourcis, le Fuel Calculator, les connecteurs REST API et rF2, le démarrage de l'app.
- Signature de la release avec Azure Artifact Signing quand elle est configurée.
- Notes de release avec images avant / après des changements d'overlay.

## 0.12.2 (2026-10-01)

- Correction : les outils (Telemetry, éditeurs, replay) ne s'ouvraient pas dans la version installée.
- Image d'aperçu du README avec tous les widgets sur des données de course réalistes.

## 0.12.1 (2026-10-01)

- Telemetry : améliorations de l'enregistreur de tours, de la visionneuse, du replay et du flux de données.

## 0.12.0 (2026-10-01)

- Fenêtre miroir VR pour les jeux OpenXR, via les overlays de capture de fenêtre (OpenKneeboard...).
- Code de partage de preset : copier un preset en texte, l'importer avec un aperçu.
- Carte de trajectoire dans la visionneuse de tours, comparant les deux tours au curseur et la partie zoomée.
- Replay de télémétrie pour rFactor 2 et LMU, données REST API enregistrées dans les replays.
- Packs de langue JSON et générateur de modèle pour ajouter une langue sans code.
- Mode d'édition visuel : contour, nom et poignée de redimensionnement des widgets déverrouillés.
- Échelle globale de l'overlay, annuler / rétablir dans les réglages.
- Page d'accueil (jeu, preset, widgets, overlay et version d'un coup d'œil), palette de commandes (`Ctrl+K`) et filtre par catégorie.
- Notifications (toasts), import de presets, paquets et plugins par glisser-déposer.
- Widgets affichés selon la session et le contexte des stands, avec fondu.
- Positions des widgets mémorisées par configuration d'écrans.
- Export et import des thèmes d'overlay, aperçu des widgets au survol de la liste.
- Thème clair / sombre du système suivi, fenêtre maximisable.
- Widgets cachés plus mis à jour, rafraîchissement plus lent par défaut pour les widgets qui changent peu.

## 0.11.0 (2026-10-01)

- Page Outils et actions rapides dans la barre de navigation, assistant de configuration affiché une seule fois.

## 0.10.2 (2026-10-01)

- Proposition d'installer les mises à jour dès qu'elles sont détectées.

## 0.10.1 (2026-10-01)

- Style visuel de la Black box appliqué à tous les overlays, listes de widgets triées par ordre alphabétique.

## 0.10.0 (2026-10-01)

Première version de Modern Tiny Pedals, basée sur TinyPedal 2.50.0.

- Installateur Windows et installation des mises à jour depuis l'app.
- Éditeur de disposition pour placer les widgets sur une capture du jeu.
- Black box : phares et état moteur, source du delta et des pédales, répartition de freinage, réglages, analyse du freinage, enregistreur d'incidents, suspensions en direct et angles de roue réels.
- Mises à jour et changelog via GitHub Releases.
- Corrections : sonde de l'hôte local, plantage REST API, valeurs de télémétrie non finies, réglages texte / booléens refusés, accès à des widgets supprimés.

Changelog de TinyPedal jusqu'à la version 2.50.0 : [docs/changelog.txt](docs/changelog.txt).
