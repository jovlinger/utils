# utils

Sub-projects each have their own **`requirements.txt`** and a **project-local venv**.

Shared shell helpers live in **`lib/`** (e.g. **`lib/venv-resolve.sh`**).

## Venv layout (do not mix these up)

| Tree | Venv path | How to create |
|------|-----------|---------------|
| **`utils/<project>/`** | nearest **`.venv/`**, **`venv/`**, or legacy **`env/`** marker walking upward | `./create_pipenv.sh <project>` from utils root (e.g. `thermo/dmz`) |
| **`bin/`** (sibling repo) | **`bin/.venv/`** (one shared venv for all bin scripts) | `bin/setup-venv.sh` |

Examples:

- `utils/thermo/dmz/manage` -> use **`utils/thermo/dmz/.venv`**, not `bin/.venv`.
- `utils/shadup/ingest.sh` → use **`utils/shadup/.venv`**.
- Python CLIs use `#!/usr/bin/env venv-run` on their `.py` files; put `utils/extdeps` (or sibling `bin/`) on `PATH` so the shebang resolves. `venv-run` walks up for the nearest `.venv/`, `venv/`, or legacy `env/` marker.

If your shell has **`bin/.venv` activated** while you work under **`utils/thermo/`**, run `manage` through its launcher or deactivate before using `./manage.py` directly.

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

## Use a project launcher

```bash
PATH="$PWD/extdeps:$PWD/thermo/dmz:$PATH"
manage healthz
```

Scripts can source **`lib/venv-resolve.sh`** to pick the nearest `.venv`, `venv`, or legacy `env` marker and fail with the right setup hint. Empty marker directories keep the intended venv root in git with only `README.md`; generated venv contents stay untracked.
