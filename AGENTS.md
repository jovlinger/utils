# Agent Notes

## Clear instructions: do not ask, just do

When the user gives a clear instruction, execute it. Do **not** ask for
permission, confirmation, or acknowledgment first. Do **not** use
multiple-choice prompts to re-confirm an already-stated task. Ask only when a
required decision cannot be resolved from the request, the code, or sensible
defaults.

## Prefer tools over ad-hoc Python

Do not pipe through `python` / `python3 -c` for menial edits or bookkeeping.
When a CLI already exposes the step (e.g. `todo.py work-item-delete`,
`work-item-done`, `set`, `set-json-path`), run that command. Same for shell
builtins and existing scripts: prefer a short sequence of tool invocations over
a one-off Python transformer.

Reserve Python for real logic (tests, nontrivial transforms, project code)—not
for “inspect JSON then reshape it” when the next action is a documented CLI.

## Python virtualenvs

- Use one project-local `.venv/` per touched Python subproject, located at `utils/xxx/.venv/`.
- Create or sync it from the repo root with `./create_pipenv.sh [--sync] <project-path>`.
- Commit only `.venv/README.md` as the marker. Do not commit generated virtualenv contents.
- Prefer tool binaries from the project venv, for example `.venv/bin/pytest`, over global tools.
- For ad-hoc / targeted Python test runs, prefer `detest` (sibling `bin/detest.py`, usually on PATH via `bin/binlinks/detest`) over calling pytest / unittest / doctest directly. It accepts their combined argv and selects the runner.
- Makefile test targets should depend on the needed venv tool and run that binary directly.
- Legacy `env/` directories are local-only; `create_pipenv.sh` migrates them to `.venv/`.

Shared shell helpers live in `lib/` (e.g. `lib/venv-resolve.sh`).

### Venv layout (do not mix these up)

| Tree | Venv path | How to create |
|------|-----------|---------------|
| `utils/<project>/` | nearest `.venv/`, `venv/`, or legacy `env/` marker walking upward | `./create_pipenv.sh <project>` from utils root (e.g. `thermo/dmz`) |
| `bin/` (sibling repo) | `bin/.venv/` (one shared venv for all bin scripts) | `bin/setup-venv.sh` |

Examples:

- `utils/thermo/dmz/manage` -> use `utils/thermo/dmz/.venv`, not `bin/.venv`.
- `utils/shadup/ingest.sh` -> use `utils/shadup/.venv`.
- Python CLIs use `#!/usr/bin/env venv-run` on their `.py` files; put `utils/extdeps` (or sibling `bin/`) on `PATH` so the shebang resolves. `venv-run` walks up for the nearest `.venv/`, `venv/`, or legacy `env/` marker.

If your shell has `bin/.venv` activated while you work under `utils/thermo/`, run `manage` through its launcher or deactivate before using `./manage.py` directly.

Legacy `env/` directories (older thermo layout) are migrated to `.venv/` automatically the next time you run `create_pipenv.sh` on that project.

### Prereq (once)

```bash
python3 -m venv --help
```

If that fails, use Python 3.3+ or install `python3-venv`.

### Create / refresh envs

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

### Use a project launcher

```bash
PATH="$PWD/extdeps:$PWD/thermo/dmz:$PATH"
manage healthz
```

Scripts can source `lib/venv-resolve.sh` to pick the nearest `.venv`, `venv`, or legacy `env` marker and fail with the right setup hint. Empty marker directories keep the intended venv root in git with only `README.md`; generated venv contents stay untracked.

## Test execution

- **`test`** - default, fast: host/unit pytest, `cargo test --lib`, no Docker or e2e.
- **`all-tests`** - full suite: `test` plus Docker builds, compose stacks, integration/e2e where defined.
- Legacy names **`testall`** and **`test_e2e`** alias **`all-tests`** where they still exist.
- **`test-local`** / **`test-docker`** - thermo building blocks; not invoked from the repo root.

- From `utils/`: `make test` runs `make test` in every immediate subdir with a Makefile; `make all-tests` does the same for slow suites.
- For each subdirectory touched, keep pytest and related test tools in `utils/xxx/.venv/`, and run the normal fast suite with `(cd xxx; make test)`.
- The top-level `make test` target inside a subdirectory must invoke fast tests only.
- Subdirectories may also have more targeted internal test commands for debugging, but those do not replace `make test` as the normal verification path.
- Use `make all-tests` when tests need Docker, special hardware, network services, credentials, or other infrastructure intentionally excluded from `make test`.
- Use `detest` (or, if unavailable, the project `.venv` runner) for targeted/debug runs when a Makefile target is missing or too broad.
- Run tests in the foreground with the tool's `block_until_ms` sized for the expected runtime.
- Do not wrap tests in a background `sleep N; kill -0 $PID; wait $PID` timeout. That pattern can miss completed tests because unreaped exited children still answer `kill -0`.
- If a shell timeout is needed and `timeout`/`gtimeout` is unavailable, poll with `kill -0` in short intervals and `wait` as soon as the process exits, preserving the test command's exit code.

## Repo index and AGENTS split

- `make index` rebuilds root `README.md` from `**/.www/blurb.md` (see `lib/build-index.py`).
- Agent operating notes live in `AGENTS.md` files next to the relevant tree
  (this file at the utils root; others under e.g. `thermo/onboard/AGENTS.md`).
  Do not put agent checklists, make conventions, or debug playbooks back into
  human `README.md` files.
