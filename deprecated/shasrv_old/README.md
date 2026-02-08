# Hash-backed FLAC store on gmk (design notes)

Music storage (shaserv)
- Mount: f2fs SD card at /mnt/sdb2 (fstab mounts ro; automount + idle timeout)
- Store root: /mnt/sdb2/music/flac
  - Objects: data/XX/<sha256> (regular files, 0644; dirs 0755)
  - Human tree: files/<Artist>/<Album>/<NN. Title>.flac (symlinks -> ../../data/XX/<sha256>)
- Design/spec: ~/shaserv/README.md
- Ingest: sudo ~/shaserv/ingest.sh <file-or-dir> [...]
  - Remounts /mnt/sdb2 rw -> ingest (hash>data, files/<basename(arg)>/...) -> remounts ro (trap)
  - Logs per-file: hashing, sha256, copy target, link target, source removal
- Permissions fixer (persistent): sudo ~/hashserv/fix-perms.sh
  - Remounts rw; fixes data/ files to 0644 and dirs to 0755; remounts ro


This machine stores FLAC content in a content-addressed layout and exposes a human-readable tree for browsing. The current on-disk state (verified 2025‑10‑29):

- Root mount (read-only in fstab): `/mnt/sdb2` (F2FS)
- Store root: `/mnt/sdb2/music/flac`
  - `data/XX/<sha256>`: payload objects, where `XX` is the first two hex digits of the file’s SHA‑256
  - `files/<Artist> - <Album>/<NN. Title>.flac`: human-readable paths
  - `files` entries are relative symlinks to `../../data/XX/<sha256>`

Example:
```
/mnt/sdb2/music/flac/files/Aim - Cold Water Music/01. Intro.flac -> ../../data/3b/3b89c85d5c...fcfc7
/mnt/sdb2/music/flac/data/3b/3b89c85d5c...fcfc7            (regular file)
```

## Goals
- Deduplicate identical audio by content (SHA‑256) regardless of original file name/path.
- Provide a stable, user-friendly tree under `files/` for playback and SMB access.
- Keep the object store (`data/`) immutable and garbage-collectable.

## Why symlinks (soft links) and not hardlinks
We do not actually have a practical choice here; the design requires symlinks. Reasons:

1) Filesystem boundary and future mobility
   - Hardlinks cannot cross filesystems. Today `files/` and `data/` live together, but the design needs the freedom to split them later (e.g., keep `data/` on large, slow media and project multiple `files/` views elsewhere). Symlinks continue to work across such refactors; hardlinks would not.

2) Object–reference semantics and GC
   - With hardlinks, each “reference” increments the link count of the payload. Determining liveness requires enumerating link counts across every tree that might ever point to an object (including transient trees, temporary imports, etc.). Symlinks keep the payload as a single, obvious object and make GC a pure reachability scan of `files/` → target hashes. That keeps the GC/repair logic simple, explicit, and auditable.

3) Stable, relative addressing
   - We use relative symlinks (`../../data/XX/<sha256>`). This allows the entire `flac/` subtree to be moved together without rewriting link targets, and it avoids absolute paths baked into millions of entries.

4) Samba/Windows behavior is accounted for
   - Samba is configured to follow symlinks for this share (`wide links = Yes`, `allow insecure wide links = Yes`, `unix extensions = No`). Clients see regular files. No client-side hardlink support is required and no client will create links.

5) Safety under read-only mounts
   - The card is mounted `ro` during steady state. We ingest while explicitly `rw` (or off-host), then return to `ro`. Symlinks preserve the invariant that the object store remains immutable; nothing in `files/` modifies link counts on payloads, and accidental writes are blocked by `ro`.

In short: hardlinks complicate GC and future storage topology, and they couple the object’s lifetime to every presentation path. Symlinks keep the model clear: `files/` is a view; `data/` is the truth.

## Ingest pipeline (content-addressed write)
1) Compute SHA‑256 of the source file’s bytes.
2) Place the payload at `data/<sha[:2]>/<sha>` if not already present; write atomically (temp + rename) and fsync for durability.
3) Create/ensure the artist/album directory under `files/`.
4) Create/update a relative symlink `files/.../Track.flac -> ../../data/<sha[:2]>/<sha>`.
5) Optional: record sidecar metadata (tags, sample rate) in a manifest or extended attributes.

This is idempotent: repeating an ingest never duplicates payloads.

## Garbage collection and repair
- Live set: all hashes reachable by traversing symlink targets under `files/`.
- GC: delete objects in `data/` not in the live set (after grace period and safety checks).
- Repair: for each `files/` entry, verify that the symlink’s target exists and matches the expected length/hash; fix any broken targets by reingest or relink.

## Hash choice
- SHA‑256: widely available, collision-resistant for this use-case, already present in the existing layout.

## Samba and mount requirements
- Share path is `files/` (not `data/`).
- Samba needs symlink following enabled (current config allows it). Keep `unix extensions = No`, `wide links = Yes`.
- Mount `sdb2` as `ro` during normal operation (as in fstab) to enforce immutability and safety.

## Directory ownership and permissions
- `flac/` is owned by root, world-readable. Payloads (`data/`) are regular files; `files/` are symlinks. Clients read via SMB; no client writes to this tree.

## Non-goals
- No in-place tag editing in `files/` (card is `ro`). Tag updates require reingest.
- No reliance on hardlink counts for liveness.

## Appendix: On-disk shape
- `data/` fan-out 256 directories (00..ff) prevents large-directory performance cliffs.
- Relative symlinks make the tree relocatable and snapshot-friendly.

