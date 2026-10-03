# Feuille de route

Ce fichier liste uniquement ce qui **reste à faire**. L'historique des audits et de ce qui a été fait est dans [AUDIT.md](AUDIT.md).

Chaque entrée est rédigée pour être copiée telle quelle en issue GitHub sur [Keenny38/ModernTinyPedals](https://github.com/Keenny38/ModernTinyPedals/issues) : le titre en gras, puis le contexte et le résultat attendu. Une fois les issues créées, retirez les entrées d'ici et gardez seulement le lien vers les issues.

Légende : 🟠 à faire en priorité · 🟡 utile · 💡 idée

## Distribution

- 🟠 **Vérifier la première release avec l'installeur Windows.** Le workflow `Build and Release` compile maintenant `ModernTinyPedals-<version>-windows-setup.exe` et son fichier `.sha256`, mais n'a encore jamais tourné (Inno Setup n'est pas installé en local). Installer la release 0.10.0, puis tester `Télécharger et installer` depuis une version plus ancienne.
- 🟡 **Acheter un certificat de signature de code.** Le workflow `Build and Release` signe l'exécutable et l'installeur dès que les secrets `WINDOWS_CERT_PFX_BASE64` (fichier .pfx en base64) et `WINDOWS_CERT_PASSWORD` sont définis. Sans certificat, Windows SmartScreen avertit à chaque installation.

## Télémétrie

- 🟠 **Vérifier les nouveaux canaux de l'enregistreur en jeu** (LMU et rF2) : signe et unités de l'usure des pneus (fraction restante ?), de la vitesse de roue (rayon appris par le module Wheels, 0 si le module est désactivé), de la hauteur de caisse et du débattement, et le temps du secteur (indice de secteur mis à jour à 5 Hz seulement). Vérifier aussi qu'un tour de sortie est bien reconnu sur un circuit où la ligne de départ passe dans la voie des stands.
- 🟡 **Tester l'enregistrement automatique des rejeux** sur une vraie session (démarrage en piste, arrêt 10 s après le retour au garage, rotation des fichiers `replay-auto-`).
- 💡 **Autres simulateurs** via l'architecture d'adaptateurs : Automobilista 2 / Project CARS (mémoire partagée), Assetto Corsa / ACC, iRacing.

## Performance

- 💡 **Alléger encore le widget Standings** : 4,7 ms par image avec 20 voitures depuis la mise en cache des fonds de cellule (8,5 ms avant). Le coût restant est le texte (`drawText`) de chaque cellule.

## Interface

- 💡 **Overlay VR OpenXR natif.** Demande une « API layer » OpenXR en C++ injectée dans le jeu, impossible en Python. En attendant, la fenêtre miroir VR (`Config > VR Overlay`) s'affiche dans le casque avec OpenKneeboard, OVR Toolkit, XSOverlay ou Desktop+.
- 🟡 **Tester en VR** l'overlay SteamVR et la fenêtre miroir avec OpenKneeboard, sur un vrai casque.
