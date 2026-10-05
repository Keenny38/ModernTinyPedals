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


def test_preset_share_code():
    import pytest

    from tinypedal.userfile.preset_share import decode_preset, encode_preset, summarize_preset

    preset = {"speedometer": {"enable": True, "font_size": 15}, "gear": {"enable": False}, "module_delta": {"enable": True}}
    code = encode_preset(preset)
    assert code.startswith("MTP1:") and "\n" not in code
    # Line breaks added by chat apps are ignored
    assert decode_preset(code[:20] + "\n" + code[20:]) == preset
    summary = summarize_preset(preset, ("speedometer", "gear"), ("module_delta",))
    assert summary.widgets == ("speedometer",) and summary.modules == ("module_delta",)
    for bad in ("hello", "MTP1:!!!", encode_preset({"a": 1})[:-4], "MTP1:" + code[5:15]):
        with pytest.raises(ValueError):
            decode_preset(bad)


def test_share_code_and_package_refuse_nan():
    import base64
    import zlib

    import pytest

    from tinypedal.userfile.preset_package import is_json_dict
    from tinypedal.userfile.preset_share import decode_preset

    raw = b'{"speedometer": {"opacity": NaN, "font_size": 1e999}}'
    for data in (raw, b"[" * 100_000):  # non-finite numbers, too deeply nested
        with pytest.raises(ValueError, match="damaged"):
            decode_preset("MTP1:" + base64.urlsafe_b64encode(zlib.compress(data)).decode("ascii"))
    assert not is_json_dict(raw) and is_json_dict(b'{"speedometer": {"opacity": 0.5}}')


def test_import_share_code_dialog(ui_env, monkeypatch):
    import os

    from PySide6.QtWidgets import QApplication

    from tinypedal.setting import cfg
    from tinypedal.ui._common import TextInputDialog
    from tinypedal.ui.preset_view import PresetList
    from tinypedal.userfile.preset_share import SHARE_PREFIX, encode_preset

    QApplication.clipboard().setText(encode_preset({"speedometer": {"enable": True}}))
    shown = []

    def answer(dialog):  # code input keeps pasted clipboard code, name input gets a name
        shown.append(dialog.text())
        if len(shown) == 2:
            dialog.edit.setText("My: shared")
        dialog.accepting()

    monkeypatch.setattr(TextInputDialog, "open", answer)
    view = PresetList(None)
    view.import_share_code()
    assert os.path.exists(os.path.join(cfg.path.settings, "My shared.json"))
    assert shown[0].startswith(SHARE_PREFIX)  # clipboard code proposed
    assert shown[1] == "Shared preset"
    view.deleteLater()
