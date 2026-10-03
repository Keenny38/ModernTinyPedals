"""
Generate French option labels: tinypedal/i18n/data/fr_options.json

Run from project root after adding new options:
    python tools/gen_fr_options.py

Labels are composed from a term dictionary (English compounds are head-final,
French is head-initial, so noun groups are reversed), attribute templates
(color, width...), and full-key overrides for special cases.
Review generated file, and add overrides to FULL for poor results.
"""

from __future__ import annotations

import json
import os
import re
import sys
from itertools import zip_longest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT = "tinypedal/i18n/data/fr_options.json"

# Single words
WORDS = {
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "10": "10",
    "above": "au-dessus", "abs": "ABS", "absolute": "absolu", "acceleration": "accélération", "access": "accès",
    "ackermann": "Ackermann", "activated": "activé", "activation": "activation", "active": "actif",
    "actual": "réel", "additional": "supplémentaire", "aero": "aéro", "ahead": "devant", "align": "aligner",
    "alignment": "alignement", "all": "tous", "allocation": "répartition", "allowed": "autorisé",
    "ambient": "ambiante", "angle": "angle", "animated": "animé", "animation": "animation", "api": "API", "application": "application",
    "arb": "barre antiroulis", "area": "zone", "attempts": "tentatives", "auto": "auto", "automatic": "automatique",
    "available": "disponible", "average": "moyen", "axle": "essieu", "background": "fond", "backup": "sauvegarde",
    "backups": "sauvegardes", "bar": "barre", "base": "base", "baseline": "référence", "batch": "groupée",
    "battery": "batterie", "behind": "derrière", "below": "sous", "best": "meilleur", "bias": "répartition",
    "bind": "lier", "blue": "bleu", "body": "carrosserie", "border": "bordure", "bottom": "bas",
    "bottoming": "talonnage", "brake": "frein", "braking": "freinage", "brand": "marque", "break": "saut",
    "bump": "compression", "bypass": "contourner", "calculator": "calculateur", "camber": "carrossage",
    "capacity": "capacité", "caption": "légende", "car": "voiture", "carcass": "carcasse", "center": "centre",
    "chance": "probabilité", "change": "variation", "character": "caractères", "charge": "charge",
    "check": "vérifier", "circle": "cercle", "class": "classe", "classification": "classement", "cliff": "falaise",
    "clipping": "saturation", "clock": "horloge", "closed": "fermé", "clutch": "embrayage", "coast": "roue libre",
    "cold": "froid", "collision": "collision", "color": "couleur", "column": "colonne", "combined": "combiné",
    "comments": "commentaires", "compass": "boussole", "compatibility": "compatibilité", "compound": "gomme",
    "cone": "cône", "confirmation": "confirmation", "connection": "connexion", "consistency": "régularité",
    "constant": "stable", "consumption": "consommation", "control": "contrôle", "cooldown": "délai",
    "coordinates": "coordonnées", "corner": "virage", "correction": "correction", "count": "nombre",
    "countdown": "compte à rebours", "course": "trajectoire", "coverage": "couverture", "critical": "critique",
    "cross": "croisé", "cruise": "croisière", "current": "actuel", "curve": "virage", "custom": "personnalisé",
    "cut": "coupure", "cycle": "alterner", "damage": "dégâts", "dark": "sombre", "data": "données",
    "day": "jour", "debugging": "débogage", "decimal": "décimales", "decreasing": "en baisse",
    "deflection": "déflexion", "degree": "degré", "delay": "délai", "delta": "delta", "deltabest": "delta best",
    "discharge": "décharge",
    "deltalast": "delta dernier tour", "density": "densité", "detached": "détaché", "detail": "détail",
    "deviation": "écart", "difference": "différence", "differential": "différentiel", "digits": "chiffres",
    "direction": "direction", "display": "affichage", "disqualify": "disqualification", "distance": "distance",
    "distribution": "répartition", "dot": "point", "double": "double", "downforce": "appui", "dpi": "DPI",
    "drain": "décharge", "driver": "pilote", "drop": "chute", "drs": "DRS", "dry": "sec", "duration": "durée",
    "dynamic": "dynamique", "each": "chaque", "early": "anticipé", "edge": "bord", "electric": "électrique",
    "elevation": "altitude", "empty": "vide", "enable": "activer", "encoding": "encodage", "end": "fin",
    "energy": "énergie", "engine": "moteur", "entry": "entrée", "estimate": "estimation", "estimated": "estimé",
    "example": "exemple", "exclusive": "exclusif", "exponential": "exponentielle", "extended": "étendu",
    "extra": "supplémentaire", "extreme": "extrême", "extremely": "extrêmement", "fade": "fondu",
    "faster": "plus rapide", "fastest": "plus rapide", "ffb": "FFB", "file": "fichier", "filtered": "filtré",
    "finish": "arrivée", "fixed": "fixe", "flag": "drapeau", "flash": "clignotement", "flashes": "clignotements",
    "flat": "plat", "flickering": "scintillement", "font": "police", "force": "force", "forecast": "prévision",
    "forecasts": "prévisions", "format": "format", "formatted": "formaté", "frames": "images",
    "freeze": "figer", "friction": "adhérence", "front": "avant", "fuel": "carburant", "full": "complet",
    "g": "G", "gain": "gain", "gap": "écart", "garage": "garage", "gauge": "jauge", "gear": "rapport",
    "gentle": "douce", "global": "global", "go": "go", "grade": "niveau", "gravitational": "gravitationnelle",
    "green": "vert", "grid": "grille", "group": "groupe", "guides": "guides", "hairpin": "épingle",
    "head": "tête", "heading": "cap", "headlights": "phares", "headset": "casque", "heatmap": "palette thermique",
    "heavy": "lourd", "height": "hauteur", "hide": "masquer", "high": "élevé", "highlight": "surbrillance",
    "highlighted": "en surbrillance", "history": "historique", "horizontal": "horizontal", "host": "hôte",
    "hot": "chaud", "hotkey": "raccourci", "hybrid": "hybride", "icon": "icône", "id": "ID", "idle": "inactif",
    "ignition": "allumage", "image": "image", "impact": "impact", "incidents": "incidents",
    "increasing": "en hausse", "increment": "incrément", "index": "index", "indicator": "indicateur",
    "info": "infos", "inner": "intérieur", "input": "entrée", "instrument": "instruments",
    "integrity": "intégrité", "interval": "intervalle", "invalid": "invalide", "inverted": "inversé",
    "language": "langue", "lap": "tour", "laps": "tours", "laptime": "temps au tour", "last": "dernier",
    "lateral": "latéral", "layer": "couche", "layout": "disposition", "leader": "leader", "leading": "de tête",
    "led": "LED", "left": "gauche", "legacy": "ancienne", "length": "longueur", "lengthy": "long",
    "less": "moins", "level": "niveau", "lifespan": "durée de vie", "lift": "levée", "liftforce": "portance",
    "light": "léger", "lights": "feux", "limiter": "limiteur", "limits": "limites", "line": "ligne",
    "live": "en direct", "lmu": "LMU", "load": "charge", "loading": "chargement", "lock": "blocage",
    "locked": "verrouillé", "locking": "blocage", "logo": "logo", "long": "long", "longitudinal": "longitudinal",
    "loss": "perte", "low": "faible", "lower": "inférieur", "manager": "gestionnaire", "manual": "manuel",
    "map": "carte", "mapping": "cartographie", "margin": "marge", "mark": "repère", "marked": "marqué",
    "matching": "correspondance", "major": "majeur", "maximum": "maximum", "minor": "mineur", "measurement": "mesure", "median": "médiane",
    "medium": "moyen", "meter": "mètre", "meters": "mètres", "middle": "milieu", "migration": "migration",
    "minimize": "réduire", "minimum": "minimum", "minutes": "minutes", "mixed": "mixte", "mode": "mode",
    "moderate": "modérée", "modern": "moderne", "module": "module", "more": "plus", "motion": "mouvement",
    "motor": "moteur", "move": "déplacement", "multi": "multi", "multiplier": "multiplicateur", "name": "nom",
    "navigation": "navigation", "near": "proche", "nearby": "proche", "nearest": "plus proche",
    "negative": "négatif", "net": "net", "neutral": "neutre", "next": "suivant", "night": "nuit",
    "normal": "normal", "not": "non", "notes": "notes", "notification": "notification", "notify": "notifier",
    "occupancy": "occupation", "odometer": "odomètre", "off": "arrêt", "offroad": "hors piste",
    "offset": "décalage", "oil": "huile", "onboard": "embarqué", "opacity": "opacité", "optimal": "optimal",
    "option": "option", "order": "ordre", "orientation": "orientation", "osculating": "osculateur",
    "others": "autres", "outer": "extérieur", "outline": "contour", "over": "sur", "overall": "général",
    "overheat": "surchauffe", "overlap": "chevauchement", "overlay": "overlay", "override": "forçage",
    "oversteer": "survirage", "pace": "rythme", "padding": "marge interne", "parts": "pièces",
    "pass": "passage", "path": "dossier", "paused": "en pause", "pedal": "pédale", "penalty": "pénalité",
    "percentage": "pourcentage", "performance": "performances", "personal": "personnel", "phase": "phase",
    "pit": "stand", "pitout": "sortie des stands", "pitstop": "arrêt au stand", "places": "décimales",
    "planner": "planificateur", "platform": "plateforme", "playback": "lecture", "player": "joueur",
    "players": "joueurs", "plugin": "plugin", "podium": "podium", "points": "points", "port": "port",
    "position": "position", "positive": "positif", "power": "puissance", "practice": "essais",
    "predicted": "prévu", "prediction": "prédiction", "prefix": "préfixe", "preset": "preset",
    "pressure": "pression", "previous": "précédent", "private": "privées", "process": "processus",
    "progress": "progression", "progression": "progression", "proximity": "proximité", "puncture": "crevaison",
    "push": "push", "qualify": "qualifications", "qualifying": "qualifications", "queue": "file d'attente",
    "quit": "quitter", "race": "course", "radar": "radar", "radius": "rayon", "rain": "pluie",
    "raininess": "pluviosité", "rake": "assiette", "range": "plage", "rate": "taux", "ratio": "rapport",
    "raw": "brut", "reading": "valeur", "readings": "valeurs", "rear": "arrière", "rebound": "détente",
    "recent": "récents", "recorder": "enregistreur", "red": "rouge", "redline": "zone rouge",
    "reduction": "réduction", "reference": "référence", "refill": "remplissage", "refilling": "remplissage",
    "refueling": "ravitaillement", "regen": "régénération", "regeneration": "régénération",
    "relative": "relatif", "reload": "recharger", "remaining": "restant", "remember": "mémoriser",
    "remote": "à distance", "repairs": "réparations", "repository": "dépôt", "request": "demande",
    "requested": "demandé", "requests": "demandes", "reserve": "réserve", "reset": "réinitialisation",
    "restapi": "RestAPI", "restart": "redémarrer", "retry": "nouvelle tentative", "rev": "régime",
    "rf2": "RF2", "ride": "hauteur de caisse", "right": "droite", "rivals": "rivaux", "roll": "roulis",
    "rotation": "rotation", "rpm": "RPM", "rubber": "gomme sur piste", "safe": "sûr", "safety": "sécurité",
    "same": "même", "sampling": "échantillonnage", "save": "enregistrer", "saved": "enregistrés",
    "saver": "économiseur", "saving": "économie", "scale": "échelle", "scaled": "mis à l'échelle",
    "scaling": "mise à l'échelle", "scheduled": "prévues", "seconds": "secondes", "section": "section",
    "sector": "secteur", "sectors": "secteurs", "select": "sélectionner", "selection": "sélection",
    "selector": "sélecteur", "session": "session", "setting": "réglage", "settings": "réglages",
    "setup": "réglage", "setups": "réglages", "shape": "forme", "short": "court", "shorten": "raccourcir",
    "side": "côté", "sign": "signe", "single": "unique", "size": "taille", "slip": "glissement",
    "slope": "pente", "slower": "plus lent", "smoothing": "lissage", "snap": "aimantation", "sound": "son",
    "source": "source", "spacing": "espacement", "spectate": "spectateur", "speed": "vitesse",
    "speedometer": "compteur de vitesse", "split": "séparation", "spot": "plat", "spring": "ressort",
    "stalling": "calage", "standings": "classement", "start": "départ", "starting": "de départ",
    "startup": "démarrage", "state": "état", "static": "statique", "stationary": "à l'arrêt",
    "stats": "statistiques", "status": "statut", "steep": "raide", "steer": "virage", "steering": "direction",
    "step": "pas", "stint": "relais", "stop": "arrêt", "stopped": "arrêté", "straight": "ligne droite",
    "strategy": "stratégie", "style": "style", "styling": "style", "suffix": "suffixe", "sunlight": "soleil",
    "surface": "surface", "suspension": "suspension", "swap": "inverser", "symbol": "symbole",
    "symmetric": "symétrique", "synchronization": "synchronisation", "system": "système", "tail": "queue",
    "tank": "réservoir", "target": "cible", "tc": "TC", "telemetry": "télémétrie", "temperature": "température",
    "testday": "journée d'essais", "text": "texte", "theme": "thème", "thickness": "épaisseur",
    "third": "troisième", "threshold": "seuil", "throttle": "accélérateur", "time": "temps",
    "timeout": "délai d'attente", "timer": "chrono", "timing": "chronométrage", "tinypedal": "TinyPedal",
    "title": "titre", "toe": "pincement", "toggle": "basculer", "top": "haut", "torque": "couple",
    "total": "total", "totaled": "détruit", "trace": "trace", "track": "piste", "traffic": "trafic",
    "trailing": "historique", "transient": "transitoire", "translucent": "translucide", "trap": "radar",
    "travel": "débattement", "tray": "zone de notification", "trend": "tendance", "turbo": "turbo",
    "turning": "braquage", "type": "type", "tyre": "pneu", "unavailable": "indisponible", "under": "sous",
    "understeer": "sous-virage", "unfiltered": "non filtré", "unit": "unité", "units": "unités",
    "unsprung": "non suspendu", "update": "mise à jour", "updates": "mises à jour", "upper": "supérieur",
    "uppercase": "majuscules", "url": "URL", "user": "utilisateur", "vehicle": "véhicule",
    "vehicles": "véhicules", "version": "version", "vertical": "vertical", "very": "très", "view": "vue",
    "viewer": "visionneuse", "virtual": "virtuelle", "visibility": "visibilité", "visible": "visible",
    "volume": "volume", "vr": "VR", "warmup": "warm-up", "warning": "alerte", "water": "eau",
    "wear": "usure", "weather": "météo", "weight": "poids", "wet": "mouillé", "wetness": "humidité",
    "wheel": "roue", "wheelbase": "empattement", "wheels": "roues", "widget": "widget", "width": "largeur",
    "window": "fenêtre", "x": "X", "x11": "X11", "y": "Y", "yaw": "lacet", "yellow": "jaune", "zero": "zéro",
    "samples": "échantillons", "number": "nombre", "attach": "attacher", "show": "afficher",
    "bars": "barres", "code": "code", "dashboard": "tableau de bord", "inactive": "inactif", "lan": "réseau local",
    "spin": "patinage", "tread": "sculptures", "web": "web", "wizard": "assistant",
    "bands": "bandes", "label": "libellé", "leds": "LED", "mid": "moyen", "pedals": "pédales",
    "refuel": "carburant à ajouter", "shift": "passage de rapport",
    "and": "et", "at": "au", "for": "pour", "from": "depuis", "if": "si", "in": "en", "instead": "au lieu",
    "into": "dans", "of": "de", "on": "actif", "only": "uniquement", "out": "sortie", "per": "par",
    "to": "vers", "while": "pendant", "without": "sans", "as": "comme", "by": "par",
}

