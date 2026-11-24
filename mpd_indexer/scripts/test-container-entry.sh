#!/bin/bash
# Entry for the mpd_indexer test container.
# 1) RECREATE the SHD nested-path bug (ParentAllows only matches "files").
# 2) Only then build newest /src and prove the fix.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "==> apt"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates python3 python3-pip ninja-build pkg-config g++ gcc git \
  meson ffmpeg mpc psmisc \
  libflac-dev libcurl4-gnutls-dev zlib1g-dev \
  libboost-dev libogg-dev libsqlite3-dev >/tmp/apt.log 2>&1 || {
  tail -40 /tmp/apt.log
  exit 1
}

build_mpd() {
  local src="$1"
  rm -rf "$src/build"
  (
    cd "$src"
    meson setup build --buildtype=release \
      -Dauto_features=disabled \
      -Dflac=enabled -Dcurl=enabled -Dzlib=enabled -Dicu=disabled \
      -Ddatabase=true -Ddaemon=true -Dtcp=true \
      -Ddocumentation=disabled -Dhtml_manual=false -Dmanpages=false \
      --force-fallback-for=fmt
    ninja -C build
  )
}

setup_fixture() {
  ROOT=/tmp/music
  FILES="$ROOT/NAS/gmk/files"
  ALBUM="$FILES/AlbumA"
  rm -rf "$ROOT" /tmp/mpd-run
  mkdir -p "$ALBUM" "$FILES/_tags/album/albuma" \
    "$FILES/_meta/AlbumA" /tmp/mpd-run/{playlists,log,run}
  ffmpeg -y -loglevel error -f lavfi -i "sine=f=440:d=1" -c:a flac \
    "$ALBUM/01.flac"
  ln -sfn ../../AlbumA "$FILES/_meta/AlbumA/album"
  ln -sfn ../../../_meta/AlbumA "$FILES/_tags/album/albuma/AlbumA"
  printf '%s\n' '_meta' > "$FILES/.mpdignore"
  cat >/tmp/mpd-run/mpd.conf <<EOF
music_directory		"$ROOT"
playlist_directory	"/tmp/mpd-run/playlists"
db_file			"/tmp/mpd-run/tag_cache"
log_file			"/tmp/mpd-run/log/mpd.log"
pid_file			"/tmp/mpd-run/run/mpd.pid"
bind_to_address		"127.0.0.1"
port				"6601"
auto_update			"no"
follow_outside_symlinks	"yes"
follow_inside_symlinks	"yes"
audio_output {
	type		"null"
	name		"null"
}
EOF
}

stop_test_mpd() {
  # Do not toggle set -e here (it is process-global and breaks callers).
  if [ -n "${MPD_TEST_PID:-}" ]; then
    kill "$MPD_TEST_PID" 2>/dev/null || true
    wait "$MPD_TEST_PID" 2>/dev/null || true
  fi
  MPD_TEST_PID=
  fuser -k 6601/tcp >/dev/null 2>&1 || true
  sleep 0.5
}

