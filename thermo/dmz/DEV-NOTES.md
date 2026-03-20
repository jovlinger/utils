# DMZ dev notes (tooling preferences)

- **Tests (DMZ):** Use **`python -m pytest`** (same **`python`** as **`app.py`** in **`thermo/dmz/run.sh`**). **Temporary:** **`run.sh`** runs pytest before **`app.py`**; plan is to remove that for Docker-based fidelity tests. **`install/run_raw.sh`** has no **`--debug`**; only optional **`--no-bwrap`** (chroot). It chains **`run-with-stdout-logged.py` → `sh ./run.sh`**.
- **Repo search in a plain shell:** Prefer portable patterns such as  
  `find . -type f -exec grep -Hn 'pattern' {} +`  
  over assuming **`rg`** (ripgrep) is installed.
