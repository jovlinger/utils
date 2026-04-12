# DMZ unit / integration tests (host venv: `make test-local`; image parity: `make test-docker`; both: `make test`)

**`pytest`** against the **source tree** using Flask `test_client()` (no real HTTP server).

```bash
cd thermo/dmz
./test/run.sh
```

Needs venv with **`requirements.txt`** (and **`requirements-dev.txt`** if you also run **`../smoketest/`**). **`create_pipenv.sh`** installs both when **`requirements-dev.txt`** exists. **`pytest`** is listed in **`requirements.txt`** for image and host test parity.

Same pytest suite inside the built image:

```bash
make test-docker
```

**Smoketests** (Docker + live HTTP, **pytest** on the host) live in **`../smoketest/`**.

Optional: repo **`../pytest.ini`** limits default collection to **`test/`** (so **`pytest`** from **`thermo/dmz`** does not pick up **`smoketest/`**).