# Multi-word terms (matched first, longest first), never reversed
PHRASES = {
    "abs_activation": "activation ABS", "tc_activation": "activation TC", "tc_cut": "coupure TC",
    "tc_slip": "glissement TC", "ffb_clipping": "saturation FFB", "ffb_meter": "jauge FFB",
    "brake_bias": "répartition de freinage", "brake_migration": "migration de freinage",
    "brake_pressure": "pression de freinage", "brake_temperature": "température des freins",
    "brake_wear": "usure des freins", "brake_performance": "performance de freinage",
    "braking_rate": "taux de freinage", "brake_input": "entrée frein", "brake_line": "ligne frein",
    "fuel_bias": "répartition carburant", "fuel_ratio": "ratio carburant", "fuel_level": "niveau de carburant",
    "fuel_density": "densité du carburant", "fuel_energy_saver": "économiseur carburant/énergie",
    "fuel_calculator": "calculateur de carburant", "energy_level": "niveau d'énergie",
    "virtual_energy": "énergie virtuelle", "energy_remaining": "énergie restante",
    "tank_capacity": "capacité du réservoir", "delta_best": "delta best",
    "lap_time": "temps au tour", "laptime": "temps au tour", "best_laptime": "meilleur tour",
    "last_laptime": "dernier tour", "average_laptime": "tour moyen", "fastest_last_laptime": "dernier tour le plus rapide",
    "time_gap": "écart", "time_interval": "intervalle", "time_gain": "temps gagné", "time_loss": "temps perdu",
    "position_in_class": "position dans la classe", "position_change": "évolution de position",
    "position_gain": "places gagnées", "position_loss": "places perdues", "position_same": "position inchangée",
    "position_overall": "position générale", "driver_name": "nom du pilote", "vehicle_name": "nom du véhicule",
    "brand_logo": "logo de la marque", "tyre_compound": "gomme", "tyre_wear": "usure des pneus",
    "tyre_pressure": "pression des pneus", "tyre_temperature": "température des pneus",
    "tyre_load": "charge des pneus", "tyre_integrity": "intégrité des pneus", "tyre_carcass": "carcasse des pneus",
    "tyre_deflection": "déflexion des pneus", "tyre_inner_layer": "couche interne des pneus",
    "inner_layer": "couche interne", "wheel_camber": "carrossage", "wheel_toe": "pincement",
    "toe_angle": "angle de pincement", "wheel_slip": "glissement de roue", "wheel_lock": "blocage de roue",
    "wheel_lift_off": "levée de roue", "lift_off": "levée", "slip_angle": "angle de dérive",
    "slip_ratio": "taux de glissement", "yaw_rate": "vitesse de lacet", "yaw_angle": "angle de lacet",
    "roll_angle": "angle de roulis", "rake_angle": "assiette", "ride_height": "hauteur de caisse",
    "steering_angle": "angle de braquage", "steering_ratio": "démultiplication de direction",
    "steering_wheel": "volant", "steering_meter": "jauge de direction", "turning_radius": "rayon de braquage",
    "front_wheel_angle": "angle des roues avant", "front_wheel_lock": "blocage roues avant",
    "rear_wheel_lock": "blocage roues arrière", "front_arb": "barre antiroulis avant",
    "rear_arb": "barre antiroulis arrière", "front_downforce": "appui avant", "rear_downforce": "appui arrière",
    "downforce_ratio": "répartition d'appui", "front_to_rear_distribution": "répartition avant/arrière",
    "left_to_right_distribution": "répartition gauche/droite", "weight_distribution": "répartition des masses",
    "cross_weight": "poids croisé", "static_weight": "poids statique", "dynamic_weight": "poids dynamique",
    "unsprung_weight": "masse non suspendue", "power_to_weight_ratio": "rapport poids/puissance",
    "coast_locking": "blocage en roue libre", "power_locking": "blocage à l'accélération",
    "g_force": "force G", "lateral_g_force": "force G latérale", "longitudinal_g_force": "force G longitudinale",
    "friction_circle": "cercle d'adhérence", "osculating_circle": "cercle osculateur",
    "gravitational_acceleration": "accélération gravitationnelle", "acceleration_reduction": "réduction d'accélération",
    "motion_ratio": "rapport de mouvement", "bump_travel": "course en compression",
    "rebound_travel": "course en détente", "total_travel": "course totale", "travel_ratio": "rapport de course",
    "suspension_travel": "débattement de suspension", "suspension_position": "position de suspension",
    "suspension_force": "force de suspension", "suspension_integrity": "intégrité de la suspension",
    "third_spring": "troisième ressort", "body_integrity": "intégrité de la carrosserie",
    "aero_integrity": "intégrité aéro", "vehicle_integrity": "intégrité du véhicule",
    "flat_spot": "plat sur pneu", "engine_temperature": "température moteur", "oil_temperature": "température d'huile",
    "water_temperature": "température d'eau", "motor_temperature": "température du moteur électrique",
    "motor_map": "cartographie moteur", "electric_motor": "moteur électrique",
    "electric_braking_allocation": "répartition du freinage électrique", "regeneration_level": "niveau de régénération",
    "battery_charge": "charge batterie", "battery_drain": "décharge batterie", "battery_regen": "régénération batterie",
    "battery_cooldown": "refroidissement batterie", "push_to_pass": "push-to-pass",
    "speed_limiter": "limiteur de vitesse", "speed_trap": "radar de vitesse", "top_speed": "vitesse de pointe",
    "rpm_maximum": "RPM maximum", "over_rev": "sur-régime", "stalling_rpm": "régime de calage",
    "start_lights": "feux de départ", "red_lights": "feux rouges", "start_line": "ligne de départ",
    "blue_flag": "drapeau bleu", "yellow_flag": "drapeau jaune", "green_flag": "drapeau vert",
    "safety_car": "safety car", "track_limits": "limites de piste", "track_limits_points": "points limites de piste",
    "track_clock": "horloge de piste", "system_clock": "horloge système", "track_map": "carte de piste",
    "track_notes": "notes de piste", "pace_notes": "notes de rythme", "track_length": "longueur de piste",
    "distance_into_lap": "distance dans le tour", "lap_distance": "distance du tour",
    "pit_stop": "arrêt au stand", "pit_stop_estimate": "estimation d'arrêt au stand", "pit_time": "temps aux stands",
    "pit_timer": "chrono des stands", "pit_request": "demande d'arrêt", "pit_requests": "demandes d'arrêt",
    "pit_closed": "stands fermés", "pit_occupancy": "occupation des stands", "pit_entry": "entrée des stands",
    "pit_in": "entrée des stands", "pit_out": "sortie des stands", "pit_status": "statut des stands",
    "pit_notes": "notes de stand", "pit_comments": "commentaires de stand", "pitstop_count": "nombre d'arrêts",
    "pitstop_duration": "durée d'arrêt", "stop_go": "stop & go", "penalty_count": "nombre de pénalités",
    "scheduled_repairs": "réparations prévues", "car_setup": "réglage voiture", "car_setups": "réglages voiture",
    "garage_setup_info": "infos de réglage garage", "session_best": "meilleur de la session",
    "session_personal_best": "record personnel de la session", "session_deltabest": "delta best de la session",
    "stint_best": "meilleur du relais", "stint_deltabest": "delta best du relais", "all_time_deltabest": "delta best absolu",
    "all_time_best": "meilleur absolu", "personal_best": "record personnel", "stint_laps": "tours du relais",
    "stint_history": "historique des relais", "lap_time_history": "historique des temps au tour",
    "consumption_history": "historique de consommation", "last_stint": "dernier relais",
    "end_stint": "fin de relais", "end_remaining": "restant à l'arrivée", "estimated_laps": "tours estimés",
    "estimated_minutes": "minutes estimées", "estimated_time": "temps estimé", "estimated_consumption": "consommation estimée",
    "target_consumption": "consommation cible", "target_laps": "tours cibles", "target_time": "temps cible",
    "target_laptime": "temps au tour cible", "saving_target": "objectif d'économie",
    "net_change": "variation nette", "rate_of_change": "vitesse de variation", "lift_and_coast": "lift & coast",
    "live_position": "position en direct", "live_wear_difference": "écart d'usure en direct",
    "wear_difference": "écart d'usure", "lifespan_laps": "durée de vie (tours)", "lifespan_minutes": "durée de vie (minutes)",
    "sunlight_phase": "phase solaire", "rain_chance": "probabilité de pluie", "ambient_temperature": "température ambiante",
    "weather_forecast": "prévisions météo", "track_temperature": "température de piste",
    "time_scale": "échelle de temps", "session_time": "temps de session", "session_name": "nom de la session",
    "current_time": "heure actuelle", "spectate_mode": "mode spectateur", "global_hotkey": "raccourci global",
    "locked_preset": "preset verrouillé", "auto_backup_car_setup": "sauvegarde auto des réglages",
    "nearest_time_gap": "écart le plus proche", "traffic_highlight": "surbrillance du trafic",
    "multi_class": "multi-classe", "single_class": "mono-classe", "vehicle_class": "classe de véhicule",
    "brand_logo_path": "dossier des logos", "user_path": "dossier utilisateur", "high_dpi_scaling": "mise à l'échelle haute résolution",
    "window_manager": "gestionnaire de fenêtres", "character_encoding": "encodage des caractères",
    "process_id": "ID de processus", "access_mode": "mode d'accès", "active_state": "état actif",
    "player_index": "index du joueur", "restapi_access": "accès RestAPI", "restapi_update": "mise à jour RestAPI",
    "connection_timeout": "délai de connexion", "connection_retry": "nouvelle tentative de connexion",
    "update_interval": "intervalle de mise à jour", "idle_update": "mise à jour au repos",
    "layout_guides": "guides d'alignement", "remote_control": "contrôle à distance", "vr_overlay": "overlay VR",
    "overlay_lock": "verrouillage de l'overlay", "overlay_theme": "thème de l'overlay",
    "overlay_auto_hide": "masquage auto de l'overlay", "overlay_visibility": "visibilité de l'overlay",
    "auto_hide": "masquage auto", "auto_load_preset": "chargement auto du preset", "grid_move": "déplacement sur grille",
    "font_name": "police", "font_weight": "graisse de police", "font_size": "taille de police",
    "font_offset_vertical": "décalage vertical du texte", "auto_font_offset": "décalage auto du texte",
    "modern_font": "police moderne", "text_alignment": "alignement du texte", "decimal_places": "décimales",
    "display_order": "ordre d'affichage", "option_group_title": "titres des groupes d'options",
    "bar_padding": "marge interne", "bar_gap": "espacement", "inner_gap": "espacement interne",
    "display_margin": "marge d'affichage", "leading_zero": "zéro initial", "percentage_sign": "signe %",
    "degree_sign": "signe degré", "extra_digits": "chiffres supplémentaires", "delta_laptime": "delta temps au tour",
    "delta_time": "delta temps", "delta_bar": "barre de delta", "deltabest_source": "source du delta best",
    "reference_circle": "cercle de référence", "reference_line": "ligne de référence",
    "distance_circle": "cercle de distance", "proximity_circle": "cercle de proximité",
    "center_mark": "repère central", "scale_mark": "graduation", "angle_mark": "repère d'angle",
    "position_mark": "repère de position", "collision_course": "trajectoire de collision",
    "overlap_indicator": "indicateur de chevauchement", "impact_cone": "cône d'impact",
    "curve_grade": "difficulté du virage", "length_grade": "longueur", "slope_grade": "pente",
    "sector_time": "temps du secteur", "race_leader": "leader de la course", "top_vehicles": "premiers véhicules",
    "relative_finish_order": "ordre d'arrivée relatif", "laps_and_position": "tours et position",
    "vehicles_per_split": "véhicules par séparation", "time_gap_leader": "écart au leader",
    "time_interval_leader": "intervalle au leader", "lap_difference": "différence de tours",
    "laps_ahead": "tours d'avance", "laps_behind": "tours de retard", "same_lap": "même tour",
    "invalid_laps": "tours invalides", "saved_laps": "tours enregistrés", "per_track": "par piste",
    "zero_elevation": "altitude zéro", "rubber_coverage": "couverture de gomme",
    "starting_rubber": "gomme de départ", "fixed_pitstop_duration": "durée d'arrêt fixe",
    "pitout_prediction": "prédiction de sortie des stands", "auto_pitout_prediction": "prédiction auto de sortie des stands",
    "additional_pitstop_time": "temps d'arrêt supplémentaire", "early_pitstop_count": "arrêts anticipés",
    "remaining_pitstop": "arrêts restants", "estimated_pitstop_count": "nombre d'arrêts estimé",
    "minimum_total_duration": "durée totale minimale", "pass_duration": "durée de passage",
    "stop_duration": "durée d'arrêt", "rubber_time_scale": "échelle de temps de la gomme",
    "manual_steering_range": "plage de braquage manuelle", "neutral_steer": "neutre",
    "critical_slip_ratio": "taux de glissement critique", "optimal_slip_ratio": "taux de glissement optimal",
    "hot_pressure": "pression à chaud", "pressure_cold": "pression à froid", "pressure_hot": "pression à chaud",
    "pressure_deviation": "écart de pression", "heatmap_name": "palette thermique",
    "heatmap_auto_matching": "palette thermique automatique", "window_color_theme": "thème de couleur de la fenêtre",
    "window_position_correction": "correction de la position de la fenêtre",
    "x11_platform_plugin_override": "forçage du plugin X11", "vr_compatibility": "compatibilité VR",
    "check_for_updates": "vérifier les mises à jour", "on_startup": "au démarrage", "at_startup": "au démarrage",
    "minimize_to_tray": "réduire dans la zone de notification", "quit_application": "quitter l'application",
    "restart_application": "redémarrer l'application", "restart_api": "redémarrer l'API",
    "reload_preset": "recharger le preset", "load_next_preset": "charger le preset suivant",
    "load_previous_preset": "charger le preset précédent", "select_next_api": "API suivante",
    "select_previous_api": "API précédente", "spectate_next_driver": "pilote suivant (spectateur)",
    "spectate_previous_driver": "pilote précédent (spectateur)", "bypass_window_manager": "contourner le gestionnaire de fenêtres",
    "attach_to_headset": "attacher au casque", "number_of_automatic_backups": "nombre de sauvegardes automatiques",
    "update_repository": "dépôt de mise à jour", "api_selection_from_preset": "sélection de l'API depuis le preset",
    "legacy_api_selection": "sélection des anciennes API", "private_qualifying": "qualifications privées",
    "for_race_only": "en course uniquement", "if_available": "si disponible", "if_not_available": "si indisponible",
    "while_in_pit": "aux stands", "in_pit": "aux stands", "in_garage": "au garage", "on_throttle": "à l'accélération",
    "off_throttle": "au lever de pied", "off_brake": "sans frein", "off_track": "hors piste",
    "from_same_class": "de la même classe", "from_same_class_only": "de la même classe uniquement",
    "from_current_lap": "depuis le tour actuel", "in_race": "en course", "while_offroad": "hors piste",
    "while_dry": "sur sec", "while_stationary_only": "à l'arrêt uniquement", "while_limiter_on": "limiteur actif",
    "while_requested_pitstop": "pendant une demande d'arrêt", "instead_of_class": "au lieu de la classe",
    "align_center": "centré", "color_theme": "thème de couleur", "user_image_file": "fichier image",
    "image_file": "fichier image", "file_name": "nom de fichier", "sound_format": "format audio",
    "sound_path": "dossier audio", "sound_volume": "volume audio", "global_offset": "décalage global",
    "line_break": "retour à la ligne", "warning_flash": "clignotement d'alerte", "damage_stats": "statistiques de dégâts",
    "onboard_setting": "réglages embarqués", "system_performance": "performances système",
    "tinypedal_performance": "performances de TinyPedal", "track_map_viewer": "visionneuse de carte",
    "tyre_strategy_planner": "planificateur de stratégie pneus", "vehicle_classification": "classement des véhicules",
    "class_standings": "classement par classe", "podium_by_class": "podium par classe",
    "multi_class_styling": "style multi-classe", "multi_class_split_mode": "mode de séparation multi-classe",
    "vehicles_combined_mode": "mode combiné", "vehicles_exclusive_mode": "mode exclusif",
    "vehicles_split_mode": "mode séparé", "single_class_exclusive_mode": "mode exclusif mono-classe",
    "raw_throttle": "accélérateur brut", "raw_brake": "frein brut", "raw_clutch": "embrayage brut",
    "throttle_filtered": "accélérateur filtré", "brake_filtered": "frein filtré", "clutch_filtered": "embrayage filtré",
    "yellow_flag_status": "statut du drapeau jaune", "blue_flag_for_race_only": "drapeau bleu en course uniquement",
    "sector_best": "meilleurs secteurs", "sector_best_path": "dossier des meilleurs secteurs",
    "delta_best_path": "dossier des delta best", "energy_delta_path": "dossier des deltas d'énergie",
    "fuel_delta_path": "dossier des deltas de carburant", "pace_notes_path": "dossier des notes de rythme",
    "track_map_path": "dossier des cartes", "track_notes_path": "dossier des notes de piste",
    "car_setups_path": "dossier des réglages voiture", "settings_path": "dossier des presets",
    "telemetry_path": "dossier de télémétrie", "last_file_path": "dernier fichier",
    "url_host": "hôte URL", "url_port": "port URL", "remote_control_port": "port du contrôle à distance",
    "custom_steering_wheel": "volant personnalisé", "headlights": "phares", "session_info": "infos de session",
    "time_scaled_countdown": "compte à rebours mis à l'échelle", "track_clock_synchronization": "synchronisation de l'horloge de piste",
    "overlay_width_meters": "largeur de l'overlay (mètres)", "distance_meters": "distance (mètres)",
    "vertical_offset_meters": "décalage vertical (mètres)", "horizontal_offset_meters": "décalage horizontal (mètres)",
    "save_invalid_laps": "enregistrer les tours invalides", "saved_laps_per_track": "tours conservés par piste",
    "minimum_lap_distance_percentage": "distance minimale du tour (%)",
    "speed_fastest": "vitesse la plus rapide", "speed_maximum": "vitesse maximum", "speed_minimum": "vitesse minimum",
    "above_critical": "au-dessus du seuil critique", "padding_horizontal": "marge interne horizontale",
    "padding_vertical": "marge interne verticale", "wheel_track": "voie", "for_each_wheel": "pour chaque roue",
    "relative_to_static_position": "par rapport à la position statique",
    "inner_center_outer": "intérieur, centre, extérieur", "player_highlighted": "joueur en surbrillance",
    "deltabest_extended": "delta best étendu", "fade_in": "fondu d'entrée", "fade_out": "fondu de sortie",
    "edge_fade_in": "fondu d'entrée du bord", "edge_fade_out": "fondu de sortie du bord",
    "radar_fade": "fondu du radar", "radar_fade_in": "fondu d'entrée du radar",
    "radar_fade_out": "fondu de sortie du radar", "trace_fade_out": "fondu de sortie de la trace",
    "in_private_qualifying": "en qualifications privées", "less_laps": "tours en moins", "more_laps": "tours en plus",
    "extra_laps": "tours supplémentaires", "marked_coordinates": "coordonnées marquées",
    "near_start": "proche du départ", "near_finish": "proche de l'arrivée",
    "highlighted_coordinates": "coordonnées en surbrillance",
    "traffic_extended": "trafic étendu", "position_increment": "incrément de position",
}

