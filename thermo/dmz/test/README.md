# DMZ unit / integration tests (host venv or `make test`)

**Stdlib `unittest`** against the **source tree** using Flask `test_client()` (no real HTTP server).

```bash
cd thermo/dmz
./test/run.sh
```

Needs venv with **`requirements.txt`** (and **`requirements-dev.txt`** if you also run **`../smoketest/`**). **`create_pipenv.sh`** installs both when **`requirements-dev.txt`** exists.

Same tests run inside the built image:

```bash
make test
```

**Smoketests** (Docker + live HTTP, **pytest** on the host) live in **`../smoketest/`**.

Optional: with **`pytest`** installed from **`requirements-dev.txt`**, repo **`../pytest.ini`** limits default collection to **`test/`** (so **`pytest`** from **`thermo/dmz`** does not pick up **`smoketest/`**).
