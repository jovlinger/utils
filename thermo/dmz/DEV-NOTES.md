# DMZ dev notes

- **Tests:** `make test` / `./test/run.sh` (stdlib unittest; Flask test client). Smoketests: `./smoketest/run.sh` (pytest on host). See `test/README.md` and `smoketest/README.md`.
- **Entry:** `start.sh` runs as **root** only for mounts; the app always runs as **`dmz`** via `su-exec`.
- **Pydantic:** Stay on **v1** (`pydantic<2` in `requirements.txt`) for musl / ARM wheel consistency; Dockerfile forces pydantic-core build from source when needed.
