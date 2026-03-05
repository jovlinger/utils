#!/usr/bin/env python3
"""Generate Ed25519 keypair for zone machine auth. Writes to keys/priv.pem and keys/pub.pem."""

import os
import sys

# Add dmz to path for zone_auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dmz"))
from zone_auth import generate_keypair

KEYS_DIR = os.path.join(os.path.dirname(__file__), "keys")


def main() -> None:
    os.makedirs(KEYS_DIR, exist_ok=True)
    priv_pem, pub_pem = generate_keypair()
    priv_path = os.path.join(KEYS_DIR, "priv.pem")
    pub_path = os.path.join(KEYS_DIR, "pub.pem")
    with open(priv_path, "wb") as f:
        f.write(priv_pem)
    with open(pub_path, "wb") as f:
        f.write(pub_pem)
    print(f"Wrote {priv_path} {pub_path}")


if __name__ == "__main__":
    main()
