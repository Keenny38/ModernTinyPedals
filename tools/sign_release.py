"""
Write & sign the release manifest, or verify a downloaded release

Release workflow (release job, "release" environment): lists the sha256 & size of every build file of the
version (tools/release.py BUILD_ASSETS) in "NeoPedal-<version>-manifest.json" (canonical JSON), signs its exact
bytes with the Ed25519 private key of the RELEASE_SIGNING_KEY environment variable (PEM PKCS8) and writes the
base64 signature to "NeoPedal-<version>-manifest.json.sig". Refused (exit code 1) without the key, with a key
whose public key is not in neopedal/release_manifest.py RELEASE_PUBLIC_KEYS (apps would refuse the update),
or with a missing build file. The app updater installs an official release only with a valid manifest.

Usage (from project root):
    python tools/sign_release.py 0.28.0 --dist builds            write manifest & signature (key in environment)
    python tools/sign_release.py 0.28.0 --dist builds --verify   check downloaded release files (no key needed)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from release import BUILD_ASSETS, REPO

KEY_VARIABLE = "RELEASE_SIGNING_KEY"


def load_manifest_module():
    """neopedal/release_manifest.py loaded by file path: app package (PySide6) not needed"""
    path = os.path.join(ROOT, "neopedal", "release_manifest.py")
    spec = importlib.util.spec_from_file_location("neopedal_release_manifest", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


manifest = load_manifest_module()


def file_asset(path: str):
    """sha256 & size of file"""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return manifest.ManifestAsset(digest.hexdigest(), size)


def build_files(version: str, folder: str) -> dict:
    """Build files of version in folder: name: sha256 & size (raise SystemExit if one is missing)"""
    assets = {}
    for suffix in BUILD_ASSETS:
        name = f"{manifest.RELEASE_FILE_PREFIX}-{version}{suffix}"
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            raise SystemExit(f"Release file missing: {path}")
        assets[name] = file_asset(path)
    return assets


def load_private_key(pem: str):
    """Ed25519 private key of PEM text (raise SystemExit, key never printed)"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        key = serialization.load_pem_private_key(pem.strip().encode("ascii") + b"\n", password=None)
    except (TypeError, ValueError, UnicodeEncodeError):
        raise SystemExit(f"{KEY_VARIABLE} is not a PEM PKCS8 private key without password") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit(f"{KEY_VARIABLE} is not an Ed25519 key")
    return key


def sign(data: bytes, pem: str) -> bytes:
    """Base64 signature file of data, checked against the app public keys"""
    import base64

    key = load_private_key(pem)
    signature = base64.b64encode(key.sign(data)) + b"\n"
    try:
        manifest.verify_manifest(data, signature)
    except manifest.ManifestError as error:
        raise SystemExit(f"Signature refused by the app public keys ({error}): add the public key of "
                         f"{KEY_VARIABLE} to RELEASE_PUBLIC_KEYS of neopedal/release_manifest.py") from None
    return signature


def write_manifest(version: str, folder: str, tag: str, repository: str, commit: str, pem: str) -> tuple[str, str]:
    """Write manifest & signature files into folder, their paths"""
    if not pem.strip():
        raise SystemExit(f"{KEY_VARIABLE} is not set: create the secret {KEY_VARIABLE} in the \"release\" "
                         "environment (releases without signed manifest are refused by the app updater)")
    data = manifest.build_manifest(repository, tag, version, build_files(version, folder), commit)
    signature = sign(data, pem)
    path = os.path.join(folder, manifest.manifest_name(version))
    with open(path, "wb") as file:
        file.write(data)
    with open(path + manifest.SIGNATURE_SUFFIX, "wb") as file:
        file.write(signature)
    return path, path + manifest.SIGNATURE_SUFFIX


def verify_release(version: str, folder: str, tag: str, repository: str) -> list[str]:
    """Problems of downloaded release files in folder (manifest, signature, hashes), empty if valid"""
    path = os.path.join(folder, manifest.manifest_name(version))
    try:
        with open(path, "rb") as file:
            data = file.read(manifest.MAX_MANIFEST_SIZE + 1)
        with open(path + manifest.SIGNATURE_SUFFIX, "rb") as file:
            signature = file.read(manifest.MAX_SIGNATURE_SIZE + 1)
        found = manifest.verify_manifest(data, signature)
    except (OSError, manifest.ManifestError) as error:
        return [str(error)]
    problems = []
    if (found.repository.lower(), found.tag, found.version) != (repository.lower(), tag, version):
        problems.append(f"manifest is for {found.repository} {found.tag} ({found.version})")
    for name, expected in found.assets.items():
        file_path = os.path.join(folder, name)
        if not os.path.isfile(file_path):
            continue  # not downloaded: only the files present are checked
        if file_asset(file_path) != expected:
            problems.append(f"{name} does not match the signed manifest")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("version", help="release version (0.28.0)")
    parser.add_argument("--dist", default="builds", help="folder of release files")
    parser.add_argument("--tag", default="", help="release tag (default: v<version>)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or REPO, help="owner/name")
    parser.add_argument("--commit", default=os.environ.get("RELEASE_COMMIT", ""), help="released commit")
    parser.add_argument("--verify", action="store_true", help="check downloaded release files instead")
    options = parser.parse_args()
    tag = options.tag or f"v{options.version}"
    if options.verify:
        problems = verify_release(options.version, options.dist, tag, options.repo)
        for problem in problems:
            print(f"FAIL {problem}")
        if not problems:
            print(f"OK: release files of {options.repo} {tag} match the signed manifest")
        return 1 if problems else 0
    paths = write_manifest(options.version, options.dist, tag, options.repo, options.commit,
                           os.environ.get(KEY_VARIABLE, ""))
    for path in paths:
        print(f"Written {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
