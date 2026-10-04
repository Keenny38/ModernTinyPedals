# Changelog

Toutes les nouveautés de **Modern Tiny Pedals**, la version la plus récente en premier.
La liste détaillée des commits de chaque version est aussi sur la page [Releases](https://github.com/Keenny38/ModernTinyPedals/releases).

## 0.17.0 (2026-10-04)

### Visionneuse de télémétrie refaite

La visionneuse est entièrement refaite en Qt Quick : courbes, carte et cercle G sont dessinés par la carte graphique.

- **Fluide** : zoom et déplacement animés, à la fréquence de l'écran. Avant, chaque cran de molette demandait environ 160 ms de dessin.
- **Navigation** : mini-courbe du tour entier sous les graphes pour voir et déplacer la partie zoomée, bouton `Reset`, `Maj` + glisser pour zoomer une zone, glisser le nom d'une voie pour la déplacer.
- **Liste des tours** : sessions repliables, couleur de chaque tour, badge `RÉF`, drapeau (ou double-clic) pour choisir la référence, `Tours propres` pour masquer les tours invalides, de sortie et de rentrée.
- **Clic droit sur un tour** : référence, export MoTeC, garder, note, supprimer.
- **Barre d'outils** : légende des tours, `Imported Laps...`, menu `Export` (MoTeC : tour de référence, tours affichés ou tous les tours du circuit ; CSV pour Excel).
- **Onglet Virages** : barre de temps gagné/perdu par virage et, sous chaque virage, point de freinage, plein gaz, freinage dégressif, roue libre et chevauchement des pédales.
- **Mémoire** : les tours chargés sont libérés après 3 minutes en arrière-plan, puis rechargés avec le même zoom.

![Visionneuse de télémétrie](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-telemetry-viewer.png)

### Carte de trajectoire

- **4 colorations** : par tour, gain/perte de temps face au tour de référence, vitesse (du plus lent au plus rapide, avec l'échelle) ou pédales (gaz, frein, les deux, roue libre).
- **Suivre le zoom** : la carte zoome toute seule sur la partie du tour zoomée dans les courbes.
- **Points de freinage** de chaque tour.
- **Circuit soigné** : route avec bordure, ligne de départ en damier, limites de secteurs, échelle et boutons de zoom.
- **Virages cliquables** avec le temps gagné ou perdu par le tour comparé : un clic zoome les courbes sur le virage.

### Vrais numéros de virages

Les virages portent leur numéro officiel (`T1`, `T10a`…, `V1` en français) sur les courbes, la carte et l'onglet Virages, au lieu d'un numéro dans l'ordre du tour.

- **Circuits** : Silverstone, Imola, Spa-Francorchamps, Circuit of the Americas, Interlagos, Paul Ricard (tracé F1), Monza, Bahreïn, Portimão, Lusail, Road Atlanta, Laguna Seca et Long Beach. Au Mans, sans numérotation officielle, les virages sont nommés (Dunlop, Tertre Rouge, Mulsanne, Indianapolis, Arnage, Virages Porsche, Chicanes Ford).
- **Placés sur le vrai tracé** : chaque virage est calé sur l'apex du virage correspondant de ton tour (ou de la carte du circuit). La carte montre tous les virages, même ceux passés à fond, et un virage détecté qui en couvre plusieurs s'appelle `T2-4`.
- Les autres circuits et tracés gardent la numérotation dans l'ordre du tour.

![Onglet Virages](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-corners.png)

### Track Map Viewer refait

- **Carte dessinée par la carte graphique** : route à sa vraie largeur, ligne colorée par secteur (longueur de S1, S2 et S3), ligne de départ, limites de secteurs, virages officiels (un clic y amène la position).
- **À la position** : section de courbe, cercle osculateur, cercles de distance et repère central ; infos de position (virage, nœud, secteur, XYZ), de courbe (« Droite 3 », rayon, longueur, angle) et de pente.
- **Profil d'altitude** de tout le tour, cliquable, avec la position.
- **Navigation** : clic sur la carte, curseur, flèches du clavier, bouton `Play` pour parcourir le circuit, `Suivre la position` pour garder la position au centre.
- Menu `Afficher` pour chaque élément ; couleurs, largeurs et seuils de courbe de la configuration existante conservés.

![Track Map Viewer](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.17.0-track-map-viewer.png)

### Et aussi

- L'app ne s'alourdit que de 20 Mo pour Qt Quick : seuls les modules utilisés sont embarqués (sans ça, plus de 300 Mo).

## 0.16.0 (2026-10-04)

### Calculateur de course (nouveau)

Le calculateur de carburant et la stratégie pneus ne font plus qu'un outil, **Calculateur de course** (entrée « Course » de la barre de navigation). Les anciennes entrées de la barre et les pages ouvertes s'y redirigent toutes seules.

- **Une page, deux onglets** : réglages de course et chiffres clés en haut, communs, puis onglets **Carburant** et **Pneus**. Tout est en français, s'adapte aux petites fenêtres et se recalcule dès qu'une valeur est validée (Entrée ou en quittant le champ).
- **Plan d'arrêts tour par tour** : à chaque arrêt, tour, carburant et énergie à remettre (plein tant que d'autres relais suivent, juste ce qu'il faut au dernier), pneus, pilote et durée de l'arrêt. Bouton `Copier` pour le partager en texte.
- **Frise de stratégie** : un bloc par relais, tours d'arrêt au-dessus (en orange quand on change de pneus), lisible même en course de 24 h.
- **Chiffres clés** : carburant et énergie de la course, arrêts (et ce qui les impose : carburant, énergie ou durée des relais), relais le plus long, plein moyen par arrêt (ou carburant à charger quand il n'y a pas d'arrêt), pneus utilisés sur le maximum autorisé.
- **Course au temps juste** : carburant et énergie partagent les mêmes arrêts, et le nombre de tours dépend vraiment du temps perdu aux stands (ravitaillement, pneus, changement de pilote).
- **Marge de sécurité** en tours, gardée à chaque arrêt et à l'arrivée.
- **Arrêts au stand réalistes** : débit de ravitaillement carburant et énergie (un complément coûte moins qu'un plein), pneus changés pendant le ravitaillement ou après, temps de changement de pilote.
- **Règlement** : arrêts obligatoires, durée maximale d'un relais, pilotes qui se relaient.
- **Rythme** : effet du carburant sur le temps au tour et évolution de la piste au fil des heures.
- **Objectif d'économie** : consommation à tenir pour gagner un arrêt, ou pour faire un nombre de tours par relais.
- **Voitures à énergie seule** planifiées sur l'énergie.
- **Remplissage intelligent** depuis le direct ou un fichier : moyenne des 5 derniers tours valides au rythme course (tours de stand écartés). En direct, la longueur de la course est reprise de la session, l'historique se met à jour tout seul, et l'option `Suivre le direct` met aussi à jour les saisies.
- **Historique de consommation** : tri par colonne, filtre `Tours valides seulement`, sélection par tours entiers (tours invalides ignorés), bouton `Colonnes`, et suppression de tours ou de tout l'historique (`Supprimer la sélection`, `Tout supprimer`).
- **Plan pneus relié à la stratégie** : une ligne par relais, temps de changement de pneus ajouté à l'arrêt, usure = usure par tour x tours du relais, ajustée selon la gomme (`Gomme mesurée`).
- **`Proposer les changements`** : pneus neufs roue par roue au relais où la gomme passerait sous le minimum (2 pneus quand un seul essieu en a besoin), dans la limite des pneus autorisés ; s'il en manque, les meilleurs pneus usés sont remontés et les relais concernés signalés.
- **Plan pneus gardé d'une session à l'autre**, avec annuler / rétablir (`Ctrl+Z` / `Ctrl+Y`) ; en tapant une valeur, les lignes ne sont plus perdues.
- **Fichier plan de course** (`.race-plan`) : réglages, saisies et plan pneus dans un seul fichier, à garder ou partager avec l'équipe. Toutes les saisies sont aussi retrouvées à la réouverture, et `Remettre à zéro` les efface.

### Widget Plan de course (nouveau)

- **Le prochain arrêt en jeu** : tour de l'arrêt et tours restants (mis en évidence à l'approche), carburant et énergie à remettre, pneus à changer, arrêts restants. Le plan est refait à partir des saisies du calculateur, même fermé.

### Black box

- **Plus aucun chevauchement** : pneus, disques et suspensions qui braquent et bougent avec la suspension ne passent plus sur les LEDs RPM, les pastilles TC/BB/MAP ni les températures de freins. La place est réservée au braquage maximum, l'arrière braquant moins, et le débattement dessiné est plafonné.

### Statistiques pilote

- **Page modernisée** : chiffres clés du circuit (meilleur tour et sa voiture, niveau, distance, temps de conduite, tours valides, courses), tableau lisible, carte de référence de la voiture sélectionnée.
- **Comparaison aux temps de la communauté** (feuille LMU d'[ohne_speed](https://www.youtube.com/@ohne_speed)) : chaque record est placé sur une échelle de niveaux, d'**Alien** à **Hors rythme**, avec son écart en % au temps de référence de la catégorie et la voiture la plus rapide. Les noms de circuits LMU et leurs variantes sont reconnus automatiquement. La feuille est téléchargée une fois par jour et gardée hors ligne ; menu `Référence` pour l'actualiser, changer de feuille ou désactiver la comparaison.

### Mises à jour

- **Page « Nouveautés » modernisée** : version et date de publication en en-tête, une carte par thème, détails techniques (commits, empreintes SHA256) repliés, texte adapté à la taille de la fenêtre.
- **Bouton `Télécharger et installer` toujours disponible** (téléchargement dans le navigateur quand l'installation automatique n'est pas possible). La demande d'installation d'une nouvelle version utilise la même page.
- **Messages de mise à jour traduits** (« Nouvelle version : v… », « Aucune mise à jour disponible »).

### Interface

- **Retour sur la dernière page au redémarrage**, même après un plantage ou un arrêt de Windows : la page affichée est enregistrée dès qu'elle change, plus seulement en quittant par le menu.
- **Palette de commandes** : chercher « carburant », « stratégie pneus » ou « fuel calculator » trouve le Calculateur de course.

## 0.15.0 (2026-10-04)

### Visionneuse de télémétrie (Telemetry)

- **Unités de tes réglages** : vitesse (km/h, mph), températures (°C, °F), pressions (kPa, psi, bar) et carburant (litres, gallons). Pédales et volant en pourcentage.
- **Axes gradués** : distance sous les courbes, valeurs haute et basse de chaque courbe.
- **Valeurs au curseur dans chaque courbe**, une étiquette colorée par tour, et la ligne du haut colorée comme les tours.
- **Virages numérotés (T1, T2…)** sur les courbes et sur la carte.
- **Clic sur la carte** pour placer le curseur à cet endroit dans les courbes.
- **Rapport engagé dessiné en marches d'escalier.**
- **Courbe « Gain/Perte de temps »** : où le temps se perd ou se gagne face au tour de référence, en secondes par 100 m.
- **Axe en temps** (au lieu de la distance), la partie zoomée du tour est conservée.
- **Analyse de pilotage par virage** (onglet Virages) : freinage dégressif, roue libre et chevauchement gaz / frein des deux tours.
- **Noms de tours clairs partout** : « Tour 12 · 1:11.525 · Course 03/10 » dans la légende.
- **Liste des tours** : étoile sur le meilleur tour de chaque session, option pour masquer les tours invalides, de sortie et de rentrée, tours ajoutés regroupés par log.
- **Garder un tour** (jamais supprimé par l'enregistreur), **note par tour** et **suppression** depuis le clic droit.
- **Tours cochés et tour de référence mémorisés** par circuit.
- **Export CSV pour Excel** des courbes affichées (virgule décimale et point-virgule si Windows est en français).
- **Plus fluide** : à partir de 3 tours à lire, chargement en arrière-plan sans figer la fenêtre, et « Actualiser » ne relit que les tours modifiés.

## 0.14.0 (2026-10-04)

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

- **Black box** : pressions cibles des pneus en psi ou bar.
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
- Le changelog de chaque version s'affiche en tête des notes de release et dans `Voir les nouveautés` de l'app.

## 0.13.0 (2026-10-03)

- **Black box** : ABS, TC, répartition de freinage et carte moteur en pastilles entre les roues droites.
- Notes de release avec images avant / après des changements d'overlay.
- Correction de la vérification de types avec mypy 2.4.

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
