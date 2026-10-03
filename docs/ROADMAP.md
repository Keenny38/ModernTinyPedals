# Feuille de route

Ce fichier liste uniquement ce qui **reste à faire**. L'historique des audits et de ce qui a été fait est dans [AUDIT.md](AUDIT.md).

Chaque entrée est rédigée pour être copiée telle quelle en issue GitHub sur [Keenny38/ModernTinyPedals](https://github.com/Keenny38/ModernTinyPedals/issues) : le titre en gras, puis le contexte et le résultat attendu. Une fois les issues créées, retirez les entrées d'ici et gardez seulement le lien vers les issues.

Légende : 🟠 à faire en priorité · 🟡 utile · 💡 idée

## Distribution

- 🟠 **Tester l'installeur Windows et la mise à jour depuis l'app.** Le workflow `Build and Release` publie bien `ModernTinyPedals-<version>-windows-setup.exe` et son `.sha256` (vérifié sur la release 0.13.0). Reste à l'essayer sur une vraie machine : installer la 0.13.0, puis lancer `Télécharger et installer` depuis une version plus ancienne (la 0.12.2 par exemple).
- 🟡 **Acheter un certificat de signature de code.** Le workflow `Build and Release` signe l'exécutable et l'installeur dès que les secrets `WINDOWS_CERT_PFX_BASE64` (fichier .pfx en base64) et `WINDOWS_CERT_PASSWORD` sont définis. Sans certificat, Windows SmartScreen avertit à chaque installation.

## Télémétrie

- 🟡 **Vérifier les canaux de l'enregistreur sous rFactor 2.** Vérifié le 03/10/2026 sur des tours LMU (Road Atlanta en Hypercar, Laguna Seca en LMP2) : usure en pourcentage restant (environ −0,85 % par tour), vitesse de roue en km/h à ±0,1 % de la vitesse en ligne droite, hauteur de caisse et débattement en mm, tours de sortie et de rentrée écartés, tour incomplet marqué « invalid ». Les lignes de secteur suivent maintenant les temps officiels (la colonne secteur arrive 0,1 à 0,2 s en retard). Reste rF2, et un tour de sortie enregistré avec `enable_out_and_in_lap_recording` sur un circuit où la ligne de départ passe dans la voie des stands.
- 🟡 **Tester l'enregistrement automatique des rejeux** sur une vraie session (démarrage en piste, arrêt 10 s après le retour au garage, rotation des fichiers `replay-auto-`).
- 💡 **Autres simulateurs** via l'architecture d'adaptateurs : Automobilista 2 / Project CARS (mémoire partagée), Assetto Corsa / ACC, iRacing.

## Performance

- 💡 **Alléger encore le widget Standings** : fonds de cellule (8,5 → 4,7 ms) puis mise en page du texte (`QStaticText`, environ −8 % sur Standings et −20 % sur Relative) mis en cache. Le coût restant est l'appel Python `paintEvent` de chaque cellule (un widget par cellule) : dessiner chaque ligne dans un seul widget le réduirait encore.

## Interface

- 💡 **Overlay VR OpenXR natif.** Demande une « API layer » OpenXR en C++ injectée dans le jeu, impossible en Python. En attendant, la fenêtre miroir VR (`Config > VR Overlay`) s'affiche dans le casque avec OpenKneeboard, OVR Toolkit, XSOverlay ou Desktop+.
- 🟡 **Tester en VR** l'overlay SteamVR et la fenêtre miroir avec OpenKneeboard, sur un vrai casque.
