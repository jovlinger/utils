# Agent Notes -- DMZ smoketests

Human how-to (`./run.sh`, Docker flags, log paths): [`README.md`](README.md).

## Makefile targets

From `thermo/dmz/smoketest`:

- `make test-docker` or `make test` runs `./run.sh`.
- `make test-local` is a no-op -- there is no host-only suite here. Do not invent
  one.

## Logs

DMZ stdout/stderr goes to `/var/log/dmz.log` via `run-with-stdout-logged.py`, not
Docker's log stream -- `docker logs` is usually thin. Prefer
`--leave-container` and `docker exec` to inspect `/var/log/dmz.log` or
`/var/log/startup_tests.log`.
