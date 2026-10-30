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
Self-signed TLS certificate for web dashboard (HTTPS)

Certificate & key are kept in config folder and reused, so a browser that accepted
the certificate once keeps trusting it. A new one is created when missing, expiring,
or when it does not cover a current address of this computer.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import os
import ssl
import threading

from . import replace_retry

logger = logging.getLogger(__name__)

CERT_FILE = "web_dashboard_cert.pem"
KEY_FILE = "web_dashboard_key.pem"
VALID_DAYS = 3650
RENEW_DAYS = 30  # create a new certificate this many days before expiry
_lock = threading.Lock()  # certificate made & loaded by GUI (server start) & background thread (new address)


def cert_paths(folder: str) -> tuple[str, str]:
    """Certificate & key file paths"""
    return os.path.join(folder, CERT_FILE), os.path.join(folder, KEY_FILE)


def covers(cert_file: str, addresses: list[str]) -> bool:
    """Whether existing certificate is valid for a while and covers all addresses"""
    from cryptography import x509

    try:
        with open(cert_file, "rb") as file:
            cert = x509.load_pem_x509_certificate(file.read())
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    expiry = cert.not_valid_after_utc
    if expiry - datetime.timedelta(days=RENEW_DAYS) < datetime.datetime.now(datetime.UTC):
        return False
    known = {str(ip) for ip in names.get_values_for_type(x509.IPAddress)}
    return set(addresses) <= known


def create_certificate(cert_file: str, key_file: str, addresses: list[str]) -> None:
    """Create self-signed certificate for localhost & given IP addresses"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NeoPedal web dashboard")])
    now = datetime.datetime.now(datetime.UTC)
    alt_names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    alt_names.extend(x509.IPAddress(ipaddress.ip_address(address)) for address in addresses)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # Both written in full first, then replaced (never a truncated file); key readable by current user only:
    # mode on POSIX, DACL on Windows (a config folder moved to a shared disk would let other accounts read it,
    # the rename keeps the DACL set on the new file)
    _write_new(key_file, key_bytes, 0o600)
    _restrict_key(f"{key_file}.tmp")
    _write_new(cert_file, cert.public_bytes(serialization.Encoding.PEM), 0o644)
    replace_retry(f"{key_file}.tmp", key_file)
    replace_retry(f"{cert_file}.tmp", cert_file)
    _forget_fingerprint(cert_file)
    logger.info("WEB DASHBOARD: created self-signed certificate for %s", ", ".join(["localhost", *addresses]))


def _write_new(filename: str, data: bytes, mode: int) -> None:
    """Write data to filename.tmp (no disk flush: a pair lost or damaged by a crash is made again, see
    load_certificate, and the flush froze the GUI thread for up to hundreds of ms on a busy disk)"""
    fd = os.open(f"{filename}.tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as file:
        file.write(data)


def _restrict_key(path: str) -> None:
    """Private key file accessible by the user running the app only (Windows DACL, POSIX mode); never fatal"""
    from ..vr_shared import restrict_to_user  # ctypes only (no Qt), same ACL code as the OpenXR layer folder

    try:
        restrict_to_user(path, 0o600)
    except OSError as error:  # access not changed: key kept with the folder's access
        logger.warning("WEB DASHBOARD: private key access not restricted to current user (%s)", error)


def server_context(folder: str, addresses: list[str]) -> ssl.SSLContext:
    """TLS server context, creating certificate if needed (raise OSError, ValueError or ImportError)"""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    load_certificate(context, folder, addresses)
    return context


def load_certificate(context: ssl.SSLContext, folder: str, addresses: list[str]) -> None:
    """Load certificate in context (running server: used by next connections), creating it if it does not
    cover addresses (raise OSError, ValueError or ImportError)"""
    cert_file, key_file = cert_paths(folder)
    addresses = sorted({"127.0.0.1", *addresses})
    with _lock:
        if not (os.path.exists(key_file) and covers(cert_file, addresses)):
            create_certificate(cert_file, key_file, addresses)
        try:
            context.load_cert_chain(cert_file, key_file)
        except ssl.SSLError as error:  # key not matching certificate or damaged (crash while written): made again
            logger.warning("WEB DASHBOARD: certificate not loaded (%s), creating a new one", error)
            create_certificate(cert_file, key_file, addresses)
            context.load_cert_chain(cert_file, key_file)


_fingerprints: dict[str, tuple[tuple[int, int], str]] = {}  # certificate file: ((mtime ns, size), fingerprint)
_fingerprints_lock = threading.Lock()


def _forget_fingerprint(cert_file: str) -> None:
    with _fingerprints_lock:
        _fingerprints.pop(cert_file, None)


def fingerprint(folder: str) -> str:
    """SHA-256 fingerprint of certificate, to check it on the other device

    Kept by certificate file (modified time & size): asked at every refresh of the settings page on the UI
    thread, the certificate is read & parsed (cryptography import) only once per certificate.
    """
    cert_file, _ = cert_paths(folder)
    try:
        stat = os.stat(cert_file)
    except OSError:
        _forget_fingerprint(cert_file)
        return ""
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _fingerprints_lock:
        cached = _fingerprints.get(cert_file)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    try:
        with open(cert_file, "rb") as file:
            cert = x509.load_pem_x509_certificate(file.read())
    except (OSError, ValueError):
        return ""
    text = cert.fingerprint(hashes.SHA256()).hex(":").upper()
    with _fingerprints_lock:
        _fingerprints[cert_file] = (stamp, text)
    return text
