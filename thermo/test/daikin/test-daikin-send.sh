#!/usr/bin/env bash
# Test daikin-send.py with a fake ir-ctl at head of PATH. Asserts the fake received
# a pulse/space file with expected ARC452A9 content (2 frames: F1 + F3).
set -e
TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
THERMO_DIR="$(cd "$TEST_DIR/../.." && pwd)"
SCRIBBLE="$THERMO_DIR/scribble"
SEND_LOG="/tmp/fake-ir-ctl-send.log"
rm -f "$SEND_LOG"

_timeout() { local s=$1; shift; perl -e 'alarm(shift @ARGV); exec @ARGV' "$s" "$@"; }

export PATH="${TEST_DIR}:${PATH}"
cd "$SCRIBBLE"

echo "DEBUG: TEST_DIR=$TEST_DIR"
echo "DEBUG: SCRIBBLE=$SCRIBBLE"
echo "DEBUG: which ir-ctl => $(which ir-ctl)"
echo "DEBUG: running daikin-send.py --dry-run first..."
_timeout 10 python3 daikin-send.py --power on --mode heat --temp 22 --dry-run || {
  echo "FAIL: --dry-run failed (exit $?), import or arg problem" >&2
  exit 1
}
echo "DEBUG: --dry-run OK, now running real send..."

if ! _timeout 10 python3 daikin-send.py --power on --mode heat --temp 22 2>&1; then
  echo "FAIL: daikin-send.py timed out or failed (exit $?)" >&2
  echo "DEBUG: SEND_LOG exists=$(test -f "$SEND_LOG" && echo yes || echo no)" >&2
  exit 1
fi

if [ ! -f "$SEND_LOG" ]; then
  echo "FAIL: fake ir-ctl did not write $SEND_LOG (send path was not invoked)" >&2
  echo "DEBUG: ls /tmp/fake*: $(ls -la /tmp/fake* 2>&1)" >&2
  exit 1
fi

echo "DEBUG: SEND_LOG has $(wc -l < "$SEND_LOG") lines"
echo "DEBUG: first 5 lines:"
head -5 "$SEND_LOG"
echo "DEBUG: last 5 lines:"
tail -5 "$SEND_LOG"

if ! grep -q '^pulse 3400$' "$SEND_LOG"; then
  echo "FAIL: expected start pulse 3400 in $SEND_LOG" >&2
  echo "DEBUG: first pulse lines:" >&2
  grep '^pulse' "$SEND_LOG" | head -3 >&2
  exit 1
fi
if ! grep -q '^space 1750$' "$SEND_LOG"; then
  echo "FAIL: expected start space 1750 in $SEND_LOG" >&2
  exit 1
fi
if ! grep -q '^space 30000$' "$SEND_LOG"; then
  echo "FAIL: expected inter-frame gap space 30000 in $SEND_LOG" >&2
  echo "DEBUG: large spaces:" >&2
  grep '^space' "$SEND_LOG" | awk '$2 > 2000' >&2
  exit 1
fi
line_count=$(wc -l < "$SEND_LOG")
if [ "$line_count" -lt 100 ]; then
  echo "FAIL: expected at least 100 lines in send log, got $line_count" >&2
  exit 1
fi

echo "PASS: daikin-send.py invoked fake ir-ctl and sent expected ARC452A9 pulse train ($line_count lines)"
