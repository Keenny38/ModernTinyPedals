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

- 🟠 **Tester l'installeur Windows et la mise à jour depuis l'app.** Depuis la 0.20.1, le workflow `Build and Release` publie l'installeur `ModernTinyPedals-<version>-windows-setup.exe` avec son `.sha256`, le même installeur dans `ModernTinyPedals-<version>-setup.zip` et `ModernTinyPedals-<version>-source.zip` (plus de ZIP portable). L'app 0.20 et suivantes vérifie l'empreinte SHA-256 du ZIP (donnée par GitHub) puis lance l'installeur qu'il contient ; les versions jusqu'à 0.19 prennent l'`.exe` et son `.sha256` (la 0.20.0 ne les avait pas : ces versions se mettent à jour depuis l'app à partir de la 0.20.1). Reste à l'essayer sur une vraie machine : `Télécharger et installer` depuis une version installée vers la suivante.
- 🟡 **Signer l'exécutable et l'installeur.** Sans signature, Windows SmartScreen avertit à chaque installation. Le workflow `Build and Release` sait signer de deux façons, il suffit de fournir l'une d'elles dans l'environnement `release` du dépôt (`Settings > Environments`, ouvert à `master` seulement) : un certificat .pfx (secrets `WINDOWS_CERT_PFX_BASE64` et `WINDOWS_CERT_PASSWORD`), ou Azure Artifact Signing, sans fichier de certificat et environ 10 $ par mois (variables `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT`, `AZURE_SIGNING_PROFILE` et secrets `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` d'une application Entra ID ayant le rôle « Artifact Signing Certificate Profile Signer »). Pour un projet libre, SignPath Foundation signe gratuitement sur demande. Reste à souscrire l'une de ces offres.

## Télémétrie

- 🟡 **Vérifier les canaux de l'enregistreur sous rFactor 2.** Vérifié le 03/10/2026 sur des tours LMU (Road Atlanta en Hypercar, Laguna Seca en LMP2) : usure en pourcentage restant (environ −0,85 % par tour), vitesse de roue en km/h à ±0,1 % de la vitesse en ligne droite, hauteur de caisse et débattement en mm, tours de sortie et de rentrée écartés, tour incomplet marqué « invalid ». Les lignes de secteur suivent maintenant les temps officiels (la colonne secteur arrive 0,1 à 0,2 s en retard). Reste rF2, et un tour de sortie enregistré avec `enable_out_and_in_lap_recording` sur un circuit où la ligne de départ passe dans la voie des stands.
- 🟡 **Tester l'enregistrement automatique des rejeux** sur une vraie session (démarrage en piste, arrêt 10 s après le retour au garage, rotation des fichiers `replay-auto-`).
- 💡 **Autres simulateurs** via l'architecture d'adaptateurs : Automobilista 2 / Project CARS (mémoire partagée), Assetto Corsa / ACC, iRacing.

## Performance

- 💡 **Alléger encore le widget Standings** : fonds de cellule mis en cache (8,5 → 4,7 ms), mise en page du texte (`QStaticText`) puis fond gardé par cellule (environ −30 %, 2,1 ms avec 20 voitures). Le coût restant est l'appel Python `paintEvent` de chaque cellule (un widget par cellule) : dessiner chaque ligne dans un seul widget le réduirait encore, au prix d'une réécriture des widgets Standings et Relative.

## Interface

- 🟠 **Tester la couche OpenXR de l'overlay VR sur de vrais casques avant de l'annoncer.** Codée (`native/openxr_layer`, « implicit API layer » enregistrée par l'app pour l'utilisateur sous `HKCU\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit`, retirée quand l'option est désactivée et à la désinstallation), compilée par la CI (MSVC) et testée sans casque : tests unitaires de la mémoire partagée, et DLL pilotée par un faux runtime OpenXR avec de vrais périphériques D3D11, D3D12 et Vulkan (Wine et WARP), image relue dans la swapchain. Depuis le protocole v2, seules les parties visibles du canevas sont envoyées : une tuile par groupe d'overlays proches, rangées dans un atlas, un quad par tuile (une seule swapchain, `imageRect` par quad), tuiles fusionnées si le runtime n'a plus assez de couches ; une couche d'une autre version (jeu lancé avant une mise à jour de l'app) ne dessine rien et le signale dans le journal. Reste à vérifier dans un vrai jeu : LMU en OpenXR (D3D11) avec Meta Quest Link / Air Link, Virtual Desktop (VDXR) et SteamVR comme runtime OpenXR (overlay SteamVR alors masqué, pas d'image en double) ; couleurs (swapchain sRGB, alpha non prémultiplié), overlays éloignés les uns des autres (plusieurs quads alignés comme sur le bureau, sans liseré entre tuiles), placement assis (espace `LOCAL`) et attaché au casque (`VIEW`), absence d'à-coups, jeu lancé avant l'app, app fermée pendant le jeu, mise à jour de l'app pendant que le jeu tourne (DLL verrouillée), et un anti-triche (EAC) qui refuserait une DLL non signée. Puis retirer « (Experimental) » du menu.
- 🟡 **Tester en VR** l'overlay SteamVR (créé seulement quand SteamVR tourne, recréé si SteamVR redémarre) dans rFactor 2 et LMU en mode SteamVR, et la fenêtre miroir avec OpenKneeboard, sur un vrai casque.
