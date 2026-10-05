# Feuille de route

Ce fichier liste uniquement ce qui **reste à faire**. L'historique des audits et de ce qui a été fait est dans [AUDIT.md](AUDIT.md).

Chaque entrée est rédigée pour être copiée telle quelle en issue GitHub sur [Keenny38/ModernTinyPedals](https://github.com/Keenny38/ModernTinyPedals/issues) : le titre en gras, puis le contexte et le résultat attendu. Une fois les issues créées, retirez les entrées d'ici et gardez seulement le lien vers les issues.

Légende : 🟠 à faire en priorité · 🟡 utile · 💡 idée

## Vérifier en jeu (0.20.0)

Ce qui a été codé et testé sans le jeu, et dont les valeurs ou le comportement réels restent à confirmer dans Le Mans Ultimate (et rFactor 2 quand c'est indiqué).

- 🟠 **Nouvelles données LMU** : unité de l'état de charge de la batterie (pourcentage supposé, tuile `show_state_of_charge` désactivée par défaut en attendant), température idéale des pneus (°C supposés), ordre des secteurs des drapeaux jaunes (indice 0 du jeu supposé être le secteur 3), signe des écarts `mTimeGap*`, événements de session, hauteurs de caisse, delta officiel face au delta du jeu, `mLapInvalidated` sur une sortie de piste, `mFlat` sur une crevaison.
- 🟠 **Nouveaux overlays** : spotter en peloton serré (seuils de distance latérale), aide en voie des stands (apparition à l'approche avec arrêt demandé, états du limiteur, barre du box, unités du ravitaillement), alertes de course (début et fin de FCY, pas de fausse alerte de position au départ), minuteur de relais (changement de pilote, part équitable en course au temps), graphique de delta au passage de la ligne.
- 🟠 **Stratégie** : arrêt réel, drive-through et arrêt non compté par le jeu ; temps de relais après un arrêt anticipé ; conso médiane pendant une neutralisation ; pilote de chaque relais après un changement de pilote.
- 🟡 **Données du jeu** : démarrage avec une mémoire partagée d'une autre taille (ancien plugin rF2), rejeu en pause et image par image, rejeu d'une ancienne version refusé avec message, chat et contacts en moins d'une seconde, onglet « Données du jeu » du moniteur de performance.
- 🟡 **Interface** : mise à jour installée (`Ignorer cette version`, progression, `Annuler`, message dans la zone de notification au démarrage caché), version ZIP portable (page de la release), corbeille des presets, `Ctrl+S`, validation pendant la saisie.

## Distribution

- 🟠 **Tester l'installeur Windows et la mise à jour depuis l'app.** Depuis la 0.20.0, le workflow `Build and Release` publie l'installeur dans `ModernTinyPedals-<version>-setup.zip` (avec `ModernTinyPedals-<version>-source.zip`, plus de ZIP portable ni de `.sha256`) : l'app vérifie l'empreinte SHA-256 du ZIP (donnée par GitHub) puis lance l'installeur qu'il contient. Reste à l'essayer sur une vraie machine : `Télécharger et installer` depuis la 0.20.0 vers la version suivante. Les versions 0.19.x et plus anciennes ne trouvent plus d'installeur `.exe` dans la release : elles ouvrent la page de téléchargement, mise à jour à la main une seule fois.
- 🟡 **Signer l'exécutable et l'installeur.** Sans signature, Windows SmartScreen avertit à chaque installation. Le workflow `Build and Release` sait signer de deux façons, il suffit de fournir l'une d'elles dans l'environnement `release` du dépôt (`Settings > Environments`, ouvert à `master` seulement) : un certificat .pfx (secrets `WINDOWS_CERT_PFX_BASE64` et `WINDOWS_CERT_PASSWORD`), ou Azure Artifact Signing, sans fichier de certificat et environ 10 $ par mois (variables `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT`, `AZURE_SIGNING_PROFILE` et secrets `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` d'une application Entra ID ayant le rôle « Artifact Signing Certificate Profile Signer »). Pour un projet libre, SignPath Foundation signe gratuitement sur demande. Reste à souscrire l'une de ces offres.

## Télémétrie

- 🟡 **Vérifier les canaux de l'enregistreur sous rFactor 2.** Vérifié le 03/10/2026 sur des tours LMU (Road Atlanta en Hypercar, Laguna Seca en LMP2) : usure en pourcentage restant (environ −0,85 % par tour), vitesse de roue en km/h à ±0,1 % de la vitesse en ligne droite, hauteur de caisse et débattement en mm, tours de sortie et de rentrée écartés, tour incomplet marqué « invalid ». Les lignes de secteur suivent maintenant les temps officiels (la colonne secteur arrive 0,1 à 0,2 s en retard). Reste rF2, et un tour de sortie enregistré avec `enable_out_and_in_lap_recording` sur un circuit où la ligne de départ passe dans la voie des stands.
- 🟡 **Tester l'enregistrement automatique des rejeux** sur une vraie session (démarrage en piste, arrêt 10 s après le retour au garage, rotation des fichiers `replay-auto-`).
- 💡 **Autres simulateurs** via l'architecture d'adaptateurs : Automobilista 2 / Project CARS (mémoire partagée), Assetto Corsa / ACC, iRacing.

## Performance

- 💡 **Alléger encore le widget Standings** : fonds de cellule mis en cache (8,5 → 4,7 ms), mise en page du texte (`QStaticText`) puis fond gardé par cellule (environ −30 %, 2,1 ms avec 20 voitures). Le coût restant est l'appel Python `paintEvent` de chaque cellule (un widget par cellule) : dessiner chaque ligne dans un seul widget le réduirait encore, au prix d'une réécriture des widgets Standings et Relative.

## Interface

- 💡 **Overlay VR OpenXR natif.** Demande une « API layer » OpenXR en C++ (DLL chargée par le jeu), impossible en Python. Architecture prévue : l'app écrit l'image de l'overlay (déjà produite pour la fenêtre miroir) dans une mémoire partagée nommée avec un compteur d'images ; la couche intercepte `xrCreateSession` (pour créer sa swapchain avec l'API graphique du jeu, D3D11 pour LMU et rF2), copie l'image dans la swapchain à chaque `xrEndFrame` quand le compteur change, et ajoute un `XrCompositionLayerQuad` (position, taille et opacité lues dans la mémoire partagée). L'installeur enregistre la couche comme « implicit API layer » (clé `HKLM\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit`, avec variable d'environnement pour la désactiver). La DLL peut être compilée par la CI (MSVC sur `windows-latest`), mais doit être testée sur un vrai casque avant toute release : une erreur dans la couche fait planter le jeu. En attendant, la fenêtre miroir VR (`Config > VR Overlay`) s'affiche dans le casque avec OpenKneeboard, OVR Toolkit, XSOverlay ou Desktop+.
- 🟡 **Tester en VR** l'overlay SteamVR et la fenêtre miroir avec OpenKneeboard, sur un vrai casque.
