#!/bin/bash
# test_ingest.sh - Integration tests for shadup/ingest.sh observable behavior.
#
# Uses a copied harness under /tmp so tests can run without touching real mounts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_BASE="/tmp/shadup_test_ingest_$$"
HARNESS="$TEST_BASE/harness"
STORE="$TEST_BASE/store"
SRC="$TEST_BASE/src"
DB="$TEST_BASE/db/shadup.db"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

cleanup() { rm -rf "$TEST_BASE"; }
trap cleanup EXIT

mk_harness() {
    mkdir -p "$HARNESS"
    cp "$SCRIPT_DIR/ingest.sh" "$HARNESS/ingest.sh"
    cp "$SCRIPT_DIR/ingest.py" "$HARNESS/ingest.py"
    cp "$SCRIPT_DIR/shadup.py" "$HARNESS/shadup.py"
    cp "$SCRIPT_DIR/with-ro-remounted-rw.sh" "$HARNESS/with-ro-remounted-rw.sh"
    chmod +x "$HARNESS/ingest.sh" "$HARNESS/ingest.py" "$HARNESS/with-ro-remounted-rw.sh"

    # Keep the binary behavior but remove root/mount requirements in test harness:
    # - bypass sudo check
    # - make remount wrapper a plain exec passthrough
    sed -i '' '/if \[ "\${EUID:-\$(id -u)}" -ne 0 \]; then/,/fi/d' "$HARNESS/ingest.sh"
    cat > "$HARNESS/with-ro-remounted-rw.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec "$@"
EOF
    chmod +x "$HARNESS/with-ro-remounted-rw.sh"
}

assert_relative_data_link() {
    local link="$1"
    [ -L "$link" ] || fail "expected symlink: $link"
    local target
    target="$(readlink "$link")"
    [[ "$target" != /* ]] || fail "expected relative symlink, got absolute: $target"
    local resolved
    resolved="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$link")"
    local data_root
    data_root="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$STORE/data")"
    [[ "$resolved" == "$data_root/"* ]] || fail "symlink does not resolve under data/: $target"
}

mkdir -p "$STORE/data" "$STORE/files" "$SRC/A/Disc 1" "$SRC/A/Disc 2"
mk_harness

# ---- Test 1: directory ingest shape + dedup + sorted walk ----
printf 'A' > "$SRC/A/Disc 1/1.flac"
printf 'B' > "$SRC/A/Disc 1/2.flac"
printf 'C' > "$SRC/A/Disc 1/10.flac"
printf 'A' > "$SRC/A/Disc 2/1.flac"

stderr_log="$TEST_BASE/ingest.stderr"
SHASRV_STORE_ROOT="$STORE" SHASRV_DB="$DB" "$HARNESS/ingest.sh" "$SRC/A" 2>"$stderr_log"

[ ! -e "$SRC/A/Disc 1/1.flac" ] || fail "source file should be removed on success"
[ ! -d "$SRC/A" ] || fail "source directory should be pruned when empty"
pass "source files removed and empty tree pruned"

assert_relative_data_link "$STORE/files/A/Disc 1/1.flac"
assert_relative_data_link "$STORE/files/A/Disc 1/2.flac"
assert_relative_data_link "$STORE/files/A/Disc 1/10.flac"
assert_relative_data_link "$STORE/files/A/Disc 2/1.flac"
pass "files tree created with relative data symlinks"

obj_count="$(find "$STORE/data" -type f | wc -l | tr -d ' ')"
[ "$obj_count" = "3" ] || fail "expected 3 payload objects (dedup), got $obj_count"
pass "payload dedup uses content hashes"

doing_lines=()
while IFS= read -r line; do
    doing_lines+=("$line")
done < <(grep '^Doing: ' "$stderr_log")
[ "${#doing_lines[@]}" = "4" ] || fail "expected 4 Doing lines"
[ "${doing_lines[0]}" = "Doing: files/A/Disc 1/1.flac" ] || fail "unexpected first Doing line: ${doing_lines[0]}"
[ "${doing_lines[1]}" = "Doing: files/A/Disc 1/2.flac" ] || fail "unexpected second Doing line: ${doing_lines[1]}"
[ "${doing_lines[2]}" = "Doing: files/A/Disc 1/10.flac" ] || fail "unexpected third Doing line: ${doing_lines[2]}"
pass "version-aware deterministic processing order"

# ---- Test 2: single file argument uses parent basename as prefix ----
mkdir -p "$SRC/singles"
printf 'single' > "$SRC/singles/track.flac"
SHASRV_STORE_ROOT="$STORE" SHASRV_DB="$DB" "$HARNESS/ingest.sh" "$SRC/singles/track.flac" >/dev/null 2>&1
[ -L "$STORE/files/singles/track.flac" ] || fail "single-file ingest path layout mismatch"
[ ! -e "$SRC/singles/track.flac" ] || fail "single-file source should be removed"
pass "single-file ingest prefix matches parent basename"

# ---- Test 3: shell glob with mixed dir/file args ----
mkdir -p "$SRC/source/dir1" "$SRC/source/dir2"
printf 'd1' > "$SRC/source/dir1/a.flac"
printf 'd2' > "$SRC/source/dir2/b.flac"
printf 'root file' > "$SRC/source/file 1"

glob_stderr="$TEST_BASE/ingest_glob.stderr"
SHASRV_STORE_ROOT="$STORE" SHASRV_DB="$DB" "$HARNESS/ingest.sh" "$SRC/source"/* 2>"$glob_stderr"

# dir args map to files/<dir>/..., file args map to files/<parent-basename>/...
[ -L "$STORE/files/dir1/a.flac" ] || fail "glob dir1 path missing"
[ -L "$STORE/files/dir2/b.flac" ] || fail "glob dir2 path missing"
[ -L "$STORE/files/source/file 1" ] || fail "glob file path missing under parent basename"
pass "glob ingest stores expected mixed paths"

[ ! -e "$SRC/source/dir1/a.flac" ] || fail "glob ingest should remove dir1 file source"
[ ! -e "$SRC/source/dir2/b.flac" ] || fail "glob ingest should remove dir2 file source"
[ ! -e "$SRC/source/file 1" ] || fail "glob ingest should remove top-level file source"
pass "glob ingest removes all successful sources"

echo ""
echo "All ingest tests passed!"