# Attribute templates (checked in order, longest first)
PREFIX_TEMPLATES = (
    ("background_color_", "Couleur de fond : {}"),
    ("bkg_color_", "Couleur de fond : {}"),
    ("font_color_", "Couleur du texte : {}"),
    ("decimal_places_", "Décimales : {}"),
    ("display_order_", "Ordre d'affichage : {}"),
    ("column_index_", "Colonne : {}"),
    ("column_", "Colonne : {}"),
    ("plugin_", "Plugin : {}"),
    ("caption_text_", "Légende : {}"),
    ("prefix_", "Préfixe : {}"),
    ("suffix_", "Suffixe : {}"),
    ("number_of_", "Nombre de {}"),
    ("widget_", "Widget : {}"),
    ("module_", "Module : {}"),
    ("show_column_", "Afficher la colonne : {}"),
    ("show_", "Afficher {}"),
    ("font_weight_", "Graisse de police : {}"),
    ("font_name_", "Police : {}"),
    ("enable_", "Activer {}"),
    ("warning_color_", "Couleur d'alerte : {}"),
    ("highlight_color_", "Couleur de surbrillance : {}"),
    ("font_size_", "Taille de police : {}"),
    ("font_scale_", "Échelle de police : {}"),
    ("maximum_", "{} maximum"),
    ("minimum_", "{} minimum"),
)
SUFFIX_TEMPLATES = (
    ("_outline_color", "Couleur du contour : {}"),
    ("_outline_width", "Épaisseur du contour : {}"),
    ("_line_width", "Épaisseur de ligne : {}"),
    ("_line_style", "Style de ligne : {}"),
    ("_text_alignment", "Alignement du texte : {}"),
    ("_decimal_places", "Décimales : {}"),
    ("_highlight_color", "Couleur de surbrillance : {}"),
    ("_warning_color", "Couleur d'alerte : {}"),
    ("_font_size", "Taille de police : {}"),
    ("_radius_g", "Rayon (G) : {}"),
    ("_color", "Couleur : {}"),
    ("_width", "Largeur : {}"),
    ("_height", "Hauteur : {}"),
    ("_size", "Taille : {}"),
    ("_style", "Style : {}"),
    ("_offset_x", "Décalage X : {}"),
    ("_offset_y", "Décalage Y : {}"),
    ("_radius", "Rayon : {}"),
    ("_scale", "Échelle : {}"),
    ("_threshold", "Seuil : {}"),
    ("_duration", "Durée : {}"),
    ("_samples", "Échantillons : {}"),
    ("_interval", "Intervalle : {}"),
    ("_length", "Longueur : {}"),
    ("_opacity", "Opacité : {}"),
    ("_margin", "Marge : {}"),
    ("_prefix", "Préfixe : {}"),
    ("_suffix", "Suffixe : {}"),
    ("_unit", "Unité : {}"),
    ("_range", "Plage : {}"),
    ("_text", "Texte : {}"),
)

