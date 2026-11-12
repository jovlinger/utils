# dedup

Content-addressed file store (internally called **shasrv**). Files live once under
`data/` by SHA-256; the logical tree is symlinks under `files/`.

Store layout:

```text
<target>/
  data/<sha[:2]>/<sha256>   # unique blobs
  files/<relative/path>     # symlinks into data/
```

PATH commands (via `utils/binlinks`, refreshed by `make binlinks`): `dedup`,
`cpdup`, `redup`, `fixdup`. Those names point at the shell wrappers below; do
not link `dedup.py` directly.

## Commands

### `dedup` (`dedup.sh`)

Wrapper around `dedup.py`. Activates this project's venv, and if the target
filesystem is mounted read-only, remounts it read-write for the run and remounts
read-only on exit.

```sh
dedup <sources...> <target_dir> [-v] [--dryrun] [--remove-source]
```

| flag | effect |
|------|--------|
| `-v` / `--verbose` | progress |
| `--dryrun` | hash and plan only; no writes |
| `--remove-source` | delete each source file after a successful store |

`dedup.py` is the core ingest implementation (stdlib Python); call it only when
you do not need remount/venv handling.

### `cpdup` (`cpdup.sh`)

Copy one dedup store into another, preserving the `data/` + `files/` layout.
Creates the destination if needed; skips blobs already present in the destination
`data/` tree.

```sh
cpdup <src_dedup_dir> <dst_dedup_dir>
```

### `redup` (`redup.sh`)

Materialize a normal directory tree from a store: follow each `files/` symlink
and copy the blob contents (no symlinks in the output). Multiple `files/` links
to the same blob become hardlinks in the export (shared inode). Default
destination is `./dup`.

```sh
redup [--unlink] <source_dir> [destination_dir]
```

| flag | effect |
|------|--------|
| `--unlink` | after a full successful export, remove exported `files/` entries and their `data/` blobs; blobs never referenced by this export stay |

### `fixdup` (`fixdup.sh`)

### `fixdup` (`fixdup.sh`)

Repair `files/` symlinks so they point at the correct `data/` blob.

```sh
fixdup {relative|absolute} <dedup_dir> [-v] [--dryrun]
```

| style | effect |
|-------|--------|
| `relative` | rewrite as relative paths into `data/` (use after moving links under `files/`) |
| `absolute` | rewrite as absolute paths into `data/` |

## Tests

Shell e2e scripts in this directory (`e2e_test.sh`, `simple_e2e_test.sh`,
`cpdup_e2e_test.sh`, `test_fix.sh`, `test_mount.sh`). The Makefile `test` /
`all-tests` targets are currently no-ops.
