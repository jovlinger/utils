# Agent Notes -- DMZ install / SD ops

FAT file map and human boot notes: [`README.md`](README.md).

## Priv and host keys

- Treat `thermo/priv/` as private material (backup if needed, never commit).
- Generate rescue SSH host keys once per clone:

```bash
cd thermo/dmz
./install/gen-dmz-rescue-host-keys.sh
```

`build-and-write.sh` copies them into the apkovl; if missing it runs the
generator first.

## Hot reload (no SD reburn)

`start.sh` sets `RUN_WITH_STDOUT_RUNFILE=/tmp/dmz.run`. While that file exists,
`run-with-stdout-logged.py` restarts `run.sh` after each exit. Copy updated
Python into `/tmp/dmz_rootfs/app/`, then kill `app.py` or `run.sh` inside the
chroot (runfile stays). **Stop:** `rm /tmp/dmz_rootfs/tmp/dmz.run` (or host path
into chroot tmpfs), then stop the process tree (e.g. kill `tini -- /app/start.sh`
from the rescue shell).

On a running Pi, edit `/etc/dmz/dmz-app.env` inside the chroot and send
`kill -USR1 <dmz-pid>` to reload `LOG_LEVEL`, long-poll timeouts, and obsolete-log
suppression without rebooting (`app.py` `reload_dmz_config_from_disk`).
