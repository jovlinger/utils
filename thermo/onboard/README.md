# Thermo Onboard

Layout:

- `common/` -- shared Python (twoway, deployment metadata, heatpump IR).
- `hardware/pizero2w/` -- Pi Zero 2 W Docker images and compose deploy.
- `hardware/pico2w/` -- Pico2W Rust firmware.
- `zones/<zone>/` -- per-room `zone.env` and Makefile (`kitchen`, `office`, `bedroom`).
- `install/` -- deploy dispatcher used by zone Makefiles.

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
in BOOTSEL. See [`hardware/pico2w/README.md`](hardware/pico2w/README.md).

Legacy wrapper (still works): `./deploy-room.sh pico2w office-pico2w.env`

Pi Zero 2 W: [`hardware/pizero2w/README.md`](hardware/pizero2w/README.md).
Committed room templates also remain under [`../config/`](../config/README.md);
canonical deploy envs live in `zones/<zone>/zone.env`.
