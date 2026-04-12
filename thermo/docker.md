# Thermo Docker notes

DMZ image: `**jovlinger/thermo/dmz**` (Alpine, non-root `dmz` user, entrypoint `**tini` → `start.sh` → `run.sh` → app`). Default app port **`8080`** (`PORT` env).

## DMZ: run the service (host)

```text
docker run --rm -p 8080:8080 --tmpfs /tmp --tmpfs /var/log jovlinger/thermo/dmz
```

## DMZ: unit tests inside the image

```text
docker run --rm --workdir /app --entrypoint python jovlinger/thermo/dmz \
  -m pytest -q test
```

Or from `**thermo/dmz**`: `make test-docker` (in-image pytest) or `make test-local` (host venv); `make test` runs both.

## DMZ: interactive shell (Alpine has `/bin/sh`, not `bash`)

Override the entrypoint; otherwise `tini` starts the app.

```text
docker run --rm -it --entrypoint /bin/sh jovlinger/thermo/dmz
```

## Compose (DMZ + onboard + testdriver)

See `**thermo/test/docker-compose.yml**`. DMZ is reached at `**http://dmz:8080**` on the compose network.