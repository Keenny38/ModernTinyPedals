"""Preset package export & import tests"""

import json
import zipfile

import pytest

from tinypedal.userfile.preset_package import (
    PACKAGE_FORMAT,
    export_preset_package,
    import_preset_package,
)


@pytest.fixture
def source(tmp_path):
    settings = tmp_path / "src"
    notes = tmp_path / "src_notes"
    settings.mkdir()
    notes.mkdir()
    (settings / "race.json").write_text(json.dumps({"relative": {"enable": True}}), encoding="utf-8")
    (settings / "classes.json").write_text(json.dumps({"Hypercar": {}}), encoding="utf-8")
    (notes / "Le Mans.tptn").write_text("notes", encoding="utf-8")
    return settings, notes


def test_export_import_roundtrip(tmp_path, source):
    settings, notes = source
    package = tmp_path / "race.zip"
    count = export_preset_package(
        str(package), f"{settings}/", "race.json", notes_paths={"tracknotes": str(notes)}
    )
    assert count == 3

    target = tmp_path / "dst"
    target_notes = tmp_path / "dst_notes"
    target.mkdir()
    target_notes.mkdir()
    (target / "race.json").write_text("{}", encoding="utf-8")  # existing preset is never overwritten
    result = import_preset_package(
        str(package), f"{target}/", overwrite_styles=True, notes_paths={"tracknotes": str(target_notes)}
    )
    assert result.presets == ["race (2).json"]
    assert result.styles == ["classes.json"]
    assert result.notes == 1
    assert json.loads((target / "race (2).json").read_text(encoding="utf-8")) == {"relative": {"enable": True}}
    assert (target / "race.json").read_text(encoding="utf-8") == "{}"


def test_styles_not_overwritten_by_default(tmp_path, source):
    settings, _ = source
    package = tmp_path / "race.zip"
    export_preset_package(str(package), f"{settings}/", "race.json")
    target = tmp_path / "dst"
    target.mkdir()
    result = import_preset_package(str(package), f"{target}/")
    assert result.styles == []
    assert not (target / "classes.json").exists()


def test_malicious_package_cannot_escape(tmp_path):
    package = tmp_path / "evil.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": PACKAGE_FORMAT, "version": 1}))
        zf.writestr("presets/../../evil.json", "{}")
        zf.writestr("../outside.json", "{}")
        zf.writestr("presets/script.py", "print('x')")
        zf.writestr("presets/not_json.json", "not json")
        zf.writestr("presets/brakes.json", "{}")  # reserved style name as preset
    target = tmp_path / "dst"
    target.mkdir()
    result = import_preset_package(str(package), f"{target}/", overwrite_styles=True)
    assert result.presets == []
    assert not (tmp_path / "evil.json").exists()
    assert not (tmp_path / "outside.json").exists()
    assert sorted(p.name for p in target.iterdir()) == []


def test_invalid_package(tmp_path):
    package = tmp_path / "other.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(ValueError):
        import_preset_package(str(package), f"{tmp_path}/")
