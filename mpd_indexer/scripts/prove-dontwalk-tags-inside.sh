#!/bin/bash
# Runs INSIDE the prove container. Builds native dont-walk MPD, indexes a
# SHD-shaped fixture, prints proof lines, exits non-zero on failure.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "==> apt"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates python3 python3-pip ninja-build pkg-config g++ gcc git \
  meson ffmpeg mpc \
  libflac-dev libcurl4-gnutls-dev zlib1g-dev libpcre2-dev \
  libicu-dev libboost-dev libogg-dev libsystemd-dev libsqlite3-dev \
  libid3tag0-dev >/tmp/apt.log 2>&1 || {
  tail -50 /tmp/apt.log
  exit 1
}

echo "==> meson build"
cp -a /src /tmp/mpd-src
cd /tmp/mpd-src
rm -rf build
meson setup build --buildtype=release \
  -Dauto_features=disabled \
  -Dflac=enabled \
  -Dcurl=enabled \
  -Dzlib=enabled \
  -Dicu=enabled \
  -Ddatabase=true \
  -Ddaemon=true \
  -Dtcp=true \
  -Ddocumentation=disabled \
  -Dhtml_manual=false \
  -Dmanpages=false \
  --force-fallback-for=fmt
ninja -C build
MPD=/tmp/mpd-src/build/mpd
"$MPD" --version | head -2

echo "==> fixture NAS/gmk/files (SHD path shape)"
ROOT=/tmp/music
FILES="$ROOT/NAS/gmk/files"
ALBUM="$FILES/AlbumA"
rm -rf "$ROOT" /tmp/mpd-run
mkdir -p "$ALBUM" "$FILES/_tags/album/albuma" \
  "$FILES/_meta/AlbumA" /tmp/mpd-run/{playlists,log,run}

# Real song
ffmpeg -y -loglevel error -f lavfi -i "sine=f=440:d=1" -c:a flac \
  "$ALBUM/01.flac"
# _meta -> real album (one hop); _tags leaf -> _meta (SHD-like)
ln -s ../../AlbumA "$FILES/_meta/AlbumA/album"
ln -s ../../../_meta/AlbumA \
  "$FILES/_tags/album/albuma/AlbumA"
# Honor ops layout: ignore _meta, walk _tags
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

echo "==> mpd update"
"$MPD" --no-daemon /tmp/mpd-run/mpd.conf &
MPD_PID=$!
cleanup() { kill "$MPD_PID" 2>/dev/null || true; wait "$MPD_PID" 2>/dev/null || true; }
trap cleanup EXIT
for i in $(seq 1 50); do
  if mpc -h 127.0.0.1 -p 6601 status >/dev/null 2>&1; then break; fi
  sleep 0.1
done

mpc -h 127.0.0.1 -p 6601 update
for i in $(seq 1 120); do
  if ! mpc -h 127.0.0.1 -p 6601 status 2>/dev/null | grep -q 'Updating'; then
    break
  fi
  sleep 0.5
done
echo "==> stats"
mpc -h 127.0.0.1 -p 6601 stats

echo "==> lsinfo files"
mpc -h 127.0.0.1 -p 6601 ls "NAS/gmk/files" || true
# mpc 0.34 uses ls; also raw protocol for lsinfo
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

print("PROOF files_children=", files)
print("PROOF tags_children=", tags)
print("PROOF tags_album_children=", album)
print("PROOF tags_leaf_children=", leaf)
print("PROOF meta_lsinfo=", meta)
print("PROOF songs=", songs)

fail = []
if any(x.rstrip("/").endswith("_meta") for x in files):
    fail.append("_meta must not appear under files when .mpdignore lists it")
if not any(x.rstrip("/").endswith("_tags") for x in files):
    fail.append("_tags missing under files")
if not any(x.endswith("album") for x in tags):
    fail.append("_tags/album missing")
if not any("albuma" in x for x in album):
    fail.append("_tags/album/albuma missing")
if not any("AlbumA" in x for x in leaf):
    fail.append("_tags leaf AlbumA directory missing (link not indexed)")
if len(songs) != 1:
    fail.append("expected exactly 1 song, got %d" % len(songs))
if songs and "/_tags/" in songs[0]:
    fail.append("song path must be real album, not under _tags")
if any(m.startswith("directory:") or m.startswith("file:") for m in meta):
    fail.append("_meta still browsable")

if fail:
    print("FAIL:")
    for f in fail:
        print(" -", f)
    sys.exit(1)
print("PROOF_OK")
PY
