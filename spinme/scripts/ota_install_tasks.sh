#!/usr/bin/env bash
# PUT each build/tasks/<key> blob to http://HOST/kv/<key>.
# Empty stage (no blobs) is OK until all-but-nucleus ELFs exist: linked
# actors still ride usbinstallall. Set SPINME_OTA_REQUIRE_BLOBS=1 to fail.
set -euo pipefail
HOST="${1:-${SPINME_HOST:-spinme.local}}"
TASKS_DIR="${2:-}"
if [[ -z "$TASKS_DIR" || ! -d "$TASKS_DIR" ]]; then
  echo "usage: ota_install_tasks.sh HOST TASKS_DIR" >&2
  exit 2
fi
if [[ ! -f "$TASKS_DIR/.built" ]]; then
  echo "missing $TASKS_DIR/.built; run make build-tasks first" >&2
  exit 1
fi
shopt -s nullglob
blobs=("$TASKS_DIR"/*)
files=()
for b in "${blobs[@]}"; do
  [[ -f "$b" ]] || continue
  base="$(basename "$b")"
  [[ "$base" == ".built" ]] && continue
  [[ "$base" == README || "$base" == README.md ]] && continue
  files+=("$b")
done
if ((${#files[@]} == 0)); then
  msg="otainstalltasks: no task blobs under $TASKS_DIR (linked actors use usbinstallall until all-but-nucleus split)"
  if [[ "${SPINME_OTA_REQUIRE_BLOBS:-}" == "1" ]]; then
    echo "$msg" >&2
    exit 1
  fi
  echo "$msg"
  exit 0
fi
ok=0
for f in "${files[@]}"; do
  key="$(basename "$f")"
  # Key must match ta_net_kv_http is_key_char set.
  if [[ ! "$key" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "skip bad key name: $key" >&2
    continue
  fi
  len="$(wc -c <"$f" | tr -d ' ')"
  echo "PUT /kv/$key ($len bytes) -> $HOST"
  code="$(curl -sS -o /tmp/spinme_ota_body.$$ -w '%{http_code}' \
    -X PUT "http://${HOST}/kv/${key}" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"$f")"
  body="$(cat /tmp/spinme_ota_body.$$ 2>/dev/null || true)"
  rm -f /tmp/spinme_ota_body.$$
  if [[ "$code" != "200" ]]; then
    echo "PUT /kv/$key failed HTTP $code body=$body" >&2
    exit 1
  fi
  ok=$((ok + 1))
done
echo "otainstalltasks: put $ok blob(s); reboot or exit_all+boot_from_kv to activate code keys"
