# `thermo/dmz/.secrets/` — local-only material

Everything under `thermo/dmz/.secrets/` is **gitignored** (`.gitignore: .secrets/`) and is **per dev/build host**. Two kinds of files live here:

| Subdir | Purpose | Generator | Consumer |
|--------|---------|-----------|----------|
| `.secrets/zone/` | Ed25519 zone machine-auth keypair (`priv.pem`, `pub.pem`) used by twoway → DMZ signing | `make -C thermo/dmz zone-keys` | DMZ (pub) baked into SD via `build-and-write.sh --include-pub-key=.secrets/zone/pub.pem`; onboard (priv) bind-mounted into the twoway container |
| `.secrets/ssh-host/` | Stable rescue **`sshd`** host keys for the Pi 1B (so `known_hosts` does not churn each flash) | `install/gen-dmz-rescue-host-keys.sh` (auto-invoked by `build-and-write.sh` if missing) | apkovl `/etc/ssh/` (baked into the SD image) |

**Treat `.secrets/` like private material.** Back it up if you care about stable Pi identities; never commit it; copy between dev hosts only over a trusted channel.

## Quick reference

Generate (or regenerate) the zone keypair:

```bash
make -C thermo/dmz zone-keys                  # writes .secrets/zone/{priv,pub}.pem
```

Bake the **public** half into a fresh SD image (see [`build-and-write.sh`](build-and-write.sh) for the full flag list):

```bash
cd thermo/dmz
./build-and-write.sh --include-pub-key=.secrets/zone/pub.pem            # build only
./build-and-write.sh --include-pub-key=.secrets/zone/pub.pem /Volumes/PIBOOT  # + flash
```

Distribute the **private** half to the onboard Pi (mode `0400`, root-owned), then point twoway at it via `ZONE_PRIVATE_KEY_PATH` and bind-mount it into the container — see [`../KEYS-AND-CERTS.md`](../KEYS-AND-CERTS.md) §1 for the full ops procedure.

Without `--include-pub-key`, the SD image boots with **machine auth disabled** and the DMZ accepts unsigned `POST /zone/<z>/sensors` from anywhere on the public internet.
