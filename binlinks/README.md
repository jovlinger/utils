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
| `render_socks5_util` | `render_socks5/render_socks5_util.py` -- bring the Render SOCKS5 proxy up or down |
| `dedup` | `dedup/dedup.sh` -- ingest into a SHA-256 store (rw/ro remount) |
| `cpdup` | `dedup/cpdup.sh` -- copy one dedup store into another |
| `redup` | `dedup/redup.sh` -- materialize real files from a store |
| `fixdup` | `dedup/fixdup.sh` -- repair files/ symlinks (relative or absolute) |

Agent notes (e.g. do not symlink `ingest.py`): [`AGENTS.md`](AGENTS.md).
