# Agent Notes -- thermo/test

Testing thesis and future plan: [`README.md`](README.md). Align names with root
[`AGENTS.md`](../../AGENTS.md) (`test` / `all-tests`; legacy `test_e2e` aliases
`all-tests` where present).

## Canned commands

- Run dockerized thermo stack tests (builds onboard GHCR-tagged images, dmz,
  testdriver; then compose):

```bash
make dockertest
```

- Same stack (`testcases/test_e2e.py` compose mode): `make test-docker` or alias
  `make test_e2e`.

- Copy a file from a container (need not be running):

```bash
docker cp <container_id>:/app/twoway.out -
```

- Interactive shell in a stopped container:

```bash
docker start <container_id>
docker exec -it <container_id> bash
```

Set `THERMO_ENV_FILE` for host pytest (see [`../config/AGENTS.md`](../config/AGENTS.md)).
