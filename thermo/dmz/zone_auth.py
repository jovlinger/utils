"""
Ed25519 machine auth for zone → DMZ requests.

Twoway signs each request with its private key. DMZ verifies with the public key.
Payload: method + path + timestamp + body_hash (SHA256 of raw body).
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from typing import Optional

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError:
    Ed25519PrivateKey = None  # type: ignore
    Ed25519PublicKey = None  # type: ignore
    InvalidSignature = Exception  # type: ignore

REPLAY_WINDOW_SEC = 300  # 5 minutes
HEADER_SIGNATURE = "X-Zone-Signature"
HEADER_TIMESTAMP = "X-Zone-Timestamp"
HEADER_ZONE = "X-Zone-Name"

_ZONE_KEY_HINT = (
    "Zone machine auth uses thermo/dmz/.secrets/zone/priv.pem "
    "(PKCS8 PEM from `make -C thermo/dmz zone-keys`), matching pub.pem on the DMZ. "
    "See thermo/KEYS-AND-CERTS.md."
)


def _read_key_bytes(path_or_pem: str) -> bytes:
    if path_or_pem.strip().startswith("-----"):
        return (
            path_or_pem.encode()
            if isinstance(path_or_pem, str)
            else path_or_pem
        )
    with open(path_or_pem, "rb") as f:
        return f.read()


def _looks_like_ssh_login_key(path_or_pem: str) -> bool:
    """True for ~/.ssh/id_ed25519-style paths (SSH login keys, not zone keys)."""
    if path_or_pem.strip().startswith("-----"):
        return False
    norm = os.path.expanduser(path_or_pem).replace("\\", "/").lower()
    base = os.path.basename(norm)
    return "/.ssh/" in norm or base in (
        "id_ed25519",
        "id_rsa",
        "id_ecdsa",
        "id_dsa",
        "id_ed25519_sk",
        "id_rsa_sk",
    )


def _load_private_key(path_or_pem: str) -> "Ed25519PrivateKey":
    """Load private key from file path or PEM string."""
    if Ed25519PrivateKey is None:
        raise RuntimeError(
            "cryptography not installed; install with: python -m pip install cryptography "
            "(use the same python that runs manage.py — see manage.py signing error for details)"
        )
    if _looks_like_ssh_login_key(path_or_pem):
        raise ValueError(
            f"ZONE_PRIVATE_KEY_PATH looks like an SSH login key "
            f"({os.path.expanduser(path_or_pem)}), not the thermo zone key. "
            + _ZONE_KEY_HINT
        )
    from cryptography.hazmat.primitives import serialization

    data = _read_key_bytes(path_or_pem)
    if b"BEGIN OPENSSH PRIVATE KEY" in data:
        try:
            key = serialization.load_ssh_private_key(data, password=None)
        except Exception as exc:
            raise ValueError(
                "could not load OpenSSH-format private key "
                "(passphrase-protected keys are not supported). "
                + _ZONE_KEY_HINT
            ) from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(
                "zone machine auth requires an Ed25519 private key. " + _ZONE_KEY_HINT
            )
        return key
    if data.startswith(b"-----"):
        try:
            key = serialization.load_pem_private_key(data, password=None)
        except Exception as exc:
            raise ValueError(
                "could not load PEM private key (expected PKCS8 from `make zone-keys`). "
                + _ZONE_KEY_HINT
            ) from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(
                "zone machine auth requires an Ed25519 private key. " + _ZONE_KEY_HINT
            )
        return key
    return Ed25519PrivateKey.from_private_bytes(data)


def _load_public_key(path_or_pem: str) -> "Ed25519PublicKey":
    """Load public key from file path or PEM string."""
    if Ed25519PublicKey is None:
        raise RuntimeError(
            "cryptography not installed; install with: python -m pip install cryptography "
            "(use the same python that runs manage.py — see manage.py signing error for details)"
        )
    if path_or_pem.strip().startswith("-----"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_public_key(
            path_or_pem.encode() if isinstance(path_or_pem, str) else path_or_pem
        )
    with open(path_or_pem, "rb") as f:
        data = f.read()
    if data.startswith(b"-----"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_public_key(data)
    return Ed25519PublicKey.from_public_bytes(data)


def sign_request(
    method: str,
    path: str,
    body: bytes,
    zonename: str,
    private_key_path: str,
) -> tuple[str, str, str]:
    """Sign a request. Returns (signature_b64, timestamp, zonename) for headers."""
    ts = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = f"{method}\n{path}\n{ts}\n{body_hash}"
    key = _load_private_key(private_key_path)
    sig = key.sign(payload.encode())
    return base64.b64encode(sig).decode(), ts, zonename


def verify_request(
    method: str,
    path: str,
    body: bytes,
    zonename: str,
    signature_b64: str,
    timestamp: str,
    public_key_path: str,
) -> bool:
    """Verify a signed request. Returns True if valid."""
    if Ed25519PublicKey is None:
        return False
    try:
        ts = int(timestamp)
        now = int(time.time())
        if abs(now - ts) > REPLAY_WINDOW_SEC:
            return False
    except (ValueError, TypeError):
        return False
    body_hash = hashlib.sha256(body).hexdigest()
    payload = f"{method}\n{path}\n{timestamp}\n{body_hash}"
    try:
        sig = base64.b64decode(signature_b64)
    except Exception:
        return False
    try:
        key = _load_public_key(public_key_path)
        key.verify(sig, payload.encode())
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate Ed25519 keypair. Returns (private_pem, public_pem)."""
    if Ed25519PrivateKey is None:
        raise RuntimeError(
            "cryptography not installed; install with: python -m pip install cryptography "
            "(use the same python that runs manage.py — see manage.py signing error for details)"
        )
    from cryptography.hazmat.primitives import serialization

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem
