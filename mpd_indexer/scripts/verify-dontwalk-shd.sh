#!/bin/bash
# Post-deploy SHD verification. Failures here are what "getState=200 alone"
# previously missed: stale Volumio MpdClient (browse hang) and a binary that
# never re-proved against a NAS/gmk/files fixture on the device.
#
# Env: SHD_HOST SHD_USER SHD_PASS (same as deploy-dontwalk-shd.sh)
set -euo pipefail

SHD_HOST="${SHD_HOST:-192.168.88.39}"
SHD_USER="${SHD_USER:-volumiooem}"
SHD_PASS="${SHD_PASS:-}"

if [ -z "$SHD_PASS" ]; then
  echo "SHD_PASS is required" >&2
  exit 1
fi
command -v expect >/dev/null || {
  echo "expect is required" >&2
  exit 1
}

REMOTE=$(cat <<'REMOTE'
set -euo pipefail
echo '==> restart volumio (MPD restart leaves Node MpdClient stale)'
systemctl restart volumio
# getState alone is not enough: it can 200 while browse still hangs on MPD.
ok=0
for i in $(seq 1 90); do
  gs=$(curl -sS -m3 -o /tmp/gs-verify.json -w '%{http_code}' \
    http://127.0.0.1:3000/api/v1/getState 2>/dev/null || true)
  br=$(curl -sS -m8 -o /tmp/br-files.json -w '%{http_code}' \
    'http://127.0.0.1:3000/api/v1/browse?uri=music-library/NAS/gmk/files' \
    2>/dev/null || true)
  if [ "$gs" = "200" ] && [ "$br" = "200" ] && [ -s /tmp/br-files.json ]; then
    echo "ready try=$i getState=$gs browse_files=$br"
    ok=1
    break
  fi
  echo "wait try=$i getState=$gs browse_files=$br"
  sleep 2
done
[ "$ok" = "1" ] || { echo FAIL browse never ready after volumio restart; exit 1; }

echo '==> browse contract'
fail=0
code=$(curl -sS -m25 -o /tmp/br-files.json -w '%{http_code}' \
  'http://127.0.0.1:3000/api/v1/browse?uri=music-library/NAS/gmk/files' \
  2>/dev/null || true)
echo "browse files -> $code"
[ "$code" = "200" ] || fail=1
python3 - <<'PY'
import json, sys
d = json.load(open("/tmp/br-files.json"))
items = d.get("navigation", {}).get("lists", [{}])[0].get("items", [])
titles = [str(i.get("title") or "") for i in items]
uris = [str(i.get("uri") or "") for i in items]
blob = "\n".join(titles + uris)
if "_tags" not in blob:
    print("FAIL: _tags missing under files browse")
    sys.exit(1)
if "_meta" in blob:
    print("FAIL: _meta still visible under files browse")
    sys.exit(1)
print("browse_files_ok n=", len(items))
PY

code=$(curl -sS -m25 -o /tmp/br-tags.json -w '%{http_code}' \
  'http://127.0.0.1:3000/api/v1/browse?uri=music-library/NAS/gmk/files/_tags' \
  2>/dev/null || true)
echo "browse _tags -> $code"
[ "$code" = "200" ] || fail=1
python3 - <<'PY'
import json, sys
d = json.load(open("/tmp/br-tags.json"))
items = d.get("navigation", {}).get("lists", [{}])[0].get("items", [])
titles = [str(i.get("title") or "") for i in items]
need = ("album", "artist")
for n in need:
    if not any(n == t or t.endswith("/" + n) for t in titles):
        print("FAIL: _tags browse missing", n, "got", titles[:12])
        sys.exit(1)
print("browse_tags_ok n=", len(items))
PY

code=$(curl -sS -m10 -o /tmp/br-meta.json -w '%{http_code}' \
  'http://127.0.0.1:3000/api/v1/browse?uri=music-library/NAS/gmk/files/_meta' || true)
echo "browse _meta -> $code (expect non-200 or empty)"
# Volumio may 200 with empty/error navigation; also accept curl fail.
python3 - <<'PY'
import json, os, sys
path = "/tmp/br-meta.json"
if not os.path.exists(path) or os.path.getsize(path) == 0:
    print("browse_meta_absent_ok")
    sys.exit(0)
d = json.load(open(path))
items = d.get("navigation", {}).get("lists", [{}])[0].get("items", [])
if items:
    print("FAIL: _meta browse returned items", [i.get("title") for i in items[:5]])
    sys.exit(1)
print("browse_meta_empty_ok")
PY

echo '==> on-device binary prove (fixture; does not touch production tag_cache)'
MPD=/usr/bin/mpd
ROOT=/tmp/prove-music-deploy
RUN=/tmp/prove-mpd-run-deploy
PORT=6602
rm -rf "$ROOT" "$RUN"
FILES="$ROOT/NAS/gmk/files"
ALBUM="$FILES/AlbumA"
mkdir -p "$ALBUM" "$FILES/_tags/album/albuma" "$FILES/_meta/AlbumA" \
  "$RUN"/{playlists,log,run}
SRC=$(find /mnt/NAS/gmk/files -name '*.flac' 2>/dev/null | head -1 || true)
if [ -n "$SRC" ]; then
  dd if="$SRC" of="$ALBUM/01.flac" bs=64k count=40 status=none 2>/dev/null || \
    cp "$SRC" "$ALBUM/01.flac" || true
fi
[ -s "$ALBUM/01.flac" ] || printf 'fLaC' > "$ALBUM/01.flac"
ln -sfn ../../AlbumA "$FILES/_meta/AlbumA/album"
ln -sfn ../../../_meta/AlbumA "$FILES/_tags/album/albuma/AlbumA"
printf '%s\n' '_meta' > "$FILES/.mpdignore"
cat >"$RUN/mpd.conf" <<EOF
music_directory		"$ROOT"
playlist_directory	"$RUN/playlists"
db_file			"$RUN/tag_cache"
log_file			"$RUN/log/mpd.log"
pid_file			"$RUN/run/mpd.pid"
bind_to_address		"127.0.0.1"
port				"$PORT"
auto_update			"no"
follow_outside_symlinks	"yes"
follow_inside_symlinks	"yes"
audio_output {
	type		"null"
	name		"null"
}
EOF
fuser -k ${PORT}/tcp >/dev/null 2>&1 || true
"$MPD" --no-daemon "$RUN/mpd.conf" >"$RUN/log/stdout.log" 2>&1 &
PID=$!
ready=0
for _ in $(seq 1 80); do
  if mpc -h 127.0.0.1 -p "$PORT" status >/dev/null 2>&1; then ready=1; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo FAIL mpd exited; tail -30 "$RUN/log/stdout.log"; exit 1
  fi
  sleep 0.1
done
[ "$ready" = 1 ] || { echo FAIL mpd not ready; kill "$PID" || true; exit 1; }
mpc -h 127.0.0.1 -p "$PORT" update >/dev/null
for _ in $(seq 1 120); do
  mpc -h 127.0.0.1 -p "$PORT" status 2>/dev/null | grep -q Updating || break
  sleep 0.2
done
python3 - <<PY
import socket, sys
PORT = $PORT

def cmd(c):
    s = socket.create_connection(("127.0.0.1", PORT), 5)
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
meta_empty = not any(m.startswith("directory:") or m.startswith("file:") for m in meta)
songs_ok = len(songs) >= 1 and all("/_tags/" not in s and "/_meta/" not in s for s in songs)
if not (tags_ok and meta_gone and meta_empty and songs_ok):
    print("PROOF_BROKEN")
    sys.exit(1)
print("PROOF_OK")
PY
kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true
[ "$fail" = "0" ] || exit 1
echo OK verify-dontwalk-shd
REMOTE
)

B64=$(printf '%s' "$REMOTE" | base64 | tr -d '\n')
echo "==> verify on $SHD_USER@$SHD_HOST"
expect <<EOF
set timeout 300
spawn ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  ${SHD_USER}@${SHD_HOST} "echo $SHD_PASS | sudo -S -p '' bash -lc 'echo $B64 | base64 -d | bash'"
expect {
  -re "(?i)password:" { send "$SHD_PASS\r"; exp_continue }
  eof
}
catch wait result
set code [lindex \$result 3]
if {\$code != 0} { exit \$code }
EOF
echo "OK verify complete"
