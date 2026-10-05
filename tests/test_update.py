"""Installer update: release asset parsing, download & hash verification"""

import hashlib
import http.server
import io
import json
import threading
import zipfile

import pytest

from tinypedal import update

DIGEST = "ab" * 32


def release_body(assets, body=""):
    """Release response, assets (name, url) or (name, url, digest)"""
    return b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps({
        "tag_name": "v2.60.0", "published_at": "2026-10-01T00:00:00Z", "body": body,
        "assets": [{"name": asset[0], "browser_download_url": asset[1],
                    **({"digest": asset[2]} if len(asset) > 2 else {})} for asset in assets],
    }).encode()


def test_parse_installer():
    base = "https://github.com/Keenny38/ModernTinyPedals/releases/download/v2.60.0/"
    found = update.parse_installer(release_body([
        ("ModernTinyPedals-2.60.0-source.zip", base + "ModernTinyPedals-2.60.0-source.zip", f"sha256:{'cd' * 32}"),
        ("ModernTinyPedals-2.60.0-setup.zip", base + "ModernTinyPedals-2.60.0-setup.zip", f"sha256:{DIGEST.upper()}"),
    ]))
    assert found == update.InstallerAsset(
        "ModernTinyPedals-2.60.0-setup.zip", base + "ModernTinyPedals-2.60.0-setup.zip", DIGEST)


def test_parse_installer_hash_from_release_notes():
    """No asset digest: hash from SHA256 list of release notes"""
    base = "https://github.com/Keenny38/ModernTinyPedals/releases/download/v2.60.0/"
    notes = (f"### SHA256\n\n- `{'cd' * 32}  ModernTinyPedals-2.60.0-source.zip`\n"
             f"- `{DIGEST}  ModernTinyPedals-2.60.0-setup.zip`\n")
    found = update.parse_installer(release_body([
        ("ModernTinyPedals-2.60.0-source.zip", base + "ModernTinyPedals-2.60.0-source.zip"),
        ("ModernTinyPedals-2.60.0-setup.zip", base + "ModernTinyPedals-2.60.0-setup.zip"),
    ], notes))
    assert found is not None and found.sha256 == DIGEST


def test_parse_installer_of_older_release():
    """Releases before setup.zip: installer attached itself"""
    base = "https://github.com/Keenny38/ModernTinyPedals/releases/download/v0.19.3/"
    found = update.parse_installer(release_body([
        ("ModernTinyPedals-0.19.3-windows.zip", base + "ModernTinyPedals-0.19.3-windows.zip", f"sha256:{'cd' * 32}"),
        ("ModernTinyPedals-0.19.3-windows-setup.exe", base + "ModernTinyPedals-0.19.3-windows-setup.exe",
         f"sha256:{DIGEST}"),
    ]))
    assert found is not None and found.name.endswith("-windows-setup.exe") and found.sha256 == DIGEST


def test_parse_installer_requires_hash_and_github_url():
    assert update.parse_installer(release_body([("TinyPedal-1.0.0-setup.zip", "https://github.com/a")])) is None
    assert update.parse_installer(release_body([
        ("TinyPedal-1.0.0-setup.zip", "https://github.com/a", "md5:abc"),  # not a sha256 digest
    ])) is None
    assert update.parse_installer(release_body([
        ("x-setup.zip", "https://evil.example/x.zip", f"sha256:{DIGEST}"),
    ])) is None
    assert update.parse_installer(b"") is None


def test_parse_sha256():
    digest = "a" * 64
    assert update.parse_sha256(f"{digest}  TinyPedal-setup.exe\n") == digest
    with pytest.raises(ValueError):
        update.parse_sha256("not a hash")


