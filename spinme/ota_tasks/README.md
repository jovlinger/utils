# Optional OTA task blobs

Files here are staged by `make build-tasks` into `build/tasks/` and uploaded
by `make otainstalltasks` as `PUT /kv/<basename>`.

Basename must be a KV key (`[A-Za-z0-9_-]+`). Until the all-but-nucleus ELF
split ships, leave this directory empty: linked TaskActors still ride
`make usbinstallall`.