# Prints PROOF_*. Exit 0 = healthy _tags tree; 1 = SHD empty-_tags bug;
# 2 = infrastructure failure (mpd did not start).
run_prove() {
  local mpd_bin="$1"
  stop_test_mpd
  rm -f /tmp/mpd-run/tag_cache
  mkdir -p /tmp/mpd-run/log /tmp/mpd-run/run /tmp/mpd-run/playlists
  "$mpd_bin" --version | head -1
  "$mpd_bin" --no-daemon /tmp/mpd-run/mpd.conf \
    >/tmp/mpd-run/log/stdout.log 2>&1 &
  MPD_TEST_PID=$!
  local ready=0
  for _ in $(seq 1 80); do
    if mpc -h 127.0.0.1 -p 6601 status >/dev/null 2>&1; then
      ready=1
      break
    fi
    if ! kill -0 "$MPD_TEST_PID" 2>/dev/null; then
      echo "mpd exited early:" >&2
      tail -40 /tmp/mpd-run/log/stdout.log >&2 || true
      tail -40 /tmp/mpd-run/log/mpd.log >&2 || true
      return 2
    fi
    sleep 0.1
  done
  if [ "$ready" != "1" ]; then
    echo "mpd did not accept connections on :6601" >&2
    tail -40 /tmp/mpd-run/log/stdout.log >&2 || true
    stop_test_mpd
    return 2
  fi
  mpc -h 127.0.0.1 -p 6601 update >/dev/null
  for _ in $(seq 1 120); do
    mpc -h 127.0.0.1 -p 6601 status 2>/dev/null | grep -q Updating || break
    sleep 0.2
  done

  set +e
  python3 - <<'PY'
import socket, sys

def cmd(c):
    s = socket.create_connection(("127.0.0.1", 6601), 5)
    f = s.makefile("rw", buffering=1)
    f.readline()
    f.write(c + "\n"); f.flush()
    out = []
    while True:
        r = f.readline()
        if not r:
            break
        out.append(r.rstrip("\n"))
        if r.startswith("OK") or r.startswith("ACK"):
            break
    s.close()
    return out

def dirs(path):
    return [ln.split(":", 1)[1].strip()
            for ln in cmd("lsinfo " + path)
            if ln.startswith("directory:")]

files = dirs("NAS/gmk/files")
tags = dirs("NAS/gmk/files/_tags")
album = dirs("NAS/gmk/files/_tags/album")
leaf = dirs("NAS/gmk/files/_tags/album/albuma")
meta = cmd("lsinfo NAS/gmk/files/_meta")
songs = [ln for ln in cmd("listall") if ln.startswith("file:")]
print("PROOF files=", files)
print("PROOF tags=", tags)
print("PROOF album=", album)
print("PROOF leaf=", leaf)
print("PROOF meta_lsinfo=", meta)
print("PROOF songs=", songs)

tags_ok = (
    any(x.rstrip("/").endswith("_tags") for x in files)
    and any(x.endswith("album") for x in tags)
    and any("albuma" in x for x in album)
    and any("AlbumA" in x for x in leaf)
)
meta_gone = not any(x.rstrip("/").endswith("_meta") for x in files)
meta_empty = not any(
    m.startswith("directory:") or m.startswith("file:") for m in meta
)
songs_ok = len(songs) == 1 and bool(songs) and "/_tags/" not in songs[0]

if tags_ok and meta_gone and meta_empty and songs_ok:
    print("PROOF_OK")
    sys.exit(0)
print("PROOF_BROKEN")
if not tags_ok:
    print(" reason: _tags tree empty or incomplete (SHD nested-path bug)")
sys.exit(1)
PY
  local rc=$?
  stop_test_mpd
  return "$rc"
}

echo "==> fixture"
setup_fixture

echo ""
echo "========================================"
echo " PHASE 1: RECREATE the problem (broken)"
echo "========================================"
rm -rf /tmp/mpd-broken
cp -a /src /tmp/mpd-broken
python3 - <<'PY'
from pathlib import Path
import re
p = Path("/tmp/mpd-broken/src/db/update/Walk.cxx")
text = p.read_text()
pat = re.compile(
    r"(gcc_pure\n)?static bool\nIsFilesDirPath\(const char \*path\) noexcept\n\{.*?\n\}",
    re.S,
)
broken = """gcc_pure
static bool
IsFilesDirPath(const char *path) noexcept
{
	/* INTENTIONAL BUG (pre-fix): SHD uses NAS/gmk/files, not bare files. */
	if (path == nullptr || path[0] == '\\0')
		return false;
	return StringIsEqual(path, "files");
}"""
new, n = pat.subn(broken, text, count=1)
if n != 1:
    raise SystemExit("failed to patch IsFilesDirPath for recreate (%d)" % n)
if "StringEndsWith(path, \"/files\")" in new:
    raise SystemExit("bug patch left StringEndsWith in IsFilesDirPath")
p.write_text(new)
print("patched IsFilesDirPath -> files-only (bug)")
PY
build_mpd /tmp/mpd-broken
set +e
run_prove /tmp/mpd-broken/build/mpd
rc1=$?
set -e
if [ "$rc1" -eq 2 ]; then
  echo "PHASE1_FAIL: mpd infrastructure" >&2
  exit 1
fi
if [ "$rc1" -eq 0 ]; then
  echo "PHASE1_FAIL: expected empty _tags with nested NAS/gmk/files bug" >&2
  exit 1
fi
echo "PROBLEM_RECREATED"

echo ""
echo "========================================"
echo " PHASE 2: newest /src (fix) and prove"
echo "========================================"
rm -rf /tmp/mpd-src
cp -a /src /tmp/mpd-src
# sanity: newest must have EndsWith
grep -q 'StringEndsWith(path, "/files")' /tmp/mpd-src/src/db/update/Walk.cxx
build_mpd /tmp/mpd-src
set +e
run_prove /tmp/mpd-src/build/mpd
rc2=$?
set -e
if [ "$rc2" -ne 0 ]; then
  echo "PHASE2_FAIL: newest code did not index _tags (rc=$rc2)" >&2
  exit 1
fi
echo "FIXED_PROOF_OK"

if [ "${INTERACTIVE:-0}" = "1" ]; then
  echo "INTERACTIVE=1: dropping to bash (mpd not left running)"
  exec bash
fi
