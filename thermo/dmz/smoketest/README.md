# DMZ smoketests (black-box HTTP)

Build the image (after **`stage-docker-import.sh`** copies **`../onboard/run-with-stdout-logged.py`** into **`.docker-import/`**), run a container like **`make runlocal`**, then **`pytest test_smoke.py`** from the host venv against the live API.

```bash
cd thermo/dmz
./smoketest/run.sh
./smoketest/run.sh --no-cache   # full docker rebuild
```

Requires Docker, `curl`, and venv (`create_pipenv.sh thermo/dmz`). Set **`DMZ_URL`** if you map a different host/port.

Unit / in-process tests live under **`../test/`** — see **`../test/README.md`**.