@pytest.fixture
def file_server():
    files = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield files, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def setup_zip(files: dict[str, bytes]) -> bytes:
    """Setup ZIP with files (name: content)"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize("valid", [True, False])
def test_download_installer_verifies_hash(file_server, tmp_path, valid):
    files, base = file_server
    content = b"installer" * 1000
    files["/setup.exe"] = content
    digest = hashlib.sha256(content if valid else b"other").hexdigest()
    asset = update.InstallerAsset("setup.exe", f"{base}/setup.exe", digest)
    if valid:
        path = update.download_installer(asset, str(tmp_path))
        with open(path, "rb") as file:
            assert file.read() == content
    else:
        with pytest.raises(ValueError):
            update.download_installer(asset, str(tmp_path))
        assert not (tmp_path / "setup.exe").exists()


@pytest.mark.parametrize("valid", [True, False])
def test_download_setup_zip_extracts_installer(file_server, tmp_path, valid):
    files, base = file_server
    installer = b"MZ installer" * 1000
    archive = setup_zip({"ModernTinyPedals-2.60.0-windows-setup.exe": installer})
    files["/ModernTinyPedals-2.60.0-setup.zip"] = archive
    digest = hashlib.sha256(archive if valid else b"other").hexdigest()
    asset = update.InstallerAsset("ModernTinyPedals-2.60.0-setup.zip", f"{base}/ModernTinyPedals-2.60.0-setup.zip", digest)
    if valid:
        path = update.download_installer(asset, str(tmp_path))
        assert path == str(tmp_path / "ModernTinyPedals-2.60.0-windows-setup.exe")
        with open(path, "rb") as file:
            assert file.read() == installer
        assert [item.name for item in tmp_path.iterdir()] == ["ModernTinyPedals-2.60.0-windows-setup.exe"]  # ZIP removed
    else:
        with pytest.raises(ValueError):
            update.download_installer(asset, str(tmp_path))
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("files", [
    {},  # no installer
    {"readme.txt": b"text"},
    {"a-setup.exe": b"MZ", "b-setup.exe": b"MZ"},  # which one?
])
def test_setup_zip_must_hold_one_installer(tmp_path, files):
    (tmp_path / "setup.zip").write_bytes(setup_zip(files))
    with pytest.raises(ValueError):
        update.extract_installer(str(tmp_path / "setup.zip"), str(tmp_path))
    assert sorted(item.name for item in tmp_path.iterdir()) == ["setup.zip"]


def test_setup_zip_never_extracts_outside_folder(tmp_path):
    folder = tmp_path / "download"
    folder.mkdir()
    (folder / "setup.zip").write_bytes(setup_zip({"../../evil/x-setup.exe": b"MZ"}))
    path = update.extract_installer(str(folder / "setup.zip"), str(folder))
    assert path == str(folder / "x-setup.exe") and not (tmp_path / "evil").exists()


def test_invalid_setup_zip(tmp_path):
    (tmp_path / "setup.zip").write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        update.extract_installer(str(tmp_path / "setup.zip"), str(tmp_path))


def test_parse_release_notes():
    body = release_body([])[:-1] + b', "body": "### Added\\n\\n- Add replay"}'
    assert update.parse_release_notes(body) == "### Added\n\n- Add replay"
    assert update.parse_release_notes(b"") == ""
    with_visuals = release_body([])[:-1] + b', "body": "### Added\\n\\n- Add MAP\\n\\n### Visuals\\n\\n![MAP](https://x/y.png)"}'
    assert update.parse_release_notes(with_visuals) == "### Added\n\n- Add MAP"


def test_release_notes_visuals(tmp_path):
    import sys

    from PySide6.QtGui import QColor, QImage

    sys.path.insert(0, "tools")
    from gen_release_notes import Visual, format_visuals, png_title, unshown_visuals

    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    image.setText("Title", "Black box : cartographie moteur")
    image.save(str(tmp_path / "visual.png"))
    assert png_title((tmp_path / "visual.png").read_bytes()) == "Black box : cartographie moteur"
    assert png_title(b"") == ""
    notes = format_visuals([Visual("abc123", "docs/changes/x.png", "MAP")])
    assert notes.startswith("### Visuals\n")
    assert "![MAP](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/abc123/docs/changes/x.png)" in notes
    assert format_visuals([]) == ""
    shown = Visual("abc123", "docs/changes/shown.png", "SHOWN")
    summary = "![Shown](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changes/shown.png)"
    assert unshown_visuals([shown, Visual("abc123", "docs/changes/x.png", "MAP")], summary)[0].title == "MAP"
    assert unshown_visuals([shown], "") == [shown]  # no changelog section: every visual shown


def test_old_repository_name_is_migrated(ui_env):
    from tinypedal.setting import cfg

    cfg.application["update_repository"] = "Keenny38/overlays"
    assert update.update_repository() == "Keenny38/ModernTinyPedals"


def test_release_notes_start_with_changelog_section(tmp_path):
    import sys

    sys.path.insert(0, "tools")
    from gen_release_notes import changelog_section

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\nIntro.\n\n## 1.2.0 (2026-10-04)\n\n### Pages\n\n- New pages.\n\n"
        "## 1.1.0 (2026-10-01)\n\n- Older.\n", encoding="utf-8")
    assert changelog_section("1.2.0", str(changelog)) == "### Pages\n\n- New pages.\n"
    assert changelog_section("1.1.0", str(changelog)) == "- Older.\n"
    assert changelog_section("1.3.0", str(changelog)) == ""  # not written: commits only
    assert changelog_section("1.2.0", str(tmp_path / "missing.md")) == ""
