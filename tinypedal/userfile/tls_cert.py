#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
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

logger = logging.getLogger(__name__)

CERT_FILE = "web_dashboard_cert.pem"
KEY_FILE = "web_dashboard_key.pem"
VALID_DAYS = 3650
RENEW_DAYS = 30  # create a new certificate this many days before expiry


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
    if expiry - datetime.timedelta(days=RENEW_DAYS) < datetime.datetime.now(datetime.timezone.utc):
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
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TinyPedal web dashboard")])
    now = datetime.datetime.now(datetime.timezone.utc)
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
    # Key readable by current user only (POSIX), written before certificate
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(key_bytes)
    with open(cert_file, "wb") as file:
        file.write(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("WEB DASHBOARD: created self-signed certificate for %s", ", ".join(["localhost", *addresses]))


def server_context(folder: str, addresses: list[str]) -> ssl.SSLContext:
    """TLS server context, creating certificate if needed (raise OSError, ValueError or ImportError)"""
    cert_file, key_file = cert_paths(folder)
    addresses = sorted({"127.0.0.1", *addresses})
    if not (os.path.exists(key_file) and covers(cert_file, addresses)):
        create_certificate(cert_file, key_file, addresses)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    return context


def fingerprint(folder: str) -> str:
    """SHA-256 fingerprint of certificate, to check it on the other device"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    cert_file, _ = cert_paths(folder)
    try:
        with open(cert_file, "rb") as file:
            cert = x509.load_pem_x509_certificate(file.read())
    except (OSError, ValueError):
        return ""
    return cert.fingerprint(hashes.SHA256()).hex(":").upper()
