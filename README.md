# utils

Sub-projects are each run in their own virtualenv and `requirements.txt`. Create an `env` in each and ignore it in git.

**Convention:** Scripts that need pip assert the env exists; if not, they point to `create_pipenv.sh` to generate it. One env per `utils/<dir>/env`. For `bin/`, use `bin/setup-venv.sh` (single shared `.venv`).

## Prereq (once)

```bash
python3 -m venv --help
```

If that fails, use Python 3.3+ or install `python3-venv`. No need to install `virtualenv`; `venv` is standard.

## Create envs

From the utils root:

```bash
./create_pipenv.sh thermo/dmz thermo/onboard thermo/test dedup shadup
```

Or create envs in all sub-projects that have `requirements.txt`:

```bash
for d in */; do
  [ -f "$d/requirements.txt" ] && ./create_pipenv.sh "$d"
done
```

For subdirs whose deps live in a subpath (e.g. `esp32/volctrl/requirements.txt`), create the venv there manually: `cd esp32 && python3 -m venv env && ... && pip install -r volctrl/requirements.txt`.

## Use a project’s env

```bash
cd esp32
source env/bin/activate
pip install -r volctrl/requirements.txt
# ... run stuff ...
deactivate
```

