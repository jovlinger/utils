#!/bin/bash
# Inside the enqueue-prefix e2e container.
# Build dont-walk MPD, index the multi-album fixture (.mpdignore = _meta
# only), assert tag prefixes have zero file rows, then run the in-repo
# resolver against that live database.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if [ ! -f /.dockerenv ] && [ ! -f /run/.containerenv ]; then
  echo "enqueue-prefixes-inside.sh must run inside Docker." >&2
  exit 1
fi

echo "==> apt"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates python3 ninja-build pkg-config g++ gcc git \
  meson ffmpeg nodejs \
  libflac-dev libcurl4-gnutls-dev zlib1g-dev \
  libboost-dev libogg-dev libsqlite3-dev >/tmp/apt.log 2>&1 || {
  tail -40 /tmp/apt.log
  exit 1
}

echo "==> meson build"
cp -a /src /tmp/mpd-src
cd /tmp/mpd-src
rm -rf build
meson setup build --buildtype=release \
  -Dauto_features=disabled \
  -Dflac=enabled -Dcurl=enabled -Dzlib=enabled -Dicu=disabled \
  -Ddatabase=true -Ddaemon=true -Dtcp=true \
  -Ddocumentation=disabled -Dhtml_manual=false -Dmanpages=false \
  --force-fallback-for=fmt
ninja -C build
MPD=/tmp/mpd-src/build/mpd
"$MPD" --version | head -2

echo "==> fixture"
ROOT=/tmp/music
FILES="$ROOT/NAS/gmk/files"
rm -rf "$ROOT" /tmp/mpd-run
mkdir -p "$FILES/Depeche Mode - 101/disc A" \
  "$FILES/Depeche Mode - 101/disc B" \
  "$FILES/Speak and Spell" \
  "$FILES/_meta/Depeche Mode - 101" \
  "$FILES/_meta/Speak and Spell" \
  "$FILES/_tags/artists/depechemode/Depeche Mode - 101" \
  /tmp/mpd-run/{playlists,log,run}
ffmpeg -y -loglevel error -f lavfi -i "sine=f=440:d=1" -c:a flac \
  "$FILES/Depeche Mode - 101/disc A/a1.flac"
ffmpeg -y -loglevel error -f lavfi -i "sine=f=554:d=1" -c:a flac \
  "$FILES/Depeche Mode - 101/disc B/b1.flac"
ffmpeg -y -loglevel error -f lavfi -i "sine=f=330:d=1" -c:a flac \
  "$FILES/Speak and Spell/01.flac"
ln -sfn "../../Depeche Mode - 101" "$FILES/_meta/Depeche Mode - 101/album"
ln -sfn "../../Speak and Spell" "$FILES/_meta/Speak and Spell/album"
ln -sfn "../../../../_meta/Depeche Mode - 101/album/disc B" \
  "$FILES/_tags/artists/depechemode/Depeche Mode - 101/disc B"
ln -sfn "../../../_meta/Speak and Spell" \
  "$FILES/_tags/artists/depechemode/Speak and Spell"
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
python3 - <<'PY'
import json, socket, sys, time

def cmd(c):
    s = socket.create_connection(("127.0.0.1", 6601), 5)
    f = s.makefile("rw", buffering=1)
    f.readline()
    f.write(c + "\n")
    f.flush()
    out = []
    while True:
        row = f.readline()
        if not row:
            break
        out.append(row.rstrip("\n"))
        if row.startswith("OK") or row.startswith("ACK"):
            break
    s.close()
    return out

ready = False
for _ in range(50):
    try:
        cmd("ping")
        ready = True
        break
    except OSError:
        time.sleep(0.1)
if not ready:
    print("MPD did not accept connections")
    sys.exit(1)

cmd("update")
for _ in range(120):
    st = cmd("status")
    if not any(line.startswith("updating_db:") for line in st):
        break
    time.sleep(0.5)

def quote(path):
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'

