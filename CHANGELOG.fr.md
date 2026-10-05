# Journal des modifications

Toutes les nouveautés de **Modern Tiny Pedals**, la version la plus récente en premier. English version: [CHANGELOG.md](CHANGELOG.md).
C'est ce fichier que l'app affiche dans la page `Nouveautés` quand elle est en français. La liste détaillée des commits de chaque version est sur la page [Releases](https://github.com/Keenny38/ModernTinyPedals/releases).

## 0.20.0 (2026-10-05)

Un audit complet de l'app : plus de 150 corrections, 7 nouveaux overlays, le design moderne au niveau de l'ancien, de nouvelles données de Le Mans Ultimate dans les overlays, les pages Calculateur de course, Statistiques pilote, Overlays et Rejeux du jeu refaites, beaucoup d'outils en plus dans la visionneuse, et les notes de version dans la langue de l'app. Plus de 2 300 tests vérifient maintenant 91 % du code.

### Nouveaux overlays

Tous sont désactivés par défaut, à activer dans l'onglet `Overlays`.

- **Graphique de delta** : le delta tout au long du tour (perte en rouge, gain en vert) avec le tour précédent en fond. Référence au choix : meilleur tour, session, relais ou dernier tour.
- **Tendance des écarts** : écart à la voiture devant et derrière sur les derniers tours, avec ce que tu reprends ou perds par tour. Toutes classes ou dans ta classe.
- **Aide en voie des stands** : vitesse face à la limite, limiteur (alerte s'il n'est pas mis), distance jusqu'au box et services prévus. Visible seulement à l'approche et dans la voie des stands.
- **Minuteur de relais** : temps et tours du relais, compte à rebours avant le relais maximum, temps de conduite de chaque pilote face à la part équitable ou au minimum imposé.
- **Spotter** : barres sur les bords de l'écran quand une voiture est à côté de toi, plus vives quand elle est très proche.
- **Alertes de course** : places gagnées ou perdues (générale et classe), pénalité, meilleur tour de la classe, drapeau bleu, neutralisation, tour invalidé. Chaque type se coupe séparément.
- **Tendance des températures pneus** : température de chaque pneu sur les dernières secondes ou par tour, avec la température idéale donnée par LMU.

![Nouveaux overlays](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-nouveaux-overlays-course.png)

![Aide en voie des stands](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-aide-voie-des-stands.png)

### Design moderne : tout ce que faisait l'ancien

- **Classements** : colonnes tour moyen, speed trap, lift & coast et logo de la marque, gommes roue par roue quand elles diffèrent, textes personnalisés (stands, garage, leader), position dans la classe à la couleur de la classe.
- **Plan de course** : recalcul en direct, contrôle du menu des stands du jeu (`80>60L` en rouge s'il diffère du plan), conso cible par tour, et en option ce qui limite les relais et la méthode d'estimation de la conso.
- **Ordre des lignes** : les options `display_order_*` s'appliquent au design moderne dès que tu en changes une, et le bouton `Ordre d'affichage` est de retour.
- Couleurs réglables des overlays redessinés (radar, carte, drapeaux…), repère du ressort central (suspension), repère de la pédale (pression de frein), régime, batterie et conso sur le rapport engagé, indicateur 100 % des pédales, noms de session personnalisés, style inversé du delta, dégâts en intégrité.

![Classements : nouvelles colonnes](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-classements-nouvelles-colonnes.png)

### Le Mans Ultimate : nouvelles données dans les overlays

- **Delta officiel du jeu** dans le delta best (option), **tour invalidé** signalé sur les chronos.
- **Crevaison** lue dans le jeu (au lieu d'une estimation par l'usure), **surchauffe moteur**.
- **Heatmap automatique** des pneus centrée sur la température idéale donnée par le jeu (option).
- **Drapeaux jaunes par secteur** et phases de neutralisation (FCY), **vent** dans la météo, **hauteur de caisse** avant et arrière, **rappel du limiteur** dans la voie des stands.

![Race plan, météo et rapport](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-overlays-nouvelles-tuiles.png)

### Visionneuse de télémétrie

#### Courbes

- **Valeurs ajustées à la partie visible**, panneau par panneau (clic droit sur un panneau).
- **Canaux calculés à toi** : formule à partir des canaux enregistrés (`+ - * /`, `abs`, `min`, `max`, dérivée `d()`), avec angle de sous-virage, vitesse de relâchement du frein et vitesse d'ouverture des gaz déjà prêts.
- **Aligner les tours sur un freinage** : les courbes sont décalées pour que les freinages d'un virage partent au même endroit.
- Export CSV sur une base de temps.

#### Carte et vues

- Zoom au clavier (`+` / `-`, flèches), zoom et filtre des tours dans le cercle G et la vue XY.
- **Régularité par mini-secteur** : chaque mini-secteur coloré selon l'écart de ses temps sur le relais, la session ou les tours affichés.

#### Comparer

- **Import des tours d'un coéquipier** depuis un autre dossier (même circuit et même classe), marqués comme étrangers.
- **Meilleur tour dans des conditions proches** (température de piste, gomme, piste mouillée) comme référence.
- **Différences de setup** entre deux tours, et **rapport des virages** en HTML ou PDF.

#### Corrections

- Delta et tour idéal exacts : les extrémités du tour étaient coupées (jusqu'à 0,19 s d'écart sur le delta, 0,4 s sur le tour idéal).
- Un fichier de tour abîmé ne relance plus le chargement en boucle, les tours d'un autre circuit sont signalés et sortis du tour idéal, les repères A/B suivent le passage distance / temps.
- Unité de distance de l'app respectée, virgule décimale en français, import MoTeC en arrière-plan.
- **Lecture du tour fluide** : le curseur avance à chaque image (il se figeait une image sur quatre puis sautait à la suivante), et les graphiques glissent vers la suite du tour au lieu de sauter.

### Calculateur de course

#### Page repensée

- **Nouvelle page moderne** (Qt Quick, comme la page `Overlays`) : réglages de la course, chiffres clés et **frise de la stratégie toujours visibles** au-dessus des onglets `Carburant`, `Pneus` et `Équipe`. La frise montre maintenant le **carburant dans le réservoir** au fil de la course, les tours sous voiture de sécurité et sous la pluie, et ses relais glissent en place quand le plan change.
- **Sections de saisie repliables** (elles restent repliées, leurs valeurs principales affichées dans le titre), interrupteur des scénarios `Voiture de sécurité` et `Pluie` dans leur titre, historique de consommation à côté du plan ou dessous si la fenêtre est étroite.
- **Saisie plus rapide** : `Haut` / `Bas` (ou la molette dans le champ sélectionné) changent une valeur d'un pas, `Maj` de dix pas, `Échap` annule la saisie, temps au tour saisi dans un seul champ (`1:59.950` ou en secondes).
- **Plan pneus** : glissez un pneu du stock sur une roue ou cliquez une roue pour en choisir un, gomme au début et à la fin de chaque relais en barre colorée, couleurs des composés, `Suppr` retire un pneu. Actions du stock et règles dans des menus compacts.
- **Historique de consommation** : sélection avec `Ctrl` / `Maj`, `Ctrl+A`, double-clic pour ajouter un tour, `Suppr` supprime les tours sélectionnés.
- **Plus léger** : la page est construite à son premier affichage, les onglets `Pneus` et `Équipe` à leur première ouverture, et seules les parties des résultats qui changent sont redessinées. L'image du plan (`Enregistrer l'image...`, `Copier l'image`) a toujours la même taille, quelle que soit la taille de la fenêtre.

![Calculateur de course : stratégie, carburant dans le réservoir et plan d'arrêts](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-race-calculator.png)

![Calculateur de course : plan pneus et stock](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-race-calculator-tyres.png)

#### Stratégie

- **Relais limités par la durée de vie des pneus** : tours par train de pneus, changements de pneus placés dans le plan.
- **Pilote de chaque relais** enregistré aux arrêts, affiché dans « Plan face à la course ».
- Unité du carburant (L / gal) sur le plan, **copier l'image du plan** pour Discord.
- Les codes de partage gardent l'unité du carburant : un plan en gallons n'est plus lu en litres.
- Corrigé : le compteur d'arrêts repartait à zéro chaque seconde en course, et le relais en cours se comptait depuis l'arrêt prévu au lieu de l'arrêt réel.

### Statistiques pilote

#### Page repensée

- **Le nom du circuit en titre de page** avec l'essentiel d'un coup d'œil : nombre de véhicules et de sessions, date de dernière sortie, un badge `Direct` sur le circuit de la session en cours dans le jeu, et un bouton de retour à `Tous les circuits` (`Alt+←`).
- **Chiffres clés avec icônes** : le niveau affiché avec sa lettre, les tours valides avec une barre de proportion, les valeurs qui apparaissent en fondu quand elles changent.
- **Échelle des niveaux** du véhicule sélectionné : les six niveaux de `Hors rythme` à `Alien`, la position de ton record, de ton meilleur tour en qualif et en course, l'écart à la référence et le temps à trouver pour le niveau suivant. La liste des niveaux marque tes meilleurs tours avec des badges.
- **Graphique de progression plus large** sous le tableau, à côté de la liste des sessions : grille de temps ronds, ligne du record sur une zone ombrée, lettre du niveau au bout des lignes de limite, tracé de gauche à droite quand tu choisis un autre véhicule. Les sessions affichent leur type (essais, qualif, course) et le podium en couleur.
- **Tous les circuits** : un **calendrier d'activité** des 12 derniers mois (temps de conduite par jour, jours de roulage, plus longue série) et les **sessions récentes** de tous les circuits : un clic ouvre leur circuit et leur véhicule.
- **Tableau** : niveaux en badges colorés, record en gras, valeurs manquantes estompées, ligne sélectionnée marquée, lignes qui glissent à leur place quand on trie. `Suppr` retire le véhicule (ou le circuit) sélectionné, `Retour arrière` revient à `Tous les circuits`, `F5` recharge, `/` cherche un circuit.
- États vides plus clairs, `Supprimer toutes les statistiques de ce circuit` et `Restaurer une sauvegarde` déplacés dans le menu `⋯`, menus en icônes seules quand la fenêtre est étroite.

![Statistiques pilote : échelle des niveaux, progression et sessions](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-driver-stats.png)

![Statistiques pilote, tous les circuits : calendrier d'activité et sessions récentes](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-driver-stats-career.png)

#### Plus rapide

- Trier ne reconstruit plus le tableau (environ 25 fois plus rapide), et les statistiques enregistrées à chaque tour pendant que tu roules rafraîchissent la page 4 à 5 fois plus vite : l'historique des sessions n'est relu que lorsqu'il change.

#### Relais, export et amis

- **Rythme et dégradation par gomme** sur les relais enregistrés, **indice de régularité** par session et par circuit.
- **Export** de l'historique des sessions en CSV ou JSON, et **comparaison avec les statistiques d'un ami** (fichier JSON exporté).

### Carburant et énergie

- **Conso hors neutralisation** (option) : médiane des derniers tours sous drapeau vert, sans les tours sous FCY ou voiture de sécurité, les tours des stands et les tours invalidés.
- Le tour en plus quand le leader passe la ligne avant la fin du temps compte maintenant dans les tours restants.
- Corrigé : « +664 tours » au tour de formation et au premier tour.

### Interface

- **Nouvelle page d'accueil** : version et bouton **`Nouveautés`** de la version installée (lisible hors ligne), mise à jour disponible mise en avant, état du jeu avec la session en cours (circuit, session, position, tour), verrouillage de l'overlay en un clic, dernière session roulée, rappel du réglage du jeu tant qu'il n'est pas lancé, **accès rapide personnalisable** (outils, pages et actions au choix, dans l'ordre voulu, avec `Personnaliser...` ou clic droit). Cartes cliquables et mise en page sur 1 à 3 colonnes selon la largeur.
- **Page `Overlays` repensée** : chaque overlay est une carte avec un **aperçu dessiné avec tes réglages** (redessiné quand tu enregistres ses options), sa catégorie et son interrupteur, ou une liste compacte (aperçu en infobulle) ; la vue choisie est mémorisée. La recherche ignore les accents et la casse et accepte plusieurs mots, les puces de catégorie indiquent combien d'overlays correspondent, filtre `Tous` / `Actifs` / `Inactifs`, liste animée. `Activer les affichés` / `Désactiver les affichés` ne basculent que les overlays filtrés. Un overlay activé qui n'a pas pu démarrer affiche un badge `Erreur`, avec un lien vers le journal. Menu au clic droit, clavier (taper pour chercher, `/`, flèches, `Espace`, `Entrée`). Plus rapide : la page est construite au premier affichage et les aperçus sont dessinés en arrière-plan, seulement quand la page est visible.

![Page Overlays : cartes avec aperçu, recherche et puces de catégorie](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-overlays-page.png)

- **Personnaliser la barre de navigation, l'accès rapide et l'ordre d'affichage** : nouvelle présentation avec les entrées affichées à gauche (numérotées, avec leur raccourci `Ctrl+1` à `Ctrl+9` pour la barre) et les entrées disponibles à droite, classées par type et avec recherche. Glisser-déposer, boutons monter / descendre / retirer sur chaque ligne, `Alt+↑` / `Alt+↓` et `Suppr` au clavier, annuler / rétablir, modifications signalées tant qu'elles ne sont pas enregistrées, `Ctrl+S` pour enregistrer.
- **Modifications non enregistrées** signalées par un point sur la page, la barre de navigation et la liste des pages ouvertes. **`Ctrl+S`** enregistre la page affichée.
- **Les pages ne s'accumulent plus** : une page que tu quittes (réglages, outil hors de la barre de navigation) se ferme toute seule. Seules celles avec des modifications non enregistrées restent ouvertes derrière, listées par le bouton `Pages ouvertes`. Les outils de la barre de navigation restent gardés tels que tu les as laissés.
- **Valeurs vérifiées pendant la saisie** dans les réglages : la case invalide est entourée de rouge avec la raison, plus de message d'erreur à l'enregistrement.
- **Corbeille des presets** : un preset supprimé peut être restauré (bouton `Annuler` pendant quelques secondes, ou page `Corbeille`).
- **Mises à jour** : `Ignorer cette version`, progression du téléchargement avec `Annuler`. Si l'app est cachée dans la zone de notification, un message y apparaît au lieu d'ouvrir la fenêtre par-dessus le jeu. La version ZIP portable ouvre la page de la release au lieu d'installer une copie à part.
- **Clavier** : contour de focus sur la barre de navigation et les outils, liste des overlays utilisable au clavier, un seul clic sur l'icône de la zone de notification.
- Meilleur contraste en thème clair, icônes des messages assorties au thème, derniers textes anglais traduits.
- **Démarrage sans échec** : si l'app a planté au lancement, elle propose de démarrer sans plugins ni overlays (aussi avec `--safe-mode`).

### Connexions

- **Tableau de bord web** en français, dans tes unités, avec l'énergie virtuelle pour les Hypercar et LMGT3, le delta officiel et le tour invalidé.
- **État des données du jeu** dans le moniteur de performance : âge de la mémoire partagée et état de chaque donnée lue par l'API REST de LMU.

### Rejeux du jeu (Le Mans Ultimate)

- **Page repensée** (`Outils` > `Rejeux du jeu`) : état du jeu d'un coup d'œil (fermé, dans les menus, en session, rejeu ouvert), rejeux regroupés par jour avec recherche, filtre `Tous` / `Essais libres` / `Qualifications` / `Course`, tri par date, taille ou circuit, dossier des rejeux en un clic.
- **Fichiers de rejeu** : `Ajouter` (ou déposer des fichiers `.Vcr` sur la page) copie les rejeux dans le dossier des rejeux du jeu, avec une barre de progression, une vérification de l'espace disque et `Arrêter la copie` ; `Exporter` les copie dans le dossier de ton choix ; `Renommer` ; `Supprimer` les met dans la corbeille de Windows, après confirmation. Plusieurs rejeux peuvent être sélectionnés (clic avec `Ctrl` / `Maj`, `Ctrl+A`). **Protège** des rejeux avec l'étoile : ils ne sont jamais supprimés. Nettoyage du dossier : supprimer les rejeux de plus de N jours, ne garder que les derniers, supprimer les fichiers temporaires laissés par le jeu. Le dossier des rejeux est demandé au jeu, il est donc connu même sans rejeu.
- **Caméra et interface du jeu** : le menu des caméras du jeu (Cockpit, Swingman, Caméra nez, Caméra capot, les 7 caméras à bord, bord de piste `Cycle All` et groupes 1 à 4) avec la caméra affichée cochée, angle précédent / suivant, caméra sur la voiture précédente / suivante, nom de la caméra affiché ; afficher ou masquer toute l'interface du jeu pour des images propres (barre du haut, classement, barre de lecture et HUD, comme un clic molette dans le jeu) ou les parties du HUD une par une (discussion, HUD de la voiture, chrono, MFD, carte du circuit). Fonctionne aussi en session en direct.
- **Lecture** : boutons ronds (`Espace` lecture / pause), ralenti, retour et avance rapides, et toutes les autres vitesses du jeu dans un menu. Temps du rejeu lu dans le rejeu lui-même, avec sa vitesse (`1x`, `4x`...) ; `DIRECT` et l'heure de la session en session en direct. Tour de la voiture suivie par la caméra avec tour précédent / suivant, débuts de tour marqués sur la frise.
- **Revoir ce moment** en session en direct : un incident ouvre le rejeu de la session à ce moment, `Retour au direct` ramène à la session.
- **Pilotes** : classement de la session ou du rejeu (position et position dans la catégorie, numéro, pilote et voiture, tours, meilleur tour en violet quand c'est le plus rapide de sa catégorie, dernier tour, écart comme le jeu l'affiche (meilleur tour derrière le premier en essais et qualifications), arrêts aux stands, énergie virtuelle des voitures de ton équipe, garage / aux stands / terminé / abandon, incidents), puces des catégories, ta voiture mise en avant, la voiture suivie par la caméra marquée (voitures au même nom de pilote distinguées) ; double-clic sur un pilote pour mettre la caméra sur sa voiture, clic droit : `Aller au tour...`.
- **Carte du circuit** : le tracé et la voie des stands de la session ou du rejeu avec toutes les voitures (couleur de catégorie, numéro), qui glissent entre deux mises à jour ; clic sur une voiture pour mettre la caméra dessus.
- Des **incidents** au lieu des contacts bruts : les deux côtés d'un contact réunis en un seul incident, numéro et catégorie des voitures, ta voiture mise en avant, filtre `Voitures` / `Murs`, `Ma voiture`, puces des pilotes avec leur nombre d'incidents, copie ou export en CSV. Les incidents et le classement de la session qu'on vient de quitter restent affichés. **Frise** sur toute la session : clic sur un incident pour y aller, clic ailleurs pour déplacer le rejeu à ce moment, molette pour zoomer.
- Réglages gardés (secondes avant, tri, filtres, onglet, rejeux protégés), liste des rejeux mise à jour à la fin d'une session, `Aujourd'hui` / `Hier` mis à jour à minuit, noms des boutons pour les lecteurs d'écran.
- Plus léger pour le jeu : interrogé seulement quand la page est affichée, sur une seule connexion par mise à jour et un seul thread en arrière-plan, moins souvent quand le jeu est fermé, classement demandé seulement quand il sert.

![Page Rejeux du jeu : rejeux par jour, lecture, caméra, carte du circuit avec les voitures](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-game-replays.png)

### Releases et documentation

- **Notes de version dans la langue de l'app** : la page `Nouveautés` affiche le changelog en français quand l'app est en français (mise à jour disponible comme version installée), en anglais sinon.
- **Releases plus simples** : deux fichiers seulement, `ModernTinyPedals-<version>-setup.zip` (l'installeur Windows) et `ModernTinyPedals-<version>-source.zip`. La mise à jour depuis l'app télécharge le ZIP, vérifie son empreinte SHA-256 et lance l'installeur qu'il contient. Le ZIP portable n'est plus publié : pour passer une copie portable en version installée, installe le setup dans son dossier (presets et données conservés).
- **Wiki** : un guide complet en anglais (installation, réglage du jeu, overlays, visionneuse de télémétrie, calculateur de course, connexions, dépannage, développement) sur le [wiki du projet](https://github.com/Keenny38/ModernTinyPedals/wiki).
- README, changelog et notes de release sur GitHub en anglais, guide de contribution réécrit pour Modern Tiny Pedals.

### Fiabilité et sécurité

- L'app démarre même si la mémoire partagée du jeu a une taille inattendue (ancien plugin rF2, autre outil).
- Rejeux : la pause ne cache plus les overlays, les rejeux d'une ancienne version du jeu sont refusés proprement, les fichiers abîmés se lisent jusqu'à la partie saine, l'export se fait en arrière-plan.
- Presets et réglages écrits de façon sûre (plus de fichier vide après une coupure de courant), données des modules enregistrées à l'arrêt, tour en cours d'enregistrement gardé si tu quittes juste après la ligne.
- Fermer la fenêtre puis choisir `Annuler` ne laisse plus l'app sans fenêtre, et les modifications d'une page de réglages ne se perdent plus au changement de preset.
- Plugins installés depuis un ZIP vérifiés (chemins, code exécuté), tableau de bord web et télécommande renforcés.
- Corrections dans les overlays : deltabest_extended, heatmaps modernes, tailles à l'échelle ×2, textes tronqués, °F, maxima du moteur et des pédales, et beaucoup d'autres (voir [l'historique de l'audit](docs/AUDIT.md)).
- La version Windows est maintenant lancée en mode test avant chaque publication.
- **Téléchargements vérifiables** : chaque fichier de la release a une attestation de provenance signée (preuve qu'il a été compilé par GitHub depuis le code du dépôt, à vérifier avec `gh attestation verify`, voir [SECURITY.md](SECURITY.md)), et une release publiée ne peut plus être modifiée. Une faille de sécurité se signale en privé, comme expliqué dans le même fichier.

## 0.19.1 (2026-10-05)

Correctif de la version Windows de la 0.19.0.

- **L'app ne démarrait pas** dans la version Windows (installeur et ZIP) : un module Python (`multiprocessing`, utilisé au lancement et par les calculs en arrière-plan de la visionneuse de télémétrie) manquait à l'exécutable.

## 0.19.0 (2026-10-05)

La plus grosse mise à jour depuis le début : tous les overlays changent de look, la page des statistiques pilote est refaite, le calculateur de course sait gérer une voiture de sécurité, la pluie et plusieurs pilotes, et l'app lit beaucoup plus de données de Le Mans Ultimate (chat, contacts, rejeux, relais de l'équipe).

### Nouveau design des overlays

- **Tous les overlays sauf le Black box** ont un nouveau design : un panneau arrondi par overlay, police **Barlow** (incluse avec l'app), libellés courts au-dessus des valeurs, traduits dans la langue de l'app.
- **Valeurs colorées selon leur sens** : gain en vert, perte en rouge, alerte en orange, meilleur temps en violet.
- **Classements** (relative, standings, rivals) en lignes : badge de position, pastille de classe avec la position dans la classe, couleur de classe sur le bord de la ligne, tour le plus rapide de la classe en violet. Colonnes au choix (`column_*`), et pour rivals l'écart de temps au tour et l'intervalle.
- **Carburant et énergie** avec une jauge, le repère du plein et les valeurs clés en tuiles (tours, minutes, conso par tour, économie, arrêts).
- **Pneus et freins** en tuiles aux couleurs de la heatmap, **LED** en pastilles lumineuses, nouvelles jauges pour le rapport, les pédales et les dégâts.
- **Options simplifiées** : la fenêtre de configuration et la recherche d'options (`Ctrl+F`) ne montrent que les options que le design utilise.
- **L'ancien look reste disponible** : pour tous les overlays (désactiver `enable_modern_style` dans `Style d'overlay`) ou pour un seul (`enable_classic_layout`).
- Police du design réglable (`modern_design_font_name`), couleurs du thème d'overlay comme avant.

![Nouveau design : classements](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-classements.png)

![Nouveau design : carburant et énergie](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-carburant.png)

![Nouveau design : voiture et pneus](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-voiture.png)

![Nouveau design : chronos](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/2026-10-05-design-chrono.png)

### Nouvelle icône et interface

- Nouvelle icône **or et noir**, et sa version **or et blanc** pour le thème sombre.
- L'icône de la fenêtre, de la barre des tâches et de la zone de notification suit le **mode clair / sombre de Windows**, comme le logo de la fenêtre `À propos` et les raccourcis créés par l'installeur.
- L'onglet `Widget` de la fenêtre principale s'appelle maintenant **`Overlays`**.

### Visionneuse de télémétrie

#### Tracé officiel et limites de piste (LMU)

- La visionneuse récupère le **tracé officiel** du circuit et la **voie des stands** auprès du jeu, puis les garde : ils restent disponibles sans le jeu.
- **Bords de piste** du jeu sur la carte, avec la **marge au bord** à chaque point clé (extérieur au freinage, intérieur à la corde, extérieur en sortie) et un nouveau **point extérieur** ■ après chaque corde.
- **Hors-piste** (2 roues ou plus dans l'herbe, la terre ou le gravier) et **limites de piste dépassées** (4 roues dehors) marqués sur la carte et comptés par tour (hors-pistes : tours enregistrés avec cette version). Pour les tours enregistrés avant cette version, les bords sont déduits des trajectoires.
- Deux nouvelles colorations de la carte : **mini-secteurs** (la trajectoire de référence colorée par le tour le plus rapide de chaque mini-secteur, avec le **tour idéal des tours affichés**) et **écart par virage**.

![Carte : tracé officiel, bords de piste, mini-secteurs et mini-carte](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-track-map.png)

#### Nouveaux onglets Session et XY

- **Session** : tous les tours de la session (tours affichés dans leur couleur, meilleur en or, tours invalides creux), carburant et usure des pneus de chaque tour, hors-pistes et limites de piste. Un clic sur un tour l'affiche ou le masque.
- **Rythme en long run** : moyenne des tours propres en écartant les tours lents (trafic, erreurs), et **tendance** du temps au tour au fil de la session (usure, carburant, évolution de la piste), aussi par % d'usure des pneus.
- **XY** : un canal contre un autre au même endroit de la piste, en **nuage de points** (vitesse / G latéral, direction / G latéral, accélérateur / glissement…), ou en **histogramme** (part du tour passée dans chaque plage de valeurs). Limité à la partie zoomée des courbes quand on zoome.

![Onglet Session : rythme en long run et tendance](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-session.png)

![Onglet XY : vitesse / G latéral](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-xy.png)

#### Où le temps est perdu

- En haut de l'onglet Virages, les virages qui coûtent le plus, avec la **cause en clair** : « Freine 6 m plus tôt », « Vitesse minimale inférieure de 7 km/h », « Roue libre 0,7 s de plus », « Plein gaz 8 m plus tard »…
- Option **delta par rapport au tour idéal** (tour propre le plus rapide de chaque mini-secteur) au lieu du tour de référence.
- **Écart des points de freinage** d'un tour à l'autre, pour juger de la régularité.

![Onglet Virages : où le temps est perdu](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-coaching.png)

#### Nouveaux canaux enregistrés

- Températures **intérieur / milieu / extérieur** de chaque pneu (et leur écart), **charge** des pneus, **angle de dérive**, **carrossage**.
- **Répartition de freinage**, niveaux **TC** et **ABS**, **cartographie moteur**, températures **eau** et **huile**, position sur la piste et distance au centre.
- Le **nom du setup** chargé dans le jeu est gardé avec chaque tour (LMU), affiché et cherchable.

#### Liste des tours

- **Recherche** : véhicule, session, setup, note.
- **Corbeille** : les tours supprimés vont à la corbeille et se restaurent avec `Ctrl+Z`. Menus de session : afficher, masquer, garder ou mettre à la corbeille tous les tours d'une session ; mêmes actions pour les tours cochés, et export MoTeC des tours cochés.
- **Utiliser comme delta meilleur tour** : un tour enregistré devient le delta meilleur tour utilisé en piste (l'ancien est gardé en copie de sauvegarde).

#### Carte, courbes et lecture

- **Règle** (`M`) pour mesurer une distance sur la carte, **zones de pédales**, **traînée du curseur**, **repères de distance**, couleurs pour daltoniens.
- **Export de l'image de la carte** (fichier ou presse-papiers), **passage A ↔ B** en CSV ou en image.
- **Zoom de la carte synchronisé** avec les courbes (ou indépendant), **zoom précédent / suivant**, **mini-carte** sur la grande carte, **garder une position** d'un clic.
- Lecture : **boucle sur le passage A-B**, reculer / avancer de 2 s (maintenir pour un retour ou une avance rapide).
- **Aide clavier et souris** (bouton `?`) et raccourcis de la carte : `F` recadrer, `R` tourner, `1`-`8` coloration, `L` blocages, `Z` zones, `T` traînée.

#### Performances de la visionneuse

- Chaque tour enregistré a une **copie binaire** : la visionneuse l'ouvre sans relire le CSV, le chargement est bien plus rapide.
- Les calculs lourds (limites de piste, valeurs de session) tournent dans un **processus séparé** : courbes et carte restent fluides pendant le calcul.
- Les exports se font en arrière-plan ; fermer la visionneuse ou quitter l'app attend qu'ils soient terminés.

### Calculateur de course

- **Course en direct** : pendant une course, le plan de la fin de course est recalculé à chaque tour et à chaque arrêt à partir de la voiture (tours et temps faits, carburant, énergie, pneus, arrêts faits).
- **Scénario voiture de sécurité** (ou drapeau jaune intégral) : à partir d'un tour, pour quelques tours, avec la conso, le temps au tour et l'usure sous voiture de sécurité, et l'option de s'arrêter sous voiture de sécurité. Comparé au plan sans voiture de sécurité.
- **Scénario pluie** : période de pluie avec conso et temps au tour adaptés, et arrêts pour pneus pluie puis slicks.
- **Plusieurs pilotes** : relais par pilote, écart de rythme, temps de conduite minimum et maximum de chacun, carte `Temps de conduite` avec les limites non respectées en rouge.
- **Comparaison des stratégies** : le plan actuel contre 1 ou 2 arrêts de moins (économie de carburant) et 1 arrêt de plus, avec le **coût de l'économie** sur le temps au tour, le temps aux stands et l'écart à l'arrivée. L'objectif d'économie dit si l'arrêt en moins est **rentable**.
- **Plan d'arrêts** : **fenêtre d'arrêt** (premier et dernier tour possibles sans changer le nombre d'arrêts), **heure de la journée** de chaque arrêt avec l'heure de départ, export en **texte, pour Discord, en CSV ou en image**.
- **Relais équilibrés** (pas de court relais d'appoint à la fin), **le leader finit d'abord (+1 tour)** en course au temps, marge de sécurité en **tours, en carburant ou en %**, conso des **tours d'entrée et de sortie** des stands.
- **Estimer depuis l'historique** : durée d'arrêt, effet du carburant et évolution de la piste tirés de l'historique de consommation.
- **Code de partage** : tout le plan sur une ligne de texte à coller dans un chat, et **plan enregistré par voiture et circuit**, rouvert automatiquement. **Annuler / rétablir** (`Ctrl+Z` / `Ctrl+Y`) sur toutes les saisies.
- **Plan contre course** (relais roulés comparés au plan) et **rivaux de la catégorie** (tours, arrêts, prochain arrêt attendu).
- **Onglet Équipe (LMU)** : relais de chaque pilote de la voiture lus dans le jeu, coéquipiers compris, avec carburant, énergie et usure par tour à reporter dans le calculateur. **Pneus autorisés** repris de la session du jeu.

![Calculateur de course : voiture de sécurité, 2 pilotes, comparaison des stratégies](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-race-calculator.png)

### Statistiques pilote

- La page est **refaite en Qt Quick**, comme la visionneuse de télémétrie.
- **Tous les circuits** : ta carrière sur une page, le meilleur tour de chaque catégorie sur chaque circuit coloré par son niveau, et le compte de tes niveaux (Alien, Compétitif, Bon…).
- **Progression** : le meilleur tour de chaque session et ton record au fil du temps, avec les paliers de niveau, filtrable par essais, qualif ou course. Liste des **sessions** avec le résultat de chaque course.
- **Nouvelles colonnes** : meilleur tour **théorique** (somme des meilleurs secteurs) et **potentiel**, départs, abandons, position moyenne, taux de victoires et de podiums, vitesse moyenne, conso aux 100 km, dernière sortie. Colonnes à afficher au choix, largeurs réglables.
- **Niveau suivant** : le temps à trouver pour passer au niveau supérieur.
- **Recherche de circuit**, tri par dernière sortie, export CSV, couleurs pour daltoniens.
- **Annuler / rétablir** les suppressions et réinitialisations, **sauvegarde automatique** avant chaque modification (les 10 dernières, restaurables).
- Bouton **`Télémétrie`** : ouvre les tours enregistrés du véhicule dans la visionneuse, avec ton record comme référence.

![Statistiques pilote : niveau, progression et sessions](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-driver-stats.png)

![Statistiques pilote : tous les circuits](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-career.png)

### Le Mans Ultimate : nouvelles données du jeu

- Nouveau widget **Chat** : les messages du chat du jeu en overlay, pratique en VR. Retour à la ligne, disparition au bout de quelques secondes, nouveaux messages surlignés, heure optionnelle.
- Nouvelle page **Rejeux du jeu** (`Outils`) : les rejeux enregistrés par le jeu, ouverture dans le jeu, commandes de lecture, et la liste des **contacts** de la session avec **saut au moment du contact**, caméra sur la voiture.
- **Black box** : le journal inscrit chaque **contact** avec le nom de l'autre pilote, ou le mur.
- Widget **Plan de course** : **distance jusqu'à l'entrée des stands**, plan recalculé à chaque tour en course, **vérification du menu des stands** (le plein réglé dans le jeu contre le plan) et **conso cible** pour atteindre le prochain arrêt.
- **Estimation de conso du jeu** : tant qu'aucun tour de la voiture n'est enregistré sur ce circuit, les overlays carburant et énergie et le calculateur partent de la conso par tour estimée par le jeu.

![Widget Chat](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.19.0-chat.png)

### Corrections

- Un virage qui traverse la ligne de départ n'est plus compté deux fois, et un coup de frein bref avant le vrai freinage n'est plus pris pour le point de freinage.
- Changer d'unités met aussi à jour les bulles de la liste des tours.
- Un export de la visionneuse qui échoue est signalé au lieu d'échouer sans rien dire.
- Statistiques pilote : une modification ne perd plus les statistiques enregistrées entre-temps par l'app, et un temps réinitialisé disparaît aussi de la progression.

## 0.18.0 (2026-10-04)

### Visionneuse de télémétrie : analyse

- **Légende interactive** au-dessus des courbes : survol pour surligner un tour (courbes, carte, cercle G), clic pour le garder surligné, double-clic pour en faire la référence, `×` pour le masquer, clic droit pour le menu.
- **Couleurs stables** : chaque tour garde sa couleur tant qu'il est affiché, même quand on en coche ou décoche d'autres, ou qu'on change de référence.
- **Écart à la référence** dans les bulles du curseur (`237 +4`, `9 % −3 %`). Quand une voie est trop petite pour sa bulle, les valeurs s'affichent sous son nom.
- **Repères A et B** (clic droit ou touches `A` / `B`) et nouvel onglet **Plage** : temps de chaque tour entre les repères, écart à la référence, et min / max / moyenne de chaque voie affichée.
- **Canaux calculés** : glissement de chaque roue (blocage au freinage, patinage à l'accélération), vitesse de braquage, carburant consommé, écart de température des pneus.
- **Panneaux combinés** : les 4 roues dans une seule voie (températures, pressions, usure, freins, suspension…) et `Accélérateur et frein` superposés.
- **Menu `Canaux`** : recherche, presets (Pédales, Pneus, Freins, Suspension), canaux non enregistrés grisés (et un message dans la voie plutôt qu'un graphe vide), **lissage** des voies bruitées, **fenêtre** du gain/perte de temps (20 à 150 m), **bande min / max** des tours affichés pour voir la régularité.
- **Voies** : hauteur réglable en glissant leur bord (double-clic pour revenir), zoom vertical avec `Ctrl` + molette, défilement quand il y a beaucoup de voies.
- **Lecture du tour** (bouton ▶ ou `Espace`, de 0,25× à 4×) : le curseur suit le tour de référence en temps réel.
- **Clavier** : `←` `→` déplacent le curseur (`Maj` : la vue), `[` `]` virage précédent / suivant, `A` `B` repères, `Échap` les efface, `R` met le tour surligné en référence.
- **Clic droit sur les courbes** : repères, zoom sur le secteur ou entre les repères, copier les valeurs ou l'image, ouvrir le replay à cet endroit.
- **Clic sur `S1`, `S2`, `S3`** dans les courbes, ou sur un temps de secteur dans la liste : zoom sur le secteur.

![Visionneuse de télémétrie](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-telemetry-viewer.png)

### Onglet Virages

- **Tour comparé au choix** quand plusieurs tours sont affichés, et **tri par temps perdu** pour voir d'abord où gagner du temps.
- Pour chaque virage : **vitesses d'entrée et de sortie**, **rapport** à la vitesse mini, **pression de freinage** maximale et **tour le plus rapide** dans ce virage.
- **Tour idéal** : le meilleur passage de chaque virage et de chaque ligne droite parmi les tours affichés, avec l'écart au tour de référence.
- La sensibilité de détection s'affiche dans ton unité de vitesse, et les virages sont recalculés au relâchement du curseur (3 fois plus vite qu'avant).

![Onglet Virages](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-corners.png)

### Carte de trajectoire

- **Points de pilotage** de chaque tour dans chaque virage : ◆ freinage, ● point de corde (vitesse mini), ▲ sortie (retour à plein gaz, pointe dans le sens de la course). Au survol : virage, vitesse et distance, avec l'écart au tour de référence. Un clic zoome les courbes sur le virage. Option pour afficher la vitesse à côté de chaque point.
- **7 colorations** : par tour, gain/perte, vitesse, pédales, **trajectoire** (le tour comparé à l'intérieur ou à l'extérieur de la référence), **rapport** et **altitude**.
- **Suivi des voitures** pendant la lecture (ou avec les flèches du clavier) : la carte zoome sur les voitures et les garde au centre, et dézoome si elles s'écartent.
- **Curseur** : une flèche par tour, orientée dans le sens de la course, avec l'écart à la référence (en secondes, ou en mètres sur l'axe en temps). Passer la souris sur la piste place le curseur des courbes au même endroit.
- **Temps des secteurs** sur la piste avec l'écart du tour comparé, **flèches de sens**, **blocages des roues avant** et **patinage arrière**.
- **Grande carte** par-dessus les courbes (bouton ⤢), **orientation auto** pour remplir la carte et rotation par quart de tour.
- Étiquettes de virages qui ne se chevauchent plus (les plus gros écarts d'abord).

![Carte : points de freinage, de corde et de sortie](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-track-map.png)

![Carte : coloration trajectoire](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.18.0-racing-line.png)

### Liste des tours et outils

- **Sélection** : `Maj` + clic coche tous les tours entre deux, menu de sélection rapide (meilleur tour vs dernier, 3 ou 5 meilleurs, tout décocher).
- **Écart au meilleur tour** sur chaque tour, et conditions en bulle (températures piste et air, humidité, carburant consommé).
- Un tour illisible est signalé dans la liste au lieu de disparaître sans rien dire.
- **Mode `Direct`** : un nouveau tour enregistré apparaît tout seul et se compare au meilleur tour.
- **Ouvrir le replay** à l'endroit du curseur quand un replay couvre ce tour.
- **Export en image** (PNG) ou copie dans le presse-papiers, pour partager sur Discord.
- La mise en page est mémorisée : largeur des colonnes, onglet de droite, hauteur des voies.

### Cercle G

- Le freinage est maintenant en bas et un virage à droite à droite (c'était inversé), avec les repères Gauche / Droite / Accélération / Freinage.
- **Enveloppe d'adhérence** de chaque tour, et une échelle qui ignore les pics (vibreurs, contacts).

### Corrections

- **Les pages Qt Quick sont enfin en français** : la visionneuse de télémétrie et le Track Map Viewer restaient en anglais.
- La carte de trajectoire n'est plus **en miroir** : elle a le même sens que la carte en jeu.
- Le zoom des courbes est gardé quand on coche un tour.
- Zoom à la molette fluide sur pavé tactile (courbes et carte).
- En axe en temps, la carte et le cercle G montrent où est chaque tour à ce temps (au lieu de tous au même endroit).
- Un tour importé de MoTeC dont la distance diffère un peu est recalé pour le delta.
- Les réglages de la visionneuse ne peuvent plus être perdus si l'app s'arrête pendant leur écriture.
- Couleurs lisibles en thème clair (meilleur tour, meilleurs secteurs, avertissements, gain/perte).

### Performances

- Les tours se chargent toujours en arrière-plan, avec la progression, et la lecture des fichiers est plus rapide.
- Cocher un tour ne recalcule que ce tour, et l'export MoTeC de tout un circuit se fait en arrière-plan.
- Le curseur demande un seul calcul par mouvement de souris pour les courbes, la carte et le cercle G.

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
