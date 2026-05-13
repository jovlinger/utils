# DMZ smoketests (black-box HTTP)

Build the image (after **`stage-docker-import.sh`** copies **`../../../bin/run-with-stdout-logged.py`** into **`.docker-import/`**), run a container like **`make runlocal`**, then **`pytest test_smoke.py`** from the host venv against the live API.

```bash
cd thermo/dmz
./smoketest/run.sh
./smoketest/run.sh --no-cache              # full docker rebuild
./smoketest/run.sh --leave-container     # keep container after tests (no --rm)
```

Requires Docker, `curl`, and venv with **`requirements.txt`** + **`requirements-dev.txt`** (`create_pipenv.sh thermo/dmz` installs both). Set **`DMZ_URL`** if you map a different host/port.

**Output:** Pytest uses **`-v -s`** and **`pytest.ini`** (**`log_cli`**) so **`logging`** from **`test_smoke.py`** shows on the console.

**Makefile:** from **`thermo/dmz/smoketest`**, **`make test-docker`** or **`make test`** runs **`./run.sh`**. **`make test-local`** is a no-op (there is no host-only suite here).

**Container logs:** The DMZ process is wrapped so its stdout/stderr is written to **`/var/log/dmz.log`** inside the container ([`run-with-stdout-logged.py`](../../../bin/run-with-stdout-logged.py)), not to Docker’s log stream — so **`docker logs`** is usually thin. In-container **`pytest`** on **`test/`** is redirected to **`/var/log/startup_tests.log`** when **`DMZ_RUN_STARTUP_PYTEST=1`** enables the pre-probe run in **`run.sh`** (default is skipped) so it does not flood **`dmz.log`**. After the host smoketest, **`run.sh`** prints a **tail of `/var/log/dmz.log`**. Use **`--leave-container`** to inspect with **`docker exec`** (e.g. **`cat /var/log/startup_tests.log`**, **`tail -f /var/log/dmz.log`**).

Unit / in-process tests live under **`../test/`** — see **`../test/README.md`**.
