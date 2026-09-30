"""Installer update: release asset parsing, download & hash verification"""

import hashlib
import http.server
import json
import threading

import pytest

from tinypedal import update


def release_body(assets):
    return b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps({
        "tag_name": "v2.60.0", "published_at": "2026-10-01T00:00:00Z",
        "assets": [{"name": name, "browser_download_url": url} for name, url in assets],
    }).encode()


def test_parse_installer():
    base = "https://github.com/Keenny38/overlays/releases/download/v2.60.0/"
    found = update.parse_installer(release_body([
        ("TinyPedal-2.60.0-windows.zip", base + "TinyPedal-2.60.0-windows.zip"),
        ("TinyPedal-2.60.0-windows-setup.exe", base + "TinyPedal-2.60.0-windows-setup.exe"),
        ("TinyPedal-2.60.0-windows-setup.exe.sha256", base + "TinyPedal-2.60.0-windows-setup.exe.sha256"),
    ]))
    assert found == update.InstallerAsset(
        "TinyPedal-2.60.0-windows-setup.exe",
        base + "TinyPedal-2.60.0-windows-setup.exe",
        base + "TinyPedal-2.60.0-windows-setup.exe.sha256",
    )


def test_parse_installer_requires_hash_and_github_url():
    assert update.parse_installer(release_body([("TinyPedal-1.0.0-windows-setup.exe", "https://github.com/a")])) is None
    assert update.parse_installer(release_body([
        ("x-windows-setup.exe", "https://evil.example/x.exe"),
        ("x-windows-setup.exe.sha256", "https://evil.example/x.sha256"),
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


@pytest.mark.parametrize("valid", [True, False])
def test_download_installer_verifies_hash(file_server, tmp_path, valid):
    files, base = file_server
    content = b"installer" * 1000
    files["/setup.exe"] = content
    digest = hashlib.sha256(content if valid else b"other").hexdigest()
    files["/setup.exe.sha256"] = f"{digest}  setup.exe\n".encode()
    asset = update.InstallerAsset("setup.exe", f"{base}/setup.exe", f"{base}/setup.exe.sha256")
    if valid:
        path = update.download_installer(asset, str(tmp_path))
        with open(path, "rb") as file:
            assert file.read() == content
    else:
        with pytest.raises(ValueError):
            update.download_installer(asset, str(tmp_path))
        assert not (tmp_path / "setup.exe").exists()
