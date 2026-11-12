#!/usr/bin/env bash
# Post-flash: POST /event/Test/TestRun (alias run_test) on the board.
set -euo pipefail

HOST="${SPINME_HOST:-spinme.local}"
MODE="one"
SELECTOR="smoke"

usage() {
  echo "usage: $0 [--host HOST] [--mode one|suite|timing] [selector]" >&2
  echo "  env SPINME_HOST overrides --host (default spinme.local)" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:-}"; shift 2 || usage
      ;;
    --mode)
      MODE="${2:-}"; shift 2 || usage
      ;;
    -h|--help)
      usage
      ;;
    --)
      shift
      break
      ;;
    -*)
      usage
      ;;
    *)
      SELECTOR="$1"
      shift
      break
      ;;
  esac
done
if [[ $# -gt 0 ]]; then
  SELECTOR="$1"
fi

case "$MODE" in
  one|suite|timing|0|1|2) ;;
  *)
    echo "bad mode: $MODE" >&2
    exit 2
    ;;
esac

URL="http://${HOST}/event/Test/TestRun"
BODY="mode=${MODE}&selector=${SELECTOR}"

echo "POST ${URL}  ${BODY}" >&2
# Prefer curl; fail clearly if missing.
if ! command -v curl >/dev/null 2>&1; then
  echo "curl required" >&2
  exit 1
fi

# Capture body + HTTP code. 200 = probe ok; 500 = fail; 201 = accepted/timeout.
TMP="$(mktemp)"
CODE="$(curl -sS -o "$TMP" -w '%{http_code}' -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data "$BODY" \
  "$URL" || true)"
RESP="$(cat "$TMP")"
rm -f "$TMP"

echo "http=${CODE} body=${RESP}"
if [[ "$CODE" == "200" ]]; then
  exit 0
fi
exit 1
