# DMZ unit / integration tests (host venv or `make test`)

Pytest against the **source tree** using Flask `test_client()` (no real HTTP server).

```bash
cd thermo/dmz
./test/run.sh
```

Same tests run inside the built image:

```bash
make test
```

**Smoketests** (Docker + live HTTP) live in **`../smoketest/`**.
