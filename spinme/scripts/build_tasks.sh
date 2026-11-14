#!/usr/bin/env bash
# Stage non-nucleus task blobs under build/tasks/.
# Until all-but-nucleus ELF split ships, optional sources live in ota_tasks/
# (basename = KV key). Always writes .built so Make deps are real.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/tasks}"
SRC="$ROOT/ota_tasks"
mkdir -p "$OUT"
# Drop stale blobs; keep only what we stage this run.
find "$OUT" -mindepth 1 -maxdepth 1 ! -name '.built' -exec rm -rf {} +
if [[ -d "$SRC" ]]; then
  # Copy regular files and leaf dirs' files as KV payloads.
  while IFS= read -r -d '' f; do
    base="$(basename "$f")"
    # Skip notes
    case "$base" in
      README|README.md|.gitkeep) continue ;;
    esac
    cp -f "$f" "$OUT/$base"
  done < <(find "$SRC" -type f -print0 2>/dev/null || true)
fi
: >"$OUT/.built"
n="$(find "$OUT" -type f ! -name '.built' | wc -l | tr -d ' ')"
echo "build-tasks: staged $n blob(s) in $OUT"
