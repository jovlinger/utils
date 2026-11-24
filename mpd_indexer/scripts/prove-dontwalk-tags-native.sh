#!/bin/bash
# Local (non-Docker) prove: build/run dont-walk MPD on this host with a
# SHD-shaped NAS/gmk/files fixture. Used when Docker Desktop is down.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MPD_SRC="${MPD_SRC:-$HOME/github.com/jovlinger/MPD}"
BUILD="${PROVE_BUILD:-$HOME/tmp/mpd-dontwalk-prove-build}"
MUSIC="${PROVE_MUSIC:-$HOME/tmp/mpd-dontwalk-prove-music}"
RUN="${PROVE_RUN:-$HOME/tmp/mpd-dontwalk-prove-run}"
PORT="${PROVE_PORT:-6601}"

if [ ! -f "$MPD_SRC/src/db/update/Walk.cxx" ]; then
  echo "MPD_SRC=$MPD_SRC missing Walk.cxx" >&2
  exit 1
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PKG_CONFIG_PATH="/opt/homebrew/opt/flac/lib/pkgconfig:${PKG_CONFIG_PATH:-}"

if [ ! -x "$BUILD/mpd" ]; then
  echo "==> meson+ninja -> $BUILD"
  rm -rf "$BUILD"
  meson setup "$BUILD" --buildtype=release \
    -Dauto_features=disabled \
    -Dflac=enabled -Dcurl=enabled -Dzlib=enabled -Dicu=disabled \
    -Ddatabase=true -Ddaemon=true -Dtcp=true \
    -Ddocumentation=disabled -Dhtml_manual=false -Dmanpages=false \
    --force-fallback-for=fmt \
    "$MPD_SRC"
fi
ninja -C "$BUILD"

lsof -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs kill 2>/dev/null || true

FILES="$MUSIC/NAS/gmk/files"
ALBUM="$FILES/AlbumA"
rm -rf "$MUSIC" "$RUN"
mkdir -p "$ALBUM" "$FILES/_tags/album/albuma" "$FILES/_meta/AlbumA" \
  "$RUN"/{playlists,log,run}
ffmpeg -y -loglevel error -f lavfi -i "sine=f=440:d=1" -c:a flac "$ALBUM/01.flac"
ln -sf ../../AlbumA "$FILES/_meta/AlbumA/album"
ln -sf ../../../_meta/AlbumA "$FILES/_tags/album/albuma/AlbumA"
printf '%s\n' '_meta' > "$FILES/.mpdignore"

cat >"$RUN/mpd.conf" <<EOF
music_directory		"$MUSIC"
playlist_directory	"$RUN/playlists"
db_file			"$RUN/tag_cache"
log_file			"$RUN/log/mpd.log"
pid_file			"$RUN/run/mpd.pid"
bind_to_address		"127.0.0.1"
port				"$PORT"
auto_update			"no"
follow_outside_symlinks	"yes"
follow_inside_symlinks	"yes"
audio_output { type "null" name "null" }
EOF

"$BUILD/mpd" --no-daemon "$RUN/mpd.conf" >"$RUN/log/stdout.log" 2>&1 &
MPD_PID=$!
cleanup() { kill "$MPD_PID" 2>/dev/null || true; wait "$MPD_PID" 2>/dev/null || true; }
trap cleanup EXIT

for i in $(seq 1 50); do
  mpc -h 127.0.0.1 -p "$PORT" status >/dev/null 2>&1 && break
  sleep 0.1
done
mpc -h 127.0.0.1 -p "$PORT" rescan
for i in $(seq 1 120); do
  mpc -h 127.0.0.1 -p "$PORT" status 2>/dev/null | grep -q Updating || break
  sleep 0.2
done
mpc -h 127.0.0.1 -p "$PORT" stats

python3 - <<PY
import socket, sys
port = int("$PORT")

def cmd(c):
    s = socket.create_connection(("127.0.0.1", port), 5)
    f = s.makefile("rw", buffering=1)
    f.readline()
    f.write(c + "\n"); f.flush()
    out = []
    while True:
        r = f.readline()
        if not r: break
        out.append(r.rstrip("\n"))
        if r.startswith("OK") or r.startswith("ACK"): break
    s.close(); return out

def dirs(path):
    return [ln.split(":",1)[1].strip() for ln in cmd("lsinfo "+path) if ln.startswith("directory:")]

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
fail = []
if any(x.rstrip("/").endswith("_meta") for x in files): fail.append("_meta listed")
if not any(x.rstrip("/").endswith("_tags") for x in files): fail.append("_tags missing")
if not any(x.endswith("album") for x in tags): fail.append("no album under _tags")
if not any("albuma" in x for x in album): fail.append("no albuma")
if not any("AlbumA" in x for x in leaf): fail.append("no link dir")
if len(songs) != 1: fail.append("songs=%d" % len(songs))
if songs and "/_tags/" in songs[0]: fail.append("dup under tags")
if any(m.startswith("directory:") or m.startswith("file:") for m in meta):
    fail.append("_meta still browsable")
if fail:
    print("FAIL", fail); sys.exit(1)
print("PROOF_OK")
PY
