# DMZ unit / integration tests

**`pytest`** against the **source tree** using Flask `test_client()` (no real HTTP server).

```bash
cd thermo/dmz
./test/run.sh
```

Needs venv with **`requirements.txt`** (and **`requirements-dev.txt`** if you also run **`../smoketest/`**). **`create_pipenv.sh`** installs both when **`requirements-dev.txt`** exists. **`pytest`** is listed in **`requirements.txt`** for image and host test parity.

Make target names, docker parity, and collection boundaries: [`AGENTS.md`](AGENTS.md).

**Smoketests** (Docker + live HTTP) live in **`../smoketest/`**.