# Words kept in place (connectors), noun groups between them are reversed
CONNECTORS = {
    "and", "at", "for", "from", "if", "in", "instead", "into", "of", "only", "per", "to", "while", "without",
    "as", "by", "above", "below", "under", "over", "on", "off",
}
CONNECTOR_PHRASES: set[str] = set()  # French text of phrases starting with a connector, filled below
LEADING_VERBS = {
    "check", "load", "quit", "restart", "select", "reload", "remember", "minimize", "attach", "swap", "bind",
    "spectate", "notify", "save", "toggle", "cycle", "freeze", "hide", "shorten", "align", "bypass",
}

# Trailing state words, appended after translated subject: (French, in parentheses)
QUALIFIERS = {
    "high": ("élevé", True), "low": ("faible", True), "extreme": ("extrême", True), "critical": ("critique", True),
    "heavy": ("lourds", True), "light": ("légers", True), "medium": ("moyens", True), "totaled": ("détruit", True),
    "full": ("complet", True), "normal": ("normal", True), "safe": ("sûr", True), "redline": ("zone rouge", True),
    "ahead": ("devant", True), "behind": ("derrière", True), "gain": ("gain", True), "loss": ("perte", True),
    "same": ("identique", True), "dry": ("sec", True), "wet": ("mouillé", True), "positive": ("positif", True),
    "negative": ("négatif", True), "start": ("début", True), "end": ("fin", True), "practice": ("essais", True),
    "qualifying": ("qualifications", True), "qualify": ("qualifications", True), "race": ("course", True),
    "testday": ("journée d'essais", True), "warmup": ("warm-up", True), "front": ("avant", False),
    "rear": ("arrière", False), "maximum": ("maximum", False), "minimum": ("minimum", False),
    "unavailable": ("indisponible", True), "available": ("disponible", True), "detached": ("détaché", True),
    "on": ("actif", True), "off": ("inactif", True), "over_rev": ("sur-régime", True), "player": ("joueur", True),
    "leader": ("leader", True), "yellow": ("jaune", True),
    "safety_car": ("safety car", True), "same_lap": ("même tour", True), "laps_ahead": ("tours d'avance", True),
    "laps_behind": ("tours de retard", True), "align_center": ("centré", False), "uppercase": ("en majuscules", False),
    "increasing": ("en hausse", True), "decreasing": ("en baisse", True), "constant": ("stable", True),
    "day": ("jour", True), "night": ("nuit", True), "flat": ("plat", True), "gentle": ("douce", True),
    "moderate": ("modérée", True), "steep": ("raide", True), "cliff": ("falaise", True),
    "hairpin": ("épingle", True), "straight": ("ligne droite", True), "short": ("court", True),
    "long": ("long", True), "very_long": ("très long", True), "extra_long": ("extra long", True),
    "extremely_long": ("extrêmement long", True), "left": ("gauche", True), "right": ("droite", True),
    "front_left": ("avant gauche", True), "front_right": ("avant droit", True), "rear_left": ("arrière gauche", True),
    "rear_right": ("arrière droit", True), "nearby": ("proche", True), "not_available": ("indisponible", True),
    "side": ("côté", True), "bottom": ("bas", True), "top": ("haut", True),
    "damage_heavy": ("dégâts lourds", True), "damage_light": ("dégâts légers", True),
    "damage_medium": ("dégâts moyens", True), "damage_totaled": ("détruit", True),
}
# Infix attributes: "<subject>_<attribute>_<state>" -> "<Attribute> : <subject> (<state>)"
INFIX = (
    ("_outline_color_", "Couleur du contour"), ("_outline_width_", "Épaisseur du contour"),
    ("_color_", "Couleur"), ("_width_", "Largeur"), ("_multiplier_", "Multiplicateur"),
    ("_threshold_", "Seuil"), ("_scale_", "Échelle"), ("_text_", "Texte"), ("_size_", "Taille"),
)

