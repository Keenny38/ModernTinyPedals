# Feuille de route

Ce fichier liste uniquement ce qui **reste à faire**. L'historique des audits et de ce qui a été fait est dans [AUDIT.md](AUDIT.md).

Chaque entrée est rédigée pour être copiée telle quelle en issue GitHub sur [Keenny38/overlays](https://github.com/Keenny38/overlays/issues) : le titre en gras, puis le contexte et le résultat attendu. Une fois les issues créées, retirez les entrées d'ici et gardez seulement le lien vers les issues.

Légende : 🟠 à faire en priorité · 🟡 utile · 💡 idée

## Distribution

- 🟠 **Vérifier la première release avec l'installeur Windows.** Le workflow `Build and Release` compile maintenant `TinyPedal-<version>-windows-setup.exe` et son fichier `.sha256`, mais n'a encore jamais tourné (Inno Setup n'est pas installé en local). Lancer le workflow une fois en mode test, installer, puis tester `Télécharger et installer` depuis une version plus ancienne.
- 🟡 **Signer l'exécutable et l'installeur.** Sans signature, Windows SmartScreen avertit à chaque installation.

## Télémétrie

- 🟡 **Rejeu de télémétrie pour rFactor 2.** `Outils > Rejeu de télémétrie` enregistre et rejoue seulement la mémoire partagée de Le Mans Ultimate. rF2 utilise plusieurs zones mémoire (`rf2_connector`) : il faut enregistrer chaque zone dans la même image.
- 🟡 **Enregistrer aussi les données de la Rest API dans le rejeu.** Réglages de pneus, détails d'énergie virtuelle et météo à venir manquent pendant un rejeu.
- 💡 **Autres simulateurs** via l'architecture d'adaptateurs : Automobilista 2 / Project CARS (mémoire partagée), Assetto Corsa / ACC, iRacing.

## Qualité du code

- 🟡 **Réactiver `attr-defined` dans mypy.** C'est la dernière catégorie masquée (environ 790 erreurs). La plupart viennent des mixins du Black box et des widgets qui lisent des attributs définis par la classe du widget : déclarer ces attributs dans chaque mixin, comme `DataReader` le fait déjà.
- 🟡 **Tester les modules Mapping, Notes et Stats** (couverture entre 10 et 20 %), avec le lecteur de télémétrie scripté de `tests/test_module_timing.py`.
- 💡 **Test de régression visuelle en CI** : comparer le rendu des widgets (`tests/_render`) à des images de référence.

## Performance

- 💡 **Alléger le widget Standings**, le plus coûteux avec une grille de 20 voitures (environ 5 ms par image, contre moins de 3 ms pour les autres ; budget 15 ms).

## Interface

- 💡 **Traductions communautaires** : fichiers de langue JSON dans un dossier `i18n/`, pour ajouter une langue sans toucher au code (aujourd'hui, le français est dans `fr.py` et `fr_messages.py`).
- 💡 **Overlay VR natif** (OpenXR) au lieu de l'overlay VR expérimental actuel.
