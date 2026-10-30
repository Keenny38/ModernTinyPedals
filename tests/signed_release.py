"""Official releases signed with a test release key: manifest & signature assets, served by a fake open_url

The app accepts only manifests signed by release_manifest.RELEASE_PUBLIC_KEYS: tests replace them with the
public key of a key generated here (use_test_key), never with the real release key.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import urllib.error

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from neopedal import release_manifest, update

TEST_KEY = Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY = base64.b64encode(TEST_KEY.public_key().public_bytes_raw()).decode("ascii")
REPO = "Keenny38/NeoPedal"


def use_test_key(monkeypatch) -> None:
    """Manifests signed by TEST_KEY accepted (only them)"""
    monkeypatch.setattr(release_manifest, "RELEASE_PUBLIC_KEYS", (TEST_PUBLIC_KEY,))


def sign(data: bytes, key: Ed25519PrivateKey = TEST_KEY) -> bytes:
    """Signature file of data"""
    return base64.b64encode(key.sign(data)) + b"\n"


def manifest_bytes(version: str, files: dict[str, bytes], tag: str = "", repository: str = REPO) -> bytes:
    """Manifest of release files (name: content)"""
    return release_manifest.build_manifest(
        repository, tag or f"v{version}", version,
        {name: release_manifest.ManifestAsset(hashlib.sha256(content).hexdigest(), len(content))
         for name, content in files.items()})


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def serve(monkeypatch, files: dict[str, bytes], fallback=None) -> dict[str, bytes]:
    """update.open_url answers files (url: content), other urls: fallback(url, timeout) or HTTP 404"""

    def open_url(url, timeout=0):
        if url in files:
            return FakeResponse(files[url])
        if fallback is not None:
            return fallback(url, timeout)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(update, "open_url", open_url)
    return files


def signed_release(version: str, files: dict[str, bytes], body: str = "", published: str = "2099-01-02T00:00:00Z",
                   manifest: bytes | None = None, signature: bytes | None = None,
                   key: Ed25519PrivateKey = TEST_KEY) -> tuple[bytes, dict[str, bytes]]:
    """GitHub API response of official release with files, its manifest & signature, and download urls: content

    Args:
        manifest: manifest bytes published (default: manifest of files), b"" for no manifest asset.
        signature: signature file published (default: signature of manifest with key), b"" for none.
    """
    tag = f"v{version}"
    base = f"https://github.com/{REPO}/releases/download/{tag}/"
    if manifest is None:
        manifest = manifest_bytes(version, files)
    if signature is None:
        signature = sign(manifest, key)
    published_files = dict(files)
    name = release_manifest.manifest_name(version)
    if manifest:
        published_files[name] = manifest
    if signature:
        published_files[f"{name}{release_manifest.SIGNATURE_SUFFIX}"] = signature
    response = b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps({
        "tag_name": tag, "published_at": published, "body": body,
        "assets": [{"name": file_name, "browser_download_url": base + file_name,
                    "digest": f"sha256:{hashlib.sha256(content).hexdigest()}"}
                   for file_name, content in published_files.items()],
    }).encode()
    return response, {base + file_name: content for file_name, content in published_files.items()}
