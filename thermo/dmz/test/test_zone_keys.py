"""Coverage for `make zone-keys` and the gen_keys.py helper it invokes.

The Makefile target only wraps `THERMO_ZONE_*_KEYS_DIR=... gen_keys.py`, so the
behavioural test runs `gen_keys.py` directly (no venv assumption) and a
separate test enforces the Makefile invariants so the wrapper cannot drift.
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest

DMZ_DIR = Path(__file__).resolve().parent.parent
THERMO_DIR = DMZ_DIR.parent
GEN_KEYS = THERMO_DIR / "test" / "gen_keys.py"
MAKEFILE = DMZ_DIR / "Makefile"

pytestmark = pytest.mark.skipif(
    not GEN_KEYS.is_file() or not MAKEFILE.is_file(),
    reason="Full thermo checkout required (dmz/Makefile + thermo/test/gen_keys.py)",
)


def _load_pem_pub(pem_bytes: bytes):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    return load_pem_public_key(pem_bytes)


def _load_pem_priv(pem_bytes: bytes):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    return load_pem_private_key(pem_bytes, password=None)


def test_gen_keys_writes_loadable_ed25519_pair(tmp_path: Path) -> None:
    """`THERMO_ZONE_KEYS_DIR=tmp gen_keys.py` writes priv.pem + pub.pem; both load as Ed25519."""
    out_dir = tmp_path / "zone"
    res = subprocess.run(
        [sys.executable, str(GEN_KEYS)],
        env={"THERMO_ZONE_KEYS_DIR": str(out_dir), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"gen_keys.py failed: {res.stderr}\n{res.stdout}"

    priv_path = out_dir / "priv.pem"
    pub_path = out_dir / "pub.pem"
    assert priv_path.is_file(), f"missing {priv_path}"
    assert pub_path.is_file(), f"missing {pub_path}"

    priv_pem = priv_path.read_bytes()
    pub_pem = pub_path.read_bytes()
    assert priv_pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert pub_pem.startswith(b"-----BEGIN PUBLIC KEY-----")

    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    priv = _load_pem_priv(priv_pem)
    pub = _load_pem_pub(pub_pem)
    assert isinstance(priv, Ed25519PrivateKey)
    assert isinstance(pub, Ed25519PublicKey)


def test_gen_keys_priv_and_pub_actually_match(tmp_path: Path) -> None:
    """Round-trip: signing with the generated priv must verify under the generated pub."""
    out_dir = tmp_path / "zone"
    subprocess.run(
        [sys.executable, str(GEN_KEYS)],
        env={"THERMO_ZONE_KEYS_DIR": str(out_dir), "PATH": "/usr/bin:/bin"},
        check=True,
    )

    sys.path.insert(0, str(DMZ_DIR))
    try:
        from zone_auth import sign_request, verify_request
    finally:
        sys.path.pop(0)

    body = b'{"temp_centigrade":21.5,"humid_percent":40}'
    sig, ts, zone = sign_request(
        "POST", "/zone/test/sensors", body, "test", str(out_dir / "priv.pem")
    )
    assert verify_request(
        "POST", "/zone/test/sensors", body, "test", sig, ts, str(out_dir / "pub.pem")
    )
    assert not verify_request(
        "POST", "/zone/other/sensors", body, "other", sig, ts, str(out_dir / "pub.pem")
    ), "signature must be bound to method+path+zone"


def test_sign_request_accepts_inline_base64_der_private_key() -> None:
    """ZONE_PRIVATE_KEY may contain one-line base64 DER from a PEM body."""
    sys.path.insert(0, str(DMZ_DIR))
    try:
        from cryptography.hazmat.primitives import serialization
        from zone_auth import generate_keypair, sign_request, verify_request
    finally:
        sys.path.pop(0)

    priv_pem, pub_pem = generate_keypair()
    priv = _load_pem_priv(priv_pem)
    priv_der = priv.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    inline_key = base64.b64encode(priv_der).decode()
    body = b"{}"
    sig, ts, zone = sign_request("GET", "/zones", body, "cli", inline_key)

    assert zone == "cli"
    assert verify_request("GET", "/zones", body, "cli", sig, ts, pub_pem.decode())


def test_makefile_zone_keys_target_invariants() -> None:
    """The Makefile wrapper must keep its contract: target name + script + env var."""
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(
        r"^zone-keys:\s*$", text, flags=re.MULTILINE
    ), "Makefile target `zone-keys:` is missing"

    target_block = re.search(
        r"^zone-keys:\s*\n((?:\t.*\n?)+)", text, flags=re.MULTILINE
    )
    assert target_block, "could not parse zone-keys recipe block"
    recipe = target_block.group(1)

    assert (
        "gen_keys.py" in recipe
    ), "zone-keys recipe must invoke ../test/gen_keys.py (single source of truth)"
    assert (
        "THERMO_ZONE_PRIVATE_KEYS_DIR=" in recipe
    ), "zone-keys recipe must set THERMO_ZONE_PRIVATE_KEYS_DIR"
    assert (
        "THERMO_ZONE_PUBLIC_KEYS_DIR=" in recipe
    ), "zone-keys recipe must set THERMO_ZONE_PUBLIC_KEYS_DIR"
    assert (
        "../priv/zone" in recipe
    ), "zone-keys recipe must write private material into thermo/priv/zone"
    assert (
        "../config/zone" in recipe
    ), "zone-keys recipe must write public material into thermo/config/zone"

    assert "zone-keys" in re.search(
        r"^\.PHONY:\s*(.+)$", text, flags=re.MULTILINE
    ).group(1), "`zone-keys` must be declared .PHONY"


def test_load_private_key_rejects_ssh_login_key_path() -> None:
    sys.path.insert(0, str(DMZ_DIR))
    try:
        from zone_auth import _load_private_key
    finally:
        sys.path.pop(0)

    with pytest.raises(ValueError, match="SSH login key"):
        _load_private_key("~/.ssh/id_ed25519")