# Full key overrides
FULL = {
    "enable": "Activer", "update_interval": "Intervalle de mise à jour (ms)",
    "idle_update_interval": "Intervalle au repos (ms)", "position_x": "Position X", "position_y": "Position Y",
    "opacity": "Opacité", "bar_gap": "Espacement", "inner_gap": "Espacement interne", "bar_padding": "Marge interne",
    "bar_padding_horizontal": "Marge interne horizontale", "bar_padding_vertical": "Marge interne verticale",
    "font_name": "Police", "font_size": "Taille de police", "font_weight": "Graisse de police",
    "enable_auto_font_offset": "Décalage auto du texte", "font_offset_vertical": "Décalage vertical du texte",
    "base_display": "Affichage de base", "font_style": "Style de police", "display_order": "Ordre d'affichage",
    "language": "Langue", "prefix": "Préfixe", "layout": "Disposition", "show_caption": "Afficher la légende",
    "text_alignment": "Alignement du texte", "decimal_places": "Décimales", "application": "Application",
    "compatibility": "Compatibilité", "user_path": "Dossiers utilisateur", "units": "Unités",
    "notification": "Notification", "overlay": "Overlay", "overlay_style": "Style de l'overlay",
    "remote_control": "Contrôle à distance", "vr_overlay": "Overlay VR", "enable_remote_control": "Activer le contrôle à distance",
    "enable_vr_overlay": "Activer l'overlay VR", "show_at_startup": "Afficher au démarrage",
    "check_for_updates_on_startup": "Vérifier les mises à jour au démarrage",
    "minimize_to_tray": "Réduire dans la zone de notification", "remember_position": "Mémoriser la position",
    "remember_size": "Mémoriser la taille", "enable_high_dpi_scaling": "Mise à l'échelle haute résolution",
    "enable_auto_load_preset": "Chargement auto du preset", "show_confirmation_for_batch_toggle": "Confirmer les activations groupées",
    "show_option_group_title": "Afficher les titres de groupes d'options",
    "enable_layout_guides": "Guides d'alignement", "show_layout_guides": "Afficher les guides d'alignement",
    "snap_distance": "Distance d'aimantation", "snap_gap": "Écart d'aimantation", "grid_move_size": "Pas de la grille",
    "number_of_automatic_backups": "Nombre de sauvegardes automatiques",
    "maximum_saving_attempts": "Tentatives d'enregistrement max.", "maximum_loading_attempts": "Tentatives de chargement max.",
    "window_color_theme": "Thème de la fenêtre", "update_repository": "Dépôt de mise à jour",
    "overlay_theme": "Thème de l'overlay", "enable_modern_font": "Police moderne",
    "modern_font_name": "Nom de la police moderne", "minimum_bar_gap": "Espacement minimal",
    "enable_rounded_corners": "Coins arrondis", "corner_radius": "Rayon des coins",
    "remote_control_port": "Port", "enable_attach_to_headset": "Attacher au casque",
    "overlay_width_meters": "Largeur (mètres)", "distance_meters": "Distance (mètres)",
    "vertical_offset_meters": "Décalage vertical (mètres)", "horizontal_offset_meters": "Décalage horizontal (mètres)",
    "number_of_saved_laps_per_track": "Tours conservés par piste", "save_invalid_laps": "Enregistrer les tours invalides",
    "minimum_lap_distance_percentage": "Distance minimale du tour (%)", "api_name": "Nom de l'API",
    "number_of_best_laps_kept_per_track": "Meilleurs tours toujours conservés par piste",
    "enable_lap_recording": "Enregistrer les tours", "lap_recording": "Enregistrement des tours",
    "enable_lap_recording_during_replay": "Enregistrer les tours pendant un rejeu",
    "enable_out_and_in_lap_recording": "Enregistrer les tours de sortie et de rentrée",
    "enable_compressed_lap_files": "Compresser les fichiers de tours",
    "enable_auto_replay_recording": "Enregistrer automatiquement un rejeu",
    "auto_replay_recording": "Enregistrement automatique du rejeu",
    "enable_replay_skip_inactive_frames": "Ignorer les images hors conduite dans les rejeux",
    "number_of_saved_replays": "Rejeux automatiques conservés",
    "access_mode": "Mode d'accès", "process_id": "ID de processus", "character_encoding": "Encodage des caractères",
    "url_host": "Hôte URL", "url_port": "Port URL", "connection_timeout": "Délai de connexion",
    "connection_retry": "Tentatives de connexion", "connection_retry_delay": "Délai entre tentatives",
    "enable_restapi_access": "Accès RestAPI", "enable_active_state_override": "Forcer l'état actif",
    "active_state": "État actif", "enable_player_index_override": "Forcer l'index du joueur", "player_index": "Index du joueur",
    "show_brake_bias": "Afficher la répartition de freinage", "show_caption_text": "Afficher le texte de légende",
    "speed_unit": "Unité de vitesse", "distance_unit": "Unité de distance", "fuel_unit": "Unité de carburant",
    "temperature_unit": "Unité de température", "tyre_pressure_unit": "Unité de pression des pneus",
    "turbo_pressure_unit": "Unité de pression turbo", "power_unit": "Unité de puissance", "weight_unit": "Unité de poids",
    "odometer_unit": "Unité de l'odomètre", "brand_logo": "Logo de la marque",
    "start_line_width": "Épaisseur : ligne de départ", "time_interval": "Intervalle", "time_scale": "Échelle de temps",
    "turning_radius": "Rayon de braquage", "ride_height": "Hauteur de caisse", "stop_duration": "Durée d'arrêt",
    "pitstop_duration": "Durée d'arrêt", "pass_duration": "Durée de passage",
    "track_clock_time_scale": "Échelle de temps de l'horloge de piste", "swap_style": "Inverser le style",
    "show_speed_below_gear": "Afficher la vitesse sous le rapport",
    "show_vehicle_brand_as_name": "Afficher la marque comme nom du véhicule",
    "maximum_vehicles_combined_mode": "Véhicules max. (mode combiné)",
    "maximum_vehicles_exclusive_mode": "Véhicules max. (mode exclusif)",
    "maximum_vehicles_split_mode": "Véhicules max. (mode séparé)",
    "maximum_vehicles_per_split_others": "Véhicules max. par séparation (autres)",
    "maximum_vehicles_per_split_player": "Véhicules max. par séparation (joueur)",
    "minimum_pitstop_threshold_seconds": "Seuil minimal d'arrêt au stand (s)",
    "minimum_stint_threshold_minutes": "Seuil minimal de relais (min)",
    "minimum_update_interval": "Intervalle de mise à jour minimal (ms)",
    "average_samples": "Échantillons de moyenne", "average_sampling_duration": "Durée d'échantillonnage de la moyenne",
    "trace_fade_out_step": "Pas du fondu de sortie de la trace", "position_increment_step": "Pas d'incrément de position",
    "wheel_track_front": "Voie avant", "wheel_track_rear": "Voie arrière",
    "black_box": "Black box", "widget_black_box": "Widget : black box",
    "display_profile": "Profil d'affichage",
    "auto_compact_display_scale": "Échelle : mode compact automatique en dessous de",
    "slow_data_update_interval": "Intervalle : mise à jour des données lentes",
    "font_color_tyre_temperature_warming": "Couleur du texte : pneus en chauffe",
    "font_color_tyre_temperature_cold": "Couleur du texte : pneus froids",
    "tyre_temperature_cold_threshold": "Seuil : pneus froids",
    "tyre_heat_trend_threshold": "Seuil : tendance température des pneus",
    "override_unit_temperature": "Unité de température (widget)",
    "override_unit_tyre_pressure": "Unité de pression des pneus (widget)",
    "override_unit_speed": "Unité de vitesse (widget)",
    "override_unit_fuel": "Unité de carburant (widget)",
    "tyre_target_by_compound": "Cibles des pneus par gomme",
    "brake_temperature_cold_threshold": "Seuil : freins froids",
    "brake_temperature_hot_threshold": "Seuil : freins en surchauffe",
    "font_color_brake_temperature_cold": "Couleur du texte : freins froids",
    "font_color_brake_temperature_hot": "Couleur du texte : freins en surchauffe",
    "show_stint_comparison": "Afficher la comparaison avec le relais précédent",
    "text_puncture": "Texte : crevaison", "text_flat_spot": "Texte : plat sur pneu",
    "text_detached": "Texte : roue détachée", "text_abs": "Texte : ABS", "text_tc": "Texte : TC",
    "text_brake_bias": "Texte : répartition de freinage", "text_brake_migration": "Texte : migration de freinage",
    "text_locking": "Texte : blocage", "text_delta": "Texte : delta", "text_laptime": "Texte : temps au tour",
    "text_pit": "Texte : stand", "text_limiter": "Texte : limiteur", "text_speed": "Texte : vitesse",
    "text_rpm": "Texte : RPM", "text_refuel": "Texte : carburant à ajouter", "text_refill": "Texte : énergie à ajouter",
    "text_fuel": "Texte : carburant", "text_energy": "Texte : énergie",
    "text_stint_wear": "Texte : usure du relais", "text_stint_pressure": "Texte : pression du relais",
    "text_damage": "Texte : dégâts", "text_impact": "Texte : impact",
    "show_suspension": "Afficher les suspensions",
    "suspension_scale": "Échelle : suspensions",
    "suspension_motion_scale": "Échelle du mouvement de suspension (1 = réel)",
    "enable_wheel_suspension_motion": "Roues et disques suivent les suspensions",
    "suspension_spring_color": "Couleur : ressort",
    "suspension_compression_color": "Couleur : suspension en compression",
    "suspension_rebound_color": "Couleur : suspension en détente",
    "suspension_bump_color": "Couleur : suspension en butée",
    "suspension_bump_force_margin": "Marge de force au-dessus du ressort pour la butée (fraction)",
    "suspension_airborne_color": "Couleur : roue en l'air",
    "show_coilover_damage": "Afficher les dégâts sur les suspensions",
    "show_tyre_camber_spread": "Afficher l'écart intérieur - extérieur (carrossage)",
    "show_tyre_surface_overheat": "Signaler la surchauffe de surface (glissade)",
    "tyre_pressure_target_rear_minimum": "Pression cible arrière minimum (0 = comme l'avant)",
    "tyre_pressure_target_rear_maximum": "Pression cible arrière maximum (0 = comme l'avant)",
    "show_tyre_pressure_range": "Afficher la pression mini-maxi du relais",
    "tyre_wear_forecast_laps": "Tours pour l'usure prévue (0 = fin du relais)",
    "show_brake_peak_temperature": "Afficher le pic de température par freinage",
    "brake_imbalance_threshold": "Seuil : écart gauche-droite des disques (°C)",
    "brake_wear_display": "Affichage de l'usure des disques",
    "show_brake_heat_balance": "Afficher l'écart de température avant - arrière des disques",
    "text_brake_heat": "Texte : écart avant - arrière des disques",
    "display_order_brake_heat": "Ordre : écart avant - arrière des disques",
    "show_motor_map": "Afficher la cartographie moteur",
    "text_motor_map": "Texte : cartographie moteur",
    "brake_bias_color": "Couleur : répartition de freinage",
    "motor_map_color": "Couleur : cartographie moteur",
    "status_icons_side": "Côté des icônes feux / moteur",
    "status_icon_scale": "Échelle : icônes feux / moteur",
    "font_scale_engine": "Échelle : texte moteur",
    "show_headlights_indicator": "Afficher le voyant des feux",
    "headlights_active_color": "Couleur : feux allumés",
    "show_engine_status": "Afficher l'état moteur (contact, huile / eau)",
    "stalling_rpm_threshold": "Seuil : régime moteur calé",
    "engine_oil_warning_temperature": "Seuil : température d'huile",
    "engine_water_warning_temperature": "Seuil : température d'eau",
    "engine_warning_color": "Couleur : moteur chaud",
    "engine_off_color": "Couleur : moteur éteint",
    "engine_ignition_color": "Couleur : contact mis",
    "engine_running_color": "Couleur : moteur en marche",
    "text_oil": "Texte : huile",
    "text_water": "Texte : eau",
    "text_engine_off": "Texte : moteur éteint",
    "text_ignition": "Texte : contact",
    "show_suspension_lap_stats": "Afficher butées et débattement utilisé par tour",
    "show_damper_histogram": "Afficher l'histogramme des vitesses d'amortisseur",
    "show_ride_height_minimum": "Afficher la hauteur de caisse mini et les talonnages par tour",
    "ride_height_bottoming_threshold": "Seuil : talonnage (hauteur de caisse, mm)",
    "show_third_spring": "Afficher le troisième ressort",
    "incident_export_format": "Format d'export des incidents",
    "damage_event_threshold": "Seuil : hausse minimum des dégâts journalisée",
    "trace_steering_color": "Couleur : volant (tracé)",
    "black_box_next_incident": "Black box : incident suivant",
    "black_box_open_incident_folder": "Black box : ouvrir le dossier des incidents",
    "enable_incident_replay": "Activer le rejeu de l'incident",
    "incident_replay": "Rejeu de l'incident",
    "show_previous_incident_trace": "Afficher la trace de l'incident précédent",
    "show_flag_events": "Journal : drapeaux",
    "show_pit_events": "Journal : entrée et sortie des stands",
    "show_penalty_events": "Journal : pénalités et limites de piste",
    "show_engine_overheat_events": "Journal : surchauffe moteur",
    "text_yellow_flag": "Texte : drapeau jaune", "text_blue_flag": "Texte : drapeau bleu",
    "text_pit_in": "Texte : entrée des stands", "text_pit_out": "Texte : sortie des stands",
    "text_penalty": "Texte : pénalité", "text_track_limits": "Texte : limites de piste",
    "text_overheat": "Texte : surchauffe", "flag_events": "Événements de drapeau",
    "enable_brake_bias_migration_merge": "Répartition et migration de freinage sur une ligne",
    "pedal_input_source": "Source des pédales",
    "show_clutch_bar": "Afficher la barre d'embrayage",
    "clutch_color": "Couleur : embrayage",
    "suspension_low_speed_threshold": "Vitesse d'amortisseur basse / haute vitesse (mm/s)",
    "suspension_velocity_scale": "Vitesse d'amortisseur pour couleur pleine (mm/s)",
    "tyre_temperature_source": "Source de la température des pneus",
    "tyre_load_display": "Affichage de la charge des pneus",
    "wheel_locked_threshold": "Seuil : roue bloquée (taux de glissement)",
    "brake_target_by_class": "Plage de température des disques par catégorie",
    "show_brake_temperature_trend": "Afficher la tendance de température des disques",
    "brake_trend_duration": "Durée : tendance des disques",
    "brake_heat_trend_threshold": "Seuil : tendance de température des disques",
    "show_gear_speed_cluster": "Regrouper rapport et vitesse dans un bloc",
    "enable_auto_resize": "Activer le redimensionnement automatique",
    "resize_delay": "Délai : redimensionnement",
    "resize_anchor": "Coin fixe lors du redimensionnement",
    "fixed_width": "Largeur fixe (0 = automatique)",
    "fixed_height": "Hauteur fixe (0 = automatique)",
    "tyre_scale": "Échelle : pneus et freins",
    "center_column_scale": "Échelle : largeur de la colonne centrale",
    "gauge_row_scale": "Échelle : hauteur des jauges",
    "event_log_line_scale": "Échelle : lignes du journal",
    "show_module_warning": "Signaler les modules de données désactivés",
    "font_color_module_warning": "Couleur du texte : module désactivé",
    "enable_required_modules": "Activer automatiquement les modules nécessaires",
    "show_fuel_gauge": "Afficher la jauge de carburant",
    "show_energy_gauge": "Afficher la jauge d'énergie virtuelle",
    "fuel_gauge_color": "Couleur : jauge de carburant",
    "energy_gauge_color": "Couleur : jauge d'énergie virtuelle",
    "gauge_low_color": "Couleur : jauge basse",
    "gauge_low_lap_threshold": "Seuil : jauge basse (tours)",
    "show_gauge_start_mark": "Afficher le repère du niveau de départ",
    "gauge_start_mark_color": "Couleur : repère du niveau de départ",
    "show_gauge_refill_mark": "Afficher le repère du niveau après ravitaillement",
    "gauge_refill_mark_color": "Couleur : repère du niveau après ravitaillement",
    "show_damage_panel": "Afficher le panneau des dégâts",
    "damage_panel_position": "Coin du panneau des dégâts",
    "damage_panel_scale": "Échelle : panneau des dégâts",
    "damage_panel_body_color": "Couleur : carrosserie intacte",
    "damage_panel_body_color_light": "Couleur : carrosserie légèrement endommagée",
    "damage_panel_body_color_heavy": "Couleur : carrosserie très endommagée",
    "damage_panel_body_color_detached": "Couleur : élément de carrosserie détaché",
    "damage_panel_suspension_color": "Couleur : suspension intacte",
    "damage_panel_suspension_color_light": "Couleur : suspension légèrement endommagée",
    "damage_panel_suspension_color_medium": "Couleur : suspension moyennement endommagée",
    "damage_panel_suspension_color_heavy": "Couleur : suspension très endommagée",
    "damage_panel_suspension_color_totaled": "Couleur : suspension détruite",
    "damage_panel_suspension_light_threshold": "Seuil : suspension légèrement endommagée",
    "damage_panel_suspension_medium_threshold": "Seuil : suspension moyennement endommagée",
    "damage_panel_suspension_heavy_threshold": "Seuil : suspension très endommagée",
    "damage_panel_suspension_totaled_threshold": "Seuil : suspension détruite",
    "damage_panel_wheel_color_detached": "Couleur : roue détachée",
    "damage_panel_puncture_color": "Couleur : crevaison",
    "show_damage_panel_impact_cone": "Afficher la direction du dernier impact",
    "damage_panel_impact_cone_angle": "Angle : cône d'impact",
    "damage_panel_impact_cone_duration": "Durée : cône d'impact",
    "damage_panel_impact_cone_color": "Couleur : cône d'impact",
    "show_damage_panel_integrity": "Afficher l'intégrité",
    "show_damage_panel_aero_integrity": "Afficher l'intégrité aéro si disponible",
    "text_integrity_body": "Texte : intégrité carrosserie", "text_integrity_aero": "Texte : intégrité aéro",
    "enable_depth_effects": "Activer les effets de profondeur",
    "smooth_transition_duration": "Durée : transition de couleur (0 = désactivée)",
    "alert_pulse_frequency": "Fréquence : pulsation des alertes (0 = désactivée)",
    "show_incident_recorder": "Afficher l'enregistreur d'incidents",
    "recorder_duration": "Durée : enregistrement",
    "incident_deceleration_threshold": "Seuil : décélération d'incident (g)",
    "incident_display_duration": "Durée : affichage de l'incident",
    "enable_incident_file_export": "Activer l'export des incidents en fichier",
    "trace_height_scale": "Échelle : hauteur de la courbe",
    "trace_speed_color": "Couleur de la courbe de vitesse",
    "trace_background_color": "Couleur du fond de la courbe",
    "incident_color": "Couleur des incidents",
    "show_event_log": "Afficher le journal des événements",
    "number_of_event_log_lines": "Nombre de lignes du journal",
    "font_color_event_log": "Couleur du texte : journal des événements",
    "display_scale": "Échelle d'affichage",
    "show_tyre_temperature_bands": "Températures intérieur / milieu / extérieur (bandes)",
    "enable_tyre_pressure_target": "Plage cible de pression", "tyre_pressure_target_minimum": "Pression cible minimale (kPa)",
    "tyre_pressure_target_maximum": "Pression cible maximale (kPa)", "tyre_pressure_low_color": "Couleur : pression trop basse",
    "tyre_pressure_high_color": "Couleur : pression trop haute",
    "show_tyre_wear_end_stint": "Afficher l'usure estimée en fin de relais",
    "show_tyre_status": "Afficher crevaison / roue détachée / méplat", "flat_spot_threshold": "Seuil de méplat (% d'usure au blocage)",
    "wheel_puncture_color": "Couleur : crevaison", "wheel_flat_spot_color": "Couleur : méplat",
    "wheel_detached_color": "Couleur : roue détachée", "show_suspension_damage": "Afficher les dégâts de suspension",
    "show_body_damage": "Afficher les dégâts de carrosserie", "show_rpm_leds": "Afficher les LED de régime",
    "number_of_rpm_leds": "Nombre de LED de régime", "rpm_led_start_ratio": "Allumage de la 1re LED (fraction du régime max)",
    "rpm_led_low_color": "Couleur : LED bas régime", "rpm_led_mid_color": "Couleur : LED régime moyen",
    "rpm_led_high_color": "Couleur : LED haut régime", "rpm_led_shift_color": "Couleur : LED passage de rapport",
    "shift_flash_interval": "Intervalle de clignotement (s)",
    "show_pit_limiter_indicator": "Afficher les voyants stands / limiteur",
    "pit_active_color": "Couleur : voie des stands", "limiter_active_color": "Couleur : limiteur actif",
    "enable_gear_rpm_color": "Couleur du rapport selon le régime", "gear_color_low": "Couleur du rapport : bas régime",
    "gear_color_mid": "Couleur du rapport : régime moyen", "gear_color_shift": "Couleur du rapport : passage",
    "gear_mid_rpm_ratio": "Début du régime moyen (fraction du régime max)",
    "enable_shift_flash": "Clignotement au passage de rapport",
    "show_fuel_remaining": "Afficher le carburant restant", "show_energy_remaining": "Afficher l'énergie restante",
    "display_order_abs": "Ordre d'affichage : ABS", "display_order_tc": "Ordre d'affichage : TC",
    "display_order_brake_bias": "Ordre d'affichage : répartition de freinage",
    "display_order_pit_limiter": "Ordre d'affichage : stands / limiteur",
    "display_order_gear": "Ordre d'affichage : rapport", "display_order_speed": "Ordre d'affichage : vitesse",
    "display_order_rpm": "Ordre d'affichage : RPM", "display_order_pedals": "Ordre d'affichage : pédales", "font_scale_gear": "Taille du rapport engagé",
    "font_scale_speed": "Taille de la vitesse", "font_scale_rpm": "Taille des RPM", "show_gear": "Afficher le rapport engagé",
    "font_color_gear": "Couleur du texte : rapport", "show_speed": "Afficher la vitesse", "show_rpm": "Afficher les RPM",
    "rpm_bar_color": "Couleur : barre RPM", "rpm_redline_color": "Couleur : RPM zone rouge",
    "rpm_redline_ratio": "Début de la zone rouge (fraction du régime max)", "show_refuel": "Afficher le carburant à ajouter",
    "show_refill": "Afficher l'énergie virtuelle à ajouter", "info_background_color": "Couleur de fond : infos",
    "font_color_info_label": "Couleur du texte : libellés", "show_tyre_wear": "Afficher l'usure des pneus",
    "tyre_wear_warning_threshold": "Seuil d'alerte d'usure (% restant)",
    "tyre_wear_warning_color": "Couleur : alerte d'usure", "font_color_tyre_wear_warning": "Couleur du texte : alerte d'usure", "show_wheel_angle": "Afficher le braquage des roues",
    "maximum_wheel_angle": "Braquage affiché maximal (°)", "show_slip_warning": "Alerte blocage / patinage",
    "wheel_lock_threshold": "Seuil de blocage de roue", "wheel_spin_threshold": "Seuil de patinage",
    "slip_warning_minimum_speed": "Vitesse minimale d'alerte (km/h)",
    "warning_outline_width": "Épaisseur du contour d'alerte", "wheel_lock_color": "Couleur : blocage de roue",
    "wheel_spin_color": "Couleur : patinage", "show_abs_indicator": "Afficher l'indicateur ABS",
    "abs_active_color": "Couleur : ABS actif", "show_tc_indicator": "Afficher l'indicateur TC",
    "tc_active_color": "Couleur : TC actif", "indicator_inactive_color": "Couleur : indicateur inactif",
    "font_color_indicator": "Couleur du texte : indicateur",
    "font_color_indicator_active": "Couleur du texte : indicateur actif",
    "show_pedal_bars": "Afficher les barres de pédales", "heatmap_name_tyre": "Palette thermique des pneus",
    "heatmap_name_brake": "Palette thermique des freins", "widget_theme": "Thème du widget",
    "show_setup_wizard_at_startup": "Assistant de configuration au démarrage",
    "last_page_index": "Dernière page ouverte",
    "enable_layout_per_screen_setup": "Disposition mémorisée par configuration d'écrans",
    "overlay_scale": "Échelle de l'overlay",
    "visibility_context": "Afficher pendant",
    "enable_vr_mirror_window": "Fenêtre miroir VR (OpenKneeboard, OVR Toolkit...)",
    "mirror_background_color": "Couleur de fond de la fenêtre miroir",
    "enable_fade_animation": "Fondu à l'affichage et au masquage",
    "web_dashboard": "Tableau de bord web", "enable_web_dashboard": "Activer le tableau de bord web",
    "enable_lan_access": "Accès depuis le réseau local", "web_dashboard_port": "Port",
    "access_code": "Code d'accès",
}
# Regex overrides for numbered families: (pattern, template), groups are passed to template
FULL_REGEX = (
    (r"^reference_circle_(\d+)_radius_g$", "Rayon du cercle de référence {0} (G)"),
    (r"^reference_circle_(\d+)_(color|style|width)$", None),
    (r"^reference_line_(\d+)_offset$", "Décalage de la ligne de référence {0}"),
    (r"^distance_circle_(\d+)_radius$", "Rayon du cercle de distance {0}"),
    (r"^speed_range_(\d+)_(start|end)$", "Plage de vitesse {0} : {1}"),
    (r"^prediction_(\d+)_(leader|player)_pit_time$", "Prédiction {0} : temps aux stands ({1})"),
    (r"^fixed_pitstop_duration_(\d+)$", "Durée d'arrêt fixe {0}"),
    (r"^(pit|preset)_(\d+)$", None),
    (r"^preset_(\d+)$", "Preset {0}"),
    (r"^curve_grade_(\d)$", "Virage niveau {0}"),
    (r"^rubber_time_scale_(\w+)$", "Échelle de temps de la gomme ({0})"),
    (r"^map_color_sector_(\d)$", "Couleur : secteur {0} de la carte"),
)
REGEX_WORDS = {
    "start": "début", "end": "fin", "leader": "leader", "player": "joueur",
    "practice": "essais", "qualifying": "qualifications", "race": "course",
}


PRE_ADJECTIVES = {"last": "dernier", "best": "meilleur", "next": "prochain", "total": "total"}
PROPER_NAMES = ("TinyPedal", "Ackermann", "RestAPI")

CONNECTOR_PHRASES.update(
    text for phrase, text in PHRASES.items() if phrase.split("_")[0] in CONNECTORS or phrase.startswith("align_")
)


def _phrase_tokens(words: list[str]) -> list[tuple[str, bool]]:
    """Split words into (text, is_phrase_or_connector) tokens, longest phrase first"""
    tokens: list[tuple[str, bool]] = []
    index = 0
    while index < len(words):
        for size in range(len(words) - index, 0, -1):
            chunk = "_".join(words[index:index + size])
            if size > 1 and chunk in PHRASES:
                tokens.append((PHRASES[chunk], True))
                index += size
                break
        else:
            tokens.append((words[index], False))
            index += 1
    return tokens


def translate_subject(subject: str) -> str:
    """Translate subject words to French noun phrase"""
    if not subject:
        return ""
    if subject in PHRASES:
        return PHRASES[subject]
    words = subject.split("_")
    verb = ""
    if words[0] in LEADING_VERBS and len(words) > 1:
        verb = WORDS.get(words[0], words[0])
        words = words[1:]
    output: list[str] = []
    group: list[str] = []  # noun group, reversed when closed
    before: list[str] = []  # French pre-nominal adjectives of current group (dernier, meilleur...)

    def close_group():
        if group or before:
            output.extend(before)
            output.extend(reversed(group))
            group.clear()
            before.clear()

    for text, fixed in _phrase_tokens(words):
        if fixed and text in CONNECTOR_PHRASES:
            close_group()
            output.append(text)
        elif fixed:
            group.append(text)
        elif text in CONNECTORS:
            close_group()
            output.append(WORDS.get(text, text))
        elif text.isdigit():
            close_group()
            output.append(text)
        elif text in PRE_ADJECTIVES and not group:
            before.append(PRE_ADJECTIVES[text])
        else:
            group.append(WORDS.get(text, text))
    close_group()
    result = " ".join(output)
    return f"{verb} {result}".strip() if verb else result


