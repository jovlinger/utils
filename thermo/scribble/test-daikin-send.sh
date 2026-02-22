#!/usr/bin/env bash
# Test daikin-send.py with a fake ir-ctl at head of PATH. Asserts the fake received
# a pulse/space file with expected Daikin-like content (start pulse, gap, etc.).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEND_LOG="/tmp/fake-ir-ctl-send.log"
rm -f "$SEND_LOG"

export PATH="${SCRIPT_DIR}/tests:${PATH}"
cd "$SCRIPT_DIR"

# Run send (no --dry-run) so it invokes ir-ctl; fake will copy sent file to $SEND_LOG.
python3 daikin-send.py --power on --mode heat --temp 22

if [ ! -f "$SEND_LOG" ]; then
  echo "FAIL: fake ir-ctl did not write $SEND_LOG (send path was not invoked)" >&2
  exit 1
fi

# Assert file looks like ir-ctl send format: lines "pulse N" and "space N".
if ! grep -q '^pulse 3400$' "$SEND_LOG"; then
  echo "FAIL: expected start pulse 3400 in $SEND_LOG" >&2
  head -5 "$SEND_LOG" >&2
  exit 1
fi
if ! grep -q '^space 1750$' "$SEND_LOG"; then
  echo "FAIL: expected start space 1750 in $SEND_LOG" >&2
  exit 1
fi
if ! grep -q '^space 30000$' "$SEND_LOG"; then
  echo "FAIL: expected inter-frame gap space 30000 in $SEND_LOG" >&2
  exit 1
fi
# Should have many pulse/space lines (3 frames * (start + 8|8|19 bytes * 16) + 2 gaps).
line_count=$(wc -l < "$SEND_LOG")
if [ "$line_count" -lt 200 ]; then
  echo "FAIL: expected at least 200 lines in send log, got $line_count" >&2
  exit 1
fi

echo "PASS: daikin-send.py invoked fake ir-ctl and sent expected pulse train"
