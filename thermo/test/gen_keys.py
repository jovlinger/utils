#!/usr/bin/env python3
"""Generate Ed25519 keypair for zone machine auth."""

import os
import sys
from pathlib import Path

# Add dmz to path for zone_auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dmz"))
from zone_auth import generate_keypair

DEFAULT_KEYS_DIR = Path(os.path.dirname(__file__)) / "keys"
PRIVATE_KEYS_DIR = Path(
    os.environ.get(
        "THERMO_ZONE_PRIVATE_KEYS_DIR",
        os.environ.get("THERMO_ZONE_KEYS_DIR", str(DEFAULT_KEYS_DIR)),
    )
)
PUBLIC_KEYS_DIR = Path(
    os.environ.get(
        "THERMO_ZONE_PUBLIC_KEYS_DIR",
        os.environ.get("THERMO_ZONE_KEYS_DIR", str(DEFAULT_KEYS_DIR)),
    )
)


def main() -> None:
    PRIVATE_KEYS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv_pem, pub_pem = generate_keypair()
    priv_path = PRIVATE_KEYS_DIR / "priv.pem"
    pub_path = PUBLIC_KEYS_DIR / "pub.pem"
    with priv_path.open("wb") as f:
        f.write(priv_pem)
    with pub_path.open("wb") as f:
        f.write(pub_pem)
    print(f"Wrote {priv_path} {pub_path}")


if __name__ == "__main__":
    main()
