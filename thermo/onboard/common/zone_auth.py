"""
Ed25519 machine auth for zone → DMZ requests.
Copy of thermo/dmz/zone_auth.py for use by twoway.
"""

from __future__ import annotations

import base64
import binascii
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

REPLAY_WINDOW_SEC = 300
HEADER_SIGNATURE = "X-Zone-Signature"
HEADER_TIMESTAMP = "X-Zone-Timestamp"
HEADER_ZONE = "X-Zone-Name"


def _load_private_key(path_or_pem: str) -> "Ed25519PrivateKey":
    if Ed25519PrivateKey is None:
        raise RuntimeError("cryptography not installed; pip install cryptography")
    data = _read_key_bytes(path_or_pem)
    if data.startswith(b"-----"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_private_key(data, password=None)
    if data.startswith(b"0"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_der_private_key(data, password=None)
    return Ed25519PrivateKey.from_private_bytes(data)


def _load_public_key(path_or_pem: str) -> "Ed25519PublicKey":
    if Ed25519PublicKey is None:
        raise RuntimeError("cryptography not installed; pip install cryptography")
    data = _read_key_bytes(path_or_pem)
    if data.startswith(b"-----"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_public_key(data)
    if data.startswith(b"0"):
        from cryptography.hazmat.primitives import serialization

        return serialization.load_der_public_key(data)
    return Ed25519PublicKey.from_public_bytes(data)


def _read_key_bytes(path_or_pem: str) -> bytes:
    key_ref = path_or_pem.strip()
    if key_ref.startswith("-----"):
        return key_ref.encode()
    path = os.path.expanduser(key_ref)
    if not os.path.exists(path):
        decoded = _decode_inline_base64_key(key_ref)
        if decoded is not None:
            return decoded
    with open(path, "rb") as f:
        return f.read()


def _decode_inline_base64_key(key_ref: str) -> Optional[bytes]:
    """Decode one-line base64 key material from env vars, not arbitrary paths."""
    compact = "".join(key_ref.split())
    if not compact:
        return None
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(decoded) == 32 or decoded.startswith(b"0"):
        return decoded
    return None


def sign_request(
    method: str,
    path: str,
    body: bytes,
    zonename: str,
    private_key_path: str,
) -> tuple[str, str, str]:
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


def public_key_fingerprint(key: "Ed25519PrivateKey | Ed25519PublicKey") -> str:
    """Stable short identifier (sha256 of the raw 32-byte public key, first 16 hex chars).

    Same fingerprint whether you pass the private half or the public half. Use to confirm in
    logs that twoway is signing with the key whose pub matches what DMZ has loaded — without
    leaking any private material to the log.
    """
    if Ed25519PrivateKey is None:
        raise RuntimeError("cryptography not installed; pip install cryptography")
    from cryptography.hazmat.primitives import serialization

    if isinstance(key, Ed25519PrivateKey):
        pub = key.public_key()
    else:
        pub = key
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:16]


def generate_keypair() -> tuple[bytes, bytes]:
    if Ed25519PrivateKey is None:
        raise RuntimeError("cryptography not installed; pip install cryptography")
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
