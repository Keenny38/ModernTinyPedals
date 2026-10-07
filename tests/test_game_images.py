"""Car brand & circuit pictures of LMU web UI: names of game data mapped to picture paths"""

import pytest

from tinypedal.process import game_images as gi


@pytest.mark.parametrize("names, key", [
    (("Circuit de la Sarthe",), "lemanswec"),
    (("LEMANS_2023", ""), "lemanswec"),
    (("Le Mans Mulsanne",), "lemanswec"),
    (("Losail International Circuit",), "qatarwec"),
    (("Autódromo Internacional do Algarve",), "portimaowec"),
    (("Autodromo Enzo e Dino Ferrari",), "imolawec"),
    (("Autódromo José Carlos Pace",), "interlagoswec"),
    (("Circuit de Spa-Francorchamps",), "spawec"),
    (("Circuit of the Americas",), "cotawec"),
    (("Michelin Raceway Road Atlanta",), "roadatlanta"),
    (("WeatherTech Raceway Laguna Seca",), "lagunaseca"),
    (("Circuit de Barcelona-Catalunya",), "barcelonaelms"),
    (("Bahrain International Circuit", "Bahrain Outer"), "bahrainwec"),
    (("Nordschleife",), ""),
    (("",), ""),
])
def test_track_key_from_any_circuit_name(names, key):
    assert gi.track_key(*names) == key


def test_image_paths_follow_game_ui():
    assert gi.image_path(gi.BRAND, "Ferrari") == "/start/images/manufacturer/Brand=Ferrari.svg"
    assert gi.image_path(gi.BRAND, "Porsche").endswith("Brand=Porsche.png")
    assert gi.image_path(gi.BRAND_DARK, "BMW").endswith("Brand=BMW Dark.svg")
    assert gi.image_path(gi.BRAND_DARK, "Ferrari").endswith("Brand=Ferrari.svg")  # no dark variant
    assert gi.image_path(gi.TRACK_LOGO, "spawec") == "/start/images/tracks/logos/spawec.svg"
    assert gi.image_path(gi.TRACK_CARD, "spawec") == "/start/images/tracks/cards/spawec.webp"
    assert gi.image_path(gi.CAR_THUMBNAIL, "720SGT3EVO_59").endswith("FrontThumbnail/720SGT3EVO_59_frontAngle.webp")
    assert gi.image_extension(gi.TRACK_BACKGROUND, "monzawec") == ".webp"
    with pytest.raises(ValueError):
        gi.image_path("nope", "x")


def test_parse_game_lists():
    vehicles = gi.parse_vehicles([
        {"name": "United Autosports #59:LM", "manufacturer": "McLaren",
         "vehFile": "C:\\Game\\Installed\\Vehicles\\McLaren_720sGT3Evo_2023\\1.4\\720S_59.VEH",
         "fullPathTree": "LMU, GT3, McLaren 720S GT3 Evo"},
        {"name": "", "manufacturer": "Ferrari"},  # skipped
        "garbage",
    ])
    assert vehicles == [gi.VehicleInfo("United Autosports #59:LM", "McLaren", "720S_59", "GT3")]
    assert gi.parse_vehicles(None) == []
    race_cars = gi.parse_vehicles([{"desc": "Ferrari AF Corse #50", "manufacturer": "Ferrari"}])
    assert race_cars == [gi.VehicleInfo("Ferrari AF Corse #50", "Ferrari", "", "")]
    tracks = gi.parse_tracks([
        {"sceneDesc": "SPA_2023", "properTrackName": "Circuit de Spa-Francorchamps", "name": "Spa"},
        {"sceneDesc": "NORDSCHLEIFE", "name": "Nordschleife"},
    ])
    assert tracks["circuit de spa-francorchamps"] == "spawec" and tracks["spa_2023"] == "spawec"
    assert "nordschleife" not in tracks


@pytest.mark.parametrize("text, brand", [
    ("Ferrari 499P", "Ferrari"),
    ("Aston Martin Vantage AMR LMGT3", "Aston Martin"),
    ("aston martin valkyrie", "Aston Martin"),
    ("Mercedes-AMG GT3 Evo", "Mercedes-AMG"),
    ("Oreca 07", "Oreca"),
    ("Unknown car", ""),
    ("", ""),
])
def test_brand_in_car_model(text, brand):
    assert gi.brand_in(text) == brand


def test_dark_and_png_brands_are_known_brands():
    """Brand names spelled as game logo files (was: "Isotto Fraschini" typo, dark logo never used)"""
    assert gi.DARK_BRANDS.issubset(gi.KNOWN_BRANDS)
    assert gi.PNG_BRANDS.issubset(gi.KNOWN_BRANDS)
