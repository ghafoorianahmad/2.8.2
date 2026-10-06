"""The shop server's own TLS certificate (self-signed, pinned by every client).

There is no public certificate authority on a shop LAN, so the server makes its
own certificate on first start. Clients do not trust it because of who signed
it but because it is *exactly this certificate*: ShopAdmin stores it during
setup after the owner compares the fingerprint shown on both screens, and from
then on refuses any other certificate (a machine in the middle cannot present
it without the private key, which never leaves the server's data folder).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import socket
from pathlib import Path

CERT_NAME = "server.crt"
KEY_NAME = "server.key"
VALID_DAYS = 3650
RENEW_BEFORE_DAYS = 30


def fingerprint_of_pem(pem: bytes) -> str:
    """SHA-256 of the DER certificate as 'AB:CD:…' (what both sides display)."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    der = x509.load_pem_x509_certificate(pem).public_bytes(Encoding.DER)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def _local_names() -> tuple[list[str], list[str]]:
    names = {"localhost"}
    addresses = {"127.0.0.1", "::1"}
    try:
        host = socket.gethostname()
        names.add(host)
        fqdn = socket.getfqdn()
        if fqdn:
            names.add(fqdn)
        for info in socket.getaddrinfo(host, None):
            addresses.add(info[4][0].split("%")[0])
    except OSError:
        pass
    return sorted(names), sorted(addresses)


def _needs_new(cert_path: Path, key_path: Path) -> bool:
    if not cert_path.exists() or not key_path.exists():
        return True
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        remaining = cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)
        return remaining < dt.timedelta(days=RENEW_BEFORE_DAYS)
    except Exception:  # noqa: BLE001 - unreadable = make a new one
        return True


def ensure_certificate(folder: Path) -> tuple[Path, Path, str]:
    """Return (cert, key, fingerprint), creating the pair when needed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / CERT_NAME, folder / KEY_NAME
    if not _needs_new(cert_path, key_path):
        return cert_path, key_path, fingerprint_of_pem(cert_path.read_bytes())

    key = ec.generate_private_key(ec.SECP256R1())
    names, addresses = _local_names()
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"ShopServer {names[-1]}"[:64]),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Shop server (self-signed)"),
    ])
    alt_names: list[x509.GeneralName] = [x509.DNSName(n) for n in names]
    for address in addresses:
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            continue
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=False,
                          content_commitment=False, key_encipherment=False,
                          data_encipherment=False, key_agreement=False,
                          encipher_only=False, decipher_only=False),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                       critical=False)
        .sign(key, hashes.SHA256())
    )
    key_tmp = key_path.with_suffix(".tmp")
    key_tmp.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    key_tmp.replace(key_path)
    pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(pem)
    (folder / "fingerprint.txt").write_text(fingerprint_of_pem(pem) + "\n", encoding="ascii")
    return cert_path, key_path, fingerprint_of_pem(pem)
