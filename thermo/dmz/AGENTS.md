# Agent Notes -- thermo/dmz

Human overview (behaviour, Docker runtime, SD image): [`README.md`](README.md).
Install / FAT layout: [`install/README.md`](install/README.md). Install agent
notes: [`install/AGENTS.md`](install/AGENTS.md).

## Tests

- **Unit / integration (in-process):** `./test/run.sh` or `make test-local` --
  see [`test/AGENTS.md`](test/AGENTS.md).
- **`make test-docker`:** pytest inside the built image.
- **`make test`:** both local and docker where defined.
- **Smoketests (Docker + live HTTP):** `./smoketest/run.sh` -- see
  [`smoketest/AGENTS.md`](smoketest/AGENTS.md).
- Do not invent a host-only suite under `smoketest/`; `make -C smoketest test-local`
  is intentionally a no-op.

Zone keys: `make -C thermo/dmz zone-keys` (private under `thermo/priv/zone/`,
public under `thermo/config/zone/`). Never commit `thermo/priv/`.
