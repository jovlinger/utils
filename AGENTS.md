# Agent Notes

## Python virtualenvs

- Use one project-local `.venv/` per touched Python subproject, located at `utils/xxx/.venv/`.
- Create or sync it from the repo root with `./create_pipenv.sh [--sync] <project-path>`.
- Commit only `.venv/README.md` as the marker. Do not commit generated virtualenv contents.
- Prefer tool binaries from the project venv, for example `.venv/bin/pytest`, over global tools.
- Makefile test targets should depend on the needed venv tool and run that binary directly.
- Legacy `env/` directories are local-only; `create_pipenv.sh` migrates them to `.venv/`.

## Test execution

- For each subdirectory touched, move toward uniform handling: keep pytest and related test tools in `utils/xxx/.venv/`, and run the normal comprehensive suite with `(cd xxx; make test)`.
- The top-level `make test` target inside a subdirectory must invoke all normal tests for that directory.
- Subdirectories may also have more targeted internal test commands for debugging, but those do not replace `make test` as the normal verification path.
- Every subdirectory should have a `make testall` target. In many directories `testall` can simply delegate to `make test`.
- Use `make testall` for truly all tests in a directory when some tests need Docker, special hardware, network services, credentials, or other infrastructure and are intentionally excluded from `make test`.
- Use direct tool binaries such as `.venv/bin/pytest` only for targeted/debug runs when a Makefile target is missing or too broad.
- Run tests in the foreground with the tool's `block_until_ms` sized for the expected runtime.
- Do not wrap tests in a background `sleep N; kill -0 $PID; wait $PID` timeout. That pattern can miss completed tests because unreaped exited children still answer `kill -0`.
- If a shell timeout is needed and `timeout`/`gtimeout` is unavailable, poll with `kill -0` in short intervals and `wait` as soon as the process exits, preserving the test command's exit code.
