#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Signed release manifest

Every official release has "NeoPedal-<version>-manifest.json" (sha256 & size of each release file, repository,
tag & version) and "NeoPedal-<version>-manifest.json.sig" (base64 Ed25519 signature of the exact manifest bytes),
written by tools/sign_release.py in the release workflow with the private key of the "release" environment
(secret RELEASE_SIGNING_KEY). The app updater installs an official release only if its manifest is signed by
one of RELEASE_PUBLIC_KEYS: a stolen GitHub token or a tampered release file is not enough to publish an update.

Standalone module (standard library, cryptography imported when verifying): also loaded by file path by
tools/sign_release.py, on a runner without the app dependencies. Never import the app package here.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import NamedTuple

# Ed25519 public keys of release signing (raw 32 bytes, base64). A manifest signed by any of them is accepted:
# key rotation adds the new key here, releases are signed with it, the old key is removed a few releases later.
RELEASE_PUBLIC_KEYS: tuple[str, ...] = (
    "IXQf44dlh0E9y51KulqUIhaLV93FqR3KzQc2gQNNSR8=",
)

MANIFEST_FORMAT = 1
MANIFEST_KIND = "NeoPedal release manifest"  # signed data is never mistaken for another signed document
RELEASE_FILE_PREFIX = "NeoPedal"  # release file names: "NeoPedal-<version><suffix>"
MANIFEST_SUFFIX = "-manifest.json"
SIGNATURE_SUFFIX = ".sig"
MAX_MANIFEST_SIZE = 64 * 1024
MAX_SIGNATURE_SIZE = 1024
SIGNATURE_LENGTH = 64  # Ed25519
VERSION_PATTERN = re.compile(r"\d{1,6}\.\d{1,6}\.\d{1,6}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ASSET_NAME_PATTERN = re.compile(r"[\w.+-]{1,200}")
REPOSITORY_PATTERN = re.compile(r"[\w.-]+/[\w.-]+")
TAG_PATTERN = re.compile(r"[\w.+-]{1,100}")


class ManifestError(ValueError):
    """Release manifest missing, not signed by a release key, or not matching the release"""


class ManifestAsset(NamedTuple):
    """Release file listed in manifest"""

    sha256: str
    size: int


class ReleaseManifest(NamedTuple):
    """Verified release manifest"""

    repository: str
    tag: str
    version: str
    assets: dict[str, ManifestAsset]  # file name: sha256 & size


def manifest_name(version: str) -> str:
    """Manifest file name of release version"""
    return f"{RELEASE_FILE_PREFIX}-{version}{MANIFEST_SUFFIX}"


def canonical_json(value: object) -> bytes:
    """JSON bytes of value, same output for same content (sorted keys, no spaces, ASCII)"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def build_manifest(repository: str, tag: str, version: str, assets: dict[str, ManifestAsset], commit: str = "") -> bytes:
    """Manifest bytes (canonical JSON) of release files, checked as the app reads them (raise ManifestError)"""
    value: dict[str, object] = {
        "format": MANIFEST_FORMAT,
        "kind": MANIFEST_KIND,
        "repository": repository,
        "tag": tag,
        "version": version,
        "assets": {name: {"sha256": asset.sha256, "size": asset.size} for name, asset in assets.items()},
    }
    if commit:
        value["commit"] = commit
    data = canonical_json(value)
    parse_manifest(data)
    return data


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSON object without repeated key"""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"repeated key in release manifest: {key}")
        result[key] = value
    return result


def _reject_constant(name: str) -> object:
    raise ManifestError(f"invalid number in release manifest: {name}")


def parse_manifest(data: bytes) -> ReleaseManifest:
    """Release manifest of JSON bytes (signature not checked here, see verify_manifest), raise ManifestError"""
    if len(data) > MAX_MANIFEST_SIZE:
        raise ManifestError("release manifest is too large")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ManifestError(f"release manifest is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError("release manifest is not an object")
    if value.get("format") != MANIFEST_FORMAT or isinstance(value.get("format"), bool):
        raise ManifestError(f"unsupported release manifest format: {value.get('format')!r}")
    if value.get("kind") != MANIFEST_KIND:
        raise ManifestError("not a release manifest")
    repository, tag, version = value.get("repository"), value.get("tag"), value.get("version")
    if not isinstance(repository, str) or not REPOSITORY_PATTERN.fullmatch(repository):
        raise ManifestError("invalid repository in release manifest")
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        raise ManifestError("invalid tag in release manifest")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ManifestError("invalid version in release manifest")
    files = value.get("assets")
    if not isinstance(files, dict) or not files:
        raise ManifestError("no release file in release manifest")
    assets = {}
    for name, item in files.items():
        if not ASSET_NAME_PATTERN.fullmatch(name) or not isinstance(item, dict):
            raise ManifestError(f"invalid release file in release manifest: {name!r}")
        sha256, size = item.get("sha256"), item.get("size")
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise ManifestError(f"invalid sha256 of {name} in release manifest")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ManifestError(f"invalid size of {name} in release manifest")
        assets[name] = ManifestAsset(sha256, size)
    return ReleaseManifest(repository, tag, version, assets)


def decode_signature(text: bytes) -> bytes:
    """Ed25519 signature of base64 signature file, raise ManifestError"""
    if len(text) > MAX_SIGNATURE_SIZE:
        raise ManifestError("release manifest signature is too large")
    try:
        signature = base64.b64decode(b"".join(text.split()), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ManifestError(f"release manifest signature is not base64: {error}") from error
    if len(signature) != SIGNATURE_LENGTH:
        raise ManifestError("release manifest signature has a wrong length")
    return signature


def verify_signature(data: bytes, signature_file: bytes, keys: tuple[str, ...] | None = None) -> None:
    """Check signature file (base64) of exact manifest bytes against public keys (None: RELEASE_PUBLIC_KEYS),
    raise ManifestError"""
    signature = decode_signature(signature_file)
    if keys is None:
        keys = RELEASE_PUBLIC_KEYS
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as error:  # never accepted unchecked
        raise ManifestError(f"release manifest signature can not be checked: {error}") from error
    for key in keys:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(signature, data)
        except InvalidSignature:
            continue
        except (binascii.Error, ValueError):  # broken key in list: other keys still tried
            continue
        return
    raise ManifestError("release manifest is not signed by a release key")


def verify_manifest(data: bytes, signature_file: bytes, keys: tuple[str, ...] | None = None) -> ReleaseManifest:
    """Release manifest of signed bytes (keys None: RELEASE_PUBLIC_KEYS), raise ManifestError if signature
    or content is not valid"""
    if len(data) > MAX_MANIFEST_SIZE:
        raise ManifestError("release manifest is too large")
    verify_signature(data, signature_file, keys)
    return parse_manifest(data)
