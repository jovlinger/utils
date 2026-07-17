# Agent Notes -- Thermo Onboard

Layout and human pointers: [`README.md`](README.md).

## Standard targets (onboard root)

```bash
make -C thermo/onboard build    # all hardware backends
make -C thermo/onboard ONBOARD_BUILD_BACKEND=pico2w build   # one backend
make -C thermo/onboard test     # host pytest (test/run.sh)
make -C thermo/onboard clean
```

## Per-zone deploy

Each zone directory has `build`, `clean`, `test`, and `deploy`. Chain is
**deploy -> test -> build**. Zone `build` builds only that zone's
`ONBOARD_DEPLOY_BACKEND` (via `ONBOARD_BUILD_BACKEND`); `deploy` uses
`zone.env` in that directory (backend, IR protocol, DMZ, etc.).

```bash
# Kitchen (Pi Zero 2 W)
make -C thermo/onboard/zones/kitchen deploy

# Office (Pico2W, AHT20 + IR TX, Midea)
make -C thermo/onboard/zones/office deploy

# Bedroom (Pico2W, Haier)
make -C thermo/onboard/zones/bedroom deploy
```

From onboard root:

```bash
make -C thermo/onboard deploy ZONE=office
```

Pico2W flash needs `thermo/priv/pico2w/<zone>.env` (WiFi password) and the board
in BOOTSEL. See [`hardware/pico2w/AGENTS.md`](hardware/pico2w/AGENTS.md).

Legacy wrapper (still works): `./deploy-room.sh pico2w office-pico2w.env`

Canonical deploy envs live in `zones/<zone>/zone.env`. Committed templates also
remain under [`../config/`](../config/README.md); agent env-selection rules:
[`../config/AGENTS.md`](../config/AGENTS.md).
