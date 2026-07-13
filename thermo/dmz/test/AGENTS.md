# Agent Notes -- DMZ unit / integration tests

Human how-to: [`README.md`](README.md).

## Targets

- Host venv, source tree + Flask `test_client()`: `./test/run.sh` or
  `make test-local` from `thermo/dmz`.
- Same suite inside the built image: `make test-docker`.
- Both: `make test`.

## Collection boundary

Repo `pytest.ini` under `thermo/dmz` limits default collection to `test/` so a
bare `pytest` from `thermo/dmz` does not pick up `smoketest/`.

Smoketests (Docker + live HTTP) live in `../smoketest/` -- see
[`../smoketest/AGENTS.md`](../smoketest/AGENTS.md).
