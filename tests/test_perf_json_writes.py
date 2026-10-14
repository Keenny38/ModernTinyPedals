"""JSON files written in one shot (write_json / json.dumps): bytes identical to json.dump to a text file"""

import json


def dumped(tmp_path, data, **kwargs) -> bytes:
    """Bytes of json.dump to a text file (former writing)"""
    path = tmp_path / "reference.json"
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, **kwargs)
    return path.read_bytes()


def test_viewer_setting_and_history_bytes(tmp_path):
    from neopedal.ui.lap_viewer import VIEWER_SETTING, save_viewer_setting
    from neopedal.ui.quick.stint_analysis import write_history_json

    save_viewer_setting(str(tmp_path), channels=["speed", "brake"], sensitivity=0.5)
    written = (tmp_path / VIEWER_SETTING).read_bytes()
    assert written == dumped(tmp_path, {"channels": ["speed", "brake"], "sensitivity": 0.5})
    document = {"driver": "Zoé", "sessions": [{"track": "Spa\nmulti", "laps": 3}]}
    write_history_json(str(tmp_path / "history.json"), document)
    assert (tmp_path / "history.json").read_bytes() == dumped(tmp_path, document, ensure_ascii=False, indent=1)
    assert not list(tmp_path.glob("*.tmp"))


def test_imported_preset_bytes(tmp_path):
    from neopedal.ui.file_drop import import_preset_file

    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "settings"
    target.mkdir()
    data = {"relative": {"x": 1}, "speedometer": {"enable": True, "font_name": "Barlow"}}
    (source / "race.json").write_text(json.dumps(data), encoding="utf-8")
    name = import_preset_file(str(source / "race.json"), str(target))
    assert (target / name).read_bytes() == dumped(tmp_path, data, indent=4)