def translate_key(key: str) -> str:
    """Translate option key to French label"""
    if key in FULL:
        return FULL[key]
    for pattern, template in FULL_REGEX:
        match = re.match(pattern, key)
        if match and template:
            return template.format(*(REGEX_WORDS.get(group, group) for group in match.groups()))
    for prefix, template in PREFIX_TEMPLATES:
        if key.startswith(prefix) and len(key) > len(prefix):
            return capitalize(template.format(translate_nested(key[len(prefix):])))
    for suffix, template in SUFFIX_TEMPLATES:
        if key.endswith(suffix) and len(key) > len(suffix):
            return capitalize(template.format(translate_nested(key[:-len(suffix)])))
    for infix, attribute in INFIX:
        subject, found, state = key.partition(infix)
        if found and subject and state:
            return f"{attribute} : {translate_nested(subject)} ({translate_nested(state)})"
    return capitalize(translate_qualified(key))


def translate_nested(key: str) -> str:
    """Translate inner part of templated key (no further templates), lowercase first letter"""
    if key in QUALIFIERS:
        text = QUALIFIERS[key][0]
    else:
        text = FULL.get(key) or translate_qualified(key)
    if len(text) > 1 and text[1].islower() and not text.startswith(PROPER_NAMES):
        return text[0].lower() + text[1:]
    return text


