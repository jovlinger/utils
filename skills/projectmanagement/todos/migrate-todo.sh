#!/usr/bin/env bash
# Move (or copy) one todo from the todo dir the current repo resolves to into another todo dir.
#
# Usage:
#   migrate-todo.sh [--keep-source] SELECTOR DEST_TODO_DIR
#
# Run from inside a git checkout (todo.py needs one). SELECTOR is an Id prefix (4+ hex) or a full digest.
# DEST_TODO_DIR must already hold a store (config.json, sqlite.db or storage/); either backend works.
#
# The todo is exported, imported into the destination, and verified there. Then it is soft-removed from
# the source, which leaves a recoverable tombstone; --keep-source skips that removal. The todo's git
# branch and worktree are not touched.
#
# Example:
#   migrate-todo.sh 1a2b3c4d ~/other-todo-dir

set -euo pipefail

SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  link="$(readlink "$SELF")"
  case "$link" in
    /*) SELF="$link" ;;
    *) SELF="$(dirname "$SELF")/$link" ;;
  esac
done
HERE="$(cd -P "$(dirname "$SELF")" && pwd)"
TODO="$HERE/todo.py"

die() {
  echo "migrate-todo.sh: $*" >&2
  exit 1
}

usage() {
  echo "Usage: migrate-todo.sh [--keep-source] SELECTOR DEST_TODO_DIR"
}

keep_source=0
while [ $# -gt 0 ]; do
  case "$1" in
    --keep-source) keep_source=1; shift ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) break ;;
  esac
done
[ $# -eq 2 ] || { usage >&2; exit 2; }
selector="$1"
dest="$2"

command -v jq >/dev/null || die "jq is required"
[ -d "$dest" ] || die "destination is not a directory: $dest"
dest="$(cd -P "$dest" && pwd)"
[ -e "$dest/config.json" ] || [ -e "$dest/sqlite.db" ] || [ -d "$dest/storage" ] ||
  die "destination holds no todo store (config.json, sqlite.db or storage/): $dest"

id="$("$TODO" read "$selector" | jq -r .Id)"
src_base="$("$TODO" basedir)"
dest_base="$(TODO_DIR="$dest" "$TODO" basedir)"
[ "$(cd -P "$src_base" && pwd)" != "$(cd -P "$dest_base" && pwd)" ] ||
  die "source and destination resolve to the same todo dir: $src_base"

# import-json overwrites an existing todo with the same Id, so absence is checked first.
if TODO_DIR="$dest" "$TODO" read "$id" >/dev/null 2>&1; then
  die "todo $id already exists in $dest_base"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

"$TODO" export-to-file "$id" --basedir "$work/src" >/dev/null
exported="$work/src/storage/$id.json"
TODO_DIR="$dest" "$TODO" import-json --from-json "$exported" >/dev/null
TODO_DIR="$dest" "$TODO" export-to-file "$id" --basedir "$work/dest" >/dev/null

# The import stamps update_dt; every other field must round-trip unchanged.
if ! cmp -s <(jq -S 'del(.update_dt)' "$exported") <(jq -S 'del(.update_dt)' "$work/dest/storage/$id.json"); then
  TODO_DIR="$dest" "$TODO" rm --hard "$id" >/dev/null
  die "the copy in $dest_base differs from the source; destination copy removed, source untouched"
fi

if [ "$keep_source" -eq 1 ]; then
  echo "$id copied: $src_base -> $dest_base"
else
  "$TODO" rm "$id" >/dev/null
  echo "$id moved: $src_base -> $dest_base (source soft-removed)"
fi
