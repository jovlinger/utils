#!/bin/bash
# test_reindex.sh - Rebuild DB entries from existing files/ symlink tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_BASE="/tmp/shadup_test_reindex_$$"
STORE="$TEST_BASE/store"
SHADIR="$STORE/data"
FILES="$STORE/files"
DB="$TEST_BASE/reindex.db"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

cleanup() { rm -rf "$TEST_BASE"; }
trap cleanup EXIT

mkdir -p "$SHADIR/aa" "$SHADIR/bb" "$FILES/Artist/Album" "$FILES/Misc"

H1="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
H2="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
echo "payload 1" > "$SHADIR/aa/$H1"
echo "payload 2" > "$SHADIR/bb/$H2"

ln -s "../../../data/aa/$H1" "$FILES/Artist/Album/01.flac"
ln -s "../../data/bb/$H2" "$FILES/Misc/file.flac"

# Non-indexable links (should be skipped)
ln -s "/tmp/not-under-shadir" "$FILES/Misc/outside.flac"
ln -s "../../data/cc/missingmissingmissingmissingmissingmissingmissingmissing" "$FILES/Misc/missing.flac"
ln -s "../../data/aa/not_a_hash_name" "$FILES/Misc/not-hash.flac"

(
    cd "$TEST_BASE"
    python3 "$SCRIPT_DIR/shadup.py" --reindex-files "$FILES" --shadir "$SHADIR" --db "$DB" >/dev/null
)

row_count="$(python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
count = conn.execute("SELECT COUNT(*) FROM stored_files WHERE deleted = 0").fetchone()[0]
print(count)
PY
)"
[ "$row_count" = "2" ] || fail "expected 2 active rows, got $row_count"
pass "indexed only valid symlink entries"

paths="$(python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
rows = conn.execute(
    "SELECT root_rel, dirpath, filename FROM stored_files WHERE deleted = 0 ORDER BY dirpath, filename"
).fetchall()
for root_rel, dirpath, filename in rows:
    if dirpath:
        print(f"{root_rel}/{dirpath}/{filename}")
    else:
        print(f"{root_rel}/{filename}")
PY
)"
echo "$paths" | grep -q '^store/files/Artist/Album/01.flac$' || fail "missing Artist path in db"
echo "$paths" | grep -q '^store/files/Misc/file.flac$' || fail "missing Misc path in db"
pass "root_rel/dirpath/filename reconstructed correctly"

(
    cd "$TEST_BASE"
    out="$(python3 "$SCRIPT_DIR/shadup.py" --lspath --shadir "$SHADIR" --db "$DB")"
    echo "$out" | grep -q "$H1" || fail "--lspath output missing first hash"
    echo "$out" | grep -q "$H2" || fail "--lspath output missing second hash"
)
pass "reindexed rows visible via --lspath"

echo ""
echo "Reindex tests passed!"
