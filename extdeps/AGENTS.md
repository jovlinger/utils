# Agent Notes -- extdeps

What this tree is (static snapshot of selected `jovlinger/bin` tools):
[`README.md`](README.md). Venv / shebang conventions: root
[`AGENTS.md`](../AGENTS.md).

- Put this directory on `PATH` so `#!/usr/bin/env venv-run` resolves for utils CLIs.
- Refresh copies with `make -C extdeps all`.
- `run-with-stdout-logged.py` supervision: set `RUN_WITH_STDOUT_RUNFILE` to a
  tmpfs path (e.g. `/tmp/dmz.run`). While the file exists, the wrapped command
  restarts after each exit; remove the file to request shutdown.
  `RUN_WITH_STDOUT_RESTART_SECS` defaults to 1.
- These copies are for small binaries without their own `requirements.txt`, or
  callers must satisfy any implied deps manually.