def files(path):
    rows = cmd("listallinfo " + quote(path))
    ack = [row for row in rows if row.startswith("ACK")]
    found = [row.split(":", 1)[1].strip() for row in rows if row.startswith("file:")]
    return found, ack

album = "NAS/gmk/files/Depeche Mode - 101"
disc_a = album + "/disc A"
disc_b = album + "/disc B"
other = "NAS/gmk/files/Speak and Spell"
tag_artist = "NAS/gmk/files/_tags/artists/depechemode"
tag_album = tag_artist + "/Depeche Mode - 101"
tag_disc = tag_album + "/disc B"

all_rows = cmd("listall")
all_files = [row.split(":", 1)[1].strip() for row in all_rows if row.startswith("file:")]
album_files, _ = files(album)
disc_a_files, _ = files(disc_a)
disc_b_files, _ = files(disc_b)
other_files, _ = files(other)
tag_disc_files, tag_disc_ack = files(tag_disc)
tag_album_files, tag_album_ack = files(tag_album)
tag_artist_files, tag_artist_ack = files(tag_artist)

print("album", album_files)
print("disc_a", disc_a_files)
print("disc_b", disc_b_files)
print("other", other_files)
print("tag_disc", tag_disc_files, tag_disc_ack)
print("tag_album", tag_album_files, tag_album_ack)
print("tag_artist", tag_artist_files, tag_artist_ack)
print("all_files", len(all_files))

fail = []
if any("/_tags/" in uri for uri in all_files):
    fail.append("MPD stored file rows under _tags")
if set(album_files) != set(disc_a_files) | set(disc_b_files):
    fail.append("canonical 101 is not the union of disc A and disc B")
if not disc_a_files:
    fail.append("disc A has no songs")
if set(disc_a_files) & set(disc_b_files):
    fail.append("disc A overlaps disc B")
if not other_files:
    fail.append("second album has no songs")
if tag_disc_files or tag_album_files or tag_artist_files:
    fail.append("tag prefix returned file rows")

payload = {
    "all_files": all_files,
    "album": album_files,
    "disc_b": disc_b_files,
    "other": other_files,
}
with open("/tmp/enq-index.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh)
if fail:
    print("RED_FAIL")
    for item in fail:
        print(" -", item)
    sys.exit(1)
print("RED_OK")
PY

echo "==> resolver against live MPD"
node <<'JS'
var assert = require('assert');
var fs = require('fs');
var m = require('/resolver/mpdignore.js');
var payload = JSON.parse(fs.readFileSync('/tmp/enq-index.json', 'utf8'));
var files = payload.all_files;
var mnt = '/tmp/music';
var album = 'NAS/gmk/files/Depeche Mode - 101';
var tagArtist = 'NAS/gmk/files/_tags/artists/depechemode';
var tagAlbum = tagArtist + '/Depeche Mode - 101';
var tagDisc = tagAlbum + '/disc B';

function sorted(list) { return list.slice().sort(); }

var gotDisc = sorted(m.enqueueSongs(tagDisc, mnt, files));
var gotAlbum = sorted(m.enqueueSongs(tagAlbum, mnt, files));
var gotArtist = sorted(m.enqueueSongs(tagArtist, mnt, files));
assert.deepStrictEqual(gotDisc, sorted(payload.disc_b));
assert.deepStrictEqual(gotAlbum, sorted(payload.album));
assert.ok(gotAlbum.some(function (uri) { return uri.indexOf('/disc A/') >= 0; }));
assert.deepStrictEqual(gotArtist, sorted(files));
assert.ok(gotArtist.length > gotAlbum.length, 'artist prefix is more than 101');
payload.other.forEach(function (uri) {
  assert.ok(gotArtist.indexOf(uri) >= 0);
});
assert.deepStrictEqual(m.enqueueSongs(tagArtist + '/missing', mnt, files), []);
console.log('RESOLVER_OK songs=' + gotArtist.length + ' albums_songs=' + gotAlbum.length);
JS

echo "ENQUEUE_E2E_OK"
