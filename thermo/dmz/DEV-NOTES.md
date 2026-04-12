# DMZ dev notes

- **Tests:** `make test-local` / `./test/run.sh` (host **pytest** under `test/`); `make test-docker` (in-image pytest + **`smoketest/`** Docker + host pytest); `make test` (both). Umbrella: **`make test`** from **`thermo/`** runs **dmz** (including **smoketest**), **onboard**, **test/**. See `test/README.md` and `smoketest/README.md`.
- **Entry:** `start.sh` runs as **root** only for mounts; the app always runs as **`dmz`** via `su-exec`.
- **Pydantic:** Stay on **v1** (`pydantic<2` in `requirements.txt`) for musl / ARM wheel consistency; Dockerfile forces pydantic-core build from source when needed.
