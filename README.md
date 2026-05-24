# utils

Sub-projects each have their own **`requirements.txt`** and a **project-local venv**.

Shared shell helpers live in **`lib/`** (e.g. **`lib/venv-resolve.sh`**).

## Venv layout (do not mix these up)

| Tree | Venv path | How to create |
|------|-----------|---------------|
| **`utils/<project>/`** | **`utils/<project>/.venv/`** | `./create_pipenv.sh <project>` from utils root (e.g. `thermo/dmz`) |
| **`bin/`** (sibling repo) | **`bin/.venv/`** (one shared venv for all bin scripts) | `bin/setup-venv.sh` |

Examples:

- `utils/thermo/dmz/manage.py` → use **`utils/thermo/dmz/.venv`**, not `bin/.venv`.
- `utils/shadup/ingest.sh` → use **`utils/shadup/.venv`**.
- `bin/pylauncher.sh` → use **`bin/.venv`**.

If your shell has **`bin/.venv` activated** while you work under **`utils/thermo/`**, `./manage.py` will run with the **wrong** Python and miss project deps (e.g. `cryptography`). **`deactivate`**, then **`source thermo/dmz/.venv/bin/activate`**.

Legacy **`env/`** directories (older thermo layout) are migrated to **`.venv/`** automatically the next time you run **`create_pipenv.sh`** on that project.

## Prereq (once)

```bash
python3 -m venv --help
```

If that fails, use Python 3.3+ or install `python3-venv`.

## Create / refresh envs

From the utils root:

```bash
./create_pipenv.sh thermo/dmz thermo/onboard thermo/test dedup shadup
./create_pipenv.sh --sync thermo/dmz   # re-pip-install after requirements change
```

Or all top-level projects with `requirements.txt`:

```bash
for d in */; do
  [ -f "$d/requirements.txt" ] && ./create_pipenv.sh "$d"
done
```

Nested deps (e.g. `esp32/volctrl/requirements.txt`): create `.venv` in that subpath manually.

## Use a project venv

```bash
cd thermo/dmz
source .venv/bin/activate
./manage.py healthz
deactivate
```

Scripts can source **`lib/venv-resolve.sh`** to pick `.venv` (or legacy `env/`) and fail with the right **`create_pipenv.sh`** hint.
