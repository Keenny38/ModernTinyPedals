"""Security audit 2026-10-29 (lot E): signed release manifest, Authenticode revocation & signer, installer held
open from its last checks until it runs, update redirects limited to GitHub, release notes hashes, release build
supply chain (hash-pinned locks, pinned Inno Setup, frozen pre-commit hooks)"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import subprocess
import sys
import urllib.request
import zipfile

import pytest

from neopedal import release_manifest, update, version
from tests import signed_release
from tests.signed_release import TEST_KEY, serve, sign, use_test_key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import sign_release
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SETUP = b"PK setup zip"
INSTALLER = b"MZ installer"
VERSION = "99.0.0"


def read(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as file:
        return file.read()


def release_files(version: str = VERSION) -> dict[str, bytes]:
    return {
        f"NeoPedal-{version}-windows-setup.exe": INSTALLER,
        f"NeoPedal-{version}-windows-setup.exe.sha256": b"hash",
        f"NeoPedal-{version}-setup.zip": SETUP,
        f"NeoPedal-{version}-source.zip": b"source",
    }


# --- Finding 1: manifest format & signature
def test_embedded_release_key():
    assert release_manifest.RELEASE_PUBLIC_KEYS[0] == "IXQf44dlh0E9y51KulqUIhaLV93FqR3KzQc2gQNNSR8="
    for key in release_manifest.RELEASE_PUBLIC_KEYS:
        assert len(base64.b64decode(key, validate=True)) == 32


def test_manifest_round_trip(monkeypatch):
    use_test_key(monkeypatch)
    data = signed_release.manifest_bytes(VERSION, release_files())
    assert data == release_manifest.canonical_json(__import__("json").loads(data))  # canonical bytes
    manifest = release_manifest.verify_manifest(data, sign(data))
    assert manifest.repository == "Keenny38/ModernTinyPedals" and manifest.tag == "v99.0.0"
    assert manifest.assets[f"NeoPedal-{VERSION}-setup.zip"] == (hashlib.sha256(SETUP).hexdigest(), len(SETUP))


def test_manifest_signature_refused(monkeypatch):
    use_test_key(monkeypatch)
    data = signed_release.manifest_bytes(VERSION, release_files())
    with pytest.raises(release_manifest.ManifestError):  # real release key only (not the test key)
        release_manifest.verify_manifest(data, sign(data), keys=("IXQf44dlh0E9y51KulqUIhaLV93FqR3KzQc2gQNNSR8=",))
    with pytest.raises(release_manifest.ManifestError):  # one byte changed
        release_manifest.verify_manifest(data.replace(b"99.0.0", b"99.0.1"), sign(data))
    with pytest.raises(release_manifest.ManifestError):  # another key
        release_manifest.verify_manifest(data, sign(data, Ed25519PrivateKey.generate()))
    for bad in (b"", b"not base64!", base64.b64encode(b"short"), b"A" * 2000):
        with pytest.raises(release_manifest.ManifestError):
            release_manifest.verify_manifest(data, bad)


def test_key_rotation_accepts_any_listed_key(monkeypatch):
    new_key = Ed25519PrivateKey.generate()
    new_public = base64.b64encode(new_key.public_key().public_bytes_raw()).decode("ascii")
    monkeypatch.setattr(release_manifest, "RELEASE_PUBLIC_KEYS", ("broken key", signed_release.TEST_PUBLIC_KEY, new_public))
    data = signed_release.manifest_bytes(VERSION, release_files())
    release_manifest.verify_manifest(data, sign(data))
    release_manifest.verify_manifest(data, sign(data, new_key))


@pytest.mark.parametrize("content", [
    b'{"format": 1, "format": 1}',  # repeated key
    b'[]',
    b'{"format": true, "kind": "NeoPedal release manifest"}',
    b'{"format": 2, "kind": "NeoPedal release manifest"}',
    b'{"format": 1, "kind": "other", "repository": "a/b", "tag": "v1.0.0", "version": "1.0.0", "assets": {}}',
    b'{"format": 1, "kind": "NeoPedal release manifest", "repository": "a/b", "tag": "v1.0.0", "version": "1.0", '
    b'"assets": {"x": {"sha256": "' + b"0" * 64 + b'", "size": 1}}}',
    b'{"format": 1, "kind": "NeoPedal release manifest", "repository": "a/b", "tag": "v1.0.0", "version": "1.0.0", '
    b'"assets": {"x": {"sha256": "' + b"0" * 64 + b'", "size": NaN}}}',
    b'{"format": 1, "kind": "NeoPedal release manifest", "repository": "a/b", "tag": "v1.0.0", "version": "1.0.0", '
    b'"assets": {"../x": {"sha256": "' + b"0" * 64 + b'", "size": 1}}}',
    b'{"format": 1, "kind": "NeoPedal release manifest", "repository": "a/b", "tag": "v1.0.0", "version": "1.0.0", '
    b'"assets": {"x": {"sha256": "' + b"A" * 64 + b'", "size": 1}}}',
    b"[" * 100000,
    b" " * (release_manifest.MAX_MANIFEST_SIZE + 1),
], ids=lambda content: str(len(content)) if len(content) > 300 else None)
def test_invalid_manifest_refused(content):
    with pytest.raises(release_manifest.ManifestError):
        release_manifest.parse_manifest(content)


# --- Finding 1: release tool
def pem_key(key: Ed25519PrivateKey = TEST_KEY) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode("ascii")


@pytest.fixture
def tool_test_key(monkeypatch):
    """Release tool & app accept the test key"""
    monkeypatch.setattr(sign_release.manifest, "RELEASE_PUBLIC_KEYS", (signed_release.TEST_PUBLIC_KEY,))
    use_test_key(monkeypatch)


def write_build(folder, version: str = VERSION):
    for name, content in release_files(version).items():
        (folder / name).write_bytes(content)


def test_sign_release_writes_verifiable_manifest(tmp_path, tool_test_key, monkeypatch):
    write_build(tmp_path)
    manifest_path, signature_path = sign_release.write_manifest(
        VERSION, str(tmp_path), f"v{VERSION}", "Keenny38/ModernTinyPedals", "a" * 40, pem_key())
    assert os.path.basename(manifest_path) == f"NeoPedal-{VERSION}-manifest.json"
    with open(manifest_path, "rb") as file:
        data = file.read()
    with open(signature_path, "rb") as file:
        signature = file.read()
    manifest = release_manifest.verify_manifest(data, signature)
    assert set(manifest.assets) == set(release_files())
    assert sign_release.verify_release(VERSION, str(tmp_path), f"v{VERSION}", "Keenny38/ModernTinyPedals") == []
    (tmp_path / f"NeoPedal-{VERSION}-setup.zip").write_bytes(b"tampered")
    problems = sign_release.verify_release(VERSION, str(tmp_path), f"v{VERSION}", "Keenny38/ModernTinyPedals")
    assert problems == [f"NeoPedal-{VERSION}-setup.zip does not match the signed manifest"]
    # Files published by the workflow: what the app updater reads (signature, hashes & sizes)
    files = {name: (tmp_path / name).read_bytes() for name in os.listdir(tmp_path)}
    files[f"NeoPedal-{VERSION}-setup.zip"] = SETUP
    response, urls = signed_release.signed_release(VERSION, files, manifest=data, signature=signature)
    serve(monkeypatch, urls)
    asset = update.verified_release(response, update.FORK_REPO_NAME, (99, 0, 0), (0, 1, 0))
    assert asset is not None and asset.sha256 == hashlib.sha256(SETUP).hexdigest() and asset.size == len(SETUP)
    assert asset.installer_sha256 == hashlib.sha256(INSTALLER).hexdigest()


def test_sign_release_refuses_without_key_or_with_wrong_key(tmp_path, tool_test_key):
    write_build(tmp_path)
    with pytest.raises(SystemExit, match="RELEASE_SIGNING_KEY is not set"):
        sign_release.write_manifest(VERSION, str(tmp_path), "v99.0.0", "a/b", "", "  ")
    with pytest.raises(SystemExit, match="RELEASE_PUBLIC_KEYS"):  # apps would refuse every update
        sign_release.write_manifest(VERSION, str(tmp_path), "v99.0.0", "a/b", "", pem_key(Ed25519PrivateKey.generate()))
    with pytest.raises(SystemExit, match="not a PEM"):
        sign_release.write_manifest(VERSION, str(tmp_path), "v99.0.0", "a/b", "", "garbage")
    assert not [name for name in os.listdir(tmp_path) if "manifest" in name]  # nothing written
    os.remove(tmp_path / f"NeoPedal-{VERSION}-source.zip")
    with pytest.raises(SystemExit, match="Release file missing"):
        sign_release.write_manifest(VERSION, str(tmp_path), "v99.0.0", "a/b", "", pem_key())


def test_sign_release_never_prints_key(tmp_path, tool_test_key, capsys, monkeypatch):
    write_build(tmp_path)
    monkeypatch.setenv("RELEASE_SIGNING_KEY", pem_key())
    monkeypatch.setattr(sys, "argv", ["sign_release.py", VERSION, "--dist", str(tmp_path)])
    assert sign_release.main() == 0
    monkeypatch.setattr(sys, "argv", ["sign_release.py", VERSION, "--dist", str(tmp_path), "--verify"])
    assert sign_release.main() == 0
    output = capsys.readouterr()
    assert "PRIVATE KEY" not in output.out + output.err and "OK:" in output.out


# --- Finding 1: update check of official releases
def check(monkeypatch, response, repo=update.FORK_REPO_NAME, current="0.27.0"):
    async def latest(repo):
        return response

    monkeypatch.setattr(update, "request_latest_release", latest)
    monkeypatch.setattr(update, "fetch_changelog", lambda *args, **kwargs: "")
    monkeypatch.setattr(version, "__version__", current)
    monkeypatch.setattr(version, "DEVELOPMENT", "")
    checker = update.UpdateChecker()
    checker._UpdateChecker__checking(repo)
    return checker


def test_official_update_uses_signed_manifest_hash(monkeypatch):
    use_test_key(monkeypatch)
    response, urls = signed_release.signed_release(VERSION, release_files(), body="### Added")
    response = response.replace(hashlib.sha256(SETUP).hexdigest().encode(), b"0" * 64)  # GitHub digest ignored
    serve(monkeypatch, urls)
    checker = check(monkeypatch, response)
    assert checker.is_updates() and not checker.is_refused() and checker.release_notes == "### Added"
    assert checker.installer is not None and checker.installer.name == f"NeoPedal-{VERSION}-setup.zip"
    assert checker.installer.sha256 == hashlib.sha256(SETUP).hexdigest() and checker.installer.size == len(SETUP)
    assert checker.message().startswith("New Updates: v99.0.0")


@pytest.mark.parametrize("case", ["no manifest", "no signature", "bad signature", "other key", "other tag",
                                  "other repository", "manifest not downloaded"])
def test_official_update_refused_without_valid_manifest(monkeypatch, caplog, case):
    use_test_key(monkeypatch)
    files = release_files()
    manifest = signed_release.manifest_bytes(VERSION, files)
    options = {
        "no manifest": {"manifest": b"", "signature": b""},
        "no signature": {"signature": b""},
        "bad signature": {"signature": sign(manifest + b" ")},
        "other key": {"key": Ed25519PrivateKey.generate()},
        "other tag": {"manifest": signed_release.manifest_bytes("98.0.0", files, tag="v98.0.0")},
        "other repository": {"manifest": signed_release.manifest_bytes(VERSION, files, repository="someone/fork")},
        "manifest not downloaded": {},
    }[case]
    response, urls = signed_release.signed_release(VERSION, files, body="### Added", **options)
    serve(monkeypatch, {} if case == "manifest not downloaded" else urls)
    checker = check(monkeypatch, response)
    assert not checker.is_updates() and checker.is_refused() and checker.installer is None
    assert checker.release_notes == ""  # unverified notes never shown
    assert checker.message() == "Update Refused: v99.0.0 Has No Valid Signature"
    assert "signed manifest not verified" in caplog.text


def test_manifest_must_be_newer_than_running_app():
    manifest = release_manifest.ReleaseManifest("Keenny38/ModernTinyPedals", "v1.2.0", "1.2.0", {})
    update.check_manifest(manifest, "v1.2.0", (1, 2, 0), (1, 1, 9))
    with pytest.raises(release_manifest.ManifestError, match="not newer"):
        update.check_manifest(manifest, "v1.2.0", (1, 2, 0), (1, 2, 0))
    update.check_manifest(manifest, "v1.2.0", (1, 2, 0), (1, 2, 0), "rc1")  # pre-release: final is newer
    with pytest.raises(release_manifest.ManifestError, match="differs"):
        update.check_manifest(manifest, "v1.2.0", (1, 3, 0), (1, 1, 0))


def test_installer_not_listed_in_manifest_not_offered(monkeypatch):
    use_test_key(monkeypatch)
    files = release_files()
    listed = {name: content for name, content in files.items() if "setup" not in name}
    response, urls = signed_release.signed_release(VERSION, files, manifest=signed_release.manifest_bytes(VERSION, listed))
    serve(monkeypatch, urls)
    checker = check(monkeypatch, response)
    assert checker.is_updates() and checker.installer is None  # verified release, nothing to install


def test_custom_repository_needs_no_manifest(monkeypatch):
    response, _ = signed_release.signed_release(VERSION, release_files(), manifest=b"", signature=b"")
    serve(monkeypatch, {})
    checker = check(monkeypatch, response, repo="someone/fork")
    assert checker.is_updates() and checker.installer is not None  # GitHub digest, Authenticode at install
    assert checker.installer.sha256 == hashlib.sha256(SETUP).hexdigest() and checker.installer.size == 0


def test_no_update_downloads_no_manifest(monkeypatch):
    response, _ = signed_release.signed_release("0.27.0", release_files("0.27.0"), manifest=b"", signature=b"")
    fetched = []
    serve(monkeypatch, {}, fallback=lambda url, timeout: fetched.append(url))
    checker = check(monkeypatch, response, current="0.27.0")
    assert not checker.is_updates() and not checker.is_refused() and not fetched
    assert checker.message() == "No Updates Available"


def test_refused_release_notice_shown_without_install(ui_env, monkeypatch):
    from neopedal.ui import notification

    checker = update.update_checker
    monkeypatch.setattr(checker, "_update_available", False)
    monkeypatch.setattr(checker, "_refused", "release has no signed manifest")
    monkeypatch.setattr(checker, "_disabled", False)
    monkeypatch.setattr(checker, "_manual_checking", False)
    monkeypatch.setattr(checker, "_last_checked_version", (99, 0, 0))
    monkeypatch.setattr(checker, "installer", None)
    monkeypatch.setattr(notification.UpdatesNotifyButton, "dismissed_message", "")
    button = notification.UpdatesNotifyButton("")
    button.checking(False)
    assert not button.isHidden() and button.text() == "Update Refused: v99.0.0 Has No Valid Signature"
    assert not button.install_update.isVisible() and not button.skip_update.isVisible()
    button.dismiss()
    button.checking(False)
    assert button.isHidden()
    button.deleteLater()


def test_refused_message_translated():
    from neopedal.i18n import fr_messages

    for pattern, replacement in fr_messages.MESSAGE_RULES:
        text = "Update Refused: v99.0.0 Has No Valid Signature"
        if re.search(pattern, text):
            assert re.sub(pattern, replacement, text) == "Mise à jour refusée : la v99.0.0 n'a pas de signature valide"
            break
    else:
        raise AssertionError("no French rule")


# --- Finding 22: redirects limited to GitHub hosts over https
@pytest.mark.parametrize("url, allowed", [
    ("https://github.com/Keenny38/ModernTinyPedals/releases/download/v1/x.zip", True),
    ("https://release-assets.githubusercontent.com/x", True),
    ("https://objects.githubusercontent.com/x", True),
    ("https://raw.githubusercontent.com/a/b/v1/CHANGELOG.md", True),
    ("https://api.github.com/repos/a/b", True),
    ("http://github.com/x", False),
    ("https://evil.example/x", False),
    ("https://github.com.evil.example/x", False),
    ("https://github.com:8443/x", False),
    ("https://user@github.com/x", False),
    ("file:///C:/Windows/win.ini", False),
    ("https://github.com:bad/x", False),
])
def test_allowed_update_urls(url, allowed):
    assert update.is_allowed_url(url) is allowed


def test_redirect_handler_refuses_other_hosts_and_http():
    handler = update.GitHubDownloadRedirect()
    request = urllib.request.Request("https://github.com/a/b/releases/download/v1/x.zip")
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/x")
    assert handler.redirect_request(request, None, 302, "Found", {}, "http://release-assets.githubusercontent.com/x") is None
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/x") is None


def test_open_url_refuses_other_hosts():
    with pytest.raises(ValueError):
        update.open_url("http://127.0.0.1:1/x", 1)
    with pytest.raises(ValueError):
        update.fetch_release_file("https://evil.example/x", 10)


def test_redirect_to_other_host_refused_by_real_opener(monkeypatch):
    """Local server allowed as first address only: its redirect to another address is refused"""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ok":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"data")
                return
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/ok")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        monkeypatch.setattr(update, "is_allowed_url", lambda url: url.startswith(f"{base}/"))
        with update.open_url(f"{base}/ok", 5) as response:
            assert response.read() == b"data"
        with pytest.raises(OSError):  # HTTPError 302: redirect to localhost refused
            update.open_url(f"{base}/redirect", 5)
    finally:
        server.shutdown()
        server.server_close()


# --- Finding 24: release notes hashes from SHA256 section only
def test_release_notes_hashes_from_sha256_section_only():
    digest = "ab" * 32
    trap = "cd" * 32
    body = (f"### Fixed\n\n- Fix `{trap}  NeoPedal-1.0.0-setup.zip` (abc)\n\n"
            f"### SHA256\n\n- `{digest}  NeoPedal-1.0.0-setup.zip`\n- `{'ef' * 32}  NeoPedal-1.0.0-source.zip`\n")
    assert update.release_notes_hashes(body) == {
        "NeoPedal-1.0.0-setup.zip": digest, "NeoPedal-1.0.0-source.zip": "ef" * 32}
    assert update.release_notes_hashes(f"- `{trap}  NeoPedal-1.0.0-setup.zip`") == {}  # no section
    # Changelog with its own SHA256 heading first: the last one (appended by the workflow) counts
    assert update.release_notes_hashes(f"### SHA256\n\n- `{trap}  x.zip`\n\n## Commits\n\n{body}") == {
        "NeoPedal-1.0.0-setup.zip": digest, "NeoPedal-1.0.0-source.zip": "ef" * 32}
    release = {"body": body, "assets": [{"name": "NeoPedal-1.0.0-setup.zip"}]}
    assert update.release_hash(release, "NeoPedal-1.0.0-setup.zip") == digest


def test_release_workflow_writes_sha256_heading():
    assert f'echo "{update.RELEASE_SHA256_HEADING}"' in read(".github/workflows/build-release.yml")


# --- Finding 16: installer held unchanged from its last checks until it runs
def downloaded(tmp_path, content: bytes = INSTALLER, name: str = "Setup.exe") -> str:
    path = tmp_path / name
    path.write_bytes(content)
    update.remember_installer(str(path), hashlib.sha256(content).hexdigest())
    return str(path)


def test_installer_changed_after_download_refused(tmp_path, monkeypatch):
    runs = []
    path = downloaded(tmp_path)
    monkeypatch.setattr(update, "check_signature", lambda path, **kwargs: update.Signature(update.SIGNATURE_UNSIGNED))
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    with open(path, "ab") as file:
        file.write(b"payload")
    with pytest.raises(update.InstallerChangedError):
        update.run_installer(path, "", update.FORK_REPO_NAME)
    other = tmp_path / "other.exe"
    other.write_bytes(INSTALLER)
    with pytest.raises(update.InstallerChangedError, match="not downloaded"):  # hash never known
        update.run_installer(str(other), "", update.FORK_REPO_NAME)
    assert not runs


def test_discard_forgets_installer_hash(tmp_path):
    path = downloaded(tmp_path)
    assert update.downloaded_installer_hash(path) == hashlib.sha256(INSTALLER).hexdigest()
    update.discard_installer(path)
    assert update.downloaded_installer_hash(path) == "" and not os.path.exists(path)


def test_signature_checked_through_held_handle(tmp_path, monkeypatch):
    seen = []

    def check(path, revocation=False, handle=None):
        seen.append((revocation, handle))
        return update.Signature(update.SIGNATURE_UNSIGNED)

    monkeypatch.setattr(update, "check_signature", check)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: None)
    update.run_installer(downloaded(tmp_path), "", update.FORK_REPO_NAME)
    assert seen[0][0] is False  # official release: nothing downloaded while checking
    assert (seen[0][1] is not None) is (sys.platform == "win32")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
def test_held_installer_can_run_but_not_change(tmp_path, monkeypatch):
    """Real file & process: while held, CreateProcess works, writing, renaming & removing fail"""
    source = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "hostname.exe")
    with open(source, "rb") as file:
        content = file.read()
    path = downloaded(tmp_path, content, "hostname.exe")
    blocked = []
    processes = []
    real_popen = subprocess.Popen

    def popen(args, **kwargs):
        try:
            with open(path, "r+b") as file:
                file.write(b"x")
        except OSError:
            blocked.append("write")
        for change in (os.remove, lambda name: os.replace(name, f"{name}.moved")):
            try:
                change(path)
            except OSError:
                blocked.append("move")
        processes.append(real_popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        return processes[-1]

    monkeypatch.setattr(update, "check_signature", lambda path, **kwargs: update.Signature(update.SIGNATURE_VALID, "Microsoft Windows"))
    monkeypatch.setattr(update.subprocess, "Popen", popen)
    update.run_installer(path, "", update.FORK_REPO_NAME)
    assert blocked == ["write", "move", "move"]  # never changed while held
    assert processes and processes[0].wait(10) == 0  # started from the held file
    with open(path, "r+b"):  # released once started
        pass
    with update.open_installer(path) as (file, handle):
        assert handle is not None
        update.verify_file_sha256(file, hashlib.sha256(content).hexdigest())
        assert subprocess.run([path], capture_output=True, timeout=10).returncode == 0


def test_custom_repository_signer_shown_then_required(tmp_path, monkeypatch):
    path = downloaded(tmp_path)
    calls = []

    def check(path, revocation=False, handle=None):
        calls.append(revocation)
        return update.Signature(update.SIGNATURE_VALID, signer[0])

    signer = ["Fork Publisher"]
    monkeypatch.setattr(update, "check_signature", check)
    runs = []
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kwargs: runs.append(args))
    assert update.installer_signer(path, "someone/fork") == "Fork Publisher"
    assert calls == [True]  # revocation checked online (download thread)
    assert update.installer_signer(path, update.FORK_REPO_NAME) == ""  # official: signed manifest
    update.run_installer(path, "", "someone/fork", signer="Fork Publisher")
    assert calls == [True, False] and runs  # same content (hash): cached revocation data only
    signer[0] = "Someone Else"
    with pytest.raises(update.InstallerChangedError, match="signer changed"):
        update.run_installer(path, "", "someone/fork", signer="Fork Publisher")
    assert len(runs) == 1


@pytest.mark.parametrize("repo, refused", [("someone/fork", True), (update.FORK_REPO_NAME, False)])
def test_revocation_unknown_refused_for_custom_repository(monkeypatch, repo, refused):
    monkeypatch.setattr(update, "check_signature",
                        lambda path, **kwargs: update.Signature(update.SIGNATURE_REVOCATION_UNKNOWN))
    if refused:
        with pytest.raises(update.RevocationUnknownError):
            update.verify_installer("Setup.exe", repo)
    else:
        update.verify_installer("Setup.exe", repo)


def test_custom_repository_revocation_checked_online(monkeypatch):
    seen = []
    monkeypatch.setattr(update, "check_signature",
                        lambda path, revocation=False, handle=None: seen.append(revocation) or update.Signature(update.SIGNATURE_VALID))
    update.verify_installer("Setup.exe", "someone/fork")
    update.verify_installer("Setup.exe", update.FORK_REPO_NAME)
    assert seen == [True, False]


@pytest.mark.skipif(sys.platform != "win32", reason="WinVerifyTrust is Windows only")
def test_real_signer_name_and_revocation():
    signature = update.check_signature(sys.executable)
    if signature.state != update.SIGNATURE_VALID:
        pytest.skip("interpreter not signed")
    assert "Python" in signature.signer  # Python Software Foundation
    online = update.check_signature(sys.executable, revocation=True)  # needs network (CRL / OCSP)
    assert online.state in (update.SIGNATURE_VALID, update.SIGNATURE_REVOCATION_UNKNOWN)
    with update.open_installer(sys.executable) as (_, handle):
        assert update.check_signature(sys.executable, handle=handle) == signature


def test_install_errors_translated_messages(ui_env):
    from neopedal.i18n import fr
    from neopedal.ui import notification

    for error in (update.RevocationUnknownError("x"), update.InstallerChangedError("x")):
        assert notification.install_error_text(error) in fr.TRANSLATION
    assert notification.display_signer("<img src=x>Pub\x00lisher") == "img src=xPublisher"


def test_custom_repository_confirmation_translated():
    from neopedal.i18n import fr_messages

    text = ("Update downloaded from someone/fork, installer signed by Fork Publisher. "
            "Install it only if you trust this publisher. Close NeoPedal and install it now?")
    assert any(re.search(pattern, text) for pattern, _ in fr_messages.MESSAGE_RULES)


# --- Finding 1 & 16: download bounded by manifest size, installer in ZIP checked against manifest
def test_download_bounded_by_manifest_size(tmp_path, monkeypatch):
    content = b"x" * 1000
    serve(monkeypatch, {"https://github.com/x/Setup.exe": content})
    asset = update.InstallerAsset("Setup.exe", "https://github.com/x/Setup.exe", hashlib.sha256(content).hexdigest(),
                                  size=999)
    with pytest.raises(ValueError, match="larger"):
        update.download_installer(asset, str(tmp_path))
    assert not os.listdir(tmp_path)


def setup_zip(content: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("NeoPedal-99.0.0-windows-setup.exe", content)
    return buffer.getvalue()


@pytest.mark.parametrize("valid", [True, False])
def test_installer_in_zip_checked_against_manifest(tmp_path, monkeypatch, valid):
    archive = setup_zip(INSTALLER)
    serve(monkeypatch, {"https://github.com/x/setup.zip": archive})
    asset = update.InstallerAsset("NeoPedal-99.0.0-setup.zip", "https://github.com/x/setup.zip",
                                  hashlib.sha256(archive).hexdigest(), update.FORK_REPO_NAME, len(archive),
                                  hashlib.sha256(INSTALLER if valid else b"other").hexdigest())
    if valid:
        path = update.download_installer(asset, str(tmp_path))
        assert update.downloaded_installer_hash(path) == hashlib.sha256(INSTALLER).hexdigest()
    else:
        with pytest.raises(ValueError, match="signed release manifest"):
            update.download_installer(asset, str(tmp_path))
        assert not os.listdir(tmp_path)


# --- Finding 5 & 25: release build supply chain
def requirement_pins(text: str) -> dict[str, str]:
    pins = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


@pytest.mark.parametrize("lock, sources", [
    ("requirements-build-lock.txt", ("requirements-lock.txt", "requirements-build.txt")),
    ("requirements-sign-lock.txt", ("requirements-lock.txt",)),
])
def test_locks_hash_pinned_and_in_sync(lock, sources):
    text = read(lock)
    entries = re.findall(r"^[A-Za-z0-9_.-]+==\S+ \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", text, re.M)
    pins = requirement_pins(text)
    assert pins and len(entries) == len(pins)  # every package with its hashes
    for source in sources:
        for name, pinned in requirement_pins(read(source)).items():
            if name in pins or source == "requirements-build.txt":
                assert pins.get(name) == pinned, f"{lock}: {name} not {pinned}, regenerate it"
    if lock == "requirements-sign-lock.txt":
        assert "cryptography" in pins


def test_release_workflow_installs_hash_pinned_packages():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(read(".github/workflows/build-release.yml"))
    runs = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
    installs = [run for run in runs if "pip install" in run or "choco install" in run]
    assert installs and all("--require-hashes --no-deps --only-binary :all:" in run or "choco" in run
                            for run in installs)
    assert not any("--upgrade pip" in run for run in runs)
    assert any("choco install innosetup --version=6." in run for run in runs)
    assert any("requirements-build-lock.txt" in run for run in runs)
    assert any("requirements-sign-lock.txt" in run for run in runs)


def test_release_job_signs_manifest_with_environment_secret():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(read(".github/workflows/build-release.yml"))
    job = workflow["jobs"]["release"]
    assert job["environment"] == "release"
    names = [step.get("name") for step in job["steps"]]
    sign = job["steps"][names.index("Sign release manifest")]
    assert sign["env"]["RELEASE_SIGNING_KEY"] == "${{ secrets.RELEASE_SIGNING_KEY }}"
    assert 'if [ -z "$RELEASE_SIGNING_KEY" ]' in sign["run"] and "exit 1" in sign["run"]
    assert "--verify" in sign["run"]
    assert names.index("Sign release manifest") < names.index("Publish release")  # published with the files
    publish = job["steps"][names.index("Publish release")]["run"]
    assert "builds/*" in publish
    for other in job["steps"]:  # secret given to the signing step only
        if other is not sign:
            assert "RELEASE_SIGNING_KEY" not in str(other)
    for step in (step for job in workflow["jobs"].values() for step in job["steps"]):
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"])  # actions pinned to commits


def test_pre_commit_hooks_frozen():
    revs = re.findall(r"^\s+rev:\s*(\S+)", read(".pre-commit-config.yaml"), re.M)
    assert revs and all(re.fullmatch(r"[0-9a-f]{40}", rev) for rev in revs)


def test_build_lock_regeneration_documented():
    assert "uv pip compile --generate-hashes" in read("requirements-build.txt")
    assert "uv pip compile --generate-hashes" in read("requirements-sign.txt")


def test_signing_tool_runs_without_app_dependencies(tmp_path):
    """Release job installs cryptography only: tool & manifest module import no PySide6"""
    script = (
        "import sys, builtins\n"
        "real = builtins.__import__\n"
        "def guard(name, *args, **kwargs):\n"
        "    if name.split('.')[0] in ('PySide6', 'shiboken6', 'neopedal'):\n"
        "        raise ImportError(name)\n"
        "    return real(name, *args, **kwargs)\n"
        "builtins.__import__ = guard\n"
        f"sys.path.insert(0, {os.path.join(ROOT, 'tools')!r})\n"
        "import sign_release\n"
        "print(sign_release.manifest.MANIFEST_KIND)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "NeoPedal release manifest" in result.stdout