def translate_qualified(key: str) -> str:
    """Translate subject, with trailing state qualifier placed after it"""
    for qualifier in sorted(QUALIFIERS, key=len, reverse=True):
        if key.endswith(f"_{qualifier}") and key not in PHRASES:
            base = key[:-len(qualifier) - 1]
            if base.rsplit("_", 1)[-1] in CONNECTORS:  # "above_critical": connector object, not qualifier
                continue
            if any(key.endswith(f"_{phrase}") and len(phrase) > len(qualifier) for phrase in PHRASES):
                continue  # longer phrase (if_not_available) has priority
            french, in_parentheses = QUALIFIERS[qualifier]
            base_text = translate_subject(base)
            return f"{base_text} ({french})" if in_parentheses else f"{base_text} {french}"
    return translate_subject(key)


def capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def collect_keys() -> list[str]:
    """All option, group, widget & module keys"""
    from tinypedal.setting import cfg
    from tinypedal.ui.config import option_group_name

    cfg.default.set_default()
    keys: set[str] = set()
    for name in ("config", "setting", "shortcuts"):
        for section, options in dict(getattr(cfg.default, name)).items():
            if not isinstance(options, dict):
                continue
            keys.add(section)
            option_keys = list(options)
            group = ""
            for key, next_key in zip_longest(option_keys, option_keys[1:], fillvalue=""):
                keys.add(key)
                if name != "shortcuts":
                    group = option_group_name(key, next_key, group)
                    if group and group != "_same_group":
                        keys.add(group)
    return sorted(keys)


def main():
    keys = collect_keys()
    unknown = sorted({
        word for key in keys for word in key.split("_")
        if word not in WORDS and not word.isdigit()
    })
    if unknown:
        print("Untranslated words:", " ".join(unknown))
    labels = {key: translate_key(key) for key in keys}
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as file:  # generated, do not edit by hand
        json.dump(labels, file, ensure_ascii=False, indent=4, sort_keys=True)
        file.write("\n")
    print(f"{len(keys)} labels written to {OUTPUT}")


if __name__ == "__main__":
    main()
