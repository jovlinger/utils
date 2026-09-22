# binlinks

PATH-visible commands for utilities under `utils/` (see also `bin/binlinks`).

`initcommon.sh` adds this directory to `PATH` via `editpath --add`.

Refresh every symlink from the repo root:

```sh
make binlinks
```

| command | target |
|---------|--------|
| `ingest` | `shadup/ingest.sh` -- album ingest with rw/ro remount |
| `postingest` | `shadup/postingest` -- musicscan, `.meta.combined.json`, tag import, `_tags` refresh |
| `shadup` | `shadup/shadup` -- content-addressed store CLI |
| `importtags` | `shadup/importtags` -- import metatool sidecar tags into shadup DB |
| `todo` | `skills/projectmanagement/todos/todo.py` -- branch-bound todo ticket CLI |
| `manage` | `thermo/dmz/manage` -- DMZ HTTP CLI |
| `onboardctl` | `thermo/onboard/onboardctl/onboardctl` -- direct onboard debug CLI (bypasses DMZ) |

Agent notes (e.g. do not symlink `ingest.py`): [`AGENTS.md`](AGENTS.md).
