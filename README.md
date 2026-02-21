# utils

Sub-projects are each run in their own virtualenv and `requirements.txt`. Create an `env` in each and ignore it in git.

## Prereq (once)

```bash
python3 -m venv --help
```

If that fails, use Python 3.3+ or install `python3-venv`. No need to install `virtualenv`; `venv` is standard.

## Create envs in all sub-projects

From the repo root:

```bash
for d in */; do
  [ -f "$d/requirements.txt" ] && (cd "$d" && python3 -m venv env && (grep -qxF 'env' .gitignore 2>/dev/null || echo env >> .gitignore))
done
```

Runs in every subdirectory that has a top-level `requirements.txt`. For subdirs whose deps live in a subpath (e.g. `esp32/volctrl/requirements.txt`), create the venv there manually: `cd esp32 && python3 -m venv env && ... && pip install -r volctrl/requirements.txt`.

## Use a project’s env

```bash
cd esp32
source env/bin/activate
pip install -r volctrl/requirements.txt
# ... run stuff ...
deactivate
```

